"""Prompt 引擎 - 动态模板组装与管理"""
import json
import logging
from typing import Optional

from src.core.retriever import format_chunks_with_citations

logger = logging.getLogger(__name__)

# ========== Layer 1-2: 固定基础 ==========

SYSTEM_PROMPT_BASE = """你是 CiteWise，一个专业的学术研究助手。你的任务是基于用户上传的文献库，辅助完成文献梳理、思路构建和论文写作。

## 核心约束（必须严格遵守）
1. 【强制溯源】所有观点、数据、结论必须引用知识库中的文献，格式：[作者, 年份]。无法引用时明确告知"该内容超出知识库范围"。
2. 【禁止幻觉】不得编造论文、数据、方法或结论。不确定时回答"我需要更多信息"。
3. 【结构化输出】严格按照要求的格式输出（Markdown表格/JSON/指定章节格式）。
4. 【忠实原文】提取信息时忠于原文表述，不得过度解读或推断。"""

# ========== Layer 3: 用户画像模板 ==========

USER_PROFILE_TEMPLATE = """
## 用户画像
- 研究领域：{research_field}
- 关注方向：{focus_areas}
- 字段偏好：{field_preferences}
- 写作风格偏好：{writing_style}"""

# ========== Layer 4: 项目状态模板 ==========

PROJECT_STATE_TEMPLATE = """
## 当前项目状态
- 项目名称：{project_name}
- 文献数量：{paper_count}
- 已提取字段：{extracted_fields}
- 论文框架：{current_framework}
- 当前焦点：{current_focus}"""

# ========== Layer 5: 任务 Prompt 模板 ==========

EXTRACT_FIELDS_PROMPT = """## 任务：结构化文献总结

你需要从以下文献片段中提取用户指定的字段信息。

### 用户自定义字段
{fields}

### 文献内容
{chunks_text}

### 输出要求
请严格按照以下 JSON 格式输出：
```json
{{
  "paper_title": "论文标题",
  "authors": "作者",
  "year": "年份",
  "fields": {{
    {fields_json_template}
  }},
  "confidence": {{
    {confidence_template}
  }}
}}
```

### 注意事项
- 如果某个字段在文献中未提及，填"未提及"，不要编造
- confidence: high=原文明确提及, medium=需要推断, low=不确定"""

RECOMMEND_FRAMEWORK_PROMPT = """## 任务：推荐论文写作框架

基于用户已上传的 {paper_count} 篇文献的结构化总结结果，推荐一个合适的论文写作框架。

### 文献分析数据
{summary_data}

### 用户研究主题
{research_topic}

### 输出要求（JSON格式）
```json
{{
  "framework": [
    {{
      "section": "章节标题",
      "goal": "该章节的写作目标",
      "suggested_words": 1000,
      "key_points": ["要点1", "要点2"]
    }}
  ],
  "rationale": "推荐理由",
  "insights": ["洞察1", "洞察2", "洞察3"]
}}
```"""

GENERATE_SECTION_PROMPT = """## 任务：生成论文章节

你正在为一篇学术论文生成「{section_name}」章节。

### 论文整体框架
{framework}

### 前文摘要（保持连贯）
{previous_summary}

### 当前章节要求
- 主题：{section_topic}
- 目标字数：{target_words} 字
- 写作风格：{writing_style}

### 参考材料（来自知识库检索）
{reference_material}

### 输出要求
1. 学术写作风格，逻辑清晰，段落间有过渡
2. 每个观点/数据必须附带引用：[作者, 年份]
3. 在章节末尾列出本节引用的参考文献
4. 如果该内容超出知识库范围，明确标注

### 输出格式
## {section_name}

（正文内容）

### 本节参考文献
- [1] 作者. 标题. 期刊, 年份."""

REWRITE_SECTION_PROMPT = """## 任务：局部修改论文段落

### 修改目标
用户要求：{instruction}

### 当前文章
{full_article}

### 目标段落
{target_paragraph}

### 修改约束
1. 仅修改目标段落，保持其他内容不变
2. 保持引用格式一致 [作者, 年份]
3. 保持与上下文的衔接自然
4. 如需新的文献支撑，使用以下参考材料：
{reference_material}

### 输出要求（JSON格式）
```json
{{
  "modified_paragraph": "修改后的段落",
  "change_summary": "修改说明"
}}
```"""

GENERATE_TABLE_PROMPT = """## 任务：生成结构化对比表格

根据以下提取结果，生成一个 Markdown 格式的对比表格。

### 提取数据
{extraction_data}

### 输出要求
生成标准 Markdown 表格，包含所有论文的对比信息。"""

GENERATE_CHART_PROMPT = """## 任务：生成可视化图表代码

### 源数据
{table_data}

### 用户要求
{chart_requirement}

### 输出要求（JSON格式）
```json
{{
  "chart_type": "bar/pie/line/scatter",
  "title": "图表标题",
  "description": "图表说明（50字以内）",
  "python_code": "matplotlib 代码",
  "data_insight": "从图表中得出的核心洞察"
}}
```"""

