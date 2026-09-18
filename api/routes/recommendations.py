"""文献推荐路由"""
import logging

from fastapi import APIRouter, Depends

from api.deps import require_auth, verify_project_owner

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/recommendations")
async def get_recommendations(project_id: str, top_k: int = 5, user: dict = Depends(require_auth)):
    """获取文献推荐（async + 并发 + 兜底降级）

    详见 ``src.core.recommender.get_recommendations_async``。
    整体上限 12s，任何子步骤失败都会降级到项目内已有论文作为推荐，
    保证前端永远不会卡在"加载中"。
    """
    verify_project_owner(project_id, user["user_id"])
    from src.core.recommender import get_recommendations_async

    try:
        recs = await get_recommendations_async(project_id, top_k=top_k)
        return {"recommendations": recs, "total": len(recs)}
    except Exception as e:
        logger.error(f"Recommendation failed: {e}", exc_info=True)
        return {"recommendations": [], "total": 0, "error": str(e)}
