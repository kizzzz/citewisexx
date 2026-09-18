"""知识地图 API — 文献关系可视化"""
import logging

from fastapi import APIRouter, Depends, Query

from api.deps import require_auth, verify_project_owner

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/knowledge-map")
async def get_knowledge_map(
    project_id: str,
    refresh: bool = Query(False, description="强制刷新缓存"),
    user: dict = Depends(require_auth),
):
    """获取文献关系图数据（节点 + 边）

    Performance: paper-level embeddings are cached in SQLite (see
    ``memory.PaperMemory.save_paper_embedding``), and the assembled graph is
    cached in-process for 10 minutes. Pass ``?refresh=true`` to bypass.
    """
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    from src.core.recommender import (
        get_paper_embeddings,
        compute_similarity_matrix,
        build_citation_graph,
        _cache_get,
        _cache_set,
        _KNOWLEDGE_MAP_CACHE,
    )

    papers = project_memory.get_papers(project_id)
    if not papers:
        return {"nodes": [], "edges": []}

    if not refresh:
        cached = _cache_get(_KNOWLEDGE_MAP_CACHE, project_id)
        if cached is not None:
            return cached

    # Build nodes
    nodes = []
    for p in papers:
        nodes.append({
            "id": p["id"],
            "title": p.get("title", "Untitled"),
            "authors": p.get("authors", ""),
            "year": str(p.get("year", "")),
            "chunk_count": p.get("chunk_count", 0),
            "filename": p.get("filename", ""),
        })

    # Build edges from similarity (paper-level averages are SQLite-cached, so
    # this is effectively O(N²) numpy over cached vectors — very fast after
    # the first hit). Threshold lowered from 0.5 to 0.35 so graphs are denser
    # and actually show relationships between papers in the same sub-field.
    edges = []
    try:
        embeddings = get_paper_embeddings(project_id)
        if embeddings and len(embeddings) >= 2:
            sim_matrix = compute_similarity_matrix(embeddings)
            for pid, similar in sim_matrix.items():
                for other_pid, score in similar:
                    if score >= 0.35:
                        edges.append({
                            "source": pid,
                            "target": other_pid,
                            "type": "similarity",
                            "weight": round(score, 3),
                        })
    except Exception as e:
        logger.warning(f"Similarity edges failed: {e}")

    # Citation graph is O(N²) string scanning — only run for small libraries
    # where it's cheap. Larger libraries fall back to similarity-only edges.
    if len(papers) <= 30:
        try:
            citation_graph = build_citation_graph(project_id)
            for pid, cited_set in citation_graph.items():
                for cited_pid in cited_set:
                    edges.append({
                        "source": pid,
                        "target": cited_pid,
                        "type": "citation",
                        "weight": 1.0,
                    })
        except Exception as e:
            logger.warning(f"Citation edges failed: {e}")

    payload = {"nodes": nodes, "edges": edges}
    _cache_set(_KNOWLEDGE_MAP_CACHE, project_id, payload)
    return payload
