"""来源标注与摘要 — 独立的纯函数模块"""
import re
import logging

logger = logging.getLogger(__name__)


def _normalize_author(author: str) -> str:
    """标准化作者名：去'等'/'et al.'，取姓氏部分"""
    author = author.strip()
    author = re.sub(r'\s*等\.?\s*$', '', author)
    author = re.sub(r'\s*et al\.?\s*$', '', author, flags=re.IGNORECASE)
    parts = author.split()
    return parts[0].lower() if parts else author.lower()


def _cite_matches_rag(cite: str, year_author_pairs: list, rag_citations: set) -> bool:
    """检查引用是否匹配 RAG 来源（精确 + 模糊）"""
    if cite in rag_citations:
        return True
    cite_year_match = re.search(r'(\d{4})', cite)
    cite_year = cite_year_match.group(1) if cite_year_match else ""
    cite_author = _normalize_author(re.sub(r',?\s*\d{4}$', '', cite))
    for ref_year, ref_author in year_author_pairs:
        if not ref_author:
            # year-only match (from chunk text extraction)
            if cite_year == ref_year:
                return True
            continue
        if cite_year == ref_year and cite_author == ref_author:
            return True
    return False


def _extract_paper_citations(text: str) -> list[str]:
    """从 chunk 文本中提取常见引用格式，返回标准化的 '作者, 年份' 列表"""
    refs = []
    # (Author, 2023) / (Author et al., 2023) / (Author & B, 2023)
    for m in re.finditer(r'\(([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&|[A-Z][a-z]+))?),\s*(\d{4})\)', text):
        refs.append(f"{m.group(1)}, {m.group(2)}")
    # [Author, 2023] / [Author et al., 2023]
    for m in re.finditer(r'\[([A-Z][\w\s]+?(?:et\s+al\.?)?),\s*(\d{4})\]', text):
        refs.append(f"{m.group(1)}, {m.group(2)}")
    return refs


def _extract_years_from_text(text: str) -> list[str]:
    """从文本中提取年份（1900-2099）"""
    return re.findall(r'\b((?:19|20)\d{2})\b', text)


def annotate_sources(content: str, rag_chunks: list[dict], web_results: list[dict]) -> str:
    """程序化标注内容来源：RAG文献 / 网络搜索 / LLM推理

    遍历每一段落，根据引用和关键词匹配判断来源类型，在段首添加标记。
    当 metadata 中 authors/year 缺失时，从 chunk 文本中自动提取引用信息作为补充。
    """
    if not content or not content.strip():
        return content

    # 1. 构建 RAG 引用匹配集合
    rag_citations = set()
    year_author_pairs = []

    for c in rag_chunks:
        meta = c.get("metadata", {})
        authors = meta.get("authors", "") or c.get("authors", "")
        year = meta.get("year", "") or c.get("year", "")
        text = c.get("text", "")

        # 优先用 metadata
        if authors and year:
            try:
                y = str(int(year))
                rag_citations.add(f"{authors}, {y}")
                year_author_pairs.append((y, _normalize_author(authors)))
                continue
            except (ValueError, TypeError):
                pass

        # 回退：从 chunk 文本中提取引用
        chunk_cites = _extract_paper_citations(text)
        chunk_years = _extract_years_from_text(text)
        for cite in chunk_cites:
            rag_citations.add(cite)
            cite_year_match = re.search(r'(\d{4})', cite)
            if cite_year_match:
                cite_author = _normalize_author(re.sub(r',?\s*\d{4}$', '', cite))
                year_author_pairs.append((cite_year_match.group(1), cite_author))
        if chunk_years:
            for y in chunk_years:
                year_author_pairs.append((y, ""))

    logger.info(f"[Annotate] RAG citation refs: {rag_citations}")
    logger.info(f"[Annotate] RAG year_author_pairs: {year_author_pairs[:5]}")

    # 2. 构建 RAG 文本关键词集合（用于无引用段落的模糊匹配）
    rag_text_keywords = set()
    for c in rag_chunks:
        text = c.get("text", "")
        if text:
            for word in re.findall(r'[一-鿿]{2,}|[a-zA-Z]{4,}', text.lower()):
                rag_text_keywords.add(word)

    # 3. 构建网络来源关键词集合
    web_keywords = set()
    web_urls = []
    for r in web_results:
        title = r.get("title", "")
        if title:
            for word in re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', title):
                web_keywords.add(word.lower())
        url = r.get("url", "")
        if url:
            web_urls.append(url)
            domain_match = re.search(r'://([^/]+)', url)
            if domain_match:
                web_keywords.add(domain_match.group(1).lower())

    # 4. 按段落处理
    paragraphs = content.split("\n")
    annotated = []
    source_stats = {"rag": 0, "web": 0, "llm": 0}

    for para in paragraphs:
        stripped = para.strip()
        if not stripped or stripped.startswith("#"):
            annotated.append(para)
            continue

        is_rag = False
        is_web = False

        en_cites = re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\]', stripped)
        zh_cites = re.findall(r'\[[一-鿿]+等?,\s*\d{4}\]', stripped)
        all_cites = en_cites + zh_cites

        # 匹配策略 1：引用标记精确/模糊匹配
        for cite in all_cites:
            if _cite_matches_rag(cite, year_author_pairs, rag_citations):
                is_rag = True
                break

        # 匹配策略 2：无引用时，用关键词重叠判断是否来自 RAG
        if not is_rag and not all_cites and rag_text_keywords:
            para_words = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{4,}', stripped.lower()))
            overlap = para_words & rag_text_keywords
            zh_words = [w for w in para_words if re.match(r'[一-鿿]', w)]
            threshold = 3 if len(zh_words) > len(para_words) // 2 else 2
            if len(overlap) >= threshold:
                is_rag = True

        # 匹配策略 3：段落与 chunk 文本做短语重叠检测（需要多个独立短语命中）
        if not is_rag and rag_chunks:
            match_count = 0
            matched_phrases = set()
            for c in rag_chunks:
                chunk_text = c.get("text", "")
                if chunk_text and len(chunk_text) > 30:
                    for phrase in re.findall(r'[一-鿿]{4,}|[a-zA-Z]{5,}', chunk_text):
                        if len(phrase) >= 5 and phrase in stripped and phrase not in matched_phrases:
                            matched_phrases.add(phrase)
                            match_count += 1
            if match_count >= 3:
                is_rag = True

        if all_cites and not is_rag:
            logger.debug(f"[Annotate] Unmatched cites: {all_cites}")

        if not is_rag and web_keywords:
            for url in web_urls:
                if url and url in stripped:
                    is_web = True
                    break
            if not is_web:
                para_words = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', stripped.lower()))
                overlap = para_words & web_keywords
                if len(overlap) >= 2:
                    is_web = True

        if is_rag:
            annotated.append(f"[KB] {para}")
            source_stats["rag"] += 1
        elif is_web:
            annotated.append(f"[WEB] {para}")
            source_stats["web"] += 1
        else:
            annotated.append(f"[AI] {para}")
            source_stats["llm"] += 1

    logger.info(f"[Annotate] RAG={source_stats['rag']}, Web={source_stats['web']}, LLM={source_stats['llm']}")
    return "\n".join(annotated)


def summarize_section(llm_client, content: str) -> str:
    """用 LLM 压缩章节为100字摘要"""
    if len(content) < 200:
        return content
    messages = [
        {"role": "system", "content": "将以下论文章节压缩为100字以内的简洁摘要，保留核心观点和关键引用。"},
        {"role": "user", "content": content[:3000]},
    ]
    return llm_client.chat(messages, temperature=0.3, max_tokens=200)
