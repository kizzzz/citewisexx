# CiteWise — Agent 架构设计

> 版本：V1.0 | 更新：2026-04-02
> 定位：面试展示用，体现对 Agent 系统的工程化设计能力

---

## 1. 设计理念

CiteWise 不是简单的 "用户问→LLM答"，而是一个**有规划能力、有工具链、有主动推荐**的 Agent 系统。

核心思路：用 **ReAct 模式**（Reason + Act），让 Agent 能够：
1. 理解用户意图
2. 拆解为多步任务
3. 调用合适的工具
4. 观察结果并决策下一步
5. 主动向用户推荐

> **职责边界**：Agent 负责意图识别（IntentRouter），Prompt Engine 只负责模板选择与组装。

---

## 2. Agent 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      用户消息                            │
└────────────────────────┬────────────────────────────────┘
                         │
                ┌────────▼────────┐
                │   意图识别器     │ ← LLM 快速分类
                │  (IntentRouter) │
                └────────┬────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
   ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼──────┐
   │  简单问答   │ │  多步任务   │ │  主动推荐   │
   │  单工具调用  │ │  ReAct 循环 │ │  系统触发   │
   └──────┬─────┘ └──────┬─────┘ └──────┬──────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
                ┌────────▼────────┐
                │   规划器         │
                │  (Planner)      │ ← 拆解任务、选择工具
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │   工具调度器     │ ← 执行工具、收集结果
                │  (ToolRunner)   │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │   观察与决策     │ ← 评估结果、决定下一步
                │  (Observer)     │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │   响应生成       │ ← 组装最终回复
                │  (Responder)    │
                └─────────────────┘
```

---

## 3. ReAct 循环

### 3.1 核心循环

```
循环开始
  │
  ├── Thought（思考）：分析当前状态，决定下一步
  │     "用户要写文献综述，我需要先检索相关段落，再组织成章节"
  │
  ├── Action（行动）：调用工具
  │     search_papers(query="电动汽车 空间异质性 MGWR")
  │
  ├── Observation（观察）：分析工具返回
  │     "找到 5 篇相关论文，其中 3 篇使用 MGWR，2 篇使用 GWR"
  │
  ├── 判断：是否需要继续？
  │     ├── 是 → 回到 Thought
  │     └── 否 → 进入 Response
  │
  └── Response（响应）：生成最终输出
        "基于检索结果，为您生成文献综述..."
```

### 3.2 ReAct Prompt 模板

```
你正在执行一个多步骤的研究辅助任务。

## 当前任务
{task_description}

## 已完成步骤
{completed_steps}

## 可用工具
{tool_descriptions}

