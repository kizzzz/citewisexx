"""联网搜索工具 — 使用 duckduckgo-search 进行真正的网页搜索"""
import logging

from src.core.llm import llm_client

logger = logging.getLogger(__name__)


def web_search(query: str, top_k: int = 5) -> list[dict]:
    """使用 DuckDuckGo 文本搜索获取真实网页结果"""
    if not query or not query.strip():
        return []
    if len(query) > 200:
        query = query[:200]

    results = []

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=top_k):
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("body", ""),
                    "url": item.get("href", ""),
                    "source": "web",
                })
    except ImportError:
        logger.warning("duckduckgo-search 未安装，回退到 Instant Answer API")
        results = _fallback_search(query, top_k)
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}")
        results = _fallback_search(query, top_k)

    return results[:top_k]


def _fallback_search(query: str, top_k: int = 5) -> list[dict]:
    """回退方案：使用 DuckDuckGo Instant Answer API"""
    import json
    import urllib.parse
    import urllib.request
    results = []
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "CiteWise/1.0 (research tool)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("AbstractText"):
            results.append({
                "title": data.get("AbstractSource", "DuckDuckGo"),
                "snippet": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
                "source": "web",
            })
    except Exception as e:
        logger.warning(f"回退搜索也失败: {e}")
    return results[:top_k]


def web_search_with_llm_summary(query: str) -> dict:
    """联网搜索 + LLM 总结"""
    search_results = web_search(query)

    llm_prompt = f"""基于你的知识，简要回答以下问题（100字以内）。请明确标注你的回答是基于自身知识。

问题：{query}"""

    llm_response = llm_client.chat(
        [{"role": "user", "content": llm_prompt}],
        temperature=0.5, max_tokens=300
    )

    return {
        "web_results": search_results,
        "llm_knowledge": llm_response,
        "query": query,
    }
