"""章节管理路由"""
import asyncio
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse

from api.deps import require_auth, verify_project_owner
from api.schemas import SectionCreate, SectionUpdate
from src.eval.metrics import record_eval

logger = logging.getLogger(__name__)
router = APIRouter()

# Valid section ID pattern: sec_ followed by hex characters
SECTION_ID_PATTERN = re.compile(r'^sec_[0-9a-f]+$')


@router.get("/sections")
async def list_sections(project_id: str, user: dict = Depends(require_auth)):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    return project_memory.get_unique_sections(project_id)


@router.get("/sections/{section_id}/chats")
async def get_section_chats(section_id: str, user: dict = Depends(require_auth)):
    """读取章节协作面板的历史对话（持久化）"""
    if not SECTION_ID_PATTERN.match(section_id):
        raise HTTPException(status_code=400, detail="Invalid section ID format")
    from src.core.memory import project_memory
    section = project_memory.get_section_by_id(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    verify_project_owner(section["project_id"], user["user_id"])
    return {"messages": project_memory.list_section_chats(section_id)}


@router.delete("/sections/{section_id}/chats")
async def clear_section_chats(section_id: str, user: dict = Depends(require_auth)):
    """清空某章节协作面板的全部历史对话（用于「新对话」上下文隔离）。

    注意：不会删除章节内容本身，只清空对话。
    """
    if not SECTION_ID_PATTERN.match(section_id):
        raise HTTPException(status_code=400, detail="Invalid section ID format")
    from src.core.memory import project_memory
    section = project_memory.get_section_by_id(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    verify_project_owner(section["project_id"], user["user_id"])
    deleted = project_memory.delete_section_chats(section_id)
    return {"status": "ok", "deleted": deleted}


@router.post("/sections")
async def create_section(req: SectionCreate, user: dict = Depends(require_auth)):
    verify_project_owner(req.project_id, user["user_id"])
    from src.core.agents.coordinator import coordinator
    from src.core.memory import project_memory

    if not req.name or not req.name.strip():
        raise HTTPException(status_code=422, detail="Section name must not be empty")
    if req.target_length < 200 or req.target_length > 10000:
        raise HTTPException(status_code=422, detail="target_length must be between 200 and 10000")
    if req.agent not in ("writer", "analyst"):
        req.agent = "writer"

    try:
        start_time = time.time()
        result = await asyncio.to_thread(
            coordinator.process,
            f"帮我写{req.name}", req.project_id,
            section_name=req.name,
            gen_params={
                "style": req.style,
                "target_length": req.target_length,
                "citation_density": req.citation_density,
            },
            agent_choice=req.agent,
            system_prompt=req.system_prompt,
            requirements=req.requirements,
        )

        # Writer agent 内部已保存，这里不再重复保存，只取内容
        content = result.get("content", "")
        citations = result.get("citations", [])
        section_id = result.get("section_id")

        # Fallback: if section_id lost in graph state, find from DB
        if not section_id:
            unique = project_memory.get_unique_sections(req.project_id)
            for s in unique:
                if s["section_name"] == req.name:
                    section_id = s["id"]
                    break

        # Record eval
        try:
            citation_check = result.get("citations") if isinstance(result.get("citations"), dict) else {}
            _citation_accuracy = citation_check.get("verification_rate", 0.0) if citation_check else 0.0
            _eval_meta = {}
            if citation_check:
                _eval_meta["citations"] = {
                    "total": citation_check.get("total_citations", 0),
                    "verified": citation_check.get("verified", 0),
                }
            record_eval(
                session_id=f"s_{req.project_id}_{int(time.time())}",
                project_id=req.project_id,
                intent="generate",
                task_type="section",
                success=bool(content),
                response_time_ms=int((time.time() - start_time) * 1000),
                has_citations=bool(citation_check),
                citation_accuracy=round(_citation_accuracy, 4),
                llm_model="glm-4.7",
                metadata=_eval_meta if _eval_meta else None,
            )
        except Exception as e:
            logger.warning(f"Section eval record failed: {e}")

        return {
            "section_id": section_id,
            "section_name": req.name,
            "content": content,
            "type": result.get("type", "section"),
            "citations": citations,
            "sources": result.get("sources"),
            "thinking_steps": result.get("thinking_steps", []),
        }
    except Exception as e:
        logger.error(f"Section creation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成章节内容失败: {str(e)[:200]}")


@router.put("/sections/{section_id}")
async def update_section(section_id: str, req: SectionUpdate, user: dict = Depends(require_auth)):
    if not SECTION_ID_PATTERN.match(section_id):
        raise HTTPException(status_code=400, detail="Invalid section ID format")
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=422, detail="Content must not be empty")
    from src.core.memory import project_memory
    section = project_memory.get_section_by_id(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    verify_project_owner(section["project_id"], user["user_id"])
    project_memory.update_section_by_id(section_id, req.content)

    # 人工编辑可能引入新的引用，保存时重新核验（只报告，不改写用户文字）
    citation_report = {}
    try:
        from src.core.source_annotation import check_inline_citations
        _, citation_report = check_inline_citations(req.content, section["project_id"])
    except Exception as e:
        logger.warning(f"Inline citation check failed: {e}")
    return {"status": "ok", "citation_report": citation_report}


@router.post("/sections/{section_id}/verify-citations")
async def verify_section_citations(section_id: str, user: dict = Depends(require_auth)):
    """按项目知识库核验某章节正文的内联引用"""
    if not SECTION_ID_PATTERN.match(section_id):
        raise HTTPException(status_code=400, detail="Invalid section ID format")
    from src.core.memory import project_memory
    section = project_memory.get_section_by_id(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    verify_project_owner(section["project_id"], user["user_id"])

    from src.core.source_annotation import check_inline_citations
    marked, report = check_inline_citations(section.get("content", ""), section["project_id"])
    return {"section_id": section_id, "content": marked, "citation_report": report}


@router.delete("/sections/{section_id}")
async def delete_section(section_id: str, user: dict = Depends(require_auth)):
    if not SECTION_ID_PATTERN.match(section_id):
        raise HTTPException(status_code=400, detail="Invalid section ID format")
    from src.core.memory import project_memory
    section = project_memory.get_section_by_id(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    verify_project_owner(section["project_id"], user["user_id"])
    project_memory.delete_section(section_id)
    return {"status": "ok"}


@router.get("/sections/export")
async def export_document(project_id: str, allow_unverified: bool = False,
                          user: dict = Depends(require_auth)):
    """导出所有章节为 Markdown 文档

    导出前统一重新核验正文内联引用（人工编辑后的内容也会被重新核验）。
    只要存在无法在项目知识库中核验的引用，默认拦截导出并返回 409，
    由调用方确认后带 allow_unverified=true 再次请求。
    """
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    from src.core.source_annotation import UNVERIFIED_MARK, check_inline_citations

    sections = project_memory.get_unique_sections(project_id)
    proj = project_memory.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    doc = f"# {proj['name']}\n\n"
    total, unverified_items = 0, []
    for s in sections:
        content = s["content"]
        try:
            content, report = check_inline_citations(content, project_id)
            total += report.get("total", 0)
            for item in report.get("items", []):
                unverified_items.append({"section": s["section_name"], "citation": item})
        except Exception as e:
            logger.warning(f"Inline citation check failed on export: {e}")
        doc += f"## {s['section_name']}\n\n{content}\n\n---\n\n"

    if unverified_items and not allow_unverified:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "unverified_citations",
                "message": f"检测到 {len(unverified_items)} 处无法在项目知识库中核验的引用，已拦截导出",
                "total_citations": total,
                "unverified": unverified_items[:50],
            },
        )

    if unverified_items:
        doc += (
            f"> 导出提示：本文档含 {len(unverified_items)} 处未能在项目知识库中核验的引用，"
            f"已用 {UNVERIFIED_MARK} 标记，请人工确认后再对外使用。\n"
        )

    filename = proj["name"].replace(" ", "_")
    return PlainTextResponse(
        content=doc,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}.md"},
    )
