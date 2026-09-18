"""论文投递 — 期刊推荐 + 格式检查 + 格式修改"""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional

logger = logging.getLogger(__name__)

# Fixed model for the submission pipeline — user requirement: GLM-4.7.
# Passed explicitly to llm_client so the default model can change without
# silently affecting journal recommendations.
_SUBMIT_MODEL = "glm-4.7"

# In-process TTL cache (small, hot). SQLite (project_memory.cache_*) holds
# the persistent copy so restarts don't blow away user-visible state.
_RECOMMEND_CACHE: dict[str, tuple[float, list]] = {}
_FORMAT_CHECK_CACHE: dict[str, tuple[float, dict]] = {}
_ANALYSIS_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 1800  # 30 minutes


def _cache_get(cache: dict, key: str):
    entry = cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: dict, key: str, value) -> None:
    cache[key] = (time.time(), value)


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _parallel_web_search(queries: list[str], top_k: int = 5, per_query_timeout: float = 6.0) -> list[dict]:
    """Run multiple web_search calls in parallel with per-query timeouts.

    Returns the merged + de-duplicated result list. Failures / timeouts are
    logged and skipped — never propagated.
    """
    from src.tools.web_search import web_search

    if not queries:
        return []

    def _do(q: str) -> list[dict]:
        try:
            return web_search(q, top_k=top_k) or []
        except Exception as e:
            logger.warning(f"web_search failed for '{q[:40]}': {e}")
            return []

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, len(queries))) as ex:
        futures = {ex.submit(_do, q): q for q in queries}
        for fut, q in futures.items():
            try:
                results.extend(fut.result(timeout=per_query_timeout))
            except FuturesTimeoutError:
                logger.warning(f"web_search timeout for '{q[:40]}'")
            except Exception as e:
                logger.warning(f"web_search error for '{q[:40]}': {e}")
    return results


def _extract_journals_from_search(web_results: list[dict], top_k: int) -> list[dict]:
    """Last-resort fallback: synthesize journal entries from raw web_search
    snippets when the LLM fails entirely. Quality is lower than LLM output but
    always returns *something* useful instead of an empty list.
    """
    if not web_results:
        return []
    journals: list[dict] = []
    seen = set()
    for r in web_results:
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        url = r.get("url") or ""
        if not title or title in seen:
            continue
        # Heuristic: only keep results that look journal-related.
        blob = (title + " " + snippet).lower()
        if not any(kw in blob for kw in ("journal", "期刊", "sci", "ei", "ssci", "impact factor", "impact")):
            continue
        seen.add(title)
        journals.append({
            "name": title[:120],
            "publisher": "",
            "level": "N/A",
            "impact_factor": "N/A",
            "match_score": 60,
            "match_reason": snippet[:80] or "基于联网搜索结果",
            "submission_url": url,
            "review_cycle": "N/A",
            "acceptance_rate": "N/A",
        })
        if len(journals) >= top_k:
            break
    return journals

# ========== Prompt 模板 ==========

_ANALYZE_PAPER_PROMPT = """## 任务：分析学术论文的研究方向

### 论文内容
{paper_content}

### 要求
分析上述论文内容，提取以下信息：
1. 主要研究领域和细分方向
2. 关键术语和研究方法
3. 论文的核心主题摘要

请用 JSON 格式回复：
```json
{{
  "research_fields": ["领域1", "领域2"],
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "methods": ["方法1", "方法2"],
  "paper_summary": "论文核心内容的100字摘要",
  "language": "中文/英文/中英混合"
}}
```
只回复 JSON，不要解释。"""

