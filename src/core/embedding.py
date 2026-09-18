"""Embedding 和向量库管理（智谱 embedding-3）"""
import hashlib
import json
import uuid
import logging
from collections import OrderedDict
from typing import Optional

import chromadb
from openai import OpenAI

from config.settings import (
    CHROMA_PATH, OPENAI_API_KEY, OPENAI_BASE_URL,
    EMBEDDING_MODEL, EMBEDDING_CACHE_SIZE
)

logger = logging.getLogger(__name__)


class EmbeddingManager:
    """Embedding 管理，使用智谱 embedding-3，带 LRU 缓存"""

    def __init__(self):
        self.client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
        )
        self.model = EMBEDDING_MODEL
        # LRU 缓存: content_hash → embedding vector
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_max_size = EMBEDDING_CACHE_SIZE

    def _content_hash(self, text: str) -> str:
        """基于文本内容生成 hash 键"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成 embedding，未缓存的文本调用 API，已缓存的直接返回"""
        if not texts:
            return []

        results: list[Optional[list[float]]] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # 查缓存
        for i, text in enumerate(texts):
            key = self._content_hash(text)
            if key in self._cache:
                results[i] = self._cache[key]
                # 移到末尾（最近使用）
                self._cache.move_to_end(key)
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # 对未缓存的文本调用 API
        if uncached_texts:
            api_results = self._call_api(uncached_texts)
            # Safety (P0.6): Earlier versions filtered out None entries with
            # ``[r for r in results if r is not None]``, which silently dropped
            # positional alignment when the API returned fewer embeddings than
            # requested. That corrupted the vector store because chunk N ended
            # up with chunk M's embedding. Now we raise and let the caller
            # skip the whole batch.
            if len(api_results) != len(uncached_texts):
                logger.error(
                    f"Embedding API returned {len(api_results)} vectors for "
                    f"{len(uncached_texts)} texts — refusing to write partial batch."
                )
                raise RuntimeError(
                    f"Embedding batch incomplete: expected {len(uncached_texts)}, "
                    f"got {len(api_results)}"
                )
            for j, idx in enumerate(uncached_indices):
                results[idx] = api_results[j]
                # 存入缓存
                key = self._content_hash(uncached_texts[j])
                self._cache[key] = api_results[j]
                if len(self._cache) > self._cache_max_size:
                    self._cache.popitem(last=False)  # 移除最旧的

        # All slots must be filled by now; defensive check against silent misalignment
        if any(r is None for r in results):
            missing = [i for i, r in enumerate(results) if r is None]
            logger.error(f"Embedding has unfilled slots at indices {missing}")
            raise RuntimeError(f"Embedding has unfilled slots at indices {missing}")
        return results

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """调用 embedding API

        Zhipu's embedding-3 endpoint rejects batches > 64 inputs with
        ``input数组最大不得超过64条``. The semantic chunker can easily pass
        100+ sentences in one go, so we slice into <=48-item sub-batches
        (safety margin under the 64 limit) and concatenate results in order.
        """
        import time
        if not texts:
            return []

        BATCH = 48  # Zhipu hard limit is 64; leave headroom for future bumps.
        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            chunk_texts = texts[start:start + BATCH]
            success = False
            for attempt in range(3):
                try:
                    resp = self.client.embeddings.create(
                        model=self.model,
                        input=chunk_texts,
                    )
                    vectors = [item.embedding for item in resp.data]
                    if len(vectors) != len(chunk_texts):
                        raise RuntimeError(
                            f"batch returned {len(vectors)} vectors for {len(chunk_texts)} inputs"
                        )
                    all_vectors.extend(vectors)
                    success = True
                    break
                except Exception as e:
                    logger.error(
                        f"Embedding 生成失败 (batch {start//BATCH + 1}, "
                        f"attempt {attempt+1}/3): {e}"
                    )
                    if attempt < 2:
                        time.sleep(1 * (attempt + 1))
            if not success:
                # Propagate failure so the caller can fall back (e.g. semantic
                # chunker degrades to rule-based chunking).
                raise RuntimeError(
                    f"Embedding batch {start//BATCH + 1} failed after 3 attempts"
                )
        return all_vectors


