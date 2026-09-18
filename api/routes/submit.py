"""论文投递路由 — 期刊推荐 + 格式检查"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Depends

from api.deps import require_auth
from api.schemas import JournalRecommendRequest, FormatCheckRequest, FormatApplyRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/submit/recommend")
async def recommend_journals_endpoint(req: JournalRecommendRequest, user: dict = Depends(require_auth)):
    """获取期刊推荐"""
    if not req.project_id or not req.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be empty")
    try:
        from src.core.submit import recommend_journals
        result = await asyncio.to_thread(
            recommend_journals,
            req.project_id,
            req.research_topic or "",
            req.top_k,
        )
        return {"journals": result, "total": len(result)}
    except Exception as e:
        logger.error(f"Journal recommendation failed: {e}", exc_info=True)
        return {"journals": [], "total": 0, "error": str(e)}


@router.post("/submit/format-check")
async def format_check_endpoint(req: FormatCheckRequest, user: dict = Depends(require_auth)):
    """格式检查"""
    if not req.project_id or not req.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be empty")
    if not req.journal_name or not req.journal_name.strip():
        raise HTTPException(status_code=422, detail="journal_name must not be empty")
    try:
        from src.core.submit import check_format
        result = await asyncio.to_thread(
            check_format,
            req.project_id,
            req.journal_name,
        )
        return result
    except Exception as e:
        logger.error(f"Format check failed: {e}", exc_info=True)
        return {"error": str(e), "checklist": []}


@router.post("/submit/format-apply")
async def format_apply_endpoint(req: FormatApplyRequest, user: dict = Depends(require_auth)):
    """应用格式修改"""
    if not req.project_id or not req.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must not be empty")
    try:
        from src.core.submit import apply_format_changes
        result = await asyncio.to_thread(
            apply_format_changes,
            req.project_id,
            req.section_name,
            req.suggestions,
        )
        return result
    except Exception as e:
        logger.error(f"Format apply failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