_RECOMMEND_JOURNALS_PROMPT = """## 任务：推荐合适的学术期刊

### 论文分析
- 研究领域：{research_fields}
- 关键词：{keywords}
- 研究方法：{methods}
- 论文摘要：{paper_summary}
- 论文语言：{language}

### 联网搜索结果
{web_results}

### 要求
基于论文内容和搜索结果，推荐 {top_k} 个最合适的投稿期刊。
请综合搜索结果和你的学术知识进行推荐。

请用 JSON 格式回复：
```json
{{
  "journals": [
    {{
      "name": "期刊全名",
      "publisher": "出版社",
      "level": "SCI-Q1/SCI-Q2/SCI-Q3/SCI-Q4/EI/CSSCI/北大核心/CSCD/普通期刊",
      "impact_factor": "影响因子（如 5.2，不确定填 N/A）",
      "match_score": 85,
      "match_reason": "匹配原因（一句话说明为什么适合这篇论文）",
      "submission_url": "投稿系统网址（不确定填 N/A）",
      "review_cycle": "审稿周期（如 2-3个月，不确定填 N/A）",
      "acceptance_rate": "录用率（如 25%，不确定填 N/A）"
    }}
  ]
}}
```
只回复 JSON。match_score 为 0-100 的整数，按匹配度从高到低排序。"""

_FORMAT_CHECK_PROMPT = """## 任务：对照期刊格式要求检查论文

### 目标期刊
{journal_name}

### 期刊投稿指南（联网搜索结果）
{web_requirements}

### 论文各章节内容
{paper_content}

### 要求
对照目标期刊的格式要求，逐项检查论文当前状态，生成修改建议清单。

请用 JSON 格式回复：
```json
{{
  "journal_name": "期刊名称",
  "requirements_summary": "该期刊格式要求的一百字概要",
  "checklist": [
    {{
      "id": 1,
      "category": "structure",
      "description": "期刊要求：应包含摘要、关键词、引言、方法、实验、结论等章节",
      "current_state": "当前论文有：xxx",
      "suggestion": "具体修改建议",
      "severity": "required"
    }}
  ]
}}
```

category 可选值：structure（结构）、formatting（排版格式）、citation（引用格式）、length（篇幅要求）、language（语言要求）、figures（图表要求）、abstract（摘要要求）
severity 可选值：required（必须）、recommended（建议）、optional（可选）

只回复 JSON，尽量覆盖所有维度，通常应有 8-15 条检查项。"""

_FORMAT_APPLY_PROMPT = """## 任务：按修改建议调整论文章节内容

### 当前章节内容
{section_content}

### 需要应用的修改建议
{suggestions_text}

### 要求
按照上述修改建议，对章节内容进行调整。注意：
1. 只修改建议中提到的方面，不要改变论文的核心学术内容
2. 保持原文的学术风格和专业术语
3. 如果建议涉及结构调整，按新结构调整内容
4. 输出修改后的完整章节内容（不要省略任何部分）

请直接输出修改后的章节全文，不要加任何说明或标记。"""


