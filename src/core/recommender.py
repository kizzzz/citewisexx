"""智能文献推荐 — 基于语义相似度和引用关系"""
import json
import logging
import re
import numpy as np
import time
from typing import Optional

from src.core.memory import project_memory
from src.core.embedding import vector_store

logger = logging.getLogger(__name__)


# In-process LRU cache for paper-level embeddings + recommendations.
# Keyed by project_id; entries expire after _CACHE_TTL_SECONDS.
_PAPER_EMB_CACHE: dict[str, tuple[float, dict[str, list[float]]]] = {}
_REC_CACHE: dict[str, tuple[float, list[dict]]] = {}
_KNOWLEDGE_MAP_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes


def _cache_get(cache: dict, key: str):
    entry = cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: dict, key: str, value) -> None:
    cache[key] = (time.time(), value)


def invalidate_project_cache(project_id: str) -> None:
    """Drop cached embeddings / recommendations for a project (e.g. after upload/delete)."""
    _PAPER_EMB_CACHE.pop(project_id, None)
    _REC_CACHE.pop(project_id, None)
    _KNOWLEDGE_MAP_CACHE.pop(project_id, None)


def get_paper_embeddings(project_id: str, force_refresh: bool = False) -> dict[str, list[float]]:
    """Compute paper-level embeddings by averaging chunk embeddings.

    Uses SQLite-cached averages (papers.avg_embedding) as the primary source,
    falling back to ChromaDB only when the cache is empty. Each miss is written
    back to SQLite + in-process cache so subsequent calls are O(1).
    """
    if not force_refresh:
        cached = _cache_get(_PAPER_EMB_CACHE, project_id)
        if cached is not None:
            return cached

    papers = project_memory.get_papers(project_id)
    result: dict[str, list[float]] = {}
    miss_paper_ids: list[str] = []

    # Pass 1: read SQLite-cached averages (cheap, no ChromaDB round-trip).
    for paper in papers:
        paper_id = paper["id"]
        cached_avg = project_memory.get_paper_embedding_cached(paper_id)
        if cached_avg:
            result[paper_id] = cached_avg
        else:
            miss_paper_ids.append(paper_id)

    # Pass 2: compute missing ones from ChromaDB (text-only fetch is not enough,
    # we DO need embeddings here — so request them explicitly).
    if miss_paper_ids:
        for paper_id in miss_paper_ids:
            try:
                chunks = vector_store.get_chunks_by_paper(paper_id, include_embedding=True)
                if not chunks:
                    continue
                # ChromaDB may return embeddings as numpy arrays; ``if emb``
                # on an array raises "truth value ambiguous". Normalise to
                # lists and filter empty ones with len() instead.
                embeddings: list[list[float]] = []
                for c in chunks:
                    emb = c.get("embedding")
                    if emb is None:
                        continue
                    if hasattr(emb, "tolist"):
                        emb = emb.tolist()
                    if isinstance(emb, list) and len(emb) > 0:
                        embeddings.append(emb)
                if embeddings:
                    avg_embedding = np.mean(embeddings, axis=0).tolist()
                    result[paper_id] = avg_embedding
                    project_memory.save_paper_embedding(paper_id, avg_embedding)
            except Exception as e:
                logger.warning(f"Failed to get embedding for paper {paper_id}: {e}")

    _cache_set(_PAPER_EMB_CACHE, project_id, result)
    return result


def compute_similarity_matrix(embeddings: dict[str, list[float]]) -> dict[str, list[tuple[str, float]]]:
    """Compute pairwise cosine similarity between paper embeddings."""
    if len(embeddings) < 2:
        return {}

    paper_ids = list(embeddings.keys())
    emb_matrix = np.array([embeddings[pid] for pid in paper_ids])

    # Normalize
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normalized = emb_matrix / norms

    # Cosine similarity
    sim_matrix = np.dot(normalized, normalized.T)

    result = {}
    for i, pid in enumerate(paper_ids):
        similarities = []
        for j, other_pid in enumerate(paper_ids):
            if i != j:
                similarities.append((other_pid, float(sim_matrix[i][j])))
        similarities.sort(key=lambda x: x[1], reverse=True)
        result[pid] = similarities

    return result


