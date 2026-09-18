"""Embedding 管理器 — 提供统一的 embed 接口供语义切块等模块使用"""
import logging

from src.core.embedding import embedding_manager

logger = logging.getLogger(__name__)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量 embedding，供语义切块等模块调用"""
    if not texts:
        return []
    return embedding_manager.embed(texts)
