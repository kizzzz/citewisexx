# CiteWise — Prompt 工程设计

> 版本：V1.0 | 更新：2026-04-02
> 定位：面试展示用，体现对 Prompt Engineering 的系统化设计能力

---

## 1. 设计理念

CiteWise 的 Prompt 工程不是"写一个好 prompt"，而是一套**动态组装、分层管理、格式可控**的系统：

```
用户意图 → 路由识别 → 模板选择 → 上下文注入 → Few-shot 填充 → 输出约束 → LLM 调用
```

核心原则：
- **动态性**：根据任务类型、章节类型、用户偏好动态组装
- **可控性**：通过 JSON Schema 约束输出格式，拒绝自由发挥
- **可溯性**：所有生成内容必须附带引用来源
- **可复用性**：模板可跨项目复用，用户可自定义

> **职责边界**：Prompt Engine 只负责模板选择与组装，意图识别由 Agent 层的 IntentRouter 负责。

---

## 2. System Prompt 架构

### 2.1 分层组装

```
┌─────────────────────────────────────────┐
│ Layer 1: 角色定义（固定）                │
│ "你是一个学术研究助手 CiteWise..."       │
├─────────────────────────────────────────┤
│ Layer 2: 约束规则（固定）                │
│ 强制溯源、禁止幻觉、输出格式要求         │
├─────────────────────────────────────────┤
│ Layer 3: 用户画像（动态，来自记忆系统）   │
│ 研究领域、关注点、历史偏好               │
├─────────────────────────────────────────┤
│ Layer 4: 项目上下文（动态，来自 RAG）     │
│ 当前项目文献数量、已提取字段、框架状态   │
├─────────────────────────────────────────┤
│ Layer 5: 任务指令（动态，根据意图路由）   │
│ 具体任务描述 + 输出格式 + few-shot       │
└─────────────────────────────────────────┘
```

### 2.2 完整 System Prompt 模板

```
你是 CiteWise，一个专业的学术研究助手。你的任务是基于用户上传的文献库，辅助完成文献梳理、思路构建和论文写作。

## 核心约束（必须严格遵守）
1. 【强制溯源】所有观点、数据、结论必须引用知识库中的文献，格式：[作者, 年份]。无法引用时明确告知"该内容超出知识库范围"。
2. 【禁止幻觉】不得编造论文、数据、方法或结论。不确定时回答"我需要更多信息"。
3. 【结构化输出】严格按照要求的格式输出（Markdown表格/JSON/指定章节格式）。
4. 【忠实原文】提取信息时忠于原文表述，不得过度解读或推断。

## 用户画像
- 研究领域：{research_field}
- 关注方向：{focus_areas}
- 字段偏好：{field_preferences}
- 写作风格偏好：{writing_style}

## 当前项目状态
- 项目名称：{project_name}
- 文献数量：{paper_count}
- 已提取字段：{extracted_fields}
- 论文框架：{current_framework}
- 当前焦点：{current_focus}
```

---

## 3. 核心任务 Prompt 设计

### 3.1 任务路由规则

| 用户意图 | 任务类型 | 使用的 Prompt 模板 |
|----------|----------|-------------------|
| "帮我总结这些文献" | 结构化总结 | `template_summarize` |
| "提取XX字段" | 字段提取 | `template_extract` |
| "帮我想想怎么写" | 框架推荐 | `template_framework` |
| "写引言部分" | 分节生成 | `template_section_introduction` |
| "写文献综述" | 分节生成 | `template_section_literature_review` |
| "写方法论" | 分节生成 | `template_section_methodology` |
| "修改第三段" | 局部修改 | `template_rewrite` |
| "生成对比图" | 图表生成 | `template_chart` |

### 3.2 结构化总结 Prompt

**场景**：用户自定义字段，批量提取每篇文献的信息。

```
## 任务：结构化文献总结

你需要从以下文献片段中提取用户指定的字段信息。

### 用户自定义字段
{user_defined_fields}

### 文献内容
{retrieved_chunks}

### 输出要求
请严格按照以下 JSON 格式输出，不要添加任何额外内容：
```json
{
  "paper_title": "论文标题",
  "authors": "作者列表",
  "year": "发表年份",
  "fields": {
    "{field_1_name}": "提取内容或'未提及'",
    "{field_2_name}": "提取内容或'未提及'",
    ...
  },
  "confidence": {
    "{field_1_name}": "high/medium/low",
    "{field_2_name}": "high/medium/low"
  },
  "source_sections": {
    "{field_1_name}": "原文所在章节",
    "{field_2_name}": "原文所在章节"
  }
}
```

### 注意事项
- 如果某个字段在文献中未提及，填"未提及"，不要编造
- confidence 表示提取结果的可靠程度：high=原文明确提及，medium=需要推断，low=不确定
- source_sections 标注信息来源的章节位置
```

