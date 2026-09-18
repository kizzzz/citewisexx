"""联网搜索路由"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Depends

from api.deps import require_auth
from api.schemas import SearchRequest

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_QUERY_LENGTH = 200


@router.post("/search")
async def web_search_endpoint(req: SearchRequest, user: dict = Depends(require_auth)):
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=422, detail="Query must not be empty")
    if len(req.query) > MAX_QUERY_LENGTH:
        raise HTTPException(status_code=422, detail=f"Query must not exceed {MAX_QUERY_LENGTH} characters")
    from src.tools.web_search import web_search_with_llm_summary
    try:
        result = await asyncio.to_thread(web_search_with_llm_summary, req.query)
        return result
    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        return {"web_results": [], "llm_knowledge": "", "error": "搜索服务暂时不可用，请稍后重试"}
