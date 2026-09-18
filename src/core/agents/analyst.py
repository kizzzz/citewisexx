"""AnalystAgent — 数据分析 + 图表生成"""
import json
import logging
from typing import Optional

from src.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """分析 Agent — 负责数据分析、洞察生成、图表工具"""

    def __init__(self):
        super().__init__("Analyst")
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from src.core.llm import llm_client
            self._llm = llm_client
        return self._llm

    def analyze_project(self, project_id: str) -> dict:
        """分析项目数据，生成洞察"""
        self.reset()
        from src.core.memory import project_memory

        state = project_memory.get_project_state(project_id)
        if not state:
            return {"type": "text", "content": "项目不存在"}

        papers = state.get("papers", [])
        extractions = project_memory.get_extractions(project_id)

        self.think(f"分析 {len(papers)} 篇论文, {len(extractions)} 条提取记录")

        # 统计分析
        methods = {}
        years = {}
        for p in papers:
            year = p.get("year", 0)
            if year:
                years[year] = years.get(year, 0) + 1

        for e in extractions:
            fields = e.get("fields", {})
            method = fields.get("研究方法", fields.get("核心方法", "未知"))
            if method:
                methods[method] = methods.get(method, 0) + 1

        insights = []
        if methods:
            top_method = max(methods, key=methods.get)
            insights.append(f"主要研究方法: {top_method} ({methods[top_method]} 篇)")
        if years:
            insights.append(f"年份分布: {dict(sorted(years.items()))}")

        # 框架推荐
        framework = self._recommend_framework(papers, extractions, state.get("topic", ""))
        self.think("分析完成，生成建议")

        return {
            "type": "analysis",
            "insights": insights,
            "method_distribution": methods,
            "year_distribution": years,
            "framework": framework,
            "thinking_steps": self.thinking_steps,
        }

    def _recommend_framework(self, papers, extractions, topic: str) -> dict:
        """基于数据推荐论文框架"""
        from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE

        summary_data = json.dumps(
            [{"paper": e.get("paper_id", ""), "fields": e.get("fields", {})}
             for e in extractions],
            ensure_ascii=False, indent=2
        )

        task_prompt = prompt_engine.build_framework_prompt(
            summary_data=summary_data,
            paper_count=len(papers),
            research_topic=topic or "研究综述",
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": task_prompt},
        ]

        result = self.llm.chat_json(messages, temperature=0.5)
        return result

    def split_table(self, table_content: str, split_by: str = "columns") -> dict:
        """拆分表格"""
        self.reset()
        self.think(f"拆分表格，按 {split_by}")

        prompt = f"""将以下表格按 "{split_by}" 拆分为两个子表格。
输出 JSON: {{"table_a": "markdown", "table_b": "markdown", "split_note": "说明"}}

表格内容:
{table_content}"""

        messages = [{"role": "user", "content": prompt}]
        result = self.llm.chat_json(messages, temperature=0.3)
        return {
            "type": "table_split",
            "content": result,
            "thinking_steps": self.thinking_steps,
        }

    def merge_descriptions(self, desc_a: str, desc_b: str) -> dict:
        """合并两个图表描述为对比描述"""
        self.reset()
        self.think("合并图表描述为对比图")

        prompt = f"""将以下两个图表描述合并为一个对比描述。
输出 JSON: {{"combined_description": "markdown", "comparison_note": "对比说明"}}

描述 A:
{desc_a}

描述 B:
{desc_b}"""

        messages = [{"role": "user", "content": prompt}]
        result = self.llm.chat_json(messages, temperature=0.3)
        return {
            "type": "chart_merge",
            "content": result,
            "thinking_steps": self.thinking_steps,
        }

    def generate_section(self, section_name: str, section_topic: str,
                         research_result: dict, project_id: str,
                         gen_params: dict = None,
                         system_prompt: str = "", requirements: str = "") -> dict:
        """Analyst 生成数据/方法导向的章节"""
        self.reset()
        from src.core.memory import project_memory, working_memory
        from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE
        from src.core.source_annotation import annotate_sources, summarize_section
        from src.core.retriever import validate_citations

        params = gen_params or {}
        target_words = params.get("target_length", 1000)
        style = params.get("style", "学术正式")

        rag_content = research_result.get("rag_content", "")
        chunks = research_result.get("chunks", [])
        previous_summary = working_memory.get_previous_summary()

        task_prompt = prompt_engine.build_section_prompt(
            section_name=section_name,
            section_topic=section_topic or f"方法论与数据分析：{section_name}",
            reference_material=rag_content,
            framework="",
            previous_summary=previous_summary,
            target_words=target_words,
            writing_style=style,
        )
        # Analyst 侧重: 强调方法、数据、统计
        task_prompt += (
            "\n\n### 额外要求（Analyst Agent）\n"
            "请侧重方法论、数据分析框架、统计结果和实证发现来撰写本章节。"
            "适当使用表格对比不同研究的方法和结论。"
        )

        # Add user requirements if provided
        if requirements and requirements.strip():
            task_prompt += f"\n\n### 用户要求\n{requirements.strip()}"

        messages = [
            {"role": "system", "content": system_prompt.strip() if system_prompt and system_prompt.strip() else SYSTEM_PROMPT_BASE},
            {"role": "user", "content": task_prompt},
        ]

        self.think("Analyst 生成方法/数据导向章节...")
        content = self.llm.chat(messages, temperature=0.7, max_tokens=4000)
        self.think(f"生成完成: {len(content)} 字")

        content = annotate_sources(content, chunks, [])
        section_id = project_memory.save_section(project_id, section_name, content)
        summary = summarize_section(self.llm, content)
        working_memory.add_section_summary(section_name, summary, len(content))

        citation_check = validate_citations(content, chunks)

        return {
            "type": "section",
            "content": content,
            "section_id": section_id,
            "section_name": section_name,
            "intent": "generate",
            "citations": citation_check,
            "word_count": len(content),
            "sources": [
                {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
                for c in chunks
            ] if chunks else [],
            "thinking_steps": self.thinking_steps,
        }

    def process(self, user_input: str, project_id: str = None, **kwargs) -> dict:
        intent = kwargs.get("intent", "analyze")
        if intent == "generate":
            return self.generate_section(
                kwargs.get("section_name", "方法论"),
                kwargs.get("section_topic", ""),
                kwargs.get("research_result", {}),
                project_id or "",
                kwargs.get("gen_params"),
                kwargs.get("system_prompt", ""),
                kwargs.get("requirements", ""),
            )
        elif intent == "analyze":
            return self.analyze_project(project_id or "")
        elif intent == "split_table":
            return self.split_table(
                kwargs.get("table_content", ""),
                kwargs.get("split_by", "columns")
            )
        elif intent == "merge_chart":
            return self.merge_descriptions(
                kwargs.get("desc_a", ""),
                kwargs.get("desc_b", "")
            )
        else:
            return self.analyze_project(project_id or "")
