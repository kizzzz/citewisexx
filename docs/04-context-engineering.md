# CiteWise — 上下文工程设计

> 版本：V1.0 | 更新：2026-04-02
> 定位：面试展示用，体现对 LLM 上下文管理的工程化设计能力

---

## 1. 核心挑战

CiteWise 的上下文工程要解决三个关键问题：

| 问题 | 场景 | 影响 |
|------|------|------|
| **长度超限** | 15 篇论文 × 平均 30 页 = 450+ 页原文 | 远超 LLM 上下文窗口 |
| **连贯性丢失** | 分节生成 5000+ 字综述，前文信息遗忘 | 后面章节与前文矛盾 |
| **焦点漂移** | 长对话中 Agent 关注点偏离当前任务 | 回答不相关 |

**设计原则**：不是把所有信息塞给 LLM，而是**精准投喂 LLM 当前最需要的信息**。

---

## 2. 上下文层级架构

> **命名说明**：本节描述的上下文层级与 Prompt Engine 文档（`01-prompt-design.md`）中的 Layer 1-5 体系对应同一套分层架构，仅从上下文管理视角展开描述。Layer 1-5 是统一的命名体系。

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: 角色定义（System Prompt 固定层）                  │
│ 角色定义 + 约束规则                                       │
│ 大小：~800 tokens                                        │
├─────────────────────────────────────────────────────────┤
│ Layer 2: 约束规则 + 用户画像（动态，来自记忆系统）          │
│ 强制溯源、禁止幻觉 + 用户研究领域、关注点、历史偏好         │
│ 大小：~500 tokens                                        │
├─────────────────────────────────────────────────────────┤
│ Layer 3: 用户画像 + 项目上下文（项目级）                   │
│ 论文列表 + 已提取字段 + 框架状态 + 项目偏好               │
│ 大小：~1000 tokens（动态压缩）                            │
├─────────────────────────────────────────────────────────┤
│ Layer 4: 项目上下文（RAG 注入）                           │
│ 当前任务相关的文献片段 + 引用信息                         │
│ 大小：~2000 tokens（检索 top-5）                          │
├─────────────────────────────────────────────────────────┤
│ Layer 5: 任务指令（当前任务）                             │
│ 任务描述 + 输出格式 + few-shot                            │
│ 大小：~500 tokens                                        │
└─────────────────────────────────────────────────────────┘

总预算：~5000 tokens（以 Qwen-72B 的 32K 窗口为参考）
剩余空间留给 LLM 输出：~27000 tokens
```

---

## 3. 滑动窗口摘要

### 3.1 问题场景

分节生成综述时，每生成一节都调用一次 LLM，但 LLM 需要知道前文写了什么，否则：
- 重复论述相同观点
- 前后表述矛盾
- 过渡不自然

### 3.2 解决方案

```
生成第 1 节（引言）
    │
    ├── 输入：框架 + 检索片段
    ├── 输出：引言全文（800字）
    │
    ▼
对引言做摘要压缩（800字 → 200字）
    │
    ├── 保留：核心观点、关键引用、段落主题
    ├── 丢弃：具体数据、展开论述
    │
    ▼
生成第 2 节（文献综述）
    │
    ├── 输入：框架 + 第1节摘要 + 检索片段
    ├── 输出：文献综述全文（2000字）
    │
    ▼
对前两节做摘要压缩（2800字 → 400字）
    │
    ▼
生成第 3 节（方法论）
    │
    ├── 输入：框架 + 前文摘要 + 检索片段
    ├── 输出：方法论全文（1500字）
    ...
