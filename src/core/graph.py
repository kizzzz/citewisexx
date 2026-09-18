"""LangGraph 多 Agent 协作图 — Supervisor 模式

流程:
    START → supervisor → (路由)
      ├── "researcher" → researcher → (再路由)
      │     ├── "writer"    → writer    → END
      │     ├── "analyst"   → analyst   → END
      │     └── "responder" → responder → END
      └── "writer" (export) → writer → END
"""
import re
import time
import logging

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.core.graph_state import AgentState
from src.core.agents.router import RouterAgent
from src.core.agents.researcher import ResearchAgent
from src.core.agents.writer import WriterAgent
from src.core.agents.analyst import AnalystAgent

logger = logging.getLogger(__name__)

# 复用的 Agent 实例
_router = RouterAgent()
_researcher = ResearchAgent()
_writer = WriterAgent()
_analyst = AnalystAgent()


def _ts() -> float:
    return time.time()


# ========== Node Functions ==========

def supervisor_node(state: AgentState) -> dict:
    """Supervisor — 意图路由 + 流程决策"""
    start = _ts()
    user_input = state.get("user_input", "")
    project_id = state.get("project_id")

    route_result = _router.process(user_input, project_id)
    intent = route_result["intent"]
    target_agent = route_result["target_agent"]

    thinking = list(state.get("thinking_steps", [])) + route_result.get("thinking_steps", [])
    events = list(state.get("agent_events", [])) + [
        {"agent": "Supervisor", "event": "start", "detail": f"分析意图...", "timestamp": start},
        {"agent": "Supervisor", "event": "end", "detail": f"意图={intent} → {target_agent}",
         "timestamp": _ts(), "duration_ms": int((_ts() - start) * 1000)},
    ]

    return {
        "intent": intent,
        "next_agent": target_agent,
        "thinking_steps": thinking,
        "agent_events": events,
    }


def researcher_node(state: AgentState) -> dict:
    """Researcher — RAG 检索 + 联网搜索"""
    start = _ts()
    user_input = state.get("user_input", "")
    project_id = state.get("project_id")
    intent = state.get("intent", "explore")

    events = list(state.get("agent_events", [])) + [
        {"agent": "Researcher", "event": "start", "detail": "检索知识库...", "timestamp": start},
    ]

    top_k = 8 if intent in ("generate", "modify") else 5
    result = _researcher.research(user_input, project_id, intent, top_k)

    thinking = list(state.get("thinking_steps", [])) + result.get("thinking_steps", [])
    chunk_count = len(result.get("chunks", []))
    web_count = len(result.get("web_results", []))
    detail = f"RAG {chunk_count} 片段" + (f", 联网 {web_count} 条" if web_count else "")

    events.append({
        "agent": "Researcher", "event": "end", "detail": detail,
        "timestamp": _ts(), "duration_ms": int((_ts() - start) * 1000),
    })

    return {
        "chunks": result.get("chunks", []),
        "rag_content": result.get("rag_content", ""),
        "web_results": result.get("web_results", []),
        "sources": result.get("sources", []),
        "thinking_steps": thinking,
        "agent_events": events,
    }