def recommend_journals(
    project_id: str,
    research_topic: str = "",
    top_k: int = 8,
) -> list[dict]:
    """推荐投稿期刊"""
    from src.core.memory import project_memory
    from src.core.llm import llm_client, LLMError

    # 1. 获取论文内容
    sections = project_memory.get_unique_sections(project_id)
    if not sections:
        return []

    paper_parts = []
    total_len = 0
    for s in sections:
        content = s.get("content", "")
        if content:
            paper_parts.append(f"### {s.get('section_name', '章节')}\n{content}")
            total_len += len(content)
        if total_len > 4000:
            break
    paper_content = "\n\n".join(paper_parts)[:5000]

    # Recommend-result cache (final output). Keyed by content+topic+top_k so
    # editing sections naturally invalidates; unchanged sections hit cache.
    rec_cache_key = f"{_content_hash(paper_content)}|{research_topic}|{top_k}"
    cached = _cache_get(_RECOMMEND_CACHE, rec_cache_key)
    if cached is not None:
        logger.info("recommend_journals in-memory cache hit")
        return cached
    cached_persist = project_memory.cache_get("submit_recommend", rec_cache_key)
    if cached_persist is not None and isinstance(cached_persist, list):
        _cache_set(_RECOMMEND_CACHE, rec_cache_key, cached_persist)
        logger.info("recommend_journals SQLite cache hit")
        return cached_persist

    # 2. LLM 分析论文 (独立缓存，失败重试推荐时不必重新分析)
    analysis_key = f"{_content_hash(paper_content)}"
    analysis = _cache_get(_ANALYSIS_CACHE, analysis_key)
    if analysis is None:
        analysis = project_memory.cache_get("submit_analysis", analysis_key)
        if analysis is not None:
            _cache_set(_ANALYSIS_CACHE, analysis_key, analysis)

    if analysis is None:
        try:
            analysis = llm_client.chat_json(
                messages=[
                    {"role": "system", "content": "你是学术分析专家，只输出 JSON。"},
                    {"role": "user", "content": _ANALYZE_PAPER_PROMPT.format(paper_content=paper_content)},
                ],
                temperature=0.3,
                model=_SUBMIT_MODEL,
            )
            if not isinstance(analysis, dict):
                analysis = {}
        except LLMError as e:
            logger.warning(f"LLM 分析失败: {e}")
            analysis = {}
        # Cache analysis regardless of success so a transient failure doesn't
        # cause a retry storm; explicit edit-based invalidation is enough.
        _cache_set(_ANALYSIS_CACHE, analysis_key, analysis)
        project_memory.cache_set("submit_analysis", analysis_key, analysis, project_id=project_id)

    research_fields = analysis.get("research_fields", []) or ([research_topic] if research_topic else [])
    keywords = analysis.get("keywords", [])
    methods = analysis.get("methods", [])
    paper_summary = analysis.get("paper_summary", research_topic or "")
    language = analysis.get("language", "中文")

    # 3. 并发联网搜索期刊 (每条 6s 超时)
    queries: list[str] = []
    for field in research_fields[:2]:
        queries.append(f"{field} 期刊 SCI 投稿 推荐")
    for kw in keywords[:3]:
        queries.append(f"{kw} journal impact factor submission")
    if not queries and research_topic:
        queries.append(f"{research_topic} 期刊 SCI 投稿 推荐")

    web_results = _parallel_web_search(queries, top_k=5, per_query_timeout=6.0) if queries else []

    # 去重
    seen_urls = set()
    unique_results = []
    for r in web_results:
        url = r.get("url", "") or r.get("title", "")
        if url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)
    web_results_text = "\n".join(
        f"- [{r.get('title', '')}]({r.get('url', '')}): {r.get('snippet', '')}"
        for r in unique_results[:15]
    ) if unique_results else "（联网搜索暂不可用，请基于你的学术知识推荐）"

    # 4. LLM 推荐期刊 (直接同步调用，让 httpx 自己的网络超时兜底；不再套线程)
    topic_hint = f"\n用户补充研究方向：{research_topic}" if research_topic else ""
    journals: list[dict] = []
    try:
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": "你是学术期刊推荐专家，只输出 JSON。"},
                {"role": "user", "content": _RECOMMEND_JOURNALS_PROMPT.format(
                    research_fields=", ".join(research_fields),
                    keywords=", ".join(keywords),
                    methods=", ".join(methods),
                    paper_summary=paper_summary,
                    language=language,
                    web_results=web_results_text,
                    top_k=top_k,
                ) + topic_hint},
            ],
            temperature=0.5,
            model=_SUBMIT_MODEL,
        )
        journals = (result or {}).get("journals", []) or []
    except LLMError as e:
        logger.warning(f"LLM 推荐失败: {e}")

    # 4.5 兜底：LLM 没给出可用的期刊，就从 web_search 结果里抽取
    if not journals:
        logger.info("LLM 未返回期刊，使用 web_search 结果兜底")
        journals = _extract_journals_from_search(unique_results, top_k)

    journals = journals[:top_k]

    # 缓存最终结果（成功才缓存，避免把空/失败结果锁死）
    if journals:
        _cache_set(_RECOMMEND_CACHE, rec_cache_key, journals)
        project_memory.cache_set("submit_recommend", rec_cache_key, journals, project_id=project_id)

    return journals