def extract_citations(text: str) -> list[str]:
    """Extract author-year citations from text."""
    # Match patterns like (Author, 2024), (Author et al., 2023)
    pattern = r'\(([^)]+?,\s*\d{4})\)'
    matches = re.findall(pattern, text)
    return list(set(matches))


def build_citation_graph(project_id: str) -> dict[str, set[str]]:
    """Build a citation graph from paper full texts."""
    papers = project_memory.get_papers(project_id)
    graph = {}

    for paper in papers:
        pid = paper["id"]
        title = paper.get("title", "")
        authors = paper.get("authors", "")
        full_text = paper.get("raw_text", "") or ""

        # This paper cites others
        cited = set()
        for other in papers:
            if other["id"] == pid:
                continue
            other_title = other.get("title", "")
            other_authors = other.get("authors", "")
            # Check if other paper is referenced
            if other_title and other_title in full_text:
                cited.add(other["id"])
            elif other_authors:
                # Check by author name
                first_author = other_authors.split(",")[0].strip()
                if first_author and first_author in full_text:
                    cited.add(other["id"])

        graph[pid] = cited

    return graph


def get_recommendations(project_id: str, top_k: int = 5) -> list[dict]:
    """Generate paper recommendations: internal similarity + external APIs + LLM fallback."""
    papers = project_memory.get_papers(project_id)

    # Try external recommendations (Semantic Scholar)
    external = _semantic_scholar_recommendations(papers, top_k)

    # Internal recommendations need >= 2 papers
    internal = []
    if len(papers) >= 2:
        # Build paper ID to title mapping
        pid_to_title = {p["id"]: p.get("title", "Untitled") for p in papers}
        pid_to_authors = {p["id"]: p.get("authors", "") for p in papers}
        pid_to_year = {p["id"]: str(p.get("year", "")) for p in papers}

        # Compute similarity
        embeddings = get_paper_embeddings(project_id)
        if embeddings:
            sim_matrix = compute_similarity_matrix(embeddings)
            citation_graph = build_citation_graph(project_id)
            citation_count = {}
            for pid, cited in citation_graph.items():
                for cited_pid in cited:
                    citation_count[cited_pid] = citation_count.get(cited_pid, 0) + 1

            for pid, similar in sim_matrix.items():
                for other_pid, score in similar[:top_k]:
                    cit_boost = citation_count.get(other_pid, 0) * 0.05
                    internal.append({
                        "source_paper_id": pid,
                        "source_paper_title": pid_to_title.get(pid, ""),
                        "recommended_paper_id": other_pid,
                        "recommended_paper_title": pid_to_title.get(other_pid, ""),
                        "recommended_paper_authors": pid_to_authors.get(other_pid, ""),
                        "recommended_paper_year": pid_to_year.get(other_pid, ""),
                        "similarity_score": round(min(1.0, score + cit_boost), 3),
                        "recommendation_reason": f"与「{pid_to_title.get(pid, '未知')[:20]}」高度相关"
                            + (f"，被引用 {citation_count.get(other_pid, 0)} 次" if citation_count.get(other_pid, 0) > 0 else ""),
                    })
        else:
            internal = _chunk_based_recommendations(project_id, papers, top_k)

    # Merge and deduplicate
    seen = set()
    merged = []
    for rec in sorted(internal + external, key=lambda x: x["similarity_score"], reverse=True):
        key = (rec.get("source_paper_id", ""), rec.get("recommended_paper_id", ""), rec.get("recommended_paper_title", ""))
        if key not in seen:
            seen.add(key)
            merged.append(rec)

    # Fallback: if no results from any source, use LLM to generate recommendations
    if not merged and papers:
        merged = _llm_fallback_recommendations(papers, top_k, project_memory.get_project(project_id))

    return merged[:top_k * max(len(papers), 1)]


