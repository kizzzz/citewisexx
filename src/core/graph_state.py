"""LangGraph 多 Agent 协作状态定义"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    """CiteWise 多 Agent 协作状态

    每个节点返回 dict，LangGraph 自动合并到全局状态。
    """

    # === 输入 ===
    user_input: str
    project_id: str
    session_id: str                # 对话会话 ID（多轮对话）
    messages: list                 # 对话历史 [{role, content}]（最近 10 轮）

    # === 路由 ===
    intent: str             # explore / summarize / generate / modify / framework / export / chart / websearch / analyze
    next_agent: str         # researcher / writer / analyst

    # === 研究结果 (Researcher 节点输出) ===
    chunks: list            # RAG 检索到的文档片段
    rag_content: str        # 格式化的 RAG 内容
    web_results: list       # 联网搜索结果
    sources: list           # 来源列表

    # === 输出 ===
    content: str            # 最终响应内容
    response_type: str      # text / section / table / analysis / framework / modify / export / chart
    section_name: str       # 章节名 (generate 时)
    citations: dict         # 引用验证结果
    content_sources: dict   # 来源标注 {rag, llm, web}
    change_summary: str     # 修改说明 (modify 时)
    word_count: int         # 字数

    # === 思考 & 追踪 ===
    thinking_steps: list    # 思考步骤文字
    agent_events: list      # [{agent, event, detail, timestamp, duration_ms?}]

    # === 额外参数 ===
    target_content: str     # modify 时的原文
    framework: list         # 章节框架
    gen_params: dict        # 生成参数 {style, target_length, citation_density}
    section_id: str         # 保存后的章节 ID
    agent_choice: str       # 用户选择的生成 Agent（writer/analyst）
    system_prompt: str      # 用户自建 Agent 的系统提示词
    requirements: str       # 章节要求：简述、重点、格式等
