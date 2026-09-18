"""RouterAgent — 意图路由 + 任务分发（LLM 增强版）"""
import logging
from functools import lru_cache
from typing import Optional

from src.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

INTENT_MAP = {
    "summarize": ["总结", "提取", "梳理", "对比", "字段", "表格", "结构化"],
    "generate": ["写", "生成", "撰写", "帮我写", "章节"],
    "framework": ["框架", "思路", "大纲", "怎么写", "结构"],
    "modify": ["修改", "调整", "改写", "重写", "换", "拆分", "合并"],
    "export": ["导出", "下载", "保存", "输出"],
    "chart": ["图表", "柱状图", "饼图", "可视化", "绘图"],
    "websearch": ["最新", "新闻", "最近", "当前", "联网", "搜索"],
    "figures": ["图表索引", "图片", "figure", "fig", "图表列表"],
    "analyze": ["分析", "洞察", "建议", "推荐", "模式"],
}

# Intents that should win in ties (higher priority)
_PRIORITY_INTENTS = {"export", "websearch", "modify"}

# All valid intents for LLM classification
ALL_INTENTS = list(INTENT_MAP.keys()) + ["explore"]

# Tiered model routing: map intent to model.
# Heavy-duty writing tasks (generate / modify / framework / chart) use glm-4.7
# for stronger Chinese academic output; lightweight intents stay on glm-4-flash.
MODEL_ROUTING_MAP = {
    "explore": "glm-4-flash",
    "summarize": "glm-4-flash",
    "websearch": "glm-4-flash",
    "figures": "glm-4-flash",
    "analyze": "glm-4-flash",
    "generate": "glm-4.7",
    "modify": "glm-4.7",
    "framework": "glm-4.7",
    "chart": "glm-4.7",
    "export": "glm-4-flash",
}

def get_model_for_intent(intent: str) -> str:
    """Get recommended model for a given intent."""
    return MODEL_ROUTING_MAP.get(intent, "glm-4-flash")

# LLM classification prompt
_INTENT_CLASSIFY_PROMPT = """你是一个意图分类器。请将以下用户输入分类到这些意图之一：

- explore: 通用问答、提问、讨论
- summarize: 总结、提取、梳理、对比、结构化
- generate: 写文章、生成内容、撰写章节
- framework: 生成框架、大纲、写作思路
- modify: 修改、调整、改写已有内容
- export: 导出、下载、保存文档
- chart: 生成图表、数据可视化
- websearch: 联网搜索最新信息
- figures: 查看图表索引、图片列表
- analyze: 分析、洞察、建议、模式发现

用户输入：{user_input}

请用 JSON 格式回复：{{"intent": "意图", "confidence": 0.0-1.0}}
只回复 JSON，不要解释。"""


@lru_cache(maxsize=500)
def _cached_keyword_route(user_input: str) -> str:
    """Cached keyword-based routing"""
    return _keyword_route_uncached(user_input)


def _keyword_route_uncached(user_input: str) -> str:
    """Keyword-based intent routing (fallback)"""
    if any(c in user_input for c in '？？'):
        return "explore"

    intent_scores = {}
    for intent, keywords in INTENT_MAP.items():
        score = sum(1 for kw in keywords if kw in user_input)
        if score > 0:
            intent_scores[intent] = score

    if not intent_scores:
        return "explore"

    max_score = max(intent_scores.values())
    top_intents = [i for i, s in intent_scores.items() if s == max_score]
    if len(top_intents) > 1:
        for pi in _PRIORITY_INTENTS:
            if pi in top_intents:
                return pi

    best = max(intent_scores, key=intent_scores.get)
    if best == "generate" and "explore" in intent_scores:
        if intent_scores.get("generate", 0) <= intent_scores.get("explore", 0):
            return "explore"

    return best


def _llm_classify_intent(user_input: str) -> tuple[str, float]:
    """Use LLM to classify intent. Returns (intent, confidence)."""
    try:
        from src.core.llm import llm_client
        messages = [
            {"role": "system", "content": "你是意图分类器，只输出 JSON。"},
            {"role": "user", "content": _INTENT_CLASSIFY_PROMPT.format(user_input=user_input)},
        ]
        result = llm_client.chat_json(messages, temperature=0.1, max_retries=1)
        intent = result.get("intent", "explore")
        confidence = float(result.get("confidence", 0.5))
        if intent not in ALL_INTENTS:
            return ("explore", 0.0)
        return (intent, confidence)
    except Exception as e:
        logger.warning(f"LLM intent classification failed: {e}")
        return ("explore", 0.0)


class RouterAgent(BaseAgent):
    """意图路由 Agent — LLM 增强 + 关键词 fallback"""

    def __init__(self):
        super().__init__("Router")

    def route(self, user_input: str) -> str:
        """识别意图：先尝试 LLM 分类，低置信度时 fallback 到关键词匹配"""
        # Step 1: Try LLM classification
        llm_intent, confidence = _llm_classify_intent(user_input)
        if confidence >= 0.7:
            self.think(f"LLM 路由 → {llm_intent} (置信度 {confidence:.1f})")
            return llm_intent

        # Step 2: Fallback to keyword matching (cached)
        kw_intent = _cached_keyword_route(user_input)
        self.think(f"关键词路由 → {kw_intent} (LLM 置信度不足: {confidence:.1f})")
        return kw_intent

    def process(self, user_input: str, project_id: str = None, **kwargs) -> dict:
        """路由入口 — 返回路由结果"""
        self.reset()
        intent = self.route(user_input)

        agent_map = {
            "explore": "researcher",
            "summarize": "researcher",
            "websearch": "researcher",
            "generate": "writer",
            "modify": "writer",
            "framework": "writer",
            "export": "writer",
            "chart": "analyst",
            "figures": "analyst",
            "analyze": "analyst",
        }

        target_agent = agent_map.get(intent, "researcher")

        return {
            "intent": intent,
            "target_agent": target_agent,
            "thinking_steps": self.thinking_steps,
        }
