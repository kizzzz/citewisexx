"""AgentEval Dashboard — 评估可视化"""
import logging
from pydantic import BaseModel, Field
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()


class EvalMetricsRequest(BaseModel):
    days: int = Field(7, ge=1, le=365)


class EvalRateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=5)


@router.get("/eval/metrics")
async def get_eval_metrics(project_id: str = None, days: int = 7):
    days = max(1, min(365, days))
    from src.eval.metrics import get_metrics_summary, generate_optimization_suggestions
    metrics = get_metrics_summary(project_id, days)
    metrics["suggestions"] = generate_optimization_suggestions(metrics)
    return metrics


@router.get("/eval/trends")
async def get_eval_trends(project_id: str = None, days: int = 30):
    days = max(1, min(365, days))
    from src.eval.metrics import get_daily_trends
    return get_daily_trends(project_id, days)


@router.post("/eval/rate")
async def submit_user_rating(req: EvalRateRequest):
    """Submit user rating for a response"""
    from src.eval.metrics import _EVAL_DB_PATH
    if not _EVAL_DB_PATH:
        return {"status": "error", "message": "Eval DB not initialized"}
    import sqlite3
    conn = sqlite3.connect(_EVAL_DB_PATH)
    try:
        conn.execute(
            "UPDATE eval_records SET user_rating=? WHERE rowid = (SELECT rowid FROM eval_records WHERE session_id=? ORDER BY timestamp DESC LIMIT 1)",
            (req.rating, req.session_id)
        )
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Rating update failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
