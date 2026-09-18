"""查询改写与 HyDE — 将模糊用户查询转为有效检索词"""
import logging
from src.core.llm import llm_client

logger = logging.getLogger(__name__)


def rewrite_query(query: str, intent: str = "explore") -> str:
    """用 glm-4-flash 将模糊查询改写为具体检索词

    保留原文语义，补充专业术语和关键词。
    """
    messages = [
        {"role": "system", "content": "你是学术检索查询优化器。将用户的模糊查询改写为精确的学术检索词，保留原文语义，补充专业术语。只输出改写后的查询文本，不要解释。"},
        {"role": "user", "content": f"意图: {intent}\n原始查询: {query}\n请改写为精确的检索词:"},
    ]
    try:
        result = llm_client.chat(messages, temperature=0.3, max_tokens=200)
        rewritten = result.strip()
        if rewritten and len(rewritten) >= len(query) * 0.3:
            logger.info(f"查询改写: '{query[:40]}...' → '{rewritten[:40]}...'")
            return rewritten
    except Exception as e:
        logger.warning(f"查询改写失败: {e}")
    return query


def generate_hypothetical_answer(query: str) -> str:
    """HyDE: 生成假设性回答，用其 embedding 检索相关文献

    原理: 假设回答与真实文献在语义空间中更接近，
    用假设回答的 embedding 检索比直接用模糊查询效果更好。
    """
    messages = [
        {"role": "system", "content": "你是学术专家。请根据问题写一段简短的学术回答（100-200字），包含相关术语和概念。"},
        {"role": "user", "content": query},
    ]
    try:
        result = llm_client.chat(messages, temperature=0.5, max_tokens=300)
        hypothetical = result.strip()
        if hypothetical:
            logger.info(f"HyDE 生成假设回答: {len(hypothetical)} 字")
            return hypothetical
    except Exception as e:
        logger.warning(f"HyDE 生成失败: {e}")
    return query


def expand_query(query: str) -> list[str]:
    """返回 [原始查询, 改写查询] 用于多查询检索"""
    rewritten = rewrite_query(query)
    if rewritten != query:
        return [query, rewritten]
    return [query]
