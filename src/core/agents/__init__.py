"""CiteWise Multi-Agent 协同架构

Agents:
  - RouterAgent: 意图路由 + 任务分发
  - ResearchAgent: RAG 检索 + 联网搜索 + 来源标注
  - WriterAgent: 章节生成 + 改写 + 导出
  - AnalystAgent: 数据分析 + 图表生成 + 主动建议
  - CoordinatorAgent: 多 Agent 编排 + 复杂任务拆分
"""
from src.core.agents.base import BaseAgent
from src.core.agents.router import RouterAgent
from src.core.agents.researcher import ResearchAgent
from src.core.agents.writer import WriterAgent
from src.core.agents.analyst import AnalystAgent
from src.core.agents.coordinator import CoordinatorAgent

__all__ = [
    "BaseAgent", "RouterAgent", "ResearchAgent",
    "WriterAgent", "AnalystAgent", "CoordinatorAgent",
]
