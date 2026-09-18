"""ReAct Agent - 意图路由、任务规划、工具调度、思考过程记录"""
import json
import logging
import re

from src.core.llm import llm_client
from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE
from src.core.memory import global_profile, project_memory, working_memory
from src.core.retriever import hybrid_search, format_chunks_with_citations, validate_citations
from src.tools.web_search import web_search_with_llm_summary

logger = logging.getLogger(__name__)


# ========== 意图路由 ==========

INTENT_MAP = {
    "summarize": ["总结", "提取", "梳理", "对比", "字段", "表格", "结构化"],
    "generate": ["写", "生成", "撰写", "帮我写", "文章", "论文", "章节"],
    "framework": ["框架", "思路", "大纲", "怎么写", "结构"],
    "modify": ["修改", "调整", "改写", "重写", "换"],
    "explore": ["有哪些", "什么方法", "怎么样", "分析", "讨论", "什么"],
    "upload": ["上传", "导入", "添加论文", "导入PDF"],
    "export": ["导出", "下载", "保存", "输出"],
    "chart": ["图表", "柱状图", "饼图", "可视化", "绘图"],
    "websearch": ["最新", "新闻", "最近", "当前", "2025", "2026", "联网", "搜索"],
}


def route_intent(user_input: str) -> str:
    """意图识别（带优先级）

    路由规则：
    1. 先检测是否为问句（含？）——走 explore
    2. 再检测其他意图
    3. generate 只在明确"写/生成"指令时触发
    """
    # 规则 1：问句检测
    if any(c in user_input for c in '？？'):
        return "explore"

    # 规则 2：正常路由
    intent_scores = {}
    for intent, keywords in INTENT_MAP.items():
        score = sum(1 for kw in keywords if kw in user_input)
        if intent == "framework" and score > 0:
            score += 2
        if intent == "export" and score > 0:
            score += 2
        if intent == "websearch" and score > 0:
            score += 1.5
        if score > 0:
            intent_scores[intent] = score

    if not intent_scores:
        return "explore"

    best = max(intent_scores, key=intent_scores.get)

    # 规则 3：generate 需要比 explore 分数更高
    if best == "generate" and "explore" in intent_scores:
        if intent_scores.get("generate", 0) <= intent_scores.get("explore", 0):
            return "explore"

    return best


# ========== Agent 核心 ==========

