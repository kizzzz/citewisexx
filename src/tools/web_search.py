"""联网搜索工具

检索顺序：
1. 智谱 Web Search API（复用 OPENAI_API_KEY，服务器可直连，稳定性最好）
2. duckduckgo-search（可选依赖，境外网络可用时生效）
3. DuckDuckGo Instant Answer API（兜底）
"""
import json
import logging
import os
import urllib.request

from src.core.llm import llm_client

logger = logging.getLogger(__name__)

# 智谱 Web Search 引擎，search_std 为基础版
ZHIPU_SEARCH_ENGINE = os.getenv("WEB_SEARCH_ENGINE", "search_std")
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "20"))


def _zhipu_search(query: str, top_k: int = 5) -> list[dict]:
    """智谱 Web Search API（与 LLM 共用 API Key / Base URL）"""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return []

    base_url = os.getenv("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    if not base_url.endswith("/"):
        base_url += "/"
    url = base_url + "web_search"

    payload = json.dumps({
        "search_engine": ZHIPU_SEARCH_ENGINE,
        "search_query": query,
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = []
    for item in (data.get("search_result") or [])[:top_k]:
        snippet = (item.get("content") or "").strip()
        results.append({
            "title": item.get("title") or item.get("media") or "网络结果",
            "snippet": snippet[:600],
            "url": item.get("link") or item.get("url") or "",
            "source": "web",
            "publish_date": item.get("publish_date", ""),
        })
    return results


def web_search(query: str, top_k: int = 5) -> list[dict]:
    """联网搜索：智谱 Web Search 优先，其次 DuckDuckGo，最后 Instant Answer"""
    if not query or not query.strip():
        return []
    if len(query) > 200:
        query = query[:200]

    try:
        results = _zhipu_search(query, top_k)
        if results:
            logger.info(f"[WebSearch] 智谱 Web Search 命中 {len(results)} 条")
            return results[:top_k]
        logger.info("[WebSearch] 智谱 Web Search 返回空结果，回退 DuckDuckGo")
    except Exception as e:
        logger.warning(f"[WebSearch] 智谱 Web Search 失败，回退 DuckDuckGo: {e}")

    results = []

    try:
        # ddgs 是 duckduckgo_search 的新包名，优先用新包避免弃用告警
        try:
            from ddgs import DDGS
        except ImportError:
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
        logger.warning("ddgs / duckduckgo-search 未安装，回退到 Instant Answer API")
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


class WebSearchTool:
    """联网搜索工具对象

    历史代码（async_graph / graph）以 `web_search_tool.search(...)` 方式调用，
    但模块此前只导出了函数 `web_search`，导致 `from ... import web_search_tool`
    直接 ImportError，联网搜索链路被 except 静默吞掉、永远拿不到结果。
    这里补上对象形态，保持两种调用方式都可用。
    """

    name = "web_search"

    def search(self, query: str, max_results: int = 5, **kwargs) -> list[dict]:
        top_k = kwargs.get("top_k", max_results)
        return web_search(query, top_k=top_k)

    # 兼容可能存在的其他调用习惯
    __call__ = search


web_search_tool = WebSearchTool()
