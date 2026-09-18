"""LangGraph 异步版本 — 支持逐字流式输出

替换 graph.py 中的同步节点为异步节点，
使 astream_events 能 yield on_chat_model_stream 事件。
"""
import logging
import time

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.core.graph_state import AgentState
from src.core.agents.router import RouterAgent, get_model_for_intent
from src.core.agents.researcher import ResearchAgent
from src.core.agents.writer import WriterAgent
from src.core.agents.analyst import AnalystAgent
from src.core.graph import (
    supervisor_node, researcher_node, analyst_node,
    route_from_supervisor, route_after_research,
    _parse_section_name, _parse_section_topic,
)

logger = logging.getLogger(__name__)

_router = RouterAgent()
_researcher = ResearchAgent()
_writer = WriterAgent()
_analyst = AnalystAgent()


# ========== Async Node Functions ==========

async def async_responder_node(state: AgentState) -> dict:
    """异步 Responder — 使用 achat_stream 逐 token 输出

    每个 token 通过 state["stream_tokens"] 传递，
    聊天路由会收集并推送。
    """
    start = time.time()

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

    # 流式 token 收集
    collected_tokens = []
    async for token in llm_client.achat_stream(messages, temperature=0.7):
        collected_tokens.append(token)

    response = "".join(collected_tokens)
    response = annotate_sources(response, chunks, web_results)

    citation_check = validate_citations(response, chunks) if chunks else {}
    sources = [
        {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
        for c in chunks
    ] if chunks else []

    thinking.append("回答生成完成")
    events.append({
        "agent": "Responder", "event": "end", "detail": f"生成 {len(response)} 字",
        "timestamp": time.time(), "duration_ms": int((time.time() - start) * 1000),
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


async def async_writer_node(state: AgentState) -> dict:
    """异步 Writer — 异步 LLM 调用"""
    start = time.time()
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
        from src.core.graph import _handle_export
        result = _handle_export(state)
    else:
        section_name = _parse_section_name(user_input)
        section_topic = _parse_section_topic(user_input, section_name)
        result = await _async_generate_section(
            section_name, section_topic, research_result, project_id,
            state.get("framework", []),
            state.get("gen_params"),
        )

    thinking = list(state.get("thinking_steps", [])) + result.get("thinking_steps", [])
    events.append({
        "agent": "Writer", "event": "end", "detail": result.get("response_type", intent),
        "timestamp": time.time(), "duration_ms": int((time.time() - start) * 1000),
    })

    return {
        **result,
        "thinking_steps": thinking,
        "agent_events": events,
    }


async def _async_generate_section(section_name, section_topic, research_result,
                                   project_id, framework, gen_params=None):
    """异步章节生成"""
    from src.core.llm import llm_client
    from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE
    from src.core.source_annotation import annotate_sources, summarize_section
    from src.core.retriever import validate_citations
    from src.core.memory import project_memory, working_memory

    params = gen_params or {}
    style = params.get("style", "学术正式")
    target_words = params.get("target_length", 1000)
    citation_density = params.get("citation_density", "正常")

    density_map = {"高": "每段至少 2 个引用", "正常": "适当引用关键观点", "低": "仅在关键结论处引用"}
    citation_instruction = density_map.get(citation_density, "适当引用关键观点")

    rag_content = research_result.get("rag_content", "")
    chunks = research_result.get("chunks", [])
    previous_summary = working_memory.get_previous_summary()

    system = SYSTEM_PROMPT_BASE
    task_prompt = prompt_engine.build_section_prompt(
        section_name=section_name,
        section_topic=section_topic,
        reference_material=rag_content,
        framework=str(framework) if framework else "",
        previous_summary=previous_summary,
        target_words=target_words,
        writing_style=style,
    )
    task_prompt += f"\n\n### 引用密度要求\n{citation_instruction}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task_prompt},
    ]

    # 流式收集
    collected_tokens = []
    async for token in llm_client.achat_stream(messages, temperature=0.7, max_tokens=4000):
        collected_tokens.append(token)
    content = "".join(collected_tokens)
    content = annotate_sources(content, chunks, [])

    project_memory.save_section(project_id, section_name, content)
    summary = summarize_section(llm_client, content)
    working_memory.add_section_summary(section_name, summary, len(content))

    citation_check = validate_citations(content, chunks)

    return {
        "type": "section",
        "content": content,
        "section_name": section_name,
        "response_type": "section",
        "intent": "generate",
        "citations": citation_check,
        "word_count": len(content),
        "sources": [
            {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
            for c in chunks
        ] if chunks else [],
        "thinking_steps": ["异步章节生成完成"],
    }


# ========== Streaming Response Builder ==========
# This function provides direct token-level streaming for the chat route.

async def stream_chat_response(user_input: str, project_id: str,
                                api_key: str = None, base_url: str = None,
                                model: str = None, session_id: str = None):
    """直接流式对话 — 路由 → RAG → 流式 LLM 输出

    Yields SSE events: agent_start, agent_end, token, content, citations, done, session
    """
    import json
    from src.core.llm import llm_client
    from src.core.prompt import SYSTEM_PROMPT_BASE, prompt_engine
    from src.core.source_annotation import annotate_sources
    from src.core.retriever import validate_citations, hybrid_search, format_chunks_with_citations
    from src.core.memory import project_memory

    start_time = time.time()

    # --- Collect agent timeline events for metadata ---
    agent_timeline = []

    # --- Session management ---
    if not session_id:
        session_id = project_memory.create_session(
            project_id, title=user_input[:30]
        )
    # Send session_id to frontend
    yield {"event": "session", "data": json.dumps({"session_id": session_id}, ensure_ascii=False)}

    # --- Load conversation history ---
    history_messages = project_memory.get_session_messages(session_id, limit=20)
    # Save user message
    project_memory.save_message(session_id, project_id, "user", user_input)

    # Step 1: Route intent (sync, fast)
    agent_timeline.append({"agent": "Supervisor", "detail": "分析意图...", "status": "running"})
    yield {"event": "agent_start", "data": json.dumps({
        "agent": "Supervisor", "detail": "分析意图..."
    }, ensure_ascii=False)}

    route_result = _router.process(user_input, project_id)
    intent = route_result.get("intent", "explore")
    agent_timeline[-1]["status"] = "done"
    agent_timeline[-1]["detail"] = f"意图: {intent}"
    yield {"event": "agent_end", "data": json.dumps({
        "agent": "Supervisor", "detail": f"意图: {intent}"
    }, ensure_ascii=False)}

    # Step 2: Research (RAG)
    chunks = []
    web_results = []
    rag_content = ""

    agent_timeline.append({"agent": "Researcher", "detail": "检索知识库...", "status": "running"})
    yield {"event": "agent_start", "data": json.dumps({
        "agent": "Researcher", "detail": "检索知识库..."
    }, ensure_ascii=False)}

    try:
        chunks = hybrid_search(user_input, project_id=project_id, intent=intent)
        if chunks:
            rag_content = format_chunks_with_citations(chunks[:10])
    except Exception as e:
        logger.warning(f"RAG 检索失败: {e}")

    # Web search if needed
    if intent == "websearch":
        try:
            from src.tools.web_search import web_search_tool
            web_results = web_search_tool.search(user_input, max_results=5)
        except Exception as e:
            logger.warning(f"联网搜索失败: {e}")

    research_detail = f"检索完成: {len(chunks)} 文献片段" + (f", {len(web_results)} 网络结果" if web_results else "")
    research_duration = int((time.time() - start_time) * 1000)
    agent_timeline[-1]["status"] = "done"
    agent_timeline[-1]["detail"] = research_detail
    agent_timeline[-1]["duration_ms"] = research_duration
    yield {"event": "agent_end", "data": json.dumps({
        "agent": "Researcher",
        "detail": research_detail,
        "duration_ms": research_duration,
    }, ensure_ascii=False)}

    # Step 3: Route to appropriate agent for streaming response
    is_writer_intent = intent in ("generate", "modify")

    if is_writer_intent:
        # --- Writer path: stream section generation ---
        agent_timeline.append({"agent": "Writer", "detail": f"处理: {intent}", "status": "running"})
        yield {"event": "agent_start", "data": json.dumps({
            "agent": "Writer", "detail": f"处理: {intent}"
        }, ensure_ascii=False)}

        research_result = {
            "chunks": chunks,
            "rag_content": rag_content,
            "web_results": web_results,
            "sources": [],
        }

        if intent == "modify":
            target_content = ""
            writer_result = _writer.modify_content(
                user_input, target_content, research_result, project_id,
            )
            full_response = writer_result.get("content", "")
        else:
            section_name = _parse_section_name(user_input)
            section_topic = _parse_section_topic(user_input, section_name)
            writer_result = await _async_generate_section(
                section_name, section_topic, research_result, project_id,
                [], None,
            )
            full_response = writer_result.get("content", "")

        full_response = annotate_sources(full_response, chunks, web_results)
        content_type = "section"

        elapsed = int((time.time() - start_time) * 1000)
        writer_detail = f"生成 {len(full_response)} 字"
        agent_timeline[-1]["status"] = "done"
        agent_timeline[-1]["detail"] = writer_detail
        agent_timeline[-1]["duration_ms"] = elapsed
        yield {"event": "agent_end", "data": json.dumps({
            "agent": "Writer", "detail": writer_detail,
            "duration_ms": elapsed,
        }, ensure_ascii=False)}

        yield {"event": "content", "data": json.dumps({
            "content": full_response, "type": content_type,
        }, ensure_ascii=False)}

    else:
        # --- Responder path: stream discussion response ---
        agent_timeline.append({"agent": "Responder", "detail": "生成回答...", "status": "running"})
        yield {"event": "agent_start", "data": json.dumps({
            "agent": "Responder", "detail": "生成回答..."
        }, ensure_ascii=False)}

        prompt = prompt_engine.build_response_prompt(user_input, rag_content, web_results, intent)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
        ]
        # Add conversation history (exclude the current message which is already in prompt)
        for msg in history_messages:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        # Add current prompt as the latest user message
        messages.append({"role": "user", "content": prompt})

        # Token-level streaming
        collected_tokens = []
        try:
            # Use tiered model routing if user didn't specify a model
            effective_model = model or get_model_for_intent(intent)
            async for token in llm_client.achat_stream(messages, temperature=0.7, api_key=api_key, base_url=base_url, model=effective_model):
                collected_tokens.append(token)
                yield {"event": "token", "data": json.dumps({"text": token}, ensure_ascii=False)}
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            yield {"event": "error", "data": json.dumps({"message": "LLM 调用失败"}, ensure_ascii=False)}
            return

        full_response = "".join(collected_tokens)
        full_response = annotate_sources(full_response, chunks, web_results)
        content_type = "text"

        elapsed = int((time.time() - start_time) * 1000)
        responder_detail = f"生成 {len(full_response)} 字"
        agent_timeline[-1]["status"] = "done"
        agent_timeline[-1]["detail"] = responder_detail
        agent_timeline[-1]["duration_ms"] = elapsed
        yield {"event": "agent_end", "data": json.dumps({
            "agent": "Responder", "detail": responder_detail,
            "duration_ms": elapsed,
        }, ensure_ascii=False)}

        yield {"event": "content", "data": json.dumps({
            "content": full_response, "type": content_type,
        }, ensure_ascii=False)}

    # Shared post-processing for both paths
    citation_check = validate_citations(full_response, chunks) if chunks else {}
    sources = [
        {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
        for c in chunks
    ] if chunks else []

    if citation_check:
        yield {"event": "citations", "data": json.dumps(citation_check, ensure_ascii=False)}
    if sources:
        yield {"event": "sources", "data": json.dumps(sources, ensure_ascii=False)}

    cove_result = None
    # CoVe 事实性验证（仅在有 RAG 材料且内容足够长时运行）
    should_verify = (
        chunks
        and len(full_response) > 200
        and intent in ("explore", "summarize", "websearch", "generate", "analyze")
    )
    logger.info(f"CoVe check: chunks={len(chunks)}, resp_len={len(full_response)}, intent={intent}, verify={should_verify}")
    if should_verify:
        try:
            from src.core.cove import async_run_cove
            cove_result = await async_run_cove(full_response, chunks)
            yield {"event": "verification", "data": json.dumps({
                "overall_score": cove_result.get("overall_score", 0.0),
                "summary": cove_result.get("summary", ""),
                "claim_count": len(cove_result.get("claims", [])),
                "flagged_count": len(cove_result.get("flagged_claims", [])),
                "flagged_claims": cove_result.get("flagged_claims", []),
                "error": cove_result.get("error"),
            }, ensure_ascii=False)}
        except Exception as e:
            logger.warning(f"CoVe 验证失败（非致命）: {e}")

    yield {"event": "done", "data": json.dumps({"type": content_type}, ensure_ascii=False)}

    # Build metadata for rich history reconstruction
    _msg_metadata = {
        "agent_timeline": agent_timeline,
        "intent": intent,
        "content_type": content_type,
    }
    if cove_result is not None:
        _msg_metadata["verification"] = {
            "overall_score": cove_result.get("overall_score", 0.0),
            "summary": cove_result.get("summary", ""),
            "claim_count": len(cove_result.get("claims", [])),
            "flagged_count": len(cove_result.get("flagged_claims", [])),
            "flagged_claims": cove_result.get("flagged_claims", []),
            "error": cove_result.get("error"),
        }
    if citation_check:
        _msg_metadata["citations"] = {
            "total": citation_check.get("total_citations", 0),
            "verified": citation_check.get("verified", 0),
        }
    if sources:
        _msg_metadata["sources"] = sources

    # Save assistant response to chat history
    try:
        project_memory.save_message(
            session_id, project_id, "assistant", full_response, intent,
            metadata=_msg_metadata,
        )
    except Exception as e:
        logger.warning(f"Failed to save assistant message: {e}")

    # Record eval
    try:
        from src.eval.metrics import record_eval

        # citation_accuracy: 优先用 CoVe overall_score，回退到 citation_check verification_rate
        if cove_result is not None:
            _citation_accuracy = cove_result.get("overall_score", 0.0)
            _hallucination_flag = len(cove_result.get("flagged_claims", [])) > 0
        elif citation_check:
            _citation_accuracy = citation_check.get("verification_rate", 0.0)
            _hallucination_flag = False
        else:
            _citation_accuracy = 0.0
            _hallucination_flag = False

        # 评估元数据（存入 metadata JSON 字段，供后续分析）
        _eval_meta = {}
        if cove_result is not None:
            _eval_meta["cove"] = {
                "claim_count": len(cove_result.get("claims", [])),
                "flagged_count": len(cove_result.get("flagged_claims", [])),
                "overall_score": cove_result.get("overall_score", 0.0),
            }
        if citation_check:
            _eval_meta["citations"] = {
                "total": citation_check.get("total_citations", 0),
                "verified": citation_check.get("verified", 0),
            }

        record_eval(
            session_id=session_id,
            project_id=project_id,
            intent=intent,
            task_type=content_type,
            success=True,
            response_time_ms=elapsed,
            has_citations=bool(citation_check),
            citation_accuracy=round(_citation_accuracy, 4),
            hallucination_flag=_hallucination_flag,
            llm_model="glm-4.7",
            metadata=_eval_meta if _eval_meta else None,
        )
    except Exception as e:
        logger.warning(f"Eval record failed: {e}")


# ========== Build Async Graph ==========

def build_async_graph():
    """构建异步版 LangGraph — Supervisor 模式，节点使用 async"""
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("responder", async_responder_node)
    workflow.add_node("writer", async_writer_node)
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


# 全局异步 graph 实例
_async_graph = None


def get_async_graph():
    global _async_graph
    if _async_graph is None:
        _async_graph = build_async_graph()
    return _async_graph