**设计亮点**：
- `confidence` 字段：自评提取可靠性，便于后续过滤低质量结果
- `source_sections`：追溯来源，支持用户验证
- JSON 输出：结构化可控，方便生成表格

### 3.3 分节生成 Prompt（以文献综述为例）

**场景**：按论文框架逐节生成，需要保持上下文连贯。

```
## 任务：生成论文章节

你正在为一篇学术论文生成「{section_name}」章节。

### 论文整体框架
{full_framework}

### 前文摘要（保持连贯）
{previous_sections_summary}

### 当前章节要求
- 主题：{section_topic}
- 目标字数：{target_words} 字
- 写作风格：{writing_style}

### 参考材料（来自知识库检索）
{relevant_chunks_with_citations}

### 输出要求
1. 学术写作风格，逻辑清晰，段落间有过渡
2. 每个观点/数据必须附带引用：[作者, 年份]
3. 在章节末尾列出本节引用的参考文献
4. 如果需要插入图表，使用格式：[图表: {图表描述}]，后续由系统处理

### 输出格式
```markdown
## {section_name}

{正文内容}

### 本节参考文献
- [1] 作者. 标题. 期刊, 年份.
- ...
```
```

### 3.4 框架推荐 Prompt

```
## 任务：推荐论文写作框架

基于用户已上传的 {paper_count} 篇文献的结构化总结结果，推荐一个合适的论文写作框架。

### 文献分析数据
{structured_summary_table}

### 用户研究主题
{research_topic}

### 请按以下结构输出：
1. **推荐框架**：列出章节标题和每个章节的目标（如"引言：阐述研究背景和研究意义"）
2. **推荐理由**：为什么适合这批文献
3. **关键洞察**：从文献分析中发现的 3-5 个核心发现，可作为写作重点
4. **建议的字数分配**：每章建议字数比例

### 输出格式
```json
{
  "framework": [
    {
      "section": "章节标题",
      "goal": "该章节的写作目标",
      "suggested_words": 建议字数,
      "key_points": ["要点1", "要点2"]
    }
  ],
  "rationale": "推荐理由",
  "insights": ["洞察1", "洞察2", "洞察3"]
}
```
```

### 3.5 局部修改 Prompt

```
## 任务：局部修改论文段落

### 修改目标
用户要求修改以下内容：{user_request}

### 当前文章
{full_article}

### 目标段落
{target_paragraph}

### 修改约束
1. 仅修改目标段落，保持其他内容不变
2. 保持引用格式一致 [作者, 年份]
3. 保持与上下文的衔接自然
4. 如需新的文献支撑，标注 [需要检索: {关键词}]

### 输出格式
```json
{
  "modified_paragraph": "修改后的段落",
  "change_summary": "修改说明",
  "new_citations_added": ["新增的引用"],
  "needs_retrieval": ["需要额外检索的关键词"]
}
```
```

### 3.6 图表生成 Prompt

```
## 任务：从表格数据生成可视化图表

### 源数据
{table_data}

### 用户要求
{chart_requirement}

### 输出要求
1. 选择最合适的图表类型（饼图/柱状图/折线图/散点图）
2. 生成 Python matplotlib 代码
3. 确保图表标题、轴标签、图例完整
4. 使用学术风格配色

### 输出格式
```json
{
  "chart_type": "bar/pie/line/scatter",
  "title": "图表标题",
  "description": "图表说明（50字以内）",
  "python_code": "matplotlib 代码",
  "data_insight": "从图表中得出的核心洞察"
}
```
```

---

## 4. Few-shot 示例库

### 4.1 字段提取 Few-shot

```json
{
  "examples": [
    {
      "input": {
        "fields": ["研究方法", "数据集", "核心指标", "主要发现"],
        "chunk": "本文提出了一种基于 Transformer 的多模态融合方法（TMFuse），在 COCO 数据集上进行实验，mAP 达到 67.3%，较基线提升 4.2 个百分点。实验表明多模态融合显著提升了检测精度。"
      },
      "output": {
        "paper_title": "（从上下文获取）",
        "fields": {
          "研究方法": "基于 Transformer 的多模态融合方法（TMFuse）",
          "数据集": "COCO 数据集",
          "核心指标": "mAP 67.3%，较基线提升 4.2 个百分点",
          "主要发现": "多模态融合显著提升了检测精度"
        },
        "confidence": {
          "研究方法": "high",
          "数据集": "high",
          "核心指标": "high",
          "主要发现": "high"
        }
      }
    }
  ]
}
```

