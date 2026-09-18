"""聊天路由 — LangGraph 流式响应（token 级流式 + agent_start/agent_end）"""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from api.deps import require_auth, verify_project_owner
from api.schemas import ChatRequest, SubChatRequest, SessionRenameRequest
from src.eval.metrics import record_eval

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_MESSAGE_LENGTH = 2000

# 需要监听的 LangGraph 节点名
_AGENT_NODES = {"supervisor", "researcher", "responder", "writer", "analyst"}


@router.post("/chat")
async def chat_endpoint(req: ChatRequest, user: dict = Depends(require_auth)):
    """主对话 — 真正的 token 级 SSE 流式输出"""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be empty")
    if len(req.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=422, detail=f"Message must not exceed {MAX_MESSAGE_LENGTH} characters")
    if not req.project_id or not req.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be empty")
    verify_project_owner(req.project_id, user["user_id"])

    async def event_generator():
        try:
            from src.core.async_graph import stream_chat_response

            async for event in stream_chat_response(
                req.message, req.project_id,
                api_key=req.api_key or None,
                base_url=req.base_url or None,
                model=req.model or None,
                session_id=req.session_id or None,
            ):
                yield event

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            yield {"event": "error", "data": json.dumps({"message": "处理请求时发生错误，请稍后重试"}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/chat/sub")
async def sub_chat_endpoint(req: SubChatRequest, user: dict = Depends(require_auth)):
    """子对话 — 章节协作面板

    Intent routing:
      * modify  — message 含「修改/改写/续写/扩展/精简/替换/删/加」等动词 → 调
        coordinator with intent=modify → 返回修改后的完整章节，前端更新编辑区。
      * chat    — 其他（提问、讨论、确认）→ 直接调 LLM 基于章节上下文回答，
        **不**触发改章节动作。前端只追加 AI 回复，保持章节内容不变。

    Both paths persist user + assistant messages into section_chats so reload
    never loses the conversation.
    """
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be empty")
    if len(req.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=422, detail=f"Message must not exceed {MAX_MESSAGE_LENGTH} characters")
    if not req.project_id or not req.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be empty")
    verify_project_owner(req.project_id, user["user_id"])
    start_time = time.time()
    try:
        from src.core.llm import llm_client, LLMError
        from src.core.memory import project_memory
        from src.core.prompt import SYSTEM_PROMPT_BASE

        # Resolve section_id so we can persist the conversation alongside the section.
        section_id = getattr(req, "section_id", "") or ""
        if not section_id:
            for s in project_memory.get_unique_sections(req.project_id):
                if s.get("section_name") == req.section_name:
                    section_id = s.get("id", "")
                    break

        # Persist the user side BEFORE the LLM call so the message survives
        # any timeout / crash.
        if section_id:
            try:
                project_memory.save_section_chat(
                    req.project_id, section_id,
                    role="user", content=req.message,
                    section_name=req.section_name, intent="pending",
                )
            except Exception as e:
                logger.warning(f"save_section_chat(user) failed: {e}")

        # --- Intent detection -------------------------------------------------
        intent = _detect_sub_intent(req.message)

        if intent == "modify":
            content, rtype = await asyncio.to_thread(
                _run_modify_path,
                req.message, req.content, req.section_name,
                req.project_id, req.api_key, req.base_url,
            )
            # Persist the modified section content.
            if content and rtype != "error":
                try:
                    project_memory.save_section(req.project_id, req.section_name, content)
                except Exception as e:
                    logger.warning(f"save_section(modify) failed: {e}")
        else:
            # Q&A / discussion path — pure LLM chat with section as context.
            content, rtype = await asyncio.to_thread(
                _run_chat_path,
                req.message, req.content, req.section_name,
                req.api_key, req.base_url,
            )

        # Persist assistant reply (always, even on failure).
        if section_id:
            reply_to_save = content if content else "（Agent 处理失败，请重试或调整指令）"
            try:
                project_memory.save_section_chat(
                    req.project_id, section_id,
                    role="assistant", content=reply_to_save,
                    section_name=req.section_name,
                    intent=("error" if not content else rtype),
                )
            except Exception as e:
                logger.warning(f"save_section_chat(assistant) failed: {e}")

        # Eval record (best-effort).
        try:
            record_eval(
                session_id=f"s_{req.project_id}_{int(time.time())}",
                project_id=req.project_id,
                intent=intent,
                task_type=rtype or "text",
                success=bool(content) and rtype != "error",
                response_time_ms=int((time.time() - start_time) * 1000),
                has_citations=False,
                citation_accuracy=0.0,
                llm_model="glm-4.7",
                metadata=None,
            )
        except Exception as e:
            logger.warning(f"Sub-chat eval record failed: {e}")

        return {
            "content": content,
            "type": rtype,
            "intent": intent,
            "section_id": section_id,
        }
    except Exception as e:
        logger.error(f"Sub-chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="处理出错，请稍后重试")


# Keywords that signal the user wants the section actually rewritten.
# Keep order‑agnostic and Chinese‑friendly; adding English synonyms is safe.
_MODIFY_KEYWORDS = (
    "修改", "改写", "重写", "续写", "扩展", "精简", "精炼", "替换",
    "删掉", "删除", "去掉", "添加", "加入", "补充", "调整", "改成",
    "转换为", "翻译", "润色", "改一下", "修改一下", "请改",
)


def _detect_sub_intent(message: str) -> str:
    """Heuristic: return 'modify' if the message clearly asks to edit the
    section, otherwise 'chat' (Q&A / discussion / confirmation).

    Why heuristic over LLM classification: this runs on every sub-chat message
    and needs to be fast + deterministic. Misrouting a rare ambiguous case is
    recoverable (user just re-phrases); adding another LLM round-trip here
    would noticeably slow the panel.
    """
    msg = (message or "").strip()
    if not msg:
        return "chat"
    if any(kw in msg for kw in _MODIFY_KEYWORDS):
        return "modify"
    return "chat"


def _run_modify_path(message: str, content: str, section_name: str,
                     project_id: str, api_key: str, base_url: str) -> tuple[str, str]:
    """Synchronous helper executed in a worker thread.

    Uses the LangGraph coordinator with intent=modify so the Writer agent
    rewrites the section. Returns (content, type).
    """
    from src.core.agents.coordinator import coordinator

    augmented_prompt = (
        f"用户正在撰写论文的「{section_name}」章节。\n\n"
        f"当前章节内容：\n{content[:3000]}\n\n"
        f"用户修改指令：{message}\n\n"
        f"请严格按用户指令修改「{section_name}」章节，直接输出修改后的完整章节内容。"
    )
    try:
        result = coordinator.process(
            augmented_prompt, project_id,
            intent="modify",
            target_content=content,
            api_key=api_key or None,
            base_url=base_url or None,
        )
    except Exception as e:
        logger.error(f"coordinator.process(modify) failed: {e}", exc_info=True)
        return "", "error"

    return result.get("content", ""), result.get("type", "modify")


def _run_chat_path(message: str, content: str, section_name: str,
                   api_key: str, base_url: str) -> tuple[str, str]:
    """Synchronous helper: answer a Q&A / discussion message WITHOUT touching
    the section content.

    Prompt strategy:
      - System: CiteWise assistant, answer in Chinese, be concise.
      - User: current section (as read-only context) + the user's question.

    The LLM's reply is returned verbatim as the assistant bubble. Section
    content is never modified by this path.
    """
    from src.core.llm import llm_client, LLMError

    # Apply API key override if the user provided one (same pattern as main chat).
    override_applied = False
    if api_key:
        try:
            llm_client.set_override(api_key, base_url)
            override_applied = True
        except Exception:
            pass

    try:
        prompt = (
            f"用户正在阅读/撰写论文的「{section_name}」章节，当前内容如下（仅供参考，不要修改）：\n\n"
            f"{content[:3000]}\n\n"
            f"用户的提问/讨论：{message}\n\n"
            f"请基于上述章节上下文回答用户的问题。要求：\n"
            f"1. 用中文回答，条理清晰\n"
            f"2. 直接回答问题，不要重复章节原文\n"
            f"3. 如果章节中没有相关信息，明确说明并基于你的知识作答\n"
            f"4. 不要修改章节内容，不要输出 JSON"
        )
        try:
            reply = llm_client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT_BASE},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                model="glm-4.7",
            )
        except LLMError as e:
            logger.error(f"sub-chat LLM call failed: {e}")
            return "", "error"
        return (reply or "").strip(), "text"
    finally:
        if override_applied:
            try:
                llm_client.clear_override()
            except Exception as clear_err:
                logger.error(f"Failed to clear LLM override: {clear_err}")


# --- Session Management ---

@router.get("/sessions")
async def list_sessions(project_id: str, user: dict = Depends(require_auth)):
    """列出项目的对话会话"""
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    sessions = project_memory.list_sessions(project_id)
    return sessions


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: int = 20, user: dict = Depends(require_auth)):
    """获取会话消息历史"""
    from src.core.memory import project_memory
    session = project_memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    verify_project_owner(session.get("project_id", ""), user["user_id"])
    messages = project_memory.get_session_messages(session_id, limit=limit)
    return messages


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(require_auth)):
    """删除对话会话"""
    from src.core.memory import project_memory
    session = project_memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    verify_project_owner(session.get("project_id", ""), user["user_id"])
    project_memory.delete_session(session_id)
    return {"status": "ok"}


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: SessionRenameRequest, user: dict = Depends(require_auth)):
    """重命名对话会话"""
    from src.core.memory import project_memory
    session = project_memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    verify_project_owner(session.get("project_id", ""), user["user_id"])
    ok = project_memory.update_session_title(session_id, req.title)
    if not ok:
        raise HTTPException(status_code=500, detail="更新失败")
    return {"status": "ok"}


@router.post("/sessions")
async def create_session(project_id: str, title: str = "", user: dict = Depends(require_auth)):
    """创建新的对话会话"""
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    session_id = project_memory.create_session(project_id, title)
    return {"session_id": session_id}
