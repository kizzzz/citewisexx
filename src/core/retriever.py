"""混合检索：BM25 + 向量 + RRF 融合 + 重排序 + 查询改写 + 意图感知"""
import re
import logging
from typing import Optional

from config.settings import (
    RRF_K, RERANK_TOP_K, VECTOR_TOP_K, BM25_TOP_K,
    ENABLE_QUERY_REWRITE, ENABLE_HYDE,
    RERANKER_TYPE,
    ENABLE_PARENT_CHUNK_EXPANSION,
    ENABLE_INTENT_RETRIEVAL,
    ENABLE_QUERY_CACHE,
    ENABLE_MULTI_QUERY,
    ENABLE_SCORE_NORMALIZATION,
    MULTI_QUERY_MAX_SUBQUERIES,
)
from src.core.embedding import vector_store
from src.core.bm25_store import PersistentBM25Index

logger = logging.getLogger(__name__)


# ========== BM25 索引（持久化） ==========
bm25_index = PersistentBM25Index()


# ========== 查询缓存 (Phase 3B) ==========

class QueryCache:
    """内存查询结果缓存，TTL 过期"""

    def __init__(self, ttl: int = 300, max_size: int = 500):
        self._store: dict[str, tuple[list, float]] = {}
        self._ttl = ttl
        self._max_size = max_size
        import threading
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[list[dict]]:
        with self._lock:
            if key not in self._store:
                return None
            results, ts = self._store[key]
            import time
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            return results

    def set(self, key: str, results: list[dict]):
        import time
        with self._lock:
            if len(self._store) >= self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]
            self._store[key] = (results, time.time())

    def _make_key(self, query: str, intent: str = "", project_id: str = "") -> str:
        return f"{query}::{intent}::{project_id}"


query_cache = QueryCache()


# ========== 意图检索配置 (Phase 3A) ==========

INTENT_RETRIEVAL_PROFILES = {
    "explore": {"vector_top_k": 20, "bm25_top_k": 20, "rerank_top_k": 5, "prefer_levels": None},
    "summarize": {"vector_top_k": 30, "bm25_top_k": 15, "rerank_top_k": 8, "prefer_levels": ["L0", "L1"]},
    "generate": {"vector_top_k": 15, "bm25_top_k": 15, "rerank_top_k": 6, "prefer_levels": None},
    "analyze": {"vector_top_k": 25, "bm25_top_k": 20, "rerank_top_k": 10, "prefer_levels": None},
}


def _get_retrieval_params(intent: str) -> dict:
    """根据意图获取检索参数"""
    profile = INTENT_RETRIEVAL_PROFILES.get(intent, INTENT_RETRIEVAL_PROFILES["explore"])
    return profile


# ========== RRF 融合 ==========

def reciprocal_rank_fusion(vector_results: list[dict], bm25_results: list[dict],
                           k: int = RRF_K) -> list[str]:
    """RRF 融合两路检索结果"""
    scores = {}

    for rank, doc in enumerate(vector_results):
        doc_id = doc["chunk_id"]
        base_score = 1.0 / (k + rank + 1)
        if ENABLE_SCORE_NORMALIZATION:
            # 加权向量距离
            dist = doc.get("distance", 1.0)
            vec_sim = max(0.0, 1.0 - dist)  # cosine distance → similarity [0,1]
            base_score *= (0.6 + 0.4 * vec_sim)
        scores[doc_id] = scores.get(doc_id, 0) + base_score

    for rank, doc in enumerate(bm25_results):
        doc_id = doc["chunk_id"]
        base_score = 1.0 / (k + rank + 1)
        if ENABLE_SCORE_NORMALIZATION:
            bm25_raw = doc.get("bm25_score", 0.0)
            # 归一化 BM25 分数到 [0,1]
            bm25_norm = min(1.0, max(0.0, bm25_raw / 30.0))
            base_score *= (0.6 + 0.4 * bm25_norm)
        scores[doc_id] = scores.get(doc_id, 0) + base_score

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_id for doc_id, _ in ranked]


# ========== Reranker (Phase 2A) ==========

def rerank_by_relevance(query: str, candidates: list[dict], top_k: int = RERANK_TOP_K) -> list[dict]:
    """根据配置分派到不同 reranker"""
    if not candidates:
        return []

    reranker = RERANKER_TYPE.lower()
    if reranker == "mmr":
        return _mmr_rerank(query, candidates, top_k)
    elif reranker == "cross_encoder":
        try:
            return _cross_encoder_rerank(query, candidates, top_k)
        except Exception as e:
            logger.warning(f"Cross-encoder rerank 失败，回退到 MMR: {e}")
            return _mmr_rerank(query, candidates, top_k)
    else:
        # 默认使用 LLM rerank
        return _llm_rerank_dispatch(query, candidates, top_k)