def _chunk_based_recommendations(project_id: str, papers: list[dict], top_k: int) -> list[dict]:
    """Fallback: recommend based on shared keywords between paper titles/abstracts."""
    from src.core.retriever import hybrid_search

    pid_to_title = {p["id"]: p.get("title", "Untitled") for p in papers}
    pid_to_authors = {p["id"]: p.get("authors", "") for p in papers}
    pid_to_year = {p["id"]: str(p.get("year", "")) for p in papers}

    recommendations = []
    for paper in papers:
        title = paper.get("title", "")
        if not title:
            continue

        # Search for similar papers
        results = hybrid_search(title, top_k=top_k + 1, project_id=project_id)
        for r in results:
            other_pid = r.get("paper_id", "")
            if other_pid and other_pid != paper["id"]:
                # Fallback title: try result field, then pid_to_title mapping
                rec_title = r.get("paper_title", "") or pid_to_title.get(other_pid, "Unknown")
                recommendations.append({
                    "source_paper_id": paper["id"],
                    "source_paper_title": pid_to_title.get(paper["id"], ""),
                    "recommended_paper_id": other_pid,
                    "recommended_paper_title": rec_title,
                    "recommended_paper_authors": pid_to_authors.get(other_pid, ""),
                    "recommended_paper_year": pid_to_year.get(other_pid, ""),
                    "similarity_score": round(1.0 / (1.0 + r.get("distance", 1.0)), 3),
                    "recommendation_reason": f"基于检索相似性推荐",
                })

    return recommendations[:top_k * len(papers)]


def _semantic_scholar_recommendations(papers: list[dict], top_k: int) -> list[dict]:
    """Recommend external papers via Semantic Scholar API (no key required for basic use)."""
    import os
    import httpx

    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    if not papers:
        return []

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    # Collect paper titles for search queries
    titles = [p.get("title", "") for p in papers if p.get("title")]
    if not titles:
        return []

    recommendations = []
    seen_titles = set()

    # Use up to 3 paper titles as search seeds
    for title in titles[:3]:
        try:
            # Search Semantic Scholar for related papers
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": title[:200],
                "limit": top_k + 2,
                "fields": "title,authors,year,citationCount,abstract,url",
            }
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Semantic Scholar API returned {resp.status_code}")
                continue

            data = resp.json()
            for paper_data in data.get("data", []):
                rec_title = paper_data.get("title", "")
                if not rec_title or rec_title in seen_titles:
                    continue
                # Skip papers already in the project
                if any(rec_title.lower() == t.lower() for t in titles):
                    continue
                seen_titles.add(rec_title)

                authors = ", ".join(a.get("name", "") for a in paper_data.get("authors", [])[:3])
                year = str(paper_data.get("year", ""))
                citations = paper_data.get("citationCount", 0)
                url = paper_data.get("url", "")

                recommendations.append({
                    "source_paper_id": "",
                    "source_paper_title": "",
                    "recommended_paper_id": url or f"ss_{paper_data.get('paperId', '')[:8]}",
                    "recommended_paper_title": rec_title,
                    "recommended_paper_authors": authors,
                    "recommended_paper_year": year,
                    "similarity_score": round(min(1.0, min(citations, 100) / 100 * 0.7 + 0.1), 3),
                    "recommendation_reason": f"外部推荐：引用 {citations} 次" if citations > 0 else "外部推荐：语义相关",
                    "external_url": url,
                })
        except Exception as e:
            logger.warning(f"Semantic Scholar search failed for '{title[:30]}': {e}")

    return recommendations[:top_k * 2]


