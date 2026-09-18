"""记忆系统 - 三层架构（全局画像/项目记忆/工作记忆）"""
import json
import os
import uuid
import sqlite3
import logging
import tempfile
from datetime import datetime
from typing import Optional

from config.settings import DB_PATH, PROFILE_PATH, DATA_DIR

logger = logging.getLogger(__name__)


class GlobalProfile:
    """Layer 1: 全局用户画像"""

    def __init__(self):
        self.path = PROFILE_PATH
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._default()

    def _default(self) -> dict:
        return {
            "user_id": "user_001",
            "research_field": "",
            "focus_areas": [],
            "field_preferences": [],
            "field_templates": [],
            "writing_style": "academic_formal",
            "projects_history": [],
        }

    def save(self):
        dir_name = os.path.dirname(self.path)
        fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            os.unlink(tmp_path)
            raise

    def update(self, key: str, value):
        """更新画像字段"""
        self.data[key] = value
        self.save()

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def add_field_template(self, name: str, fields: list[str]):
        """添加字段模板"""
        template = {
            "name": name,
            "fields": fields,
            "usage_count": 1,
            "last_used": datetime.now().isoformat(),
        }
        self.data.setdefault("field_templates", []).append(template)
        self.save()

    def get_reusable_assets(self) -> dict:
        """获取可跨项目复用的资产"""
        templates = self.data.get("field_templates", [])
        last_template = templates[-1] if templates else None
        return {
            "default_template": last_template,
            "writing_style": self.data.get("writing_style", "academic_formal"),
            "research_field": self.data.get("research_field", ""),
        }


class _ConnContext:
    """Wraps sqlite3.Connection to auto-close on context exit."""
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False