```

### 3.3 摘要压缩 Prompt

```python
SUMMARY_PROMPT = """
将以下论文章节压缩为简洁摘要，用于后续章节生成时保持上下文连贯。

要求：
1. 保留核心观点和关键论点（3-5 条）
2. 保留关键引用标记（如 [Hu et al., 2025]）
3. 保留段落之间的逻辑关系
4. 删除具体数据、展开论述、过渡句
5. 压缩到原文的 20-25%

原文：
{section_content}

输出格式：
- 主题：该章节的核心主题
- 观点：[观点1(引用), 观点2(引用), ...]
- 逻辑：章节的组织逻辑（如"按时间线梳理→总结趋势→指出空白"）
"""
```

### 3.4 滑动窗口策略

```python
class SlidingWindowSummary:
    """滑动窗口摘要管理器"""

    def __init__(self, max_summary_tokens: int = 2000):
        self.section_summaries: list[dict] = []
        self.max_summary_tokens = max_summary_tokens

    def add_section(self, section_name: str, content: str, summary: str):
        """添加新章节的摘要"""
        self.section_summaries.append({
            "section": section_name,
            "content_length": len(content),
            "summary": summary
        })
        self._compress_if_needed()

    def get_context(self) -> str:
        """获取当前所有摘要的拼接文本"""
        parts = []
        for s in self.section_summaries:
            parts.append(f"【{s['section']}】{s['summary']}")
        return "\n\n".join(parts)

    def _compress_if_needed(self):
        """如果总摘要超出预算，进行二次压缩"""
        total = sum(len(s["summary"]) for s in self.section_summaries)
        if total > self.max_summary_tokens:
            # 对最早的摘要进一步压缩
            for i in range(len(self.section_summaries) - 1):
                if total <= self.max_summary_tokens:
                    break
                old = self.section_summaries[i]["summary"]
                compressed = compress_further(old)
                total -= len(old) - len(compressed)
                self.section_summaries[i]["summary"] = compressed
```

---

## 4. 焦点管理

### 4.1 问题场景

长对话中，用户可能在多个任务间切换：

```
用户: "帮我总结这些文献"           ← 任务A：结构化总结
用户: "第3篇的方法描述不对"        ← 任务B：修正提取结果
用户: "继续总结"                   ← 回到任务A
用户: "写引言"                     ← 任务C：分节生成
```

如果上下文不管理焦点，LLM 会混淆任务。

### 4.2 焦点栈设计

```python
class FocusManager:
    """管理当前对话的任务焦点"""

    def __init__(self):
        self.focus_stack: list[dict] = []
        self.current_focus: dict = None

    def push_focus(self, task_type: str, context: dict):
        """进入新任务焦点"""
        if self.current_focus:
            self.focus_stack.append(self.current_focus)
        self.current_focus = {
            "task_type": task_type,
            "context": context,
            "entered_at": datetime.now()
        }

    def pop_focus(self):
        """回到上一个任务焦点"""
        if self.focus_stack:
            self.current_focus = self.focus_stack.pop()
        else:
            self.current_focus = None

    def get_focus_prompt(self) -> str:
        """生成焦点提示注入到 Prompt"""
        if not self.current_focus:
            return ""

        focus = self.current_focus
        return f"""
## 当前任务焦点
- 任务类型：{focus['task_type']}
- 任务上下文：{json.dumps(focus['context'], ensure_ascii=False)}
- 注意：用户的指令应在此任务范围内理解和执行
"""
```

---

## 5. 分节生成的上下文管理

### 5.1 完整的分节生成上下文组装

```python
def build_section_generation_context(
    section_config: dict,
    window: SlidingWindowSummary,
    project_state: dict,
    user_profile: dict
) -> str:
    """组装分节生成的完整上下文"""

    # Layer 1-2: 固定层（角色 + 约束）
    context = SYSTEM_PROMPT_BASE

    # Layer 3: 用户画像 + 项目上下文
    context += f"\n## 项目状态\n"
    context += f"- 论文数量：{project_state['paper_count']}\n"
    context += f"- 已完成章节：{project_state['completed_sections']}\n"

    # Layer 3: 前文摘要（滑动窗口）
    if window.section_summaries:
        context += f"\n## 前文摘要\n{window.get_context()}\n"

    # Layer 4: 检索上下文（RAG）
    relevant_chunks = hybrid_search(
        query=section_config["topic"],
        filters={"section_type": "result"},
        top_k=8
    )
    context += f"\n## 参考材料\n{format_chunks_with_citations(relevant_chunks)}\n"

    # Layer 5: 当前任务指令
    context += f"\n## 当前任务\n"
    context += f"生成章节：{section_config['section_name']}\n"
    context += f"主题：{section_config['topic']}\n"
    context += f"目标字数：{section_config.get('target_words', 1000)}\n"

    return context
