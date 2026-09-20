#!/usr/bin/env python3
"""清理验收测试账号及其关联数据（仅删除测试用户，保留真实用户）。

测试账号命名规则（均由验证脚本生成）：
  e2e<hex8> / e2e<hex8>b  —— e2e_validate.py
  v<hex8>                 —— e2e_recheck.py
  ragcheck* / acceptance  —— 早期验收脚本

用法：
  python3 cleanup_test_users.py --dry-run   # 只打印将删除的内容
  python3 cleanup_test_users.py --apply     # 实际删除
"""
import argparse
import re
import sqlite3
import sys

DB = "/app/data/db/citewise.db"
PATTERNS = [
    re.compile(r'^e2e[0-9a-f]{8}b?$'),
    re.compile(r'^v[0-9a-f]{8}$'),
    re.compile(r'^ragcheck.*$'),
    re.compile(r'^acceptance$'),
    re.compile(r'^qa_lzx.*$'),
    re.compile(r'^e2e_[0-9a-f]{8}(_b)?@example\.com$'),
]


def is_test_user(username: str) -> bool:
    return any(p.match(username or "") for p in PATTERNS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    users = cur.execute("SELECT id, username FROM users").fetchall()
    test_users = [u for u in users if is_test_user(u["username"])]
    keep = [u["username"] for u in users if not is_test_user(u["username"])]

    print(f"用户总数={len(users)}  测试账号={len(test_users)}  保留={len(keep)}")
    print("保留账号:", keep)
    if not test_users:
        print("无需清理")
        return 0

    uids = [u["id"] for u in test_users]
    qs = ",".join("?" * len(uids))
    projects = cur.execute(
        f"SELECT id, name FROM projects WHERE user_id IN ({qs})", uids
    ).fetchall()
    pids = [p["id"] for p in projects]
    print(f"待删测试账号: {[u['username'] for u in test_users]}")
    print(f"待删项目 {len(pids)} 个")

    stats = {}
    if pids:
        pqs = ",".join("?" * len(pids))
        for table in ("papers", "generated_sections", "extractions", "figures",
                      "chat_sessions", "quick_notes", "note_types", "section_chats"):
            try:
                n = cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE project_id IN ({pqs})", pids
                ).fetchone()[0]
                stats[table] = n
            except sqlite3.OperationalError:
                stats[table] = "n/a(无 project_id 列)"
    print("关联数据:", stats)

    if not args.apply:
        print("\n[dry-run] 未做任何修改。加 --apply 执行删除。")
        return 0

    if pids:
        pqs = ",".join("?" * len(pids))
        sessions = [r[0] for r in cur.execute(
            f"SELECT id FROM chat_sessions WHERE project_id IN ({pqs})", pids)]
        if sessions:
            sqs = ",".join("?" * len(sessions))
            cur.execute(f"DELETE FROM chat_messages WHERE session_id IN ({sqs})", sessions)
        for table in ("papers", "generated_sections", "extractions", "figures",
                      "chat_sessions", "quick_notes", "note_types", "section_chats"):
            try:
                cur.execute(f"DELETE FROM {table} WHERE project_id IN ({pqs})", pids)
            except sqlite3.OperationalError as e:
                print(f"跳过 {table}: {e}")
        cur.execute(f"DELETE FROM projects WHERE id IN ({pqs})", pids)
    cur.execute(f"DELETE FROM users WHERE id IN ({qs})", uids)
    conn.commit()

    left = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"\n已清理。剩余用户数={left}")
    print("剩余用户:", [r[0] for r in cur.execute("SELECT username FROM users")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