def _mmr_rerank(query: str, candidates: list[dict], top_k: int,
                lambda_param: float = 0.7) -> list[dict]:
    """MMR (最大边际相关性) rerank — 无需 LLM 调用

    兼顾相关性和多样性，使用向量距离作为相似度度量。
    """
    if len(candidates) <= top_k:
        return candidates

    # 使用 ChromaDB 原生 MMR 如果可用
    try:
        query_embedding = vector_store.embedding_manager.embed([query])
        if query_embedding:
            return _mmr_by_embedding(query_embedding[0], candidates, top_k, lambda_param)
    except Exception:
        pass

    # Fallback: 简单基于距离的排序
    scored = [(c, 1.0 / (1.0 + c.get("distance", 1.0))) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:top_k]]


def _mmr_by_embedding(query_emb: list[float], candidates: list[dict],
                       top_k: int, lambda_param: float) -> list[dict]:
    """基于 embedding 的 MMR 选择"""
    import numpy as np

    # 收集所有候选的 embedding
    texts = [c["text"] for c in candidates]
    embeddings = vector_store.embedding_manager.embed(texts)

    if not embeddings or len(embeddings) != len(candidates):
        scored = [(c, 1.0 / (1.0 + c.get("distance", 1.0))) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]

    query_vec = np.array(query_emb)
    cand_vecs = [np.array(e) for e in embeddings]

    def cosine_sim(a, b):
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        return float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else 0.0

    selected_indices = []
    remaining = set(range(len(candidates)))

    # 选第一个（与 query 最相关的）
    sims_to_query = [cosine_sim(query_vec, v) for v in cand_vecs]
    first = max(remaining, key=lambda i: sims_to_query[i])
    selected_indices.append(first)
    remaining.remove(first)

    while len(selected_indices) < top_k and remaining:
        best_idx = None
        best_score = -float("inf")
        for idx in remaining:
            relevance = sims_to_query[idx]
            diversity = max(
                cosine_sim(cand_vecs[idx], cand_vecs[s]) for s in selected_indices
            ) if selected_indices else 0.0
            mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        if best_idx is not None:
            selected_indices.append(best_idx)
            remaining.remove(best_idx)

    return [candidates[i] for i in selected_indices]