async def _semantic_scholar_recommendations_async(
    papers: list[dict], top_k: int, per_query_timeout: float = 5.0
) -> list[dict]:
    """Async + concurrent variant of :func:`_semantic_scholar_recommendations`.

    Issues all seed-title queries in parallel with per-query timeouts so one
    slow API call can't pin the whole recommendation endpoint.
    """
    import os
    import asyncio
    import httpx

    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    titles = [p.get("title", "") for p in papers if p.get("title")]
    if not titles:
        return []

    headers = {"x-api-key": api_key} if api_key else {}
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    base_params = {
        "limit": top_k + 2,
        "fields": "title,authors,year,citationCount,abstract,url",
    }

    async def _one(client: httpx.AsyncClient, title: str) -> list[dict]:
        params = {**base_params, "query": title[:200]}
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=per_query_timeout)
            if resp.status_code != 200:
                logger.warning(f"Semantic Scholar API returned {resp.status_code}")
                return []
            data = resp.json().get("data", [])
        except Exception as e:
            logger.warning(f"Semantic Scholar search failed for '{title[:30]}': {e}")
            return []

        out: list[dict] = []
        for paper_data in data:
            rec_title = paper_data.get("title", "")
            if not rec_title:
                continue
            if any(rec_title.lower() == t.lower() for t in titles):
                continue
            authors = ", ".join(a.get("name", "") for a in paper_data.get("authors", [])[:3])
            year = str(paper_data.get("year", ""))
            citations = paper_data.get("citationCount", 0)
            ext_url = paper_data.get("url", "")
            out.append({
                "source_paper_id": "",
                "source_paper_title": "",
                "recommended_paper_id": ext_url or f"ss_{paper_data.get('paperId', '')[:8]}",
                "recommended_paper_title": rec_title,
                "recommended_paper_authors": authors,
                "recommended_paper_year": year,
                "similarity_score": round(min(1.0, min(citations, 100) / 100 * 0.7 + 0.1), 3),
                "recommendation_reason": f"外部推荐：引用 {citations} 次" if citations > 0 else "外部推荐：语义相关",
                "external_url": ext_url,
            })
        return out

    try:
        async with httpx.AsyncClient() as client:
            tasks = [_one(client, t) for t in titles[:3]]
            grouped = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning(f"Semantic Scholar async batch failed: {e}")
        return []

    seen_titles = set()
    merged: list[dict] = []
    for group in grouped:
        if isinstance(group, Exception):
            continue
        for rec in group:
            t = rec["recommended_paper_title"]
            if t in seen_titles:
                continue
            seen_titles.add(t)
            merged.append(rec)
    return merged[:top_k * 2]


def _fallback_from_existing_papers(papers: list[dict], top_k: int) -> list[dict]:
    """Last-resort fallback: recommend existing project papers by chunk_count.

    Used when external API + similarity + LLM all fail or time out — at least
    returns *something* so the front-end isn't stuck on "加载中" forever.
    """
    if not papers:
        return []
    ranked = sorted(
        papers,
        key=lambda p: (p.get("chunk_count", 0), len(p.get("title", ""))),
        reverse=True,
    )
    out: list[dict] = []
    for i, p in enumerate(ranked[:top_k]):
        out.append({
            "source_paper_id": "",
            "source_paper_title": "",
            "recommended_paper_id": p["id"],
            "recommended_paper_title": p.get("title", "Untitled"),
            "recommended_paper_authors": p.get("authors", ""),
            "recommended_paper_year": str(p.get("year", "")),
            "similarity_score": round(0.5 - i * 0.05, 3),
            "recommendation_reason": "已在当前项目中，可作为延伸阅读",
        })
    return out


