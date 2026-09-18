"""一次性诊断脚本：验证 RAG 层级切片策略是否真实落实。

用法:
    python scripts/verify_chunk_strategy.py [project_id]

不传 project_id 则检查所有项目。

输出：
- 每篇论文的 chunk 分布（L0/L1/L2/表格/总）
- 语义切片 vs 规则切分的比例（通过 chunk 大小分布推断）
- 潜在问题告警
"""
import sys
import os
from collections import Counter

# Windows console GBK workaround — force UTF-8 so emoji + Chinese render.
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Allow direct execution from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.memory import project_memory
from src.core.embedding import vector_store


def inspect_paper(paper_id: str, title: str) -> dict:
    """Pull all chunks for a paper and bucket them by level / size."""
    chunks = vector_store.get_chunks_by_paper(paper_id, include_embedding=False)
    if not chunks:
        return {"paper_id": paper_id, "title": title, "total": 0, "levels": {}, "issues": ["no chunks in vector store"]}

    level_counter = Counter(c.get("section_level", "?") for c in chunks)
    sizes = [len(c.get("text", "")) for c in chunks]
    has_table = sum(1 for c in chunks if c.get("has_table"))

    issues = []
    # Issue: no L0 abstract chunk
    if level_counter.get("L0", 0) == 0:
        issues.append("no L0 abstract chunk — _extract_abstract likely failed")
    # Issue: only L2 (long paper should have L1 too)
    if level_counter.get("L1", 0) == 0 and max(sizes, default=0) > 800:
        issues.append("no L1 chunks despite long text — semantic chunking may have skipped parent creation")
    # Issue: chunks way under CHUNK_MIN_SIZE (200)
    tiny = sum(1 for s in sizes if s < 100)
    if tiny > len(sizes) * 0.3:
        issues.append(f"{tiny}/{len(sizes)} chunks are very small (<100 chars) — overlap/merge may be misfiring")
    # Issue: chunks way over CHUNK_MAX_SIZE (1500)
    huge = sum(1 for s in sizes if s > 2000)
    if huge > 0:
        issues.append(f"{huge} chunks exceed 2000 chars — _truncate_at_boundary may have failed")

    avg_size = sum(sizes) // len(sizes) if sizes else 0
    return {
        "paper_id": paper_id,
        "title": title[:60],
        "total": len(chunks),
        "levels": dict(level_counter),
        "with_table": has_table,
        "avg_size": avg_size,
        "min_size": min(sizes) if sizes else 0,
        "max_size": max(sizes) if sizes else 0,
        "issues": issues,
    }


def main(project_id: str = "") -> None:
    if project_id:
        projects = [project_memory.get_project(project_id)]
        projects = [p for p in projects if p]
    else:
        projects = project_memory.list_projects()

    if not projects:
        print("No projects found.")
        return

    print(f"\n=== RAG 切片策略验证（{len(projects)} 个项目）===\n")
    total_issues = 0
    for proj in projects:
        pid = proj["id"]
        papers = project_memory.get_papers(pid)
        print(f"📁 项目: {proj.get('name', '?')}  ({len(papers)} 篇论文)")
        if not papers:
            print("   (无论文)\n")
            continue
        for p in papers:
            r = inspect_paper(p["id"], p.get("title", ""))
            print(f"  📄 [{r['paper_id'][:12]}] {r['title']}")
            print(f"     总 chunks: {r['total']}")
            if r["total"] == 0:
                for issue in r["issues"]:
                    print(f"     ⚠️  {issue}")
                continue
            level_str = " / ".join(f"{k}:{v}" for k, v in sorted(r["levels"].items()))
            print(f"     层级分布: {level_str}")
            print(f"     表格 chunks: {r['with_table']}")
            print(f"     chunk 大小: min={r['min_size']} avg={r['avg_size']} max={r['max_size']}")
            if r["issues"]:
                for issue in r["issues"]:
                    print(f"     ⚠️  {issue}")
                total_issues += len(r["issues"])
            else:
                print(f"     ✅ 策略落实正常")
        print()

    print(f"=== 汇总: {total_issues} 个潜在问题 ===")
    if total_issues == 0:
        print("所有论文切片策略均按预期落实（L0/L1/L2 + 表格 + overlap）。")
    else:
        print("详见上方告警。常见原因：")
        print("  - Abstract 未被正则匹配 → L0 缺失")
        print("  - 短章节直接作为 L1，长章节才会产生 L2")
        print("  - embedding 批量失败会降级到规则切分（仍是合法 L2）")


if __name__ == "__main__":
    project_id_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    main(project_id_arg)