def _cross_encoder_rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Cross-encoder rerank (可选，需要 FlagEmbedding)"""
    from FlagEmbedding import FlagReranker
    model_name = RERANKER_MODEL or "BAAI/bge-reranker-v2-m3"
    reranker = FlagReranker(model_name, use_fp16=True)

    pairs = [[query, c["text"][:512]] for c in candidates]
    scores = reranker.compute_score(pairs)

    if isinstance(scores, (int, float)):
        scores = [scores]

    scored = list(zip(candidates, scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:top_k]]


def _llm_rerank_dispatch(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """LLM rerank 入口（含粗排预过滤）"""
    if len(candidates) > 10:
        scored = []
        for c in candidates:
            score = 1.0 / (1.0 + c.get("distance", 1.0))
            query_terms = set(re.findall(r'[a-zA-Z]{3,}', query.lower()))
            text_terms = set(re.findall(r'[a-zA-Z]{3,}', c["text"].lower()))
            overlap = len(query_terms & text_terms)
            if overlap > 0:
                score += 0.1 * overlap
            scored.append((c, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [c for c, s in scored[:10]]

    try:
        return _llm_rerank(query, candidates, top_k)
    except Exception as e:
        logger.warning(f"LLM rerank failed, falling back to simple scoring: {e}")
        scored = [(c, 1.0 / (1.0 + c.get("distance", 1.0))) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_k]]


def _llm_rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Use LLM to score candidate chunks for relevance to the query."""
    from src.core.llm import llm_client

    chunks_text = ""
    for i, c in enumerate(candidates):
        chunks_text += f"\n[{i+1}] {c['text'][:200]}\n"

    prompt = f"""请评估以下文献片段与查询的相关性，给每个片段打1-10分。
查询：{query}

片段：
{chunks_text}

请用 JSON 格式回复：{{"scores": [分数1, 分数2, ...]}}
只回复 JSON。"""

    messages = [
        {"role": "system", "content": "你是相关性评估器，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]

    result = llm_client.chat_json(messages, temperature=0.1, max_retries=1)
    scores = result.get("scores", [])

    if not scores or len(scores) != len(candidates):
        raise ValueError(f"Score count mismatch: got {len(scores)}, expected {len(candidates)}")

    scored = []
    for i, c in enumerate(candidates):
        llm_score = float(scores[i])
        vec_score = 1.0 / (1.0 + c.get("distance", 1.0))
        combined = 0.7 * llm_score + 0.3 * vec_score * 10
        scored.append((c, combined))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, s in scored[:top_k]]


# ========== 父 Chunk 扩展 (Phase 2B) ==========

def fetch_parent_chunks(results: list[dict]) -> list[dict]:
    """查找 L2 chunks 的父级 L1 chunk，附加为扩展上下文"""
    if not ENABLE_PARENT_CHUNK_EXPANSION:
        return []

    parent_ids = set()
    for r in results:
        meta = r.get("metadata", {})
        if meta.get("section_level") == "L2" and meta.get("parent_chunk_id"):
            parent_ids.add(meta["parent_chunk_id"])

    if not parent_ids:
        return []

    # 从 ChromaDB 获取父 chunks
    try:
        collection = vector_store.paper_collection
        parent_results = collection.get(
            ids=list(parent_ids),
            include=["documents", "metadatas"],
        )
        parents = []
        if parent_results["ids"]:
            for i in range(len(parent_results["ids"])):
                parents.append({
                    "chunk_id": parent_results["ids"][i],
                    "text": parent_results["documents"][i],
                    "metadata": parent_results["metadatas"][i],
                    "is_parent_context": True,
                })
        return parents
    except Exception as e:
        logger.warning(f"获取父 chunk 失败: {e}")
        return []


# ========== 多查询检索 (Phase 4A) ==========

def _should_decompose(query: str) -> bool:
    """启发式判断是否需要分解查询"""
    if not ENABLE_MULTI_QUERY:
        return False
    triggers = ["和", "比较", "对比", "与", "以及", "分别", "各自", " vs ", " versus ", " and ", " compare"]
    return len(query) > 20 or any(t in query.lower() for t in triggers)


def _normalize_subqueries(raw) -> list[str]:
    """把 LLM 返回的子查询归一化为纯字符串列表。

    LLM 有时不严格遵守 schema，会返回 [{"subquery": "..."}] 或
    {"1": "..."} 之类的结构；若直接透传，下游 embedding 会因
    'dict' object has no attribute 'encode' 整个 RAG 检索失败。
    """
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    for item in raw:
        text = None
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            # 常见键名兜底，否则取第一个字符串值
            for key in ("subquery", "query", "text", "question", "sub_query"):
                if isinstance(item.get(key), str):
                    text = item[key]
                    break
            if text is None:
                text = next((v for v in item.values() if isinstance(v, str)), None)
        elif item is not None:
            text = str(item)

        if text and text.strip():
            out.append(text.strip())
    return out


def decompose_query(query: str) -> list[str]:
    """用 LLM 分解复合查询为子查询"""
    from src.core.llm import llm_client

    messages = [
        {"role": "system", "content": f"将复合查询分解为 2-{MULTI_QUERY_MAX_SUBQUERIES} 个独立子查询。只输出 JSON。"},
        {"role": "user", "content": f"查询: {query}\n\n请分解为子查询，JSON 格式: {{\"subqueries\": [\"子查询1\", \"子查询2\"]}}"},
    ]
    try:
        result = llm_client.chat_json(messages, temperature=0.3, max_tokens=300)
        subqueries = _normalize_subqueries(result.get("subqueries", []))
        if subqueries and len(subqueries) >= 2:
            logger.info(f"查询分解: '{query[:40]}...' → {len(subqueries)} 个子查询")
            return subqueries[:MULTI_QUERY_MAX_SUBQUERIES]
    except Exception as e:
        logger.warning(f"查询分解失败: {e}")
    return [query]


# ========== 查询改写 (Phase 1A) ==========

def _apply_query_rewrite(query: str) -> str:
    """应用查询改写"""
    if not ENABLE_QUERY_REWRITE:
        return query

    from src.core.query_rewriter import rewrite_query, generate_hypothetical_answer

    if ENABLE_HYDE:
        # HyDE: 用假设回答替代原始查询去检索
        return generate_hypothetical_answer(query)

    return rewrite_query(query)


# ========== 主检索入口 ==========

def hybrid_search(query: str, top_k: int = RERANK_TOP_K, where: dict = None,
                  project_id: str = None, intent: str = "explore") -> list[dict]:
    """混合检索主入口：查询改写 → 多查询 → 向量 + BM25 → RRF 融合 → 重排序

    project_id 参数用于按项目过滤：查询 SQLite 获取该项目所有 paper_ids，
    然后构造 ChromaDB where 条件，确保检索结果仅来自当前项目的文献。
    """
    # Phase 3B: 查缓存
    cache_key = query_cache._make_key(query, intent, project_id or "")
    if ENABLE_QUERY_CACHE:
        cached = query_cache.get(cache_key)
        if cached is not None:
            logger.info(f"查询缓存命中: '{query[:30]}...'")
            return cached[:top_k]

    # Phase 3A: 获取意图相关检索参数
    params = _get_retrieval_params(intent) if ENABLE_INTENT_RETRIEVAL else {}
    vector_top_k = params.get("vector_top_k", VECTOR_TOP_K)
    bm25_top_k = params.get("bm25_top_k", BM25_TOP_K)
    rerank_top_k = params.get("rerank_top_k", top_k or RERANK_TOP_K)
    prefer_levels = params.get("prefer_levels")

    # 构建 where 过滤
    search_where = where
    filter_paper_ids = None  # 用于 BM25 后过滤

    # 按项目过滤：从 SQLite 查出该项目所有 paper_ids，构造 ChromaDB where 条件
    if project_id:
        try:
            from src.core.memory import project_memory
            project_papers = project_memory.get_papers(project_id)
            paper_ids = [p["id"] for p in project_papers]
            if paper_ids:
                project_where = {"paper_id": {"$in": paper_ids}}
                if search_where:
                    search_where = {"$and": [search_where, project_where]}
                else:
                    search_where = project_where
                filter_paper_ids = set(paper_ids)  # BM25 不支持 where，需后过滤
                logger.info(f"项目过滤: {len(paper_ids)} 篇文献")
            else:
                logger.info(f"项目 {project_id} 无文献，跳过检索")
                return []
        except Exception as e:
            logger.warning(f"项目过滤查询失败: {e}")

    if prefer_levels and ENABLE_INTENT_RETRIEVAL:
        # 先尝试在优选 level 中检索
        level_where = {"section_level": {"$in": prefer_levels}}
        if search_where:
            search_where = {"$and": [search_where, level_where]}
        else:
            search_where = level_where

    # Phase 1A: 查询改写
    search_query = _apply_query_rewrite(query)

    # Phase 4A: 多查询分解
    all_candidates = []
    seen_ids = set()

    if _should_decompose(query):
        subqueries = decompose_query(query)
        per_query_k = max(vector_top_k // len(subqueries), 5)
        for sq in subqueries:
            try:
                _collect_candidates(sq, per_query_k, bm25_top_k // len(subqueries),
                                    search_where, all_candidates, seen_ids, filter_paper_ids)
            except Exception as e:
                logger.warning(f"子查询检索失败，已跳过: {e}")
        # 子查询全部失败时回退原始查询，保证不出现「0 文献片段」
        if not all_candidates:
            logger.info("多查询无候选，回退原始查询检索")
            _collect_candidates(search_query, vector_top_k, bm25_top_k,
                                search_where, all_candidates, seen_ids, filter_paper_ids)
    else:
        _collect_candidates(search_query, vector_top_k, bm25_top_k,
                            search_where, all_candidates, seen_ids, filter_paper_ids)

    # 如果 level 过滤结果不够，回退全量
    if prefer_levels and len(all_candidates) < 3 and search_where != where:
        logger.info(f"优选 level 结果不足({len(all_candidates)})，回退全量检索")
        all_candidates = []
        seen_ids = set()
        _collect_candidates(search_query, vector_top_k, bm25_top_k,
                            where, all_candidates, seen_ids, filter_paper_ids)

    if not all_candidates:
        return []

    # RRF 融合
    vector_results = [c for c in all_candidates if "distance" in c]
    bm25_results = [c for c in all_candidates if "bm25_score" in c]
    fused_ids = reciprocal_rank_fusion(vector_results, bm25_results)

    id_to_doc = {c["chunk_id"]: c for c in all_candidates}
    candidates = [id_to_doc[cid] for cid in fused_ids if cid in id_to_doc]

    # 重排序
    results = rerank_by_relevance(query, candidates, top_k=rerank_top_k)

    # Phase 2B: 父 chunk 扩展
    parent_chunks = fetch_parent_chunks(results)

    # 格式化输出（带引用信息）
    for r in results:
        meta = r.get("metadata", {})
        r["citation"] = f"[{meta.get('authors', 'Unknown')}, {meta.get('year', 'N/A')}]"
        r["paper_title"] = meta.get("paper_title", "")
        r["section_title"] = meta.get("section_title", "")

    # 附加父上下文（不参与 rerank，仅作为扩展信息）
    if parent_chunks:
        for p in parent_chunks:
            meta = p.get("metadata", {})
            p["citation"] = f"[{meta.get('authors', 'Unknown')}, {meta.get('year', 'N/A')}]"
            p["paper_title"] = meta.get("paper_title", "")
            p["section_title"] = meta.get("section_title", "")
        results = results + parent_chunks

    # Phase 3B: 写入缓存
    if ENABLE_QUERY_CACHE and results:
        query_cache.set(cache_key, results)

    return results


def _collect_candidates(query: str, vector_top_k: int, bm25_top_k: int,
                        where: dict, all_candidates: list, seen_ids: set,
                        filter_paper_ids: set = None):
    """收集向量 + BM25 候选，去重

    filter_paper_ids: 如果提供，BM25 结果将按 paper_id 过滤（BM25 不支持 where 查询）
    """
    # 防御：上游（查询改写 / 多查询分解）可能传入非字符串，避免整条检索链路崩掉
    if not isinstance(query, str):
        logger.warning(f"检索查询类型异常({type(query).__name__})，已转为字符串")
        query = str(query)

    # 向量检索（已通过 where 参数过滤）
    vector_results = vector_store.vector_search(query, top_k=vector_top_k, where=where)
    for v in vector_results:
        if v["chunk_id"] not in seen_ids:
            seen_ids.add(v["chunk_id"])
            all_candidates.append(v)

    # BM25 检索（不支持 where，需后过滤）
    bm25_results = bm25_index.search(query, top_k=bm25_top_k)
    for b in bm25_results:
        if b["chunk_id"] in seen_ids:
            continue
        if filter_paper_ids:
            meta = b.get("metadata", {})
            if meta.get("paper_id") not in filter_paper_ids:
                continue
        seen_ids.add(b["chunk_id"])
        all_candidates.append(b)


def format_chunks_with_citations(chunks: list[dict]) -> str:
    """为检索片段添加引用标注，用于 Prompt 注入"""
    formatted = []
    for i, chunk in enumerate(chunks, 1):
        if chunk.get("is_parent_context"):
            continue  # 父上下文单独格式化
        citation = chunk.get("citation", "")
        paper_title = chunk.get("paper_title", "")
        section = chunk.get("section_title", "")
        header = f"--- 文献 {i}: {paper_title} {citation} | 章节: {section} ---"
        formatted.append(f"{header}\n{chunk['text']}")

    # 附加父上下文
    parent_chunks = [c for c in chunks if c.get("is_parent_context")]
    if parent_chunks:
        formatted.append("\n--- 扩展上下文（章节级） ---")
        for pc in parent_chunks:
            section = pc.get("section_title", "")
            formatted.append(f"[章节: {section}]\n{pc['text'][:500]}")

    return "\n\n".join(formatted)


def _normalize_author(author: str) -> str:
    """标准化作者名用于模糊匹配：去'等'/'et al.'，取姓氏部分"""
    author = author.strip()
    author = re.sub(r'\s*等\.?\s*$', '', author)
    author = re.sub(r'\s*et al\.?\s*$', '', author, flags=re.IGNORECASE)
    parts = author.split()
    return parts[0].lower() if parts else author.lower()


def validate_citations(generated_text: str, retrieved_chunks: list[dict]) -> dict:
    """校验生成文本中的引用是否都有检索依据"""
    en_citations = re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\]', generated_text)
    zh_citations = re.findall(r'\[([\u4e00-\u9fff]+等?,\s*\d{4})\]', generated_text)
    citations_in_text = en_citations + zh_citations

    valid_refs = set()
    year_author_pairs = []
    for c in retrieved_chunks:
        meta = c.get("metadata", {})
        authors = meta.get("authors", "") or c.get("authors", "")
        year = meta.get("year", "") or c.get("year", "")
        if authors and year:
            valid_refs.add(f"{authors}, {year}")
            year_author_pairs.append((str(year), _normalize_author(authors)))

    unverified = []
    for cite in citations_in_text:
        if cite in valid_refs:
            continue
        cite_year_match = re.search(r'(\d{4})', cite)
        cite_year = cite_year_match.group(1) if cite_year_match else ""
        cite_author = _normalize_author(re.sub(r',?\s*\d{4}$', '', cite))
        matched = False
        for ref_year, ref_author in year_author_pairs:
            if cite_year == ref_year and cite_author == ref_author:
                matched = True
                break
        if not matched:
            unverified.append(cite)

    return {
        "total_citations": len(citations_in_text),
        "verified": len(citations_in_text) - len(unverified),
        "unverified": unverified,
        "verification_rate": (len(citations_in_text) - len(unverified)) / max(len(citations_in_text), 1)
    }