async def get_recommendations_async(
    project_id: str, top_k: int = 5, total_timeout: float = 15.0
) -> list[dict]:
    """Async orchestrator: runs three sources in parallel, merges + dedups.

    Strategy:
      1. In-process cache (10 min TTL).
      2. Internal similarity (SQLite-cached paper embeddings — fast).
      3. Semantic Scholar async batch (fails silently on 429 / network).
      4. LLM + web_search fallback — ALWAYS runs so the UI gets external
         recommendations even when Semantic Scholar is rate-limited
         (which is the common case from CN networks).
      5. If everything fails: recommend from the project itself so the panel
         is never empty.

    External sources (3 + 4) run concurrently; the function returns as soon
    as all three finish OR ``total_timeout`` elapses (partial result then).
    """
    import asyncio

    cached = _cache_get(_REC_CACHE, project_id)
    if cached is not None:
        return cached[: top_k * max(len(cached), 1)]

    papers = project_memory.get_papers(project_id)
    if not papers:
        return []

    async def _internal() -> list[dict]:
        return await asyncio.to_thread(_compute_internal_recommendations, project_id, papers, top_k)

    async def _external() -> list[dict]:
        try:
            return await _semantic_scholar_recommendations_async(papers, top_k)
        except Exception as e:
            logger.warning(f"Semantic Scholar async failed: {e}")
            return []

    async def _llm_external() -> list[dict]:
        try:
            return await asyncio.to_thread(
                _llm_fallback_recommendations,
                papers, top_k, project_memory.get_project(project_id),
            )
        except Exception as e:
            logger.warning(f"LLM fallback failed: {e}")
            return []

    internal_recs: list[dict] = []
    external_recs: list[dict] = []
    llm_recs: list[dict] = []
    try:
        internal_recs, external_recs, llm_recs = await asyncio.wait_for(
            asyncio.gather(_internal(), _external(), _llm_external(), return_exceptions=False),
            timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"Recommendation gather timed out after {total_timeout}s for {project_id}; "
            f"returning partial results (internal={len(internal_recs)}, external={len(external_recs)}, llm={len(llm_recs)})"
        )
    except Exception as e:
        logger.warning(f"Recommendation gather failed: {e}")

    # Merge + dedup. Prefer higher-scored items; LLM recommendations get a
    # small bonus so they surface above low-similarity internal hits.
    seen: set[tuple] = set()
    merged: list[dict] = []

    def _key(r):
        return (r.get("source_paper_id", ""), r.get("recommended_paper_id", ""), r.get("recommended_paper_title", ""))

    def _score(r):
        s = float(r.get("similarity_score", 0) or 0)
        # Bonus only for LLM / external sources so they rank above similar
        # internal hits when scores are close.
        if r.get("source_paper_id") == "" and r.get("external_url"):
            s += 0.05
        elif r.get("source_paper_id") == "" and r.get("recommended_paper_id", "").startswith("llm_rec_"):
            s += 0.03
        return s

    for rec in sorted(internal_recs + external_recs + llm_recs, key=_score, reverse=True):
        k = _key(rec)
        if k in seen:
            continue
        seen.add(k)
        merged.append(rec)

    # Final safety net: if literally nothing came back, recommend existing
    # papers so the UI is never stuck on "loading".
    if not merged:
        merged = _fallback_from_existing_papers(papers, top_k)

    _cache_set(_REC_CACHE, project_id, merged)
    return merged[: top_k * max(len(papers), 1)]


def _compute_internal_recommendations(project_id: str, papers: list[dict], top_k: int) -> list[dict]:
    """Internal similarity-based recommendations (uses cached embeddings).

    Extracted from the legacy synchronous path so it can run in a worker thread.
    """
    if len(papers) < 2:
        return []
    pid_to_title = {p["id"]: p.get("title", "Untitled") for p in papers}
    pid_to_authors = {p["id"]: p.get("authors", "") for p in papers}
    pid_to_year = {p["id"]: str(p.get("year", "")) for p in papers}

    embeddings = get_paper_embeddings(project_id)
    if not embeddings:
        return _chunk_based_recommendations(project_id, papers, top_k)

    sim_matrix = compute_similarity_matrix(embeddings)
    citation_graph = build_citation_graph(project_id)
    citation_count: dict[str, int] = {}
    for cited_set in citation_graph.values():
        for cited_pid in cited_set:
            citation_count[cited_pid] = citation_count.get(cited_pid, 0) + 1

    internal: list[dict] = []
    for pid, similar in sim_matrix.items():
        for other_pid, score in similar[:top_k]:
            cit_boost = citation_count.get(other_pid, 0) * 0.05
            internal.append({
                "source_paper_id": pid,
                "source_paper_title": pid_to_title.get(pid, ""),
                "recommended_paper_id": other_pid,
                "recommended_paper_title": pid_to_title.get(other_pid, ""),
                "recommended_paper_authors": pid_to_authors.get(other_pid, ""),
                "recommended_paper_year": pid_to_year.get(other_pid, ""),
                "similarity_score": round(min(1.0, score + cit_boost), 3),
                "recommendation_reason": f"与「{pid_to_title.get(pid, '未知')[:20]}」高度相关"
                    + (f"，被引用 {citation_count.get(other_pid, 0)} 次" if citation_count.get(other_pid, 0) > 0 else ""),
            })
    return internal