class CiteWiseAgent:
    """CiteWise 智能研究助手 Agent"""

    def __init__(self):
        self.llm = llm_client
        self.profile = global_profile
        self.pm = project_memory
        self.wm = working_memory
        self.thinking_steps: list[str] = []  # 当前请求的思考过程

    def _think(self, step: str):
        """记录思考步骤"""
        self.thinking_steps.append(step)
        logger.info(f"[Think] {step}")

    def process_message(self, user_input: str, project_id: str = None) -> dict:
        """处理用户消息，返回响应（含思考过程）"""
        self.thinking_steps = []  # 重置

        if project_id:
            self.wm.current_project_id = project_id

        intent = route_intent(user_input)
        self.wm.current_task = intent
        self._think(f"意图识别 → **{intent}**")
        self._think(f"用户输入：{user_input[:80]}")

        handlers = {
            "summarize": self._handle_summarize,
            "generate": self._handle_generate,
            "framework": self._handle_framework,
            "modify": self._handle_modify,
            "explore": self._handle_explore,
            "export": self._handle_export,
            "chart": self._handle_chart,
            "upload": self._handle_upload_hint,
            "websearch": self._handle_websearch,
        }

        handler = handlers.get(intent, self._handle_explore)
        result = handler(user_input)

        # 将思考过程附加到结果
        result["thinking_steps"] = self.thinking_steps
        return result

    # --- 处理器 ---

    def _handle_explore(self, user_input: str) -> dict:
        """探索/讨论模式：RAG检索 + 联网补充 + LLM知识"""
        project_id = self.wm.current_project_id
        project_state = self.pm.get_project_state(project_id) if project_id else {}

        # 1. RAG 检索
        self._think("从知识库检索相关文献...")
        chunks = hybrid_search(user_input, top_k=5)

        rag_content = ""
        sources = []
        if chunks:
            rag_content = format_chunks_with_citations(chunks)
            sources = [{"title": c.get("paper_title", ""), "citation": c.get("citation", "")} for c in chunks]
            self._think(f"检索到 {len(chunks)} 个相关文献片段")
        else:
            self._think("知识库未检索到相关内容")

        # 2. LLM 自身知识
        self._think("结合大模型自身知识库...")

        # 3. 生成回答
        system = self._build_system_prompt(project_state)

        prompt_explore = f"""## 用户问题
{user_input}

## 参考材料（来自知识库 RAG 检索）
{rag_content if rag_content else "（知识库无相关内容）"}

## 输出要求
请基于参考材料和自身知识回答用户问题，给出学术风格的回答。
如果引用了参考材料中的文献，请使用 [作者, 年份] 格式标注引用。
如果需要最新信息但无法确认，请明确说明。"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_explore},
        ]

        self._think("调用 LLM 生成回答...")
        response = self.llm.chat(messages, temperature=0.7)
        self._think("回答生成完成")

        # 4. 程序化标注来源
        response = self._annotate_sources(response, chunks, [])
        self._think("来源标注完成（程序化后处理）")

        citation_check = validate_citations(response, chunks) if chunks else {"total_citations": 0, "verified": 0, "verification_rate": 0}

        return {
            "type": "text",
            "content": response,
            "intent": "explore",
            "citations": citation_check,
            "sources": sources,
            "content_sources": {
                "rag": bool(chunks),
                "llm": True,
                "web": False,
            },
        }

    def _handle_websearch(self, user_input: str) -> dict:
        """联网搜索模式"""
        self._think("触发联网搜索...")

        # 提取搜索 query（去掉触发词）
        search_query = user_input
        for kw in ["最新", "新闻", "最近", "当前", "联网搜索", "搜索", "帮我查"]:
            search_query = search_query.replace(kw, "").strip()
        if not search_query:
            search_query = user_input

        # 1. 联网搜索
        self._think(f"搜索关键词：{search_query}")
        search_result = web_search_with_llm_summary(search_query)

        web_results = search_result["web_results"]
        llm_knowledge = search_result["llm_knowledge"]

        if web_results:
            self._think(f"找到 {len(web_results)} 条网络搜索结果")
        else:
            self._think("网络搜索未返回结果，将使用 LLM 知识回答")

        # 2. 同时检索知识库
        self._think("同步检索知识库...")
        chunks = hybrid_search(search_query, top_k=3)
        rag_content = format_chunks_with_citations(chunks) if chunks else ""

        # 3. 整合生成
        self._think("整合多源信息生成回答...")
        web_snippets = "\n".join(
            f"- [{r['title']}]({r['url']}): {r['snippet']}"
            for r in web_results
        )

        prompt = f"""## 用户问题
{user_input}

## 网络搜索结果
{web_snippets if web_snippets else "（无搜索结果）"}

## 知识库文献
{rag_content if rag_content else "（知识库无相关内容）"}

## LLM 自身知识
{llm_knowledge}