```

### 5.2 Token 预算分配

```python
# Qwen-72B 上下文窗口：32K tokens
CONTEXT_BUDGET = {
    "system_prompt": 800,      # Layer 1-2
    "project_state": 500,      # Layer 3
    "dialogue_summary": 1000,  # Layer 3（动态压缩）
    "rag_chunks": 2000,        # Layer 4（top-5 chunks）
    "task_instruction": 500,   # Layer 5
    "output_reserve": 4000,    # LLM 输出预留
    "buffer": 2000,            # 安全缓冲
}
# 总计：~10800 tokens，远在窗口内
# 剩余 ~21000 tokens 可用于更复杂的场景
```

---

## 6. 局部修改的上下文定位

### 6.1 问题

用户说"修改第三段"——LLM 需要知道"第三段"指的是哪段，以及周围上下文。

### 6.2 定位策略

```
用户: "把文献综述第三段中关于 MGWR 的描述改一下，加上最近的研究"

Agent 执行:
  Step 1 → 定位目标
           - 加载完整文章结构
           - 识别"文献综述"章节
           - 定位第三段内容

  Step 2 → 组装上下文
           - 目标段落全文
           - 前后各 1 段作为上下文
           - 相关的检索片段

  Step 3 → 修改 Prompt
           - 仅包含目标段落 + 上下文 + 修改指令
           - 不需要加载整篇文章
```

```python
def locate_and_build_rewrite_context(
    article: dict,
    location: str,
    instruction: str
) -> dict:
    """定位修改目标并组装上下文"""
    # 解析位置描述
    target_section, target_paragraph = parse_location(location, article)

    # 获取目标段落
    target = article["sections"][target_section]["paragraphs"][target_paragraph]

    # 获取上下文（前后各 1 段）
    prev_para = article["sections"][target_section]["paragraphs"][target_paragraph - 1]
    next_para = article["sections"][target_section]["paragraphs"][target_paragraph + 1]

    # 检索相关新文献
    new_chunks = hybrid_search(query=instruction, top_k=3)

    return {
        "target_paragraph": target,
        "context_before": prev_para,
        "context_after": next_para,
        "relevant_new_material": new_chunks,
        "section_theme": article["sections"][target_section]["title"]
    }
```

---

## 7. 对话历史压缩

### 7.1 压缩策略

```python
async def compress_dialogue_history(messages: list[dict]) -> list[dict]:
    """压缩对话历史，保留关键信息"""

    if len(messages) <= 10:
        return messages  # 短对话不需要压缩

    # 保留最近 6 轮
    recent = messages[-12:]  # 6 轮 × 2 (user+assistant)

    # 对早期对话生成摘要
    early = messages[:-12]
    summary = await llm.summarize(
        f"将以下对话历史压缩为一段摘要，保留关键决策、用户偏好和任务状态：\n"
        f"{format_messages(early)}"
    )

    return [
        {"role": "system", "content": f"对话历史摘要：{summary}"},
        *recent
    ]
```

---

## 8. 面试展示要点

| 展示点 | 话术要点 |
|--------|----------|
| 上下文分层 | "5 层上下文架构，不是一股脑塞给 LLM，而是按需精准投喂" |
| 滑动窗口 | "分节生成时用滑动窗口摘要保持连贯，最新章节完整、早期章节压缩" |
| Token 预算 | "显式管理 Token 预算，确保不会超限" |
| 焦点管理 | "长对话中维护任务焦点栈，避免任务混淆" |
| 局部定位 | "修改时只加载目标段落和上下文，不需要整篇文章" |

---

## 9. 与其他模块的协作

```
上下文工程 ←→ Prompt Engine：上下文注入到 Prompt 模板
上下文工程 ←→ RAG：检索结果作为 Layer 4 注入
上下文工程 ←→ Agent：Agent 管理任务切换，上下文工程管理信息传递
上下文工程 ←→ 记忆系统：用户画像作为 Layer 2-3 注入
上下文工程 ←→ 多模态：图表描述作为上下文的一部分
```