def _llm_fallback_recommendations(
    papers: list[dict], top_k: int, project: Optional[dict] = None
) -> list[dict]:
    """Fallback: use LLM + web search to recommend related papers."""
    from src.core.llm import llm_client
    from src.tools.web_search import web_search

    titles = [p.get("title", "") for p in papers if p.get("title")]
    if not titles:
        return []

    topic = project.get("topic", "") if project else ""

    # Step 1: Web search for related papers
    web_results = []
    for query_seed in (titles[:2] if titles else [topic])[:2]:
        results = web_search(f"{query_seed} related papers research", top_k=5)
        web_results.extend(results)

    web_text = "\n".join(
        f"- [{r.get('title', '')}]({r.get('url', '')}): {r.get('snippet', '')}"
        for r in web_results[:10]
    ) if web_results else "No web results available."

    # Step 2: LLM generates recommendations
    prompt = f"""Based on the following research papers and web search results, recommend {top_k} related academic papers that would be valuable to read.

Current papers in the project:
{json.dumps([{'title': t} for t in titles[:5]], ensure_ascii=False, indent=2)}

Research topic: {topic or 'general'}

Web search results:
{web_text}

For each recommendation provide:
- title: exact paper title
- authors: up to 3 author names
- year: publication year (estimate if unsure)
- reason: why this paper is relevant (one sentence in Chinese)
- url: if you can find a real URL from the web results above, include it; otherwise empty string

Return JSON:
{{"recommendations": [{{"title": "...", "authors": "...", "year": "...", "reason": "...", "url": "..."}}]}}

Only return JSON. Focus on real, well-known papers if possible."""

    recommendations: list[dict] = []
    try:
        result = llm_client.chat_json(
            [
                {"role": "system", "content": "You are an academic paper recommendation expert. Only return valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            model="glm-4.7",
        )

        recs = (result or {}).get("recommendations", []) or []
        for i, r in enumerate(recs[:top_k]):
            rec_title = r.get("title", "")
            if not rec_title:
                continue
            recommendations.append({
                "source_paper_id": "",
                "source_paper_title": "",
                "recommended_paper_id": f"llm_rec_{i}",
                "recommended_paper_title": rec_title,
                "recommended_paper_authors": r.get("authors", ""),
                "recommended_paper_year": r.get("year", ""),
                "similarity_score": round(0.5 + 0.1 * (top_k - i) / top_k, 3),
                "recommendation_reason": r.get("reason", "LLM 推荐：相关研究"),
                "external_url": r.get("url", "") or "",
            })
    except Exception as e:
        logger.warning(f"LLM fallback recommendations failed: {e}")

    # Guarantee: always return at least 2 external items, even if the LLM
    # bailed — fall back to raw web_search results so the user sees real
    # clickable links to external papers.
    if len(recommendations) < 2 and web_results:
        seen = {r.get("recommended_paper_title", "") for r in recommendations}
        for wr in web_results:
            title = (wr.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            recommendations.append({
                "source_paper_id": "",
                "source_paper_title": "",
                "recommended_paper_id": f"web_{len(recommendations)}",
                "recommended_paper_title": title,
                "recommended_paper_authors": "",
                "recommended_paper_year": "",
                "similarity_score": 0.4,
                "recommendation_reason": "基于联网搜索的相关文献",
                "external_url": wr.get("url", "") or "",
            })
            if len(recommendations) >= max(2, top_k):
                break

    return recommendations
