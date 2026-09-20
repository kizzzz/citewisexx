"""检索范围隔离（hybrid_search 必须限定项目范围）的回归测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import retriever


def test_refuse_without_scope(monkeypatch=None):
    """不传 project_id 且无 paper_id where → 拒绝检索，返回空"""
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("不应进入实际检索流程")

    orig = retriever._collect_candidates
    retriever._collect_candidates = _boom
    try:
        out = retriever.hybrid_search("任意查询")
        assert out == [], out
        assert called["n"] == 0
    finally:
        retriever._collect_candidates = orig


def test_paper_scoped_where_allowed():
    """显式 paper_id where（如字段提取）不应被拦截"""
    hit = {"n": 0}

    def _fake(*a, **kw):
        hit["n"] += 1
        return None

    orig = retriever._collect_candidates
    retriever._collect_candidates = _fake
    try:
        retriever.hybrid_search("查询", where={"paper_id": "p1"})
        assert hit["n"] > 0, "paper 级范围应允许继续检索"
    finally:
        retriever._collect_candidates = orig


def test_researcher_passes_project_id():
    """ResearchAgent 必须把 project_id 透传给 hybrid_search"""
    import src.core.agents.researcher as r

    seen = {}

    def _fake_search(query, top_k=5, where=None, project_id=None, intent="explore", **kw):
        seen["project_id"] = project_id
        return []

    orig = r.hybrid_search
    r.hybrid_search = _fake_search
    try:
        r.ResearchAgent().research("自注意力机制", project_id="proj_x", intent="generate")
        assert seen.get("project_id") == "proj_x", seen
    finally:
        r.hybrid_search = orig


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\nfailed={failed}")
    sys.exit(1 if failed else 0)