## 下一步
请按以下格式输出：
Thought: [分析当前状态，决定下一步]
Action: [工具名称]
Action Input: [工具参数，JSON格式]
```

---

## 4. 工具链定义

### 4.1 工具总览

| 工具 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `search_papers` | 语义检索文献 | query, filters, top_k | chunks + 元数据 |
| `extract_fields` | 批量字段提取 | paper_ids, fields | 结构化 JSON |
| `generate_table` | 生成对比表格 | extraction_results | Markdown 表格 |
| `generate_chart` | 生成可视化图表 | table_data, chart_type | matplotlib 代码 |
| `recommend_framework` | 推荐论文框架 | topic, summary_data | 框架 JSON |
| `generate_section` | 生成论文章节 | section_config | Markdown 文本 |
| `rewrite_section` | 局部修改 | target, instruction | 修改后文本 |
| `export_document` | 导出文档 | full_content, format | 文件路径 |
| `update_memory` | 更新用户画像 | key, value | 确认信息 |
| `list_figures` | 列出论文图表 | paper_id | 图表列表 |

### 4.2 工具定义（Function Calling 格式）

```json
[
  {
    "name": "search_papers",
    "description": "从知识库中检索与查询相关的文献片段。支持按论文ID、章节类型等过滤。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "检索查询，可以是关键词或自然语言描述"
        },
        "filters": {
          "type": "object",
          "properties": {
            "paper_id": {"type": "string", "description": "限定特定论文"},
            "section_type": {"type": "string", "enum": ["abstract", "intro", "method", "result", "discussion"]},
            "has_figure": {"type": "boolean"}
          }
        },
        "top_k": {
          "type": "integer",
          "default": 5,
          "description": "返回结果数量"
        }
      },
      "required": ["query"]
    }
  },
  {
    "name": "extract_fields",
    "description": "从指定论文中批量提取用户自定义字段信息，生成结构化结果。",
    "parameters": {
      "type": "object",
      "properties": {
        "paper_ids": {
          "type": "array",
          "items": {"type": "string"},
          "description": "目标论文ID列表"
        },
        "fields": {
          "type": "array",
          "items": {"type": "string"},
          "description": "要提取的字段名称列表，如['研究方法', '数据集', '核心指标']"
        }
      },
      "required": ["paper_ids", "fields"]
    }
  },
  {
    "name": "generate_section",
    "description": "根据配置生成一个完整的论文章节。会自动检索相关文献并注入引用。",
    "parameters": {
      "type": "object",
      "properties": {
        "section_name": {"type": "string", "description": "章节标题"},
        "section_topic": {"type": "string", "description": "章节主题描述"},
        "target_words": {"type": "integer", "default": 1000},
        "style": {"type": "string", "enum": ["academic", "concise", "detailed"], "default": "academic"}
      },
      "required": ["section_name", "section_topic"]
    }
  },
  {
    "name": "rewrite_section",
    "description": "对文章中指定段落进行局部修改，保持上下文连贯和引用完整。",
    "parameters": {
      "type": "object",
      "properties": {
        "target_location": {"type": "string", "description": "要修改的位置描述，如'第三段'或'2.1节第二段'"},
        "modification_instruction": {"type": "string", "description": "修改指令"},
        "preserve_citations": {"type": "boolean", "default": true, "description": "是否保留原有引用"}
      },
      "required": ["target_location", "modification_instruction"]
    }
  }
]
```

---

## 5. 典型任务的 Agent 执行流程

### 5.1 流程一：结构化总结（Phase 2）

```
用户: "帮我把这 10 篇论文按 [方法, 数据集, 指标, 创新点] 总结一下"

Agent 执行:
  Step 1 → Thought: 需要对10篇论文批量提取4个字段
           Action: extract_fields(paper_ids=["p1".."p10"], fields=["方法","数据集","指标","创新点"])
           Observation: 得到10篇论文的结构化结果

  Step 2 → Thought: 结果已获取，需要生成对比表格
           Action: generate_table(data=extraction_results)
           Observation: 生成 Markdown 表格

  Step 3 → Thought: 用户可能需要可视化，主动推荐
           Action: → Response
           "已生成对比表格。是否需要我生成柱状图对比各论文的指标表现？"

  (用户确认后)
  Step 4 → Thought: 用户确认，生成柱状图
           Action: generate_chart(data=指标列, type="bar")
           Observation: 生成 matplotlib 代码并执行

  Step 5 → Response: 返回表格 + 图表
```

### 5.2 流程二：分节生成（Phase 4）

```
用户: "按框架帮我写完整文章"

Agent 执行:
  Step 1 → Thought: 先读取框架配置和用户偏好
           Action: update_memory(action="read", keys=["framework", "writing_style"])
           Observation: 获取框架 6 个章节 + 学术风格偏好

  Step 2 → Thought: 逐章生成，先写引言
           Action: generate_section(section="引言", topic="研究背景与意义")
           Observation: 引言已生成，800字

  Step 3 → Thought: 生成文献综述，需要传递引言摘要保持连贯
           Action: generate_section(
                     section="文献综述",
                     topic="相关研究梳理",
                     previous_summary=引言摘要
                   )
           Observation: 文献综述已生成，2000字

  Step 4 → (重复 Step 3 的模式，依次生成各章节)

  Step 5 → Thought: 所有章节生成完毕，组装完整文章
           Action: export_document(content=full_article, format="markdown")
           Observation: 已导出为 Markdown 文件

  Step 6 → Response: "文章已生成完毕，共 5000 字。包含 6 个章节，引用了 15 篇文献。已导出为 Markdown 文件。"

  Step 7 → Thought: 记录本次生成的偏好
           Action: update_memory(key="last_framework", value=current_framework)
```

### 5.3 流程三：主动推荐（Phase 3）

```
用户: 上传完文献，进入项目