## 输出要求
请整合以上三种来源的信息，回答用户问题，给出学术风格的回答。
- 如果引用了知识库文献，请使用 [作者, 年份] 格式标注引用
- 如果引用了网络搜索结果，请标注来源 URL 或标题
- 整合多源信息，给出全面准确的回答"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": prompt},
        ]

        response = self.llm.chat(messages, temperature=0.6)
        self._think("多源整合回答生成完成")

        # 程序化标注来源
        response = self._annotate_sources(response, chunks if chunks else [], web_results)
        self._think("来源标注完成（程序化后处理）")

        return {
            "type": "text",
            "content": response,
            "intent": "websearch",
            "content_sources": {
                "rag": bool(chunks),
                "llm": True,
                "web": bool(web_results),
            },
            "web_results": web_results,
            "sources": [{"title": c.get("paper_title", ""), "citation": c.get("citation", "")} for c in chunks] if chunks else [],
        }

    def _handle_summarize(self, user_input: str) -> dict:
        """结构化总结：提取字段并生成表格"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目并上传论文。", "intent": "summarize"}

        papers = self.pm.get_papers(project_id)
        if not papers:
            return {"type": "text", "content": "当前项目没有论文，请先上传。", "intent": "summarize"}

        fields = self._extract_fields_from_input(user_input)
        if not fields:
            fields = ["研究方法", "数据集", "核心发现", "创新点"]

        self._think(f"提取字段：{', '.join(fields)}")

        results = []
        for paper in papers[:10]:
            self._think(f"正在提取：{paper['title'][:40]}...")
            chunks = hybrid_search(
                query=", ".join(fields),
                top_k=5,
                where={"paper_id": paper["id"]}
            )
            if not chunks:
                continue

            chunks_text = format_chunks_with_citations(chunks)
            task_prompt = prompt_engine.build_extract_prompt(fields, chunks_text)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_BASE},
                {"role": "user", "content": task_prompt},
            ]

            extraction = self.llm.chat_json(messages, temperature=0.3)

            if "fields" in extraction:
                self.pm.save_extraction(
                    project_id=project_id,
                    paper_id=paper["id"],
                    template_name="用户自定义",
                    fields=extraction.get("fields", {}),
                    confidence=extraction.get("confidence", {}),
                )
                results.append({
                    "paper_title": paper["title"],
                    "authors": paper["authors"],
                    "year": paper.get("year", ""),
                    **extraction.get("fields", {}),
                })

        if not results:
            return {"type": "text", "content": "未能从文献中提取到有效信息。", "intent": "summarize"}

        table = self._generate_markdown_table(results, fields)
        self._think(f"完成！共提取 {len(results)} 篇论文")

        return {
            "type": "table",
            "content": table,
            "data": results,
            "fields": fields,
            "intent": "summarize",
            "paper_count": len(results),
        }

    def _handle_framework(self, user_input: str) -> dict:
        """框架推荐"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目。", "intent": "framework"}

        project_state = self.pm.get_project_state(project_id)
        extractions = self.pm.get_extractions(project_id)

        if not extractions:
            self._think("无提取数据，推荐通用框架")
            return {
                "type": "text",
                "content": "建议先进行结构化总结，这样我可以基于数据推荐更精准的框架。\n\n"
                           "通用框架：\n1. 引言\n2. 文献综述\n3. 方法论\n4. 研究发现\n5. 讨论\n6. 结论",
                "intent": "framework",
            }

        self._think("基于提取数据分析，推荐论文框架...")
        summary_data = json.dumps(
            [{"paper": e.get("paper_id", ""), "fields": e.get("fields", {})} for e in extractions],
            ensure_ascii=False, indent=2
        )

        system = self._build_system_prompt(project_state)
        task_prompt = prompt_engine.build_framework_prompt(
            summary_data=summary_data,
            paper_count=project_state.get("paper_count", 0),
            research_topic=project_state.get("topic", user_input),
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task_prompt},
        ]

        result = self.llm.chat_json(messages, temperature=0.5)
        self._think("框架推荐完成")

        return {
            "type": "framework",
            "content": result,
            "intent": "framework",
        }

    def _handle_generate(self, user_input: str) -> dict:
        """分节生成"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目。", "intent": "generate"}

        project_state = self.pm.get_project_state(project_id)
        framework = project_state.get("completed_sections", [])

        section_name, section_topic = self._parse_section_request(user_input, framework)
        self._think(f"生成章节：**{section_name}** | 主题：{section_topic}")

        self._think("检索相关文献片段...")
        chunks = hybrid_search(section_topic or section_name, top_k=8)
        reference = format_chunks_with_citations(chunks) if chunks else "（未检索到相关文献）"
        self._think(f"检索到 {len(chunks)} 个相关片段")

        previous_summary = self.wm.get_previous_summary()

        system = self._build_system_prompt(project_state)
        task_prompt = prompt_engine.build_section_prompt(
            section_name=section_name,
            section_topic=section_topic,
            reference_material=reference,
            framework=str(framework) if framework else "",
            previous_summary=previous_summary,
            target_words=1000,
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task_prompt},
        ]

        self._think("调用 LLM 生成章节内容...")
        content = self.llm.chat(messages, temperature=0.7, max_tokens=4000)
        self._think(f"章节生成完成，共 {len(content)} 字")

        # 程序化来源标注
        content = self._annotate_sources(content, chunks, [])
        self._think("来源标注完成")

        self.pm.save_section(project_id, section_name, content)

        summary = self._summarize_section(content)
        self.wm.add_section_summary(section_name, summary, len(content))

        citation_check = validate_citations(content, chunks)

        return {
            "type": "section",
            "content": content,
            "section_name": section_name,
            "intent": "generate",
            "citations": citation_check,
            "word_count": len(content),
            "sources": [{"title": c.get("paper_title", ""), "citation": c.get("citation", "")} for c in chunks] if chunks else [],
        }

    def _handle_modify(self, user_input: str) -> dict:
        """局部修改"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目并生成文章。", "intent": "modify"}

        sections = self.pm.get_unique_sections(project_id)
        if not sections:
            return {"type": "text", "content": "还没有生成任何章节，无法修改。", "intent": "modify"}

        # 匹配用户输入中提到的章节名，而非总是取最后一个
        target_section = None
        for s in sections:
            if s["section_name"] in user_input:
                target_section = s
                break
        if target_section is None:
            target_section = sections[-1]

        self._think(f"定位修改目标：章节「{target_section['section_name']}」")
        target = target_section["content"]

        chunks = hybrid_search(user_input, top_k=3)
        reference = format_chunks_with_citations(chunks) if chunks else ""

        full_article = "\n\n".join(s["content"] for s in sections)

        task_prompt = prompt_engine.build_rewrite_prompt(
            instruction=user_input,
            target_paragraph=target[:1500],
            full_article=full_article,
            reference_material=reference,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": task_prompt},
        ]

        result = self.llm.chat_json(messages, temperature=0.5)
        self._think("修改完成")

        return {
            "type": "modify",
            "content": result.get("modified_paragraph", target),
            "change_summary": result.get("change_summary", "已修改"),
            "intent": "modify",
        }

    def _handle_export(self, user_input: str) -> dict:
        """导出文档"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目。", "intent": "export"}

        sections = self.pm.get_unique_sections(project_id)
        if not sections:
            return {"type": "text", "content": "还没有生成任何章节。", "intent": "export"}

        self._think(f"导出文档，共 {len(sections)} 个章节")

        project = self.pm.get_project(project_id)
        title = project["name"] if project else "研究论文"

        doc = f"# {title}\n\n"
        for s in sections:
            doc += s["content"] + "\n\n---\n\n"

        all_citations = set()
        for s in sections:
            en = re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\]', s["content"])
            zh = re.findall(r'\[([\u4e00-\u9fff]+等?,\s*\d{4})\]', s["content"])
            all_citations.update(en + zh)

        if all_citations:
            doc += "## 参考文献\n\n"
            for i, ref in enumerate(sorted(all_citations), 1):
                doc += f"- [{i}] {ref}\n"

        self._think("文档导出完成")

        return {
            "type": "export",
            "content": doc,
            "word_count": len(doc),
            "section_count": len(sections),
            "intent": "export",
        }

    def _handle_chart(self, user_input: str) -> dict:
        """生成图表代码"""
        project_id = self.wm.current_project_id
        if not project_id:
            return {"type": "text", "content": "请先创建项目并进行结构化总结。", "intent": "chart"}

        extractions = self.pm.get_extractions(project_id)
        if not extractions:
            return {"type": "text", "content": "请先进行结构化总结以获取数据。", "intent": "chart"}

        self._think("生成可视化图表...")

        table_data = []
        for e in extractions:
            row = {"paper_id": e["paper_id"]}
            row.update(e.get("fields", {}))
            table_data.append(row)

        task_prompt = prompt_engine.build_chart_prompt(
            table_data=json.dumps(table_data, ensure_ascii=False, indent=2),
            chart_requirement=user_input,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": task_prompt},
        ]

        result = self.llm.chat_json(messages, temperature=0.3)
        self._think("图表代码生成完成")

        return {
            "type": "chart",
            "content": result,
            "intent": "chart",
        }

    def _handle_upload_hint(self, user_input: str) -> dict:
        return {
            "type": "text",
            "content": "请在左侧面板上传 PDF 文件，系统会自动解析并构建知识库。",
            "intent": "upload",
        }

    # --- 来源标注（程序化后处理） ---

    def _annotate_sources(self, content: str, rag_chunks: list[dict], web_results: list[dict]) -> str:
        """程序化标注内容来源 — 委托给独立模块"""
        from src.core.source_annotation import annotate_sources
        return annotate_sources(content, rag_chunks, web_results)

    # --- 辅助方法 ---

    def _build_system_prompt(self, project_state: dict = None) -> str:
        profile_data = {
            "research_field": self.profile.get("research_field", "未设定"),
            "focus_areas": self.profile.get("focus_areas", []),
            "field_preferences": self.profile.get("field_preferences", []),
            "writing_style": self.profile.get("writing_style", "学术正式"),
        }
        return prompt_engine.build_system_prompt(
            user_profile=profile_data,
            project_state=project_state,
        )

    def _extract_fields_from_input(self, user_input: str) -> list[str]:
        bracket_fields = re.findall(r'[\[【](.*?)[\]】]', user_input)
        quote_fields = re.findall(r'[""「](.*?)[""」]', user_input)
        fields = bracket_fields + quote_fields

        if not fields:
            for kw in ["提取", "字段", "总结"]:
                if kw in user_input:
                    after = user_input.split(kw, 1)[-1]
                    if "：" in after or ":" in after:
                        field_str = re.split(r'[：:]', after, 1)[-1]
                        fields = [f.strip() for f in re.split(r'[,，、]', field_str) if f.strip()]
                        break

        return [f for f in fields if len(f) <= 20]

    def _parse_section_request(self, user_input: str, framework: list = None) -> tuple:
        section_keywords = {
            "引言": ("引言", "研究背景、研究意义和研究问题"),
            "背景": ("研究背景", "研究背景与意义"),
            "综述": ("文献综述", "相关研究的梳理与对比"),
            "文献": ("文献综述", "相关研究的梳理与对比"),
            "方法": ("方法论", "研究方法和分析框架"),
            "结果": ("研究结果", "研究发现与数据分析"),
            "发现": ("研究发现", "研究发现与数据分析"),
            "讨论": ("讨论", "研究讨论与启示"),
            "结论": ("结论", "研究结论与未来方向"),
        }

        for kw, (name, topic) in section_keywords.items():
            if kw in user_input:
                return name, topic

        return "文献综述", "相关研究的梳理与对比分析"

    def _generate_markdown_table(self, results: list[dict], fields: list[str]) -> str:
        if not results:
            return ""

        headers = ["论文", "作者", "年份"] + fields
        header_row = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"

        rows = []
        for r in results:
            cells = [
                r.get("paper_title", "N/A")[:30],
                r.get("authors", "N/A")[:15],
                str(r.get("year", "N/A")),
            ]
            for f in fields:
                cells.append(str(r.get(f, "未提及"))[:50])
            rows.append("| " + " | ".join(cells) + " |")

        return header_row + "\n" + separator + "\n" + "\n".join(rows)

    def _summarize_section(self, content: str) -> str:
        """用 LLM 压缩章节 — 委托给独立模块"""
        from src.core.source_annotation import summarize_section
        return summarize_section(self.llm, content)


# 全局单例
agent = CiteWiseAgent()
