"""BM25 持久化索引 — 支持序列化保存/加载和增量添加"""
import re
import os
import json
import logging
from rank_bm25 import BM25Okapi
import jieba

from config.settings import BM25_INDEX_PATH

logger = logging.getLogger(__name__)


class PersistentBM25Index:
    """基于 rank_bm25 的 BM25 索引，支持 save/load 和增量添加"""

    def __init__(self, index_path: str = BM25_INDEX_PATH):
        self.bm25 = None
        self.chunk_map: dict[str, dict] = {}
        self._texts: list[str] = []  # 原始文本，用于增量重建
        self._tokenized: list[list[str]] = []  # 分词结果
        self.index_path = index_path

    def build_index(self, chunks: list[dict]):
        """从 chunks 全量构建 BM25 索引"""
        self.chunk_map = {c["chunk_id"]: c for c in chunks}
        self._texts = [c["text"] for c in chunks]
        self._tokenized = [self._tokenize(t) for t in self._texts]
        self.bm25 = BM25Okapi(self._tokenized)
        logger.info(f"BM25 索引已构建，共 {len(chunks)} 个文档")

    def add_chunks(self, chunks: list[dict]):
        """增量添加 chunks（追加后重建索引，比全量拉取快）"""
        for c in chunks:
            if c["chunk_id"] in self.chunk_map:
                continue
            self.chunk_map[c["chunk_id"]] = c
            self._texts.append(c["text"])
            self._tokenized.append(self._tokenize(c["text"]))

        if self._texts:
            self.bm25 = BM25Okapi(self._tokenized)
            logger.info(f"BM25 增量添加 {len(chunks)} chunks，总计 {len(self._texts)} 个文档")

    def save(self):
        """序列化索引到磁盘 (JSON format, safe from code execution)"""
        if not self.bm25:
            return
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        json_path = self.index_path.replace(".pkl", ".json")
        data = {
            "chunk_map": self.chunk_map,
            "_texts": self._texts,
            "_tokenized": self._tokenized,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info(f"BM25 索引已保存到 {json_path}")

    def load(self) -> bool:
        """从磁盘加载索引，成功返回 True。

        Safety note (P0.1): The legacy ``.pkl`` fallback was removed because
        ``pickle.load`` on an attacker-written file triggers arbitrary code
        execution. The on-disk format has been migrated to JSON; any stray
        ``.pkl`` is deleted without deserialisation and the caller rebuilds
        the index from the vector store.
        """
        json_path = self.index_path.replace(".pkl", ".json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.chunk_map = data["chunk_map"]
                self._texts = data["_texts"]
                self._tokenized = data["_tokenized"]
                self.bm25 = BM25Okapi(self._tokenized)
                logger.info(f"BM25 索引已从 {json_path} 加载，共 {len(self._texts)} 个文档")
                return True
            except Exception as e:
                logger.warning(f"BM25 JSON 索引加载失败: {e}")
                return False
        # Legacy .pkl index: remove without deserialising (pickle RCE risk).
        if os.path.exists(self.index_path):
            try:
                os.remove(self.index_path)
                logger.warning(
                    f"Removed legacy pickle index {self.index_path}; "
                    f"index will be rebuilt from the vector store on next build."
                )
            except OSError as e:
                logger.warning(f"Could not remove legacy pickle index {self.index_path}: {e}")
        return False

    def search(self, query: str, top_k: int = 20) -> list[dict]:
        """BM25 检索"""
        if not self.bm25:
            return []
        tokenized_query = self._tokenize(query)

        scores = self.bm25.get_scores(tokenized_query)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results = []
        chunk_ids = list(self.chunk_map.keys())
        for idx in ranked[:top_k]:
            cid = chunk_ids[idx]
            chunk = self.chunk_map[cid]
            results.append({
                "chunk_id": cid,
                "text": chunk["text"],
                "metadata": chunk.get("metadata", {}),
                "bm25_score": float(scores[idx]),
            })
        return results

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """中英文混合分词"""
        en_tokens = re.findall(r'[a-zA-Z]+', text)
        zh_tokens = list(jieba.cut(text))
        return en_tokens + zh_tokens