def check_format(
    project_id: str,
    journal_name: str,
) -> dict:
    """格式检查：对比论文内容与目标期刊要求"""
    from src.core.memory import project_memory
    from src.core.llm import llm_client

    # 1. 获取论文内容
    sections = project_memory.get_unique_sections(project_id)
    if not sections:
        return {"journal_name": journal_name, "requirements_summary": "未找到论文内容", "checklist": []}

    paper_parts = []
    for s in sections:
        content = s.get("content", "")
        name = s.get("section_name", "章节")
        if content:
            paper_parts.append(f"### {name}\n{content[:800]}...")
    paper_content = "\n\n".join(paper_parts)[:5000]

    cache_key = f"{_content_hash(paper_content)}|{journal_name}"
    cached = _cache_get(_FORMAT_CHECK_CACHE, cache_key)
    if cached is not None:
        logger.info("check_format in-memory cache hit")
        return cached
    cached_persist = project_memory.cache_get("submit_format_check", cache_key)
    if cached_persist is not None and isinstance(cached_persist, dict):
        _cache_set(_FORMAT_CHECK_CACHE, cache_key, cached_persist)
        logger.info("check_format SQLite cache hit")
        return cached_persist

    # 2. 并发联网搜索期刊格式要求
    web_reqs = _parallel_web_search([
        f"{journal_name} 投稿指南 格式要求 author guidelines",
        f"{journal_name} paper format template requirements submission",
    ], top_k=5, per_query_timeout=6.0)

    web_requirements = "\n".join(
        f"- [{r.get('title', '')}]({r.get('url', '')}): {r.get('snippet', '')}"
        for r in web_reqs[:10]
    ) if web_reqs else "（联网搜索暂不可用，请基于你掌握的该期刊格式要求作答）"

    # 3. LLM 格式检查 (直接同步调用)
    try:
        result = llm_client.chat_json(
            messages=[
                {"role": "system", "content": "你是学术期刊格式审核专家，只输出 JSON。"},
                {"role": "user", "content": _FORMAT_CHECK_PROMPT.format(
                    journal_name=journal_name,
                    web_requirements=web_requirements,
                    paper_content=paper_content,
                )},
            ],
            temperature=0.3,
            model=_SUBMIT_MODEL,
        )
    except LLMError as e:
        logger.warning(f"LLM 格式检查失败: {e}")
        return {
            "journal_name": journal_name,
            "requirements_summary": "格式检查暂不可用，请稍后重试",
            "checklist": [],
        }
    if not isinstance(result, dict):
        result = {"journal_name": journal_name, "requirements_summary": "", "checklist": []}
    _cache_set(_FORMAT_CHECK_CACHE, cache_key, result)
    project_memory.cache_set("submit_format_check", cache_key, result, project_id=project_id)
    return result


def apply_format_changes(
    project_id: str,
    section_name: str,
    suggestions: list[dict],
) -> dict:
    """应用选中的格式修改建议"""
    from src.core.memory import project_memory
    from src.core.llm import llm_client

    # 1. 获取目标章节
    sections = project_memory.get_unique_sections(project_id)
    target = None
    for s in sections:
        if s.get("section_name") == section_name:
            target = s
            break

    if not target:
        return {"status": "error", "message": f"未找到章节：{section_name}"}

    section_content = target.get("content", "")
    if not section_content:
        return {"status": "error", "message": "章节内容为空"}

    # 2. 格式化建议文本
    suggestions_text = "\n".join(
        f"- [{s.get('severity', 'recommended')}] {s.get('category', '')}: {s.get('suggestion', '')}"
        for s in suggestions
    )

    # 3. LLM 修改内容
    new_content = llm_client.chat(
        [
            {"role": "system", "content": "你是学术格式修改专家。只输出修改后的完整文本，不要加任何说明。"},
            {"role": "user", "content": _FORMAT_APPLY_PROMPT.format(
                section_content=section_content,
                suggestions_text=suggestions_text,
            )},
        ],
        temperature=0.3,
        model=_SUBMIT_MODEL,
    )

    if not new_content or not new_content.strip():
        return {"status": "error", "message": "AI 修改结果为空"}

    # 4. 保存修改
    project_memory.save_section(project_id, section_name, new_content.strip())

    return {
        "status": "ok",
        "section_name": section_name,
        "content": new_content.strip(),
    }