def responder_node(state: AgentState) -> dict:
    """Responder — 基于 RAG/联网结果生成回答 (explore / summarize / websearch)"""
    start = _ts()

    events = list(state.get("agent_events", [])) + [
        {"agent": "Responder", "event": "start", "detail": "生成回答...", "timestamp": start},
    ]

    from src.core.llm import llm_client
    from src.core.prompt import SYSTEM_PROMPT_BASE, prompt_engine
    from src.core.source_annotation import annotate_sources
    from src.core.retriever import validate_citations

    user_input = state.get("user_input", "")
    intent = state.get("intent", "explore")
    chunks = state.get("chunks", [])
    web_results = state.get("web_results", [])
    rag_content = state.get("rag_content", "")
    thinking = list(state.get("thinking_steps", []))
    thinking.append("调用 LLM 生成回答...")

    prompt = prompt_engine.build_response_prompt(user_input, rag_content, web_results, intent)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_BASE},
        {"role": "user", "content": prompt},
    ]

    response = llm_client.chat(messages, temperature=0.7)
    response = annotate_sources(response, chunks, web_results)

    citation_check = validate_citations(response, chunks) if chunks else {}
    sources = [
        {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
        for c in chunks
    ] if chunks else []

    thinking.append("回答生成完成")
    events.append({
        "agent": "Responder", "event": "end", "detail": f"生成 {len(response)} 字",
        "timestamp": _ts(), "duration_ms": int((_ts() - start) * 1000),
    })

    return {
        "content": response,
        "response_type": "text",
        "citations": citation_check,
        "sources": sources,
        "content_sources": {"rag": bool(chunks), "llm": True, "web": bool(web_results)},
        "thinking_steps": thinking,
        "agent_events": events,
    }


def writer_node(state: AgentState) -> dict:
    """Writer — 章节生成 / 改写 / 导出"""
    start = _ts()
    intent = state.get("intent", "generate")
    user_input = state.get("user_input", "")
    project_id = state.get("project_id")

    events = list(state.get("agent_events", [])) + [
        {"agent": "Writer", "event": "start", "detail": f"处理: {intent}", "timestamp": start},
    ]

    research_result = {
        "chunks": state.get("chunks", []),
        "rag_content": state.get("rag_content", ""),
        "web_results": state.get("web_results", []),
        "sources": state.get("sources", []),
    }

    if intent == "modify":
        result = _writer.modify_content(
            user_input, state.get("target_content", ""),
            research_result, project_id,
        )
    elif intent == "export":
        result = _handle_export(state)
    else:
        section_name = state.get("section_name") or _parse_section_name(user_input)
        section_topic = _parse_section_topic(user_input, section_name)
        result = _writer.generate_section(
            section_name, section_topic, research_result, project_id,
            state.get("framework", []),
            state.get("gen_params"),
            state.get("system_prompt", ""),
            state.get("requirements", ""),
        )

    thinking = list(state.get("thinking_steps", [])) + result.get("thinking_steps", [])
    events.append({
        "agent": "Writer", "event": "end", "detail": result.get("response_type", intent),
        "timestamp": _ts(), "duration_ms": int((_ts() - start) * 1000),
    })

    return {
        **result,
        "thinking_steps": thinking,
        "agent_events": events,
    }


def analyst_node(state: AgentState) -> dict:
    """Analyst — 数据分析 / 图表 / 框架推荐 / 方法论章节"""
    start = _ts()
    intent = state.get("intent", "analyze")
    project_id = state.get("project_id")
    user_input = state.get("user_input", "")

    events = list(state.get("agent_events", [])) + [
        {"agent": "Analyst", "event": "start", "detail": f"分析: {intent}", "timestamp": start},
    ]

    research_result = {
        "chunks": state.get("chunks", []),
        "rag_content": state.get("rag_content", ""),
        "web_results": state.get("web_results", []),
        "sources": state.get("sources", []),
    }

    if intent == "generate":
        section_name = state.get("section_name") or _parse_section_name(user_input)
        section_topic = _parse_section_topic(user_input, section_name)
        result = _analyst.process(
            user_input, project_id,
            intent="generate",
            section_name=section_name,
            section_topic=section_topic,
            research_result=research_result,
            gen_params=state.get("gen_params"),
            system_prompt=state.get("system_prompt", ""),
            requirements=state.get("requirements", ""),
        )
    elif intent in ("chart", "figures"):
        result = _analyst.process(user_input, project_id, intent=intent)
    else:
        result = _analyst.analyze_project(project_id or "")

    thinking = list(state.get("thinking_steps", [])) + result.get("thinking_steps", [])
    events.append({
        "agent": "Analyst", "event": "end", "detail": intent,
        "timestamp": _ts(), "duration_ms": int((_ts() - start) * 1000),
    })

    return {
        **result,
        "thinking_steps": thinking,
        "agent_events": events,
    }


# ========== Routing ==========

def route_from_supervisor(state: AgentState) -> str:
    intent = state.get("intent", "explore")
    if intent == "export":
        return "writer"
    return "researcher"


def route_after_research(state: AgentState) -> str:
    # Respect user's explicit agent choice for section generation
    agent_choice = state.get("agent_choice", "")
    if agent_choice in ("writer", "analyst"):
        return agent_choice
    next_agent = state.get("next_agent", "researcher")
    if next_agent == "writer":
        return "writer"
    if next_agent == "analyst":
        return "analyst"
    return "responder"


# ========== Helpers ==========

_SECTION_KEYWORDS = {
    "引言": "引言", "背景": "研究背景", "综述": "文献综述",
    "文献": "文献综述", "方法": "方法论", "结果": "研究结果",
    "发现": "研究发现", "讨论": "讨论", "结论": "结论",
}

_SECTION_TOPICS = {
    "引言": "研究背景、研究意义和研究问题",
    "研究背景": "研究背景与意义",
    "文献综述": "相关研究的梳理与对比分析",
    "方法论": "研究方法和分析框架",
    "研究结果": "研究发现与数据分析",
    "研究发现": "研究发现与数据分析",
    "讨论": "研究讨论与启示",
    "结论": "研究结论与未来方向",
}


def _parse_section_name(user_input: str) -> str:
    for kw, name in _SECTION_KEYWORDS.items():
        if kw in user_input:
            return name
    return "文献综述"


def _parse_section_topic(user_input: str, section_name: str) -> str:
    return _SECTION_TOPICS.get(section_name, "相关研究的梳理与对比分析")


def _handle_export(state: AgentState) -> dict:
    from src.core.memory import project_memory

    project_id = state.get("project_id")
    if not project_id:
        return {"type": "text", "content": "请先创建项目。", "response_type": "text", "intent": "export"}

    sections = project_memory.get_unique_sections(project_id)
    if not sections:
        return {"type": "text", "content": "还没有生成任何章节。", "response_type": "text", "intent": "export"}

    project = project_memory.get_project(project_id)
    title = project["name"] if project else "研究论文"

    doc = f"# {title}\n\n"
    for s in sections:
        doc += s["content"] + "\n\n---\n\n"

    all_citations = set()
    for s in sections:
        all_citations.update(re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\]', s["content"]))
        all_citations.update(re.findall(r'\[([\u4e00-\u9fff]+等?,\s*\d{4})\]', s["content"]))

    if all_citations:
        doc += "## 参考文献\n\n"
        for i, ref in enumerate(sorted(all_citations), 1):
            doc += f"- [{i}] {ref}\n"

    return {
        "content": doc, "response_type": "export", "intent": "export",
        "word_count": len(doc),
    }


# ========== Build Graph ==========

def build_graph():
    """构建 CiteWise 多 Agent 协作图 (Supervisor 模式)"""
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("responder", responder_node)
    workflow.add_node("writer", writer_node)
    workflow.add_node("analyst", analyst_node)

    workflow.add_edge(START, "supervisor")

    workflow.add_conditional_edges(
        "supervisor", route_from_supervisor,
        {"researcher": "researcher", "writer": "writer"},
    )

    workflow.add_conditional_edges(
        "researcher", route_after_research,
        {"writer": "writer", "analyst": "analyst", "responder": "responder"},
    )

    for node in ("responder", "writer", "analyst"):
        workflow.add_edge(node, END)

    return workflow.compile(checkpointer=MemorySaver())


# 全局 graph 实例（延迟初始化）
_graph = None
_graph_lock = __import__('threading').Lock()


def get_graph():
    global _graph
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                _graph = build_graph()
    return _graph
