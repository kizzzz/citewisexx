"""A/B Testing Framework for Agent Optimization"""
import json
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ABTestFramework:
    """Simple A/B test framework for comparing prompt/parameter variants"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT,
                variant TEXT,
                prompt_config TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now')),
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ab_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT,
                variant TEXT,
                session_id TEXT,
                success BOOLEAN,
                response_time_ms INTEGER,
                quality_score REAL DEFAULT 0,
                timestamp TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()

    def get_variant(self, test_name: str, session_id: str) -> str:
        """Deterministically assign variant based on session_id hash"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT DISTINCT variant FROM ab_tests WHERE test_name=? AND is_active=1",
            (test_name,)
        ).fetchall()
        conn.close()

        if not rows:
            return "default"

        variants = [r[0] for r in rows]
        hash_val = int(hashlib.md5(session_id.encode()).hexdigest(), 16)
        return variants[hash_val % len(variants)]

    def create_test(self, test_name: str, variants: dict[str, dict]):
        """Create a new A/B test with variants
        variants: {"A": {"prompt": "...", "temperature": 0.7}, "B": {...}}
        """
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        for name, config in variants.items():
            conn.execute(
                "INSERT INTO ab_tests (test_name, variant, prompt_config) VALUES (?, ?, ?)",
                (test_name, name, json.dumps(config, ensure_ascii=False))
            )
        conn.commit()
        conn.close()

    def record_result(self, test_name: str, variant: str, session_id: str,
                      success: bool, response_time_ms: int, quality_score: float = 0):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO ab_results (test_name, variant, session_id, success, response_time_ms, quality_score)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (test_name, variant, session_id, success, response_time_ms, quality_score)
        )
        conn.commit()
        conn.close()

    def get_test_results(self, test_name: str) -> dict:
        """Get comparative results for a test"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT variant,
                      COUNT(*) as total,
                      SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
                      AVG(response_time_ms) as avg_time,
                      AVG(quality_score) as avg_quality
               FROM ab_results WHERE test_name=?
               GROUP BY variant""",
            (test_name,)
        ).fetchall()
        conn.close()

        results = {}
        for r in rows:
            results[r[0]] = {
                "total": r[1],
                "successes": r[2],
                "success_rate": round(r[2]/r[1]*100, 1) if r[1] > 0 else 0,
                "avg_response_time": round(r[3] or 0, 0),
                "avg_quality": round(r[4] or 0, 2),
            }
        return results

    def deactivate_test(self, test_name: str):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE ab_tests SET is_active=0 WHERE test_name=?", (test_name,))
        conn.commit()
        conn.close()
