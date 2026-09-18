"""AgentEval — 5大核心评估指标"""
import time
import json
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# SQLite table for eval records
_EVAL_DB_PATH = None  # Set during init


def init_eval_db(db_path: str):
    """Initialize evaluation database table"""
    global _EVAL_DB_PATH
    _EVAL_DB_PATH = db_path
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            session_id TEXT,
            project_id TEXT,
            intent TEXT,
            task_type TEXT,
            success BOOLEAN,
            response_time_ms INTEGER,
            token_count INTEGER,
            has_citations BOOLEAN,
            citation_accuracy REAL DEFAULT 0,
            hallucination_flag BOOLEAN DEFAULT FALSE,
            llm_model TEXT,
            prompt_version TEXT DEFAULT 'v1',
            user_rating INTEGER,
            cost_estimate REAL DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        )
    """)
    conn.commit()
    conn.close()


def record_eval(
    session_id: str,
    project_id: str,
    intent: str,
    task_type: str,
    success: bool,
    response_time_ms: int,
    token_count: int = 0,
    has_citations: bool = False,
    citation_accuracy: float = 0,
    hallucination_flag: bool = False,
    llm_model: str = "",
    prompt_version: str = "v1",
    user_rating: Optional[int] = None,
    cost_estimate: float = 0,
    metadata: Optional[dict] = None,
):
    """Record a single evaluation event"""
    if not _EVAL_DB_PATH:
        return
    import sqlite3
    conn = sqlite3.connect(_EVAL_DB_PATH)
    try:
        conn.execute(
            """INSERT INTO eval_records
            (session_id, project_id, intent, task_type, success, response_time_ms,
             token_count, has_citations, citation_accuracy, hallucination_flag,
             llm_model, prompt_version, user_rating, cost_estimate, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, project_id, intent, task_type, success, response_time_ms,
             token_count, has_citations, citation_accuracy, hallucination_flag,
             llm_model, prompt_version, user_rating, cost_estimate,
             json.dumps(metadata or {}, ensure_ascii=False))
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Eval record failed: {e}")
    finally:
        conn.close()


def get_metrics_summary(project_id: Optional[str] = None, days: int = 7) -> dict:
    """Get aggregated metrics for dashboard"""
    if not _EVAL_DB_PATH:
        return {}
    import sqlite3
    conn = sqlite3.connect(_EVAL_DB_PATH)

    try:
        params: list = []
        safe_days = max(1, min(365, int(days)))
        where = f"WHERE timestamp >= datetime('now', '-{safe_days} days')"
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)

        total = conn.execute(f"SELECT COUNT(*) FROM eval_records {where}", params).fetchone()[0]
        success = conn.execute(f"SELECT COUNT(*) FROM eval_records {where} AND success=1", params).fetchone()[0]
        success_rate = (success / total * 100) if total > 0 else 0

        acc_rows = conn.execute(f"SELECT AVG(citation_accuracy) FROM eval_records {where} AND citation_accuracy > 0", params).fetchone()
        avg_accuracy = acc_rows[0] if acc_rows and acc_rows[0] else 0

        halluc = conn.execute(f"SELECT COUNT(*) FROM eval_records {where} AND hallucination_flag=1", params).fetchone()[0]
        halluc_rate = (halluc / total * 100) if total > 0 else 0

        avg_time = conn.execute(f"SELECT AVG(response_time_ms) FROM eval_records {where}", params).fetchone()[0] or 0

        avg_cost = conn.execute(f"SELECT AVG(cost_estimate) FROM eval_records {where}", params).fetchone()[0] or 0
        total_cost = conn.execute(f"SELECT SUM(cost_estimate) FROM eval_records {where}", params).fetchone()[0] or 0

        return {
            "total_tasks": total,
            "success_count": success,
            "success_rate": round(success_rate, 1),
            "avg_accuracy": round(avg_accuracy, 3),
            "hallucination_count": halluc,
            "hallucination_rate": round(halluc_rate, 1),
            "avg_response_time_ms": round(avg_time, 0),
            "avg_cost": round(avg_cost, 6),
            "total_cost": round(total_cost, 4),
            "period_days": days,
        }
    except Exception as e:
        logger.error(f"Metrics query failed: {e}")
        return {}
    finally:
        conn.close()


def get_daily_trends(project_id: Optional[str] = None, days: int = 30) -> list[dict]:
    """Get daily metrics for trend charts"""
    if not _EVAL_DB_PATH:
        return []
    import sqlite3
    conn = sqlite3.connect(_EVAL_DB_PATH)
    try:
        params: list = []
        safe_days = max(1, min(365, int(days)))
        where = f"WHERE timestamp >= datetime('now', '-{safe_days} days')"
        if project_id:
            where += " AND project_id=?"
            params.append(project_id)

        rows = conn.execute(f"""
            SELECT DATE(timestamp) as day,
                   COUNT(*) as total,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
                   AVG(response_time_ms) as avg_time,
                   AVG(cost_estimate) as avg_cost
            FROM eval_records {where}
            GROUP BY DATE(timestamp)
            ORDER BY day
        """, params).fetchall()

        return [{"date": r[0], "total": r[1], "successes": r[2], "avg_time": r[3], "avg_cost": r[4]} for r in rows]
    except Exception as e:
        logger.error(f"Daily trends query failed: {e}")
        return []
    finally:
        conn.close()


def generate_optimization_suggestions(metrics: dict) -> list[str]:
    """Auto-generate optimization suggestions based on metrics"""
    suggestions = []
    if metrics.get("success_rate", 100) < 85:
        suggestions.append("⚠️ 任务成功率低于85%，建议优化意图路由和错误处理")
    if metrics.get("hallucination_rate", 0) > 10:
        suggestions.append("⚠️ 幻觉率超过10%，建议增强RAG检索质量和CoVe验证")
    if metrics.get("avg_response_time_ms", 0) > 10000:
        suggestions.append("⚠️ 平均响应时间超过10秒，建议优化LLM调用或减少上下文长度")
    if metrics.get("avg_accuracy", 1) < 0.8:
        suggestions.append("⚠️ 引用准确率低于80%，建议优化retriever或增加重排序步骤")
    if not suggestions:
        suggestions.append("✅ 所有指标表现良好，继续保持！")
    return suggestions
