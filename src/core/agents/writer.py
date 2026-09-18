"""WriterAgent — 章节生成 + 改写"""
import json
import logging

from src.core.agents.base import BaseAgent
from src.core.retriever import validate_citations

logger = logging.getLogger(__name__)


class WriterAgent(BaseAgent):
    """写作 Agent — 负责内容生成和改写"""

    def __init__(self):
        super().__init__("Writer")
        self._llm = None
        self._profile = None
        self._pm = None
        self._wm = None

    def _ensure_deps(self):
        if self._llm is None:
            from src.core.llm import llm_client
            from src.core.memory import global_profile, project_memory, working_memory
            self._llm = llm_client
            self._profile = global_profile
            self._pm = project_memory
            self._wm = working_memory

    def generate_section(self, section_name: str, section_topic: str,
                         research_result: dict, project_id: str,
                         framework: list = None, gen_params: dict = None,
                         system_prompt: str = "", requirements: str = "") -> dict:
        """基于检索结果生成章节"""
        self.reset()
        self._ensure_deps()
        self.think(f"生成章节: {section_name}")

        from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE

        # Extract generation parameters with defaults
        params = gen_params or {}
        style = params.get("style", "学术正式")
        target_words = params.get("target_length", 1000)
        citation_density = params.get("citation_density", "正常")

        # Map citation density to minimum citations per paragraph
        density_map = {"高": "每段至少 2 个引用", "正常": "适当引用关键观点", "低": "仅在关键结论处引用"}
        citation_instruction = density_map.get(citation_density, "适当引用关键观点")

        rag_content = research_result.get("rag_content", "")
        chunks = research_result.get("chunks", [])
        previous_summary = self._wm.get_previous_summary()

        system = SYSTEM_PROMPT_BASE
        # Override system prompt with user-defined agent prompt if provided
        if system_prompt and system_prompt.strip():
            system = system_prompt.strip()
        task_prompt = prompt_engine.build_section_prompt(
            section_name=section_name,
            section_topic=section_topic,
            reference_material=rag_content,
            framework=str(framework) if framework else "",
            previous_summary=previous_summary,
            target_words=target_words,
            writing_style=style,
        )

        # Add citation density instruction
        task_prompt += f"\n\n### 引用密度要求\n{citation_instruction}"

        # Add user requirements if provided
        if requirements and requirements.strip():
            task_prompt += f"\n\n### 用户要求\n{requirements.strip()}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task_prompt},
        ]

        self.think("调用 LLM 生成...")
        content = self._llm.chat(messages, temperature=0.7, max_tokens=4000)
        self.think(f"生成完成: {len(content)} 字")

        # 来源标注
        from src.core.source_annotation import annotate_sources, summarize_section
        content = annotate_sources(content, chunks, [])
        self.think("来源标注完成")

        # 保存
        section_id = self._pm.save_section(project_id, section_name, content)
        summary = summarize_section(self._llm, content)
        self._wm.add_section_summary(section_name, summary, len(content))

        citation_check = validate_citations(content, chunks)

        return {
            "type": "section",
            "content": content,
            "section_id": section_id,
            "section_name": section_name,
            "intent": "generate",
            "citations": citation_check,
            "word_count": len(content),
            "sources": [
                {"title": c.get("paper_title", ""), "citation": c.get("citation", "")}
                for c in chunks
            ] if chunks else [],
            "thinking_steps": self.thinking_steps,
        }

    def modify_content(self, instruction: str, target_content: str,
                       research_result: dict, project_id: str) -> dict:
        """修改已有内容

        Robustness: the original implementation assumed the LLM always returns
        strict JSON with a ``modified_paragraph`` key. When the user's message
        is a question / discussion rather than a literal edit instruction, the
        LLM often replies with plain prose — JSON parsing then fails and the
        caller falls back to ``target_content`` (the original section), which
        made it look like the agent "didn't reply" in the collaboration panel.

        Fix: try JSON first, but on failure reuse the raw LLM text as the
        assistant reply so the user always sees a real response.
        """
        self.reset()
        self._ensure_deps()
        self.think(f"修改指令: {instruction[:50]}")

        from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE
        from src.core.llm import LLMError

        chunks = research_result.get("chunks", [])
        reference = research_result.get("rag_content", "")

        task_prompt = prompt_engine.build_rewrite_prompt(
            instruction=instruction,
            target_paragraph=target_content[:4000],
            full_article="",
            reference_material=reference,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": task_prompt},
        ]

        # Path A — preferred: strict JSON with modified_paragraph.
        try:
            result = self._llm.chat_json(messages, temperature=0.5)
            modified = (result or {}).get("modified_paragraph", "").strip()
            if modified:
                self.think("修改完成")
                return {
                    "type": "modify",
                    "content": modified,
                    "change_summary": (result or {}).get("change_summary", "已修改"),
                    "intent": "modify",
                    "thinking_steps": self.thinking_steps,
                }
            # JSON returned but without the expected key — fall through to
            # Path B so we still surface *something*.
            logger.warning("modify_content: JSON ok but missing modified_paragraph")
        except LLMError as e:
            logger.warning(f"modify_content chat_json failed, falling back to plain chat: {e}")

        # Path B — fallback: ask the LLM directly for the reply as plain text.
        # The user prompt is rewritten to make clear either an edit OR a
        # conversational answer is acceptable.
        plain_prompt = (
            f"用户正在撰写论文的章节，当前内容如下：\n{target_content[:3000]}\n\n"
            f"用户指令/问题：{instruction}\n\n"
            f"请根据用户指令直接输出修改后的完整章节内容；"
            f"如果用户是在提问或讨论而非要求修改，请用中文正常回答。"
            f"不要输出 JSON、不要解释，直接给出最终文本。"
        )
        plain_messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BASE},
            {"role": "user", "content": plain_prompt},
        ]
        try:
            text = self._llm.chat(plain_messages, temperature=0.5)
        except LLMError as e:
            logger.error(f"modify_content fallback chat also failed: {e}")
            text = ""

        self.think("修改完成（纯文本兜底）")
        return {
            "type": "modify",
            "content": (text or "").strip(),
            "change_summary": "纯文本回复",
            "intent": "modify",
            "thinking_steps": self.thinking_steps,
        }

    def process(self, user_input: str, project_id: str = None, **kwargs) -> dict:
        intent = kwargs.get("intent", "generate")
        research_result = kwargs.get("research_result", {})
        gen_params = kwargs.get("gen_params", None)

        if intent == "modify":
            target_content = kwargs.get("target_content", "")
            return self.modify_content(user_input, target_content, research_result, project_id)
        else:
            section_name = kwargs.get("section_name", "文献综述")
            section_topic = kwargs.get("section_topic", "")
            framework = kwargs.get("framework", [])
            return self.generate_section(
                section_name, section_topic, research_result, project_id, framework, gen_params
            )
