"""ResearchAgent — RAG 检索 + 联网搜索"""
import logging

from src.core.agents.base import BaseAgent
from src.core.retriever import hybrid_search, format_chunks_with_citations, validate_citations
from src.tools.web_search import web_search_with_llm_summary

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    """研究 Agent — 负责信息检索和来源标注"""

    def __init__(self):
        super().__init__("Researcher")
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from src.core.llm import llm_client
            self._llm = llm_client
        return self._llm

    def research(self, query: str, project_id: str = None,
                 intent: str = "explore", top_k: int = 5) -> dict:
        """统一检索入口"""
        self.reset()
        self.think(f"检索关键词: {query[:60]}")

        # 1. RAG 检索（retriever.hybrid_search 内部已按 paper_id 过滤项目内论文；
        #    早期版本曾传 where={"project_id": ...} 但 chunk metadata 只有 paper_id，
        #    与 retriever 的 paper_where 做 $and 后结果恒为 0，故不再传 where。）
        chunks = hybrid_search(query, top_k=top_k, intent=intent)
        rag_content = format_chunks_with_citations(chunks) if chunks else ""
        sources = [
            {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
            for c in chunks
        ] if chunks else []
        self.think(f"RAG 检索到 {len(chunks)} 个片段")

        # 2. 联网搜索（仅 websearch 意图）
        web_results = []
        if intent == "websearch":
            search_result = web_search_with_llm_summary(query)
            web_results = search_result.get("web_results", [])
            self.think(f"联网搜索到 {len(web_results)} 条结果")

        return {
            "chunks": chunks,
            "rag_content": rag_content,
            "sources": sources,
            "web_results": web_results,
            "thinking_steps": self.thinking_steps,
        }

    def process(self, user_input: str, project_id: str = None, **kwargs) -> dict:
        intent = kwargs.get("intent", "explore")
        top_k = 8 if intent == "generate" else 5
        return self.research(user_input, project_id, intent, top_k)