### 4.2 溯引写作 Few-shot

```
用户要求：写一段关于"电动汽车充电基础设施建设"的文献综述片段

【正确示例】：
近年来，中国在电动汽车充电基础设施建设方面取得了显著进展。截至2023年，全国充电桩数量超过800万个 [张明等, 2023]。然而，充电设施的 spatial distribution 呈现明显的空间不均衡特征，一线城市覆盖率远高于三四线城市 [Li et al., 2024]。Hu et al. [2025] 进一步发现，充电基础设施的密度与 EV 采用率之间存在显著正相关。

【错误示例】（不要这样做）：
近年来充电桩建设取得了很大进展，目前全国已有数百万个充电桩。研究表明充电桩分布不均匀，大城市多小城市少。充电桩越多电动车卖得越好。
（问题：无引用、数据模糊、表述不学术）
```

---

## 5. 动态 Prompt 组装流程

```
                    ┌──────────────┐
                    │  用户输入     │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  意图识别     │ ← LLM 快速分类
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──┐  ┌──────▼──┐  ┌──────▼──┐
       │ 总结类  │  │ 生成类  │  │ 修改类  │
       └──────┬──┘  └──────┬──┘  └──────┬──┘
              │            │            │
       ┌──────▼────────────▼────────────▼──┐
       │     Layer 1-2：角色 + 约束（固定）  │
       ├────────────────────────────────────┤
       │     Layer 3：用户画像（记忆系统）    │
       ├────────────────────────────────────┤
       │     Layer 4：项目上下文（RAG 检索）  │
       ├────────────────────────────────────┤
       │     Layer 5：任务指令 + Few-shot     │
       └────────────────┬───────────────────┘
                        │
                 ┌──────▼──────┐
                 │  LLM 调用    │ → Qwen-72B / DeepSeek
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐
                 │  输出解析    │ → JSON Schema 校验
                 └─────────────┘
```

---

## 6. 输出格式控制策略

### 6.1 JSON Schema 约束

对于结构化任务（字段提取、框架推荐），使用 JSON Schema 强约束：

```python
EXTRACT_SCHEMA = {
    "type": "object",
    "required": ["paper_title", "fields", "confidence"],
    "properties": {
        "paper_title": {"type": "string"},
        "fields": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        },
        "confidence": {
            "type": "object",
            "additionalProperties": {"enum": ["high", "medium", "low"]}
        }
    }
}
```

### 6.2 格式校验与重试

```python
def call_llm_with_schema(prompt, schema, max_retries=2):
    for attempt in range(max_retries + 1):
        response = llm.chat(prompt)
        try:
            result = json.loads(response)
            validate(result, schema)  # jsonschema 校验
            return result
        except (json.JSONDecodeError, ValidationError):
            if attempt < max_retries:
                # 追加修正指令后重试
                prompt += f"\n\n上次输出格式有误，请严格按 JSON 格式输出。"
            else:
                return {"error": "format_failed", "raw": response}
```

---

## 7. 面试展示要点

| 展示点 | 话术要点 |
|--------|----------|
| 动态组装 | "Prompt 不是写死的，而是根据用户画像、项目状态、任务类型 5 层动态组装" |
| 格式可控 | "通过 JSON Schema 约束输出，LLM 不能自由发挥，确保下游解析可靠" |
| 溯源机制 | "System Prompt 层面强制要求引用，生成内容没有引用等于废品" |
| Few-shot | "不是泛泛的 few-shot，而是针对每种任务类型精心设计的正反例" |
| 自评估 | "confidence 字段让模型自评提取质量，低置信度结果自动标记供人工审核" |

---

## 8. 与其他模块的协作

```
Prompt Engine ←→ 记忆系统：读取用户画像、历史偏好
Prompt Engine ←→ RAG 系统：注入检索到的文献片段
Prompt Engine ←→ Agent：由 Agent 的规划器决定调用哪个 Prompt 模板
Prompt Engine ←→ 上下文工程：接收滑动窗口摘要作为上下文
Prompt Engine → 输出：结构化结果交由 Agent 工具链后续处理
```