class ProjectMemory:
    """Layer 2: 项目记忆（SQLite）"""

    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        # Wrap to auto-close on context exit
        return _ConnContext(conn)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    topic TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    config TEXT DEFAULT '{}',
                    user_id TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    title TEXT,
                    authors TEXT,
                    year INTEGER,
                    filename TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    raw_text TEXT DEFAULT '',
                    sections_json TEXT DEFAULT '[]',
                    indexed_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS extractions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    paper_id TEXT,
                    template_name TEXT,
                    fields TEXT DEFAULT '{}',
                    confidence TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS generated_sections (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    section_name TEXT,
                    content TEXT,
                    word_count INTEGER DEFAULT 0,
                    citations TEXT DEFAULT '[]',
                    generated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS figures (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT,
                    project_id TEXT,
                    page INTEGER,
                    caption TEXT,
                    context_before TEXT DEFAULT '',
                    context_after TEXT DEFAULT '',
                    section_title TEXT DEFAULT '',
                    width REAL DEFAULT 0,
                    height REAL DEFAULT 0,
                    metadata TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    api_key TEXT DEFAULT '',
                    api_key_encrypted TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    content TEXT NOT NULL DEFAULT '',
                    intent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_chat_project ON chat_messages(project_id);

                CREATE TABLE IF NOT EXISTS quick_notes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_url TEXT DEFAULT '',
                    note_type TEXT DEFAULT 'general',
                    status TEXT DEFAULT 'note',
                    linked_paper_ids TEXT DEFAULT '[]',
                    pinned INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_notes_project ON quick_notes(project_id);

                CREATE TABLE IF NOT EXISTS note_types (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    color TEXT DEFAULT 'slate',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_note_types_project ON note_types(project_id);

                CREATE TABLE IF NOT EXISTS section_chats (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    section_id TEXT NOT NULL,
                    section_name TEXT DEFAULT '',
                    role TEXT NOT NULL DEFAULT 'user',
                    content TEXT NOT NULL DEFAULT '',
                    intent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_section_chats_sid ON section_chats(section_id);
                CREATE INDEX IF NOT EXISTS idx_section_chats_pid ON section_chats(project_id);

                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    project_id TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    value_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_llm_cache_pid ON llm_cache(project_id);
                CREATE INDEX IF NOT EXISTS idx_llm_cache_cat ON llm_cache(category);
            """)
            # Migration: add columns if they don't exist (SQLite ALTER TABLE)
            try:
                conn.execute("ALTER TABLE papers ADD COLUMN raw_text TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE papers ADD COLUMN sections_json TEXT DEFAULT '[]'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN api_key TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN api_key_encrypted TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE users ADD COLUMN password_salt TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE quick_notes ADD COLUMN pinned INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE quick_notes ADD COLUMN sort_order INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN metadata TEXT DEFAULT '{}'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE papers ADD COLUMN avg_embedding TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE papers ADD COLUMN embedding_updated_at TEXT DEFAULT ''")
            except Exception:
                pass
            conn.commit()

    # --- 项目管理 ---
    def create_project(self, name: str, topic: str = "", user_id: str = "") -> str:
        pid = f"proj_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            conn.execute("INSERT INTO projects (id, name, topic, user_id) VALUES (?, ?, ?, ?)",
                         (pid, name, topic, user_id))
            conn.commit()
        return pid

    def get_project(self, project_id: str, user_id: str = "") -> Optional[dict]:
        with self._get_conn() as conn:
            if user_id:
                row = conn.execute("SELECT * FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self, user_id: str = "") -> list[dict]:
        with self._get_conn() as conn:
            if user_id:
                rows = conn.execute("SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, project_id: str, user_id: str = "") -> bool:
        with self._get_conn() as conn:
            if user_id:
                row = conn.execute("SELECT id FROM projects WHERE id=? AND user_id=?", (project_id, user_id)).fetchone()
            else:
                row = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM figures WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM generated_sections WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM extractions WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM papers WHERE project_id=?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            conn.commit()
        return True

    # --- 论文管理 ---
    def add_paper(self, paper_id: str, project_id: str, title: str,
                  authors: str, year: int, filename: str, chunk_count: int = 0,
                  raw_text: str = "", sections_json: str = "[]"):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO papers (id, project_id, title, authors, year, filename, chunk_count, raw_text, sections_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (paper_id, project_id, title, authors, year, filename, chunk_count, raw_text, sections_json)
            )
            conn.commit()

    def get_papers(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM papers WHERE project_id=?", (project_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_paper_row(self, paper_id: str) -> Optional[dict]:
        """获取单篇论文记录"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        return dict(row) if row else None

    def delete_paper_cascade(self, paper_id: str):
        """级联删除论文及其关联的图表和提取记录"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))
            conn.execute("DELETE FROM figures WHERE paper_id=?", (paper_id,))
            conn.execute("DELETE FROM extractions WHERE paper_id=?", (paper_id,))
            conn.commit()

    def update_section_by_id(self, section_id: str, content: str):
        """按 ID 更新章节内容"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE generated_sections SET content=?, word_count=? WHERE id=?",
                (content, len(content), section_id)
            )
            conn.commit()

    def get_section_by_id(self, section_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM generated_sections WHERE id=?", (section_id,)).fetchone()
        return dict(row) if row else None

    def get_paper_count(self, project_id: str) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM papers WHERE project_id=?",
                               (project_id,)).fetchone()
        return row["cnt"] if row else 0

    def update_paper_title(self, paper_id: str, title: str):
        """Update a paper's title"""
        with self._get_conn() as conn:
            conn.execute("UPDATE papers SET title=? WHERE id=?", (title, paper_id))
            conn.commit()

    # --- 提取结果 ---
    def save_extraction(self, project_id: str, paper_id: str,
                        template_name: str, fields: dict, confidence: dict):
        eid = f"ext_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO extractions (id, project_id, paper_id, template_name, fields, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, project_id, paper_id, template_name,
                 json.dumps(fields, ensure_ascii=False),
                 json.dumps(confidence, ensure_ascii=False))
            )
            conn.commit()

    def get_extractions(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            # 每篇论文只取最新一次提取，避免重复计数
            rows = conn.execute(
                "SELECT e.* FROM extractions e "
                "INNER JOIN (SELECT paper_id, MAX(created_at) as latest FROM extractions WHERE project_id=? GROUP BY paper_id) sub "
                "ON e.paper_id = sub.paper_id AND e.created_at = sub.latest "
                "WHERE e.project_id=?",
                (project_id, project_id)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["fields"] = json.loads(d["fields"]) if d["fields"] else {}
            d["confidence"] = json.loads(d["confidence"]) if d["confidence"] else {}
            results.append(d)
        return results

    # --- 生成记录 ---
    def save_section(self, project_id: str, section_name: str,
                     content: str, citations: list = None) -> str:
        sid = f"sec_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO generated_sections (id, project_id, section_name, content, word_count, citations) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, project_id, section_name, content, len(content),
                 json.dumps(citations or [], ensure_ascii=False))
            )
            conn.commit()
        return sid

    def get_sections(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM generated_sections WHERE project_id=? ORDER BY generated_at",
                (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_section(self, section_id: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM generated_sections WHERE id=?", (section_id,))
            conn.execute("DELETE FROM section_chats WHERE section_id=?", (section_id,))
            conn.commit()

    def get_unique_sections(self, project_id: str) -> list[dict]:
        """获取去重后的章节（同名只保留最新）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT s.* FROM generated_sections s "
                "INNER JOIN (SELECT section_name, MAX(generated_at) as latest FROM generated_sections WHERE project_id=? GROUP BY section_name) sub "
                "ON s.section_name = sub.section_name AND s.generated_at = sub.latest "
                "WHERE s.project_id=? ORDER BY s.generated_at",
                (project_id, project_id)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_project_state(self, project_id: str) -> dict:
        """获取项目完整状态"""
        project = self.get_project(project_id)
        if not project:
            return {}
        papers = self.get_papers(project_id)
        extractions = self.get_extractions(project_id)
        unique_sections = self.get_unique_sections(project_id)
        figures = self.get_all_figures(project_id)

        return {
            "name": project["name"],
            "topic": project.get("topic", ""),
            "paper_count": len(papers),
            "papers": papers,
            "extracted_fields": list(set(
                k for e in extractions for k in (e.get("fields") or {}).keys()
            )),
            "completed_sections": [s["section_name"] for s in unique_sections],
            "section_count": len(unique_sections),
            "sections_with_id": [{"id": s["id"], "name": s["section_name"]} for s in unique_sections],
            "extraction_count": len(extractions),
            "figure_count": len(figures),
        }

    # --- 图表管理 ---
    def add_figure(self, figure_id: str, paper_id: str, project_id: str,
                   page: int, caption: str, context_before: str = "",
                   context_after: str = "", section_title: str = "",
                   width: float = 0, height: float = 0):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO figures (id, paper_id, project_id, page, caption, "
                "context_before, context_after, section_title, width, height) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (figure_id, paper_id, project_id, page, caption,
                 context_before, context_after, section_title, width, height)
            )
            conn.commit()

    def get_figures(self, paper_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM figures WHERE paper_id=?", (paper_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_all_figures(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM figures WHERE project_id=? ORDER BY page", (project_id,)).fetchall()
        return [dict(r) for r in rows]

    # --- 随手记管理 ---
    def add_note(self, project_id: str, content: str, source_url: str = "",
                 note_type: str = "general") -> str:
        nid = f"note_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO quick_notes (id, project_id, content, source_url, note_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (nid, project_id, content, source_url, note_type)
            )
            conn.commit()
        return nid


    def get_note(self, note_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM quick_notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["linked_paper_ids"] = json.loads(d.get("linked_paper_ids", "[]"))
        return d

    def update_note(self, note_id: str, content: str = None, source_url: str = None,
                    note_type: str = None) -> bool:
        sets = []
        params = []
        if content is not None:
            sets.append("content=?")
            params.append(content)
        if source_url is not None:
            sets.append("source_url=?")
            params.append(source_url)
        if note_type is not None:
            sets.append("note_type=?")
            params.append(note_type)
        if not sets:
            return False
        sets.append("updated_at=datetime('now')")
        params.append(note_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE quick_notes SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
        return True

    def delete_note(self, note_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT id FROM quick_notes WHERE id=?", (note_id,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM quick_notes WHERE id=?", (note_id,))
            conn.commit()
        return True

    def update_note_linked_papers(self, note_id: str, paper_ids: list[str]) -> bool:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE quick_notes SET linked_paper_ids=?, updated_at=datetime('now') WHERE id=?",
                (json.dumps(paper_ids, ensure_ascii=False), note_id)
            )
            conn.commit()
        return True

    # --- 笔记类型管理 ---
    def seed_default_types(self, project_id: str):
        """首次访问时插入默认类型"""
        existing = self.get_note_types(project_id)
        if existing:
            return
        defaults = [
            ("通用笔记", "slate"),
            ("灵感", "amber"),
            ("摘录高亮", "blue"),
        ]
        with self._get_conn() as conn:
            for i, (name, color) in enumerate(defaults):
                tid = f"ntype_{uuid.uuid4().hex[:8]}"
                conn.execute(
                    "INSERT INTO note_types (id, project_id, name, color, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (tid, project_id, name, color, i)
                )
            conn.commit()

    def add_note_type(self, project_id: str, name: str, color: str = "slate") -> str:
        tid = f"ntype_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM note_types WHERE project_id=?",
                (project_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO note_types (id, project_id, name, color, sort_order) VALUES (?, ?, ?, ?, ?)",
                (tid, project_id, name, color, max_order + 1)
            )
            conn.commit()
        return tid

    def get_note_types(self, project_id: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM note_types WHERE project_id=? ORDER BY sort_order",
                (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_note_type(self, type_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM note_types WHERE id=?", (type_id,)).fetchone()
        return dict(row) if row else None

    def rename_note_type(self, type_id: str, name: str = None, color: str = None) -> bool:
        sets, params = [], []
        if name is not None:
            sets.append("name=?")
            params.append(name)
        if color is not None:
            sets.append("color=?")
            params.append(color)
        if not sets:
            return False
        params.append(type_id)
        with self._get_conn() as conn:
            conn.execute(f"UPDATE note_types SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
        return True

    def delete_note_type(self, type_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT name, project_id FROM note_types WHERE id=?", (type_id,)).fetchone()
            if not row:
                return False
            type_name, project_id = row["name"], row["project_id"]
            conn.execute(
                "UPDATE quick_notes SET note_type='通用笔记' WHERE note_type=? AND project_id=?",
                (type_name, project_id)
            )
            conn.execute("DELETE FROM note_types WHERE id=?", (type_id,))
            conn.commit()
        return True

    # --- 笔记排序与置顶 ---
    def toggle_pin(self, note_id: str) -> dict:
        with self._get_conn() as conn:
            row = conn.execute("SELECT pinned FROM quick_notes WHERE id=?", (note_id,)).fetchone()
            if not row:
                return {"error": "not_found"}
            new_pin = 0 if row["pinned"] else 1
            conn.execute(
                "UPDATE quick_notes SET pinned=?, updated_at=datetime('now') WHERE id=?",
                (new_pin, note_id)
            )
            conn.commit()
        return {"pinned": new_pin}

    def reorder_notes(self, ordered_ids: list[str]):
        with self._get_conn() as conn:
            for i, nid in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE quick_notes SET sort_order=? WHERE id=?",
                    (i, nid)
                )
            conn.commit()

    def get_notes(self, project_id: str, limit: int = 20, offset: int = 0,
                  note_type: str = None) -> list[dict]:
        with self._get_conn() as conn:
            query = "SELECT * FROM quick_notes WHERE project_id=?"
            params: list = [project_id]
            if note_type:
                query += " AND note_type=?"
                params.append(note_type)
            query += " ORDER BY pinned DESC, sort_order ASC, created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["linked_paper_ids"] = json.loads(d.get("linked_paper_ids", "[]"))
            results.append(d)
        return results

    # --- 笔记合并 ---
    def merge_notes(self, keep_id: str, absorb_ids: list[str]) -> dict:
        with self._get_conn() as conn:
            keep = conn.execute("SELECT * FROM quick_notes WHERE id=?", (keep_id,)).fetchone()
            if not keep:
                return {"error": "keep_not_found"}
            project_id = keep["project_id"]
            keep_content = keep["content"]
            keep_papers = set(json.loads(keep["linked_paper_ids"] or "[]"))
            absorb_contents = []
            absorbed_ids = []
            for aid in absorb_ids:
                row = conn.execute(
                    "SELECT content, project_id, linked_paper_ids FROM quick_notes WHERE id=?",
                    (aid,)
                ).fetchone()
                if not row or row["project_id"] != project_id:
                    continue
                absorb_contents.append(row["content"])
                absorbed_ids.append(aid)
                absorb_papers = json.loads(row["linked_paper_ids"] or "[]")
                keep_papers.update(absorb_papers)
            merged = keep_content
            if absorb_contents:
                merged += "\n\n---\n\n" + "\n\n---\n\n".join(absorb_contents)
            conn.execute(
                "UPDATE quick_notes SET content=?, linked_paper_ids=?, updated_at=datetime('now') WHERE id=?",
                (merged, json.dumps(list(keep_papers), ensure_ascii=False), keep_id)
            )
            for aid in absorbed_ids:
                conn.execute("DELETE FROM quick_notes WHERE id=?", (aid,))
            conn.commit()
        return {"merged_id": keep_id, "absorbed_count": len(absorb_contents)}

    # --- 用户管理 ---
    def create_user(self, username: str, password_hash: str, password_salt: str = "") -> Optional[str]:
        uid = f"user_{uuid.uuid4().hex[:8]}"
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, password_salt) VALUES (?, ?, ?, ?)",
                    (uid, username, password_hash, password_salt)
                )
                conn.commit()
            return uid
        except Exception:
            return None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def update_user_api_key(self, user_id: str, api_key: str):
        """Store API key (encrypted) — only saves a marker if key is provided"""
        import hashlib
        # Only store a hash marker, not the actual key
        key_marker = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else ""
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET api_key=?, api_key_encrypted=? WHERE id=?",
                         (key_marker if api_key else "", "yes" if api_key else "", user_id))
            conn.commit()

    def get_user_api_key(self, user_id: str) -> str:
        """Check if user has configured an API key (returns marker, not the actual key)"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT api_key_encrypted FROM users WHERE id=?", (user_id,)).fetchone()
        if row and row["api_key_encrypted"]:
            return "configured"
        return ""

    # --- 对话会话管理 ---
    def create_session(self, project_id: str, title: str = "") -> str:
        """创建新的对话会话，返回 session_id"""
        sid = f"sess_{uuid.uuid4().hex[:8]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO chat_sessions (id, project_id, title) VALUES (?, ?, ?)",
                (sid, project_id, title)
            )
            conn.commit()
        return sid

    def list_sessions(self, project_id: str, limit: int = 20) -> list[dict]:
        """列出项目的对话会话"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_sessions WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话信息"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_session_title(self, session_id: str, title: str) -> bool:
        """更新会话标题"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE chat_sessions SET title=? WHERE id=?",
                (title, session_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_session(self, session_id: str):
        """删除会话及其消息"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
            conn.commit()

    def save_message(self, session_id: str, project_id: str,
                     role: str, content: str, intent: str = "",
                     metadata: dict = None):
        """保存一条对话消息，metadata 可存放 agent_timeline / verification 等富数据"""
        mid = f"msg_{uuid.uuid4().hex[:8]}"
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO chat_messages (id, session_id, project_id, role, content, intent, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mid, session_id, project_id, role, content, intent, meta_json)
            )
            conn.commit()

    def get_session_messages(self, session_id: str, limit: int = 20) -> list[dict]:
        """获取会话的最近 N 条消息"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, intent, metadata FROM chat_messages "
                "WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        # Return in chronological order (oldest first), parse metadata JSON
        messages = []
        for r in reversed(rows):
            msg = {"role": r["role"], "content": r["content"], "intent": r["intent"]}
            try:
                msg["metadata"] = json.loads(r["metadata"]) if r["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                msg["metadata"] = {}
            messages.append(msg)
        return messages

    # --- 章节协作面板对话（section_chats）---
    def save_section_chat(self, project_id: str, section_id: str,
                          role: str, content: str,
                          section_name: str = "", intent: str = "") -> str:
        """持久化协作面板的一条消息（user / assistant）。"""
        cid = f"sch_{uuid.uuid4().hex[:10]}"
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO section_chats (id, project_id, section_id, section_name, role, content, intent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, project_id, section_id, section_name, role, content, intent)
            )
            conn.commit()
        return cid

    def list_section_chats(self, section_id: str, limit: int = 200) -> list[dict]:
        """按时间正序返回某章节的协作面板历史。

        Uses rowid (monotonic insert order) rather than created_at because the
        latter has only second-level resolution — rapid back-to-back messages
        would otherwise tie and sort non-deterministically.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, intent, section_name, created_at FROM section_chats "
                "WHERE section_id=? ORDER BY rowid DESC LIMIT ?",
                (section_id, limit)
            ).fetchall()
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "intent": r["intent"],
                "section_name": r["section_name"],
                "created_at": r["created_at"],
            }
            for r in reversed(rows)
        ]

    def delete_section_chats(self, section_id: str) -> int:
        """删除某章节的全部对话（章节被删除时调用）。"""
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM section_chats WHERE section_id=?", (section_id,)
            )
            conn.commit()
            return cur.rowcount

    # --- 论文级平均向量缓存（avg_embedding）---
    def save_paper_embedding(self, paper_id: str, embedding: list[float]) -> None:
        """缓存 paper-level 平均向量（JSON 字符串）。"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE papers SET avg_embedding=?, embedding_updated_at=datetime('now') WHERE id=?",
                (json.dumps(embedding, ensure_ascii=False), paper_id)
            )
            conn.commit()

    def get_paper_embedding_cached(self, paper_id: str) -> Optional[list[float]]:
        """读取缓存的 paper 平均向量，无则返回 None。"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT avg_embedding FROM papers WHERE id=?", (paper_id,)
            ).fetchone()
        if not row:
            return None
        raw = row["avg_embedding"] if row["avg_embedding"] else ""
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, TypeError):
            return None
        return None

    # --- LLM 结果缓存（持久化到 SQLite，重启不丢）---
    def cache_get(self, category: str, cache_key: str) -> Optional[object]:
        """Read a cached JSON value. Returns None on miss."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value_json FROM llm_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value_json"])
        except (json.JSONDecodeError, TypeError):
            return None

    def cache_set(self, category: str, cache_key: str, value, project_id: str = "") -> None:
        """Persist a JSON-serialisable value under (category, cache_key)."""
        payload = json.dumps(value, ensure_ascii=False)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, project_id, category, value_json) "
                "VALUES (?, ?, ?, ?)",
                (cache_key, project_id, category, payload),
            )
            conn.commit()

    def cache_delete_category(self, project_id: str, category: str) -> int:
        """Invalidate all cached entries of a category for a project."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM llm_cache WHERE project_id=? AND category=?",
                (project_id, category),
            )
            conn.commit()
            return cur.rowcount


class WorkingMemory:
    """Layer 3: 工作记忆（会话级，内存）"""

    def __init__(self):
        self.current_project_id: Optional[str] = None
        self.current_task: Optional[str] = None
        self.focus_paper: Optional[str] = None
        self.pending_confirmation: Optional[dict] = None
        self.section_summaries: list[dict] = []  # 滑动窗口摘要
        self.max_summary_tokens: int = 2000

    def add_section_summary(self, section_name: str, summary: str, word_count: int):
        """添加章节摘要到滑动窗口"""
        self.section_summaries.append({
            "section": section_name,
            "summary": summary,
            "word_count": word_count,
        })
        self._compress_if_needed()

    def get_previous_summary(self) -> str:
        """获取前文摘要"""
        if not self.section_summaries:
            return "（这是第一章，无前文）"
        parts = [f"【{s['section']}】{s['summary']}" for s in self.section_summaries]
        return "\n\n".join(parts)

    def _compress_if_needed(self):
        """如果摘要过长，压缩早期摘要"""
        max_iterations = len(self.section_summaries)
        iteration = 0
        while iteration < max_iterations:
            total = sum(len(s["summary"]) for s in self.section_summaries)
            if total <= self.max_summary_tokens or len(self.section_summaries) <= 1:
                break
            oldest = self.section_summaries[0]
            compressed = oldest["summary"][:200] + "..."
            if len(compressed) >= len(oldest["summary"]):
                # Already compressed, pop it to avoid infinite loop
                self.section_summaries.pop(0)
            else:
                self.section_summaries[0]["summary"] = compressed
            iteration += 1

    def reset(self):
        """重置工作记忆（新会话）"""
        self.current_task = None
        self.focus_paper = None
        self.pending_confirmation = None
        self.section_summaries = []

    def reset_for_project(self, project_id: str):
        """切换项目时重置（保留全局摘要缓存）"""
        if self.current_project_id != project_id:
            self.current_project_id = project_id
            self.current_task = None
            self.focus_paper = None
            self.pending_confirmation = None
            # Keep section_summaries as they may be reused


# 全局单例
global_profile = GlobalProfile()
project_memory = ProjectMemory()
working_memory = WorkingMemory()