DISCUSS_PROMPT = """## 任务：回答用户关于文献的问题

### 用户问题
{question}

### 相关文献片段
{reference_material}

### 输出要求
1. 基于文献内容回答，不要编造
2. 引用来源：[作者, 年份]
3. 如果文献中没有相关信息，明确告知"""


class PromptEngine:
    """Prompt 引擎：动态组装 Prompt"""

    def build_system_prompt(self, user_profile: dict = None, project_state: dict = None) -> str:
        """组装完整 System Prompt（Layer 1-3）"""
        prompt = SYSTEM_PROMPT_BASE

        if user_profile:
            prompt += USER_PROFILE_TEMPLATE.format(
                research_field=user_profile.get("research_field", "未设定"),
                focus_areas=", ".join(user_profile.get("focus_areas", [])),
                field_preferences=", ".join(user_profile.get("field_preferences", [])),
                writing_style=user_profile.get("writing_style", "学术正式"),
            )

        if project_state:
            prompt += PROJECT_STATE_TEMPLATE.format(
                project_name=project_state.get("name", "未命名项目"),
                paper_count=project_state.get("paper_count", 0),
                extracted_fields=", ".join(project_state.get("extracted_fields", [])),
                current_framework=project_state.get("framework", "未设定"),
                current_focus=project_state.get("focus", "无"),
            )

        return prompt

    def build_extract_prompt(self, fields: list[str], chunks_text: str) -> str:
        """组装字段提取 Prompt"""
        fields_str = ", ".join(fields)
        fields_json = ",\n    ".join(f'"{f}": "提取内容或未提及"' for f in fields)
        confidence_json = ",\n    ".join(f'"{f}": "high/medium/low"' for f in fields)

        return EXTRACT_FIELDS_PROMPT.format(
            fields=fields_str,
            chunks_text=chunks_text,
            fields_json_template=fields_json,
            confidence_template=confidence_json,
        )

    def build_framework_prompt(self, summary_data: str, paper_count: int,
                                research_topic: str) -> str:
        """组装框架推荐 Prompt"""
        return RECOMMEND_FRAMEWORK_PROMPT.format(
            paper_count=paper_count,
            summary_data=summary_data,
            research_topic=research_topic,
        )

    def build_section_prompt(self, section_name: str, section_topic: str,
                              reference_material: str, framework: str = "",
                              previous_summary: str = "（这是第一章，无前文）",
                              target_words: int = 1000,
                              writing_style: str = "学术正式") -> str:
        """组装分节生成 Prompt"""
        return GENERATE_SECTION_PROMPT.format(
            section_name=section_name,
            section_topic=section_topic,
            reference_material=reference_material,
            framework=framework or "（框架未设定，请根据主题合理组织）",
            previous_summary=previous_summary,
            target_words=target_words,
            writing_style=writing_style,
        )

    def build_rewrite_prompt(self, instruction: str, target_paragraph: str,
                              full_article: str, reference_material: str = "（无额外参考材料）") -> str:
        """组装局部修改 Prompt"""
        return REWRITE_SECTION_PROMPT.format(
            instruction=instruction,
            target_paragraph=target_paragraph,
            full_article=full_article[:3000],  # 限制长度
            reference_material=reference_material,
        )

    def build_discuss_prompt(self, question: str, reference_material: str) -> str:
        """组装讨论问答 Prompt"""
        return DISCUSS_PROMPT.format(
            question=question,
            reference_material=reference_material,
        )

    def build_response_prompt(self, user_input: str, rag_content: str = "",
                               web_results: list = None, intent: str = "explore") -> str:
        """组装 Responder/Stream 的用户 Prompt（统一入口）

        所有 responder_node / async_responder_node / stream_chat_response 共用此方法。
        """
        safe_input = user_input.replace("```", " ").replace("<|", " ").strip()

        if intent == "websearch" and web_results:
            web_snippets = "\n".join(
                f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in web_results
            )
            return (
                f"## 用户问题\n{safe_input}\n\n"
                f"## 网络搜索结果\n{web_snippets}\n\n"
                f"## 知识库文献\n{rag_content or '（无）'}\n\n"
                "请整合以上来源回答用户问题，使用 [作者, 年份] 标注引用。"
            )

        return (
            f"## 用户问题\n{safe_input}\n\n"
            f"## 参考材料（知识库检索）\n{rag_content or '（无相关内容）'}\n\n"
            "## 输出要求\n"
            "1. **必须优先基于参考材料回答**，参考材料中有相关内容时，不得凭自身知识编造\n"
            "2. 引用格式：[作者, 年份]，每个关键观点都要标注来源\n"
            "3. 如果参考材料中无相关内容，明确回答「当前知识库中未涵盖该主题」\n"
            "4. 使用 Markdown 格式，分标题、段落、列表输出\n"
            "5. 回答结构：先用一段概括性总结，再分要点详述"
        )


# 全局单例
prompt_engine = PromptEngine()