Agent 主动触发:
  Step 1 → Thought: 检测到新项目，检查是否有历史偏好
           Action: update_memory(action="read", keys=["field_template", "last_framework"])
           Observation: 用户上次用过 [方法, 数据集, 指标] 模板

  Step 2 → Thought: 有历史偏好，主动推荐
           Action: → Response
           "检测到您之前的项目使用了 [方法, 数据集, 指标] 的字段模板，
            是否沿用？另外，我可以先分析这批文献的特点，推荐一个写作框架。"

  (用户确认后)
  Step 3 → Thought: 用户确认复用，开始分析文献
           Action: extract_fields(paper_ids=all, fields=历史模板字段)
           Action: recommend_framework(topic=项目主题, data=提取结果)

  Step 4 → Response: 返回分析结果 + 推荐框架
```

---

## 6. 任务规划策略

### 6.1 意图路由

```python
INTENT_MAP = {
    "summarize": {
        "keywords": ["总结", "提取", "梳理", "对比"],
        "complexity": "multi_step",
        "tools": ["extract_fields", "generate_table", "generate_chart"]
    },
    "generate": {
        "keywords": ["写", "生成", "撰写", "帮我写"],
        "complexity": "multi_step",
        "tools": ["search_papers", "generate_section", "export_document"]
    },
    "modify": {
        "keywords": ["修改", "调整", "改写", "重写"],
        "complexity": "single_step",
        "tools": ["rewrite_section"]
    },
    "explore": {
        "keywords": ["有哪些", "什么方法", "怎么样"],
        "complexity": "single_step",
        "tools": ["search_papers"]
    },
    "export": {
        "keywords": ["导出", "下载", "保存"],
        "complexity": "single_step",
        "tools": ["export_document"]
    }
}
```

### 6.2 规划约束

```python
PLANNING_RULES = """
## 任务规划规则
1. 涉及 5 篇以上论文的批量操作，分批执行（每批 3-5 篇），避免超时
2. 生成类任务先检索再生成，确保有文献支撑
3. 修改类任务先定位目标位置，确认后再修改
4. 每个关键步骤完成后向用户展示中间结果
5. 不确定时主动询问用户，而非自作主张
6. 记录用户在交互中的偏好，更新用户画像
"""
```

---

## 7. 错误处理与回退

```python
async def execute_with_retry(tool_name: str, params: dict, max_retries: int = 2):
    """工具执行带重试和回退"""
    for attempt in range(max_retries + 1):
        try:
            result = await tools[tool_name].run(params)

            # 质量检查
            if result.is_empty():
                if attempt < max_retries:
                    # 放宽检索条件重试
                    params = relax_params(params)
                    continue
                else:
                    return ErrorResult(
                        message="检索结果为空，请检查查询或扩大范围",
                        suggestion="尝试使用不同的关键词或减少过滤条件"
                    )

            return result

        except ToolError as e:
            if attempt < max_retries:
                log.warning(f"Tool {tool_name} failed (attempt {attempt+1}): {e}")
                continue
            else:
                return ErrorResult(
                    message=f"工具执行失败: {str(e)}",
                    suggestion="请稍后重试或联系管理员"
                )
```

---

## 8. 面试展示要点

| 展示点 | 话术要点 |
|--------|----------|
| ReAct 模式 | "不是简单的一问一答，Agent 能思考、行动、观察、迭代，完成多步复杂任务" |
| 工具链设计 | "10 个专用工具，覆盖从检索到导出的完整写作链路，每个工具职责单一明确" |
| 主动推荐 | "Agent 不是被动等待，会根据用户画像主动推荐模板和框架" |
| 任务规划 | "批量操作分批执行、生成前先检索、关键步骤展示中间结果" |
| 错误处理 | "工具调用有重试和回退机制，检索为空时自动放宽条件" |

---

## 9. 与其他模块的协作

```
Agent ←→ Prompt Engine：Agent 选择 Prompt 模板，Prompt 执行工具逻辑
Agent ←→ RAG：Agent 通过 search_papers 工具触发检索
Agent ←→ 上下文工程：Agent 管理多步任务的上下文传递
Agent ←→ 记忆系统：Agent 读写用户画像、更新偏好
Agent ←→ 多模态：Agent 通过 list_figures/generate_chart 处理图表
```