class VectorStore:
    """Chroma 向量库管理"""

    def __init__(self):
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        self.paper_collection = self.client.get_or_create_collection(
            name="paper_chunks",
            metadata={"hnsw:space": "cosine"}
        )
        self.embedding_manager = EmbeddingManager()

    def index_chunks(self, chunks: list[dict]):
        """将 chunks 索引到向量库"""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        ids = [c["chunk_id"] for c in chunks]
        metadatas = [{
            "paper_id": c["paper_id"],
            "paper_title": c.get("paper_title", ""),
            "authors": c.get("authors", ""),
            "year": c.get("year", 0),
            "section_title": c.get("section_title", ""),
            "section_level": c.get("section_level", "L2"),
            "has_table": c.get("has_table", False),
            "parent_chunk_id": c.get("parent_chunk_id", ""),
        } for c in chunks]

        # 批量生成 embedding（智谱单次最多64条）
        batch_size = 16
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            batch_meta = metadatas[i:i+batch_size]

            try:
                embeddings = self.embedding_manager.embed(batch_texts)
            except RuntimeError as e:
                # P0.6: skip the failed batch but keep indexing the rest
                logger.error(f"Embedding 批次 {i} 失败，跳过: {e}")
                continue
            if not embeddings:
                logger.error(f"Embedding 为空，跳过批次 {i}")
                continue

            self.paper_collection.upsert(
                ids=batch_ids,
                embeddings=embeddings,
                documents=batch_texts,
                metadatas=batch_meta,
            )
        logger.info(f"已索引 {len(chunks)} 个 chunks")

    def vector_search(self, query: str, top_k: int = 20, where: dict = None) -> list[dict]:
        """向量检索"""
        try:
            query_embedding = self.embedding_manager.embed([query])
        except RuntimeError as e:
            # P0.6: embedding failed — degrade gracefully to empty results
            logger.error(f"Query embedding failed: {e}")
            return []
        if not query_embedding:
            return []

        # top_k 不能超过库中总数
        count = self.paper_collection.count()
        actual_k = min(top_k, count) if count > 0 else 0
        if actual_k == 0:
            return []

        results = self.paper_collection.query(
            query_embeddings=query_embedding,
            n_results=actual_k,
            where=where,
            include=["documents", "metadatas", "distances"]
        )

        output = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                output.append({
                    "chunk_id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
        return output

    def get_all_chunks(self) -> list[dict]:
        """获取所有已索引的 chunks"""
        count = self.paper_collection.count()
        if count == 0:
            return []
        results = self.paper_collection.get(
            include=["documents", "metadatas"],
            limit=count
        )
        output = []
        if results["ids"]:
            for i in range(len(results["ids"])):
                output.append({
                    "chunk_id": results["ids"][i],
                    "text": results["documents"][i],
                    "metadata": results["metadatas"][i],
                })
        return output

    def get_chunks_by_paper(self, paper_id: str, include_embedding: bool = False) -> list[dict]:
        """获取某篇论文的所有 chunks（按 section_level 和 section_title 排序）

        Performance: 默认 ``include_embedding=False``，不拉取向量数据 —— 详情
        页只需要文本，没必要把成百上千个 1024 维向量也拉回来。
        """
        include_fields = ["documents", "metadatas"]
        if include_embedding:
            include_fields.append("embeddings")
        try:
            results = self.paper_collection.get(
                where={"paper_id": paper_id},
                include=include_fields,
            )
        except Exception as e:
            logger.error(f"获取论文 chunks 失败: {e}")
            return []

        output = []
        embeddings = results.get("embeddings") if include_embedding else None
        if results["ids"]:
            for i in range(len(results["ids"])):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                item = {
                    "chunk_id": results["ids"][i],
                    "text": results["documents"][i],
                    "section_title": meta.get("section_title", ""),
                    "section_level": meta.get("section_level", "L2"),
                    "has_table": meta.get("has_table", False),
                }
                if include_embedding:
                    item["embedding"] = embeddings[i] if embeddings is not None else []
                output.append(item)
        # Sort: L0 first (abstract), then L1, then L2
        level_order = {"L0": 0, "L1": 1, "L2": 2}
        output.sort(key=lambda c: level_order.get(c["section_level"], 2))
        return output

    def delete_paper(self, paper_id: str):
        """删除某篇论文的所有 chunks"""
        self.paper_collection.delete(
            where={"paper_id": paper_id}
        )

    def get_stats(self) -> dict:
        """获取向量库统计"""
        count = self.paper_collection.count()
        return {"total_chunks": count}


# 全局单例
vector_store = VectorStore()
embedding_manager = EmbeddingManager()
