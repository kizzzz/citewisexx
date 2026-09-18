"""CoordinatorAgent — 兼容层，委托给 LangGraph"""
import logging

from src.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """协调 Agent — 统一入口，委托 LangGraph 执行

    主对话走 LangGraph graph（在 chat.py 中直接调用），
    此类保留用于子对话和同步调用兼容。
    """

    def __init__(self):
        super().__init__("Coordinator")

    def process(self, user_input: str, project_id: str = None, **kwargs) -> dict:
        """同步处理 — 调用 LangGraph graph.invoke"""
        from src.core.graph import get_graph

        self.reset()
        graph = get_graph()

        intent_override = kwargs.get("intent")
        input_state = {
            "user_input": user_input,
            "project_id": project_id,
            "thinking_steps": [],
            "agent_events": [],
        }
        if intent_override:
            input_state["intent"] = intent_override
        if kwargs.get("target_content"):
            input_state["target_content"] = kwargs["target_content"]
        if kwargs.get("section_name"):
            input_state["section_name"] = kwargs["section_name"]
        if kwargs.get("gen_params"):
            input_state["gen_params"] = kwargs["gen_params"]
        if kwargs.get("agent_choice"):
            input_state["agent_choice"] = kwargs["agent_choice"]
        if kwargs.get("system_prompt"):
            input_state["system_prompt"] = kwargs["system_prompt"]
        if kwargs.get("requirements"):
            input_state["requirements"] = kwargs["requirements"]
        if kwargs.get("api_key"):
            input_state["api_key"] = kwargs["api_key"]
        if kwargs.get("base_url"):
            input_state["base_url"] = kwargs["base_url"]

        # Apply API key override to LLM client if provided.
        # Security (P0.2): set_override mutates the global LLM singleton, so a
        # missing cleanup would leak user A's key to user B's subsequent call.
        # We wrap graph.invoke in try/finally to guarantee clear_override even
        # on exceptions. The cleaner long-term fix is to remove the global
        # override mechanism entirely and pass api_key through input_state
        # (planned for P1.1 / P1.5).
        override_applied = False
        if kwargs.get("api_key"):
            try:
                from src.core.llm import llm_client
                llm_client.set_override(kwargs["api_key"], kwargs.get("base_url"))
                override_applied = True
            except Exception:
                pass

        config = {"configurable": {"thread_id": project_id or "default"}}
        try:
            result = graph.invoke(input_state, config)
        finally:
            if override_applied:
                try:
                    from src.core.llm import llm_client
                    llm_client.clear_override()
                except Exception as clear_err:
                    logger.error(f"Failed to clear LLM override: {clear_err}")

        # 确保 thinking_steps 汇总
        result["thinking_steps"] = result.get("thinking_steps", []) + self.thinking_steps
        return result


# 全局单例
coordinator = CoordinatorAgent()
