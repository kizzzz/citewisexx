# CiteWise 智能研究助手 — 产品需求文档 (PRD)

> **版本**: V3.2
> **日期**: 2026-04-16
> **产品定位**: AI 驱动的多 Agent 学术研究助手
> **一句话描述**: 上传论文，对话即得带引用的研究报告

---

## 1. 产品概述

### 1.1 我们解决什么问题

学术研究者（尤其是研究生和青年学者）在文献综述和论文写作中面临三个核心痛点：

| 痛点 | 现状 | 影响 |
|------|------|------|
| **读不完** | 一篇论文 30-60 分钟精读，10 篇就要一整天 | 研究进展缓慢，综述难产 |
| **对不上** | 跨论文的方法/数据/结论对比全靠手动摘抄 | 对比分析粗糙，遗漏关键差异 |
| **写不出** | 面对空白页不知道从何下笔，引用格式反复出错 | 写作焦虑，产出效率极低 |

**现有方案的不足**：ChatPDF 只能单篇问答，SciSpace 缺少写作能力，Notion AI 没有文献溯源。没有一个工具能覆盖"上传→理解→对比→写作→导出"的完整链路。

### 1.2 我们的解法

CiteWise 是一个 **多 Agent 协作的 AI 研究助手**，核心思路是：

```
用户上传论文 → AI 自动解析建库 → 用户用自然语言对话 → AI 检索+生成+标注来源 → 输出带引用的研究内容
```

**五个不可替代的产品差异化**：

1. **多 Agent 编排** — 5 个专业 Agent 协同工作（不是简单的单轮问答）
2. **混合检索引擎** — 关键词 + 语义向量双路检索，准确率远超单一方案
3. **三色来源标注** — 每段内容自动标注来自文献库(蓝)、联网搜索(绿)、还是 AI 推理(紫)
4. **全流程覆盖** — 从论文上传到章节生成到文档导出，一站式完成
5. **透明可追溯** — Agent Timeline 实时展示每一步推理过程，用户可审计

### 1.3 成功指标

| 指标 | 目标值 | 衡量方式 |
|------|--------|----------|
| 检索准确率 (Recall@20) | ≥ 85% | 标注数据集回归测试 |
| 引用标注准确率 | ≥ 95% | 人工抽检 100 条 |
| 首 Token 延迟 (TTFT) | < 3s (P95) | SSE 流式首 token 时间 |
| 任务完成率 | ≥ 85% | AgentEval 自动统计 |
| 用户满意度 | ≥ 4.2/5.0 | 反馈评分均值 |

---

## 2. 目标用户

### 2.1 用户画像

| 画像 | 研究生小李 | 博士生张教授 | 科研助理王姐 |
|------|-----------|-------------|-------------|
| **身份** | 研一，首次做文献综述 | 领域专家，需要跨论文分析 | 负责团队文献管理和报告 |
| **场景** | 读 20 篇论文→写综述章节 | 对比 10 篇方法论的异同 | 批量提取结构化信息→Excel |
| **痛点** | 不知道从哪篇开始读 | 手动对比效率极低 | 复制粘贴到手抽筋 |
| **频率** | 每日 2-3 次 | 每周 3-5 次 | 每日 5-10 次 |

### 2.2 核心使用场景

**场景 A：文献综述速成**
> 上传 15 篇相关论文 → 浏览 AI 自动解析的摘要 → 对话式提问"这些论文用了哪些研究方法" → 指令"帮我写文献综述" → 编辑修改 → 导出 Markdown

**场景 B：跨论文对比分析**
> 上传 8 篇对比论文 → 自定义提取字段（方法、数据集、准确率、结论） → AI 批量提取 → 生成对比表格 → 导出 Excel

**场景 C：单篇论文精读**
> 上传一篇难懂的论文 → 提问"第 3 节的算法核心思想是什么" → AI 基于 RAG 给出带引用的解释 → 继续追问细节

---

## 3. 功能需求

### 3.1 功能全景

```
CiteWise 功能全景
│
├── 📁 项目管理
│   ├── 创建/删除项目（项目是最高组织单元）
│   └── 项目状态总览（论文数、已提取字段、已完成章节）
│
├── 📄 文献管理
│   ├── 多格式上传（PDF/DOCX/MD/TXT/XLSX）
│   ├── 自动解析（元数据/章节/表格/图表）
│   ├── 层级切片入库（摘要级/章节级/段落级）
│   └── 论文详情查看与删除
│
├── 💬 智能对话（核心功能）
│   ├── 10 种意图自动识别与路由
│   ├── RAG 混合检索（关键词 + 语义 + 融合 + 重排）
│   ├── 联网搜索补充（知识库不足时自动触发）
│   ├── Token 级流式输出（SSE）
│   ├── 三色来源标注（文献库/联网/AI推理）
│   ├── Agent Timeline 实时可视化
│   └── 多轮对话（10+ 轮上下文保持）
│
├── ✍️ 章节写作
│   ├── AI 生成论文章节（引言/综述/方法/讨论/结论）
│   ├── 自然语言修改（"把第三段改得更学术化"）
│   ├── 子对话编辑（段落级独立上下文）
│   └── Markdown 文档导出（含自动参考文献列表）
│
├── 📊 结构化提取
│   ├── 自定义提取字段（最多 10 个）
│   ├── 批量论文信息提取
│   └── Excel 导出
│
├── 🔍 数据分析
│   ├── 项目级分析洞察
│   └── 可视化图表生成
│
├── 🧪 评估看板（AgentEval）
│   ├── 5 大指标追踪（成功率/引用准确率/幻觉率/响应时间/成本）
│   └── 自动优化建议
│
├── 🔑 模型管理
│   ├── 6+ 供应商支持（智谱/DeepSeek/OpenAI/Moonshot/通义千问/自定义）
│   └── API Key 验证与管理
│
└── 👤 用户系统
    ├── 注册/登录（JWT 认证）
    └── 数据隔离
```

### 3.2 核心功能详细说明

#### F1: 智能对话系统

**这是 CiteWise 的核心功能。** 用户通过自然语言与 AI 对话，AI 自动理解意图、检索文献库、生成带引用标注的回答。

**意图识别（10 种）**：

| 意图 | 用户会怎么说 | AI 做什么 |
|------|-------------|-----------|
| explore | "Transformer 在 NLP 中有哪些应用？" | 检索文献库→生成带引用回答 |
| summarize | "总结这篇论文的核心贡献" | 检索→生成结构化摘要 |
| generate | "帮我写文献综述" | 检索→生成论文章节 |
| modify | "把第三段改得更学术化" | 检索→局部改写 |
| framework | "帮我规划论文大纲" | 分析文献→推荐框架 |
| export | "导出所有章节" | 合并章节→生成 Markdown |
| chart | "画一个方法对比图" | 分析→生成图表配置 |
| analyze | "分析这些论文的研究趋势" | 分析→生成洞察报告 |
| websearch | "搜索最新的 RLHF 论文" | 联网搜索→整合回答 |
| figures | "列出所有图表" | 检索图表元数据 |

**交互体验**：
- 用户输入后 3 秒内开始流式输出（逐字显示）
- 右侧 Agent Timeline 面板实时显示当前执行到哪个 Agent
- 每段回答前标注来源类型：`[KB]` 文献库 / `[WEB]` 联网 / `[AI]` 推理

#### F2: 文献上传与解析

**支持的格式与解析能力**：

| 格式 | 解析方式 | 提取内容 |
|------|----------|----------|
| PDF | pdfplumber + Docling (fallback) | 元数据、章节、表格、图表 |
| DOCX | python-docx | 元数据、段落、表格 |
| MD/TXT | 文本读取 + 标题解析 | 章节切分 |
| XLSX | openpyxl | 工作表转 Markdown 表格 |

**分层切片策略**（决定检索精度）：

| 层级 | 粒度 | 大小 | 用途 |
|------|------|------|------|
| L0 | 论文级（摘要） | 全文摘要 | 全局概览 |
| L1 | 章节级 | 500-1500 字 | 上下文理解 |
| L2 | 段落级 | 200-500 字 | 精准检索 |

#### F3: 混合检索引擎

这是回答质量的关键。采用三阶段检索：

```
用户查询
  │
  ├── ① BM25 关键词检索 (Top-20, jieba 中英混合分词)
  ├── ② 向量语义检索 (Top-20, embedding-3, 2048 维)
  │
  └── ③ RRF 融合 (k=60)
        │
        └── ④ LLM 重排序 (候选 ≤10 条时触发, 70% LLM + 30% 向量相似度)
              │
              └── 最终 Top-5 + 引用格式化
```

#### F4: 三色来源标注系统

每段 AI 生成的内容都经过程序化来源判断：

| 标记 | 含义 | 判断依据 |
|------|------|----------|
| `[KB]` 蓝色 | 来自文献库 | 段落中的引用匹配到 RAG 检索结果 |
| `[WEB]` 绿色 | 来自联网搜索 | 段落关键词匹配到 DuckDuckGo 结果 |
| `[AI]` 紫色 | 来自 AI 推理 | 未匹配到上述任一来源 |

### 3.3 用户故事与验收标准

#### US-01: 智能问答
> 作为研究者，我希望用自然语言提问并获得基于文献库的精准回答（含来源标注），这样我就不用逐篇翻阅。

- [ ] 输入问题后 3s 内开始流式输出
- [ ] 回答包含 `[作者, 年份]` 格式引用
- [ ] 每段标注来源类型 `[KB]`/`[WEB]`/`[AI]`
- [ ] Agent Timeline 实时显示执行链路
- [ ] 10+ 轮对话不丢失上下文

#### US-02: 文献上传
> 作为研究者，我希望批量上传论文并自动解析建索引，这样我能快速建立个人文献库。

- [ ] 支持 PDF/DOC/DOCX/MD/TXT 五种格式
- [ ] 自动提取标题、作者、年份、摘要
- [ ] 上传进度实时显示
- [ ] 解析失败跳过并提示，不阻塞批量流程

#### US-03: 论文写作
> 作为研究者，我希望 AI 基于文献库自动生成论文各章节初稿（含引用），这样我能从框架开始而非空白页。

- [ ] 支持生成预设章节（摘要/引言/综述/方法/讨论/结论）
- [ ] 内容基于 RAG 检索，每段标注引用
- [ ] 支持自然语言修改指令
- [ ] 支持子对话编辑模式
- [ ] 最终文档可导出 Markdown

#### US-04: 跨论文对比
> 作为博士生，我希望横向对比多篇论文的方法和结果，这样我能快速发现研究空白。

- [ ] 支持 2-10 篇论文矩阵提取
- [ ] 用户可自定义对比维度
- [ ] 结果以学术风格表格展示
- [ ] 支持导出 CSV/Excel

### 3.4 Non-Goals（明确不做）

- 多用户实时协作编辑
- 论文全文翻译
- LaTeX 格式导出
- 移动端原生 App
- 付费订阅和计费系统
- Zotero / Mendeley 集成

---

## 4. 项目架构

### 4.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                     前端 (Tailwind CSS SPA)                      │
│                                                                 │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│   │ 对话界面  │ │ 文献管理  │ │ 章节编辑  │ │ Agent Timeline  │  │
│   │ (SSE流式) │ │          │ │          │ │  (实时可视化)    │  │
│   └─────┬────┘ └─────┬────┘ └─────┬────┘ └───────┬─────────┘  │
└─────────┼─────────────┼───────────┼──────────────┼─────────────┘
          │ SSE/REST    │ REST      │ REST         │ SSE
          ▼             ▼           ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI 后端 (Port 5328)                        │
│                                                                 │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│  │ Auth │ │Projec│ │Paper │ │ Chat │ │Sectio│ │Extrac│       │
│  │      │ │ ts   │ │  s   │ │(SSE) │ │ ns   │ │ tion │       │
│  └──────┘ └──────┘ └──────┘ └───┬──┘ └──────┘ └──────┘       │
│                                │                                │
│  ┌─────────────────────────────▼────────────────────────────┐  │
│  │          LangGraph 多 Agent 编排层 (Supervisor 模式)       │  │
│  │                                                          │  │
│  │   [Supervisor] ──→ 意图识别 + 路由                        │  │
│  │        │                                                 │  │
│  │        ├─── [Researcher] ──→ RAG 检索 + 联网搜索           │  │
│  │        │       │                                         │  │
│  │        │       ├──→ [Responder]  探索/总结/联网问答        │  │
│  │        │       ├──→ [Writer]     生成/修改/导出章节        │  │
│  │        │       └──→ [Analyst]    分析/图表/框架推荐        │  │
│  │        │                                                 │  │
│  │        └─── [Writer] ──→ 导出 (无需检索)                  │  │
│  │                                                          │  │
│  │   状态管理: AgentState (TypedDict, 19 字段)               │  │
│  │   持久化:   MemorySaver (LangGraph 内置)                  │  │
│  └──────────────────────┬───────────────────────────────────┘  │
│                          │                                     │
│  ┌───────────────────────▼──────────────────────────────────┐  │
│  │                    检索引擎 (RAG)                          │  │
│  │                                                          │  │
│  │   查询 ──→ BM25 (jieba 分词, Top-20)  ──┐                │  │
│  │        ──→ 向量检索 (ChromaDB, Top-20) ──┤→ RRF 融合      │  │
│  │        ──→ [可选] DuckDuckGo 联网搜索 ──┘  (k=60)        │  │
│  │                                         │                 │  │
│  │                          LLM 重排序 (70%LLM + 30%向量)    │  │
│  │                          → 最终 Top-5 + 引用格式化        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌───────────────┐ ┌───────────────┐ ┌────────────────────┐   │
│  │   ChromaDB    │ │    SQLite     │ │   智谱 GLM API     │   │
│  │  (向量存储)    │ │  (业务数据)    │ │  open.bigmodel.cn  │   │
│  └───────────────┘ └───────────────┘ └────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 多 Agent 协作流程

CiteWise 的核心是一个基于 LangGraph 的 **声明式状态图**，所有 Agent 共享 `AgentState` 状态对象：

```
用户输入
  │
  ▼
[Supervisor 节点]
  │  RouterAgent 进行意图识别
  │  策略: LLM 分类 (置信度 ≥0.7) → 关键词匹配 (fallback)
  │  输出: intent + target_agent
  │
  ├── intent == "export" ──────────────────────┐
  │                                            │
  └── 其他所有意图                              │
       │                                      │
       ▼                                      ▼
  [Researcher 节点]                      [Writer 节点] → END
    │  执行 RAG 混合检索
    │  联网搜索 (websearch 意图时)
    │  输出: chunks + rag_content + web_results
    │
    ├── target_agent == "writer"
    │       │
    │       ▼
    │   [Writer 节点]
    │     │  生成章节 / 修改内容
    │     └──→ END
    │
    ├── target_agent == "analyst"
    │       │
    │       ▼
    │   [Analyst 节点]
    │     │  数据分析 / 图表 / 框架
    │     └──→ END
    │
    └── target_agent == "responder"
            │
            ▼
        [Responder 节点]
          │  生成带引用回答 + 三色标注
          └──→ END
```

**Agent 职责矩阵**：

| Agent | 职责 | LLM 模型 | 源文件 |
|-------|------|----------|--------|
| **Supervisor** | 意图分类(10种) + 路由 | glm-4-flash | `src/core/agents/router.py` |
| **Researcher** | RAG 检索 + 联网搜索 | glm-4-flash | `src/core/agents/researcher.py` |
| **Responder** | 生成带标注的回答 | glm-4.7 | `src/core/graph.py` (内置节点) |
| **Writer** | 章节生成/修改/导出 | glm-4.7 | `src/core/agents/writer.py` |
| **Analyst** | 分析/可视化/框架 | glm-4.7 | `src/core/agents/analyst.py` |

**模型分级策略**（成本优化）：

- **轻量任务** (分类/检索) → `glm-4-flash`：低延迟、低成本
- **生成任务** (写作/分析) → `glm-4.7`：高质量、长文本
- **向量化** → `embedding-3`：2048 维，中英双语

### 4.3 检索引擎架构

```
              用户查询
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
  BM25       向量检索     [可选]
 关键词匹配  语义相似度   联网搜索
 (jieba分词) (ChromaDB)  (DuckDuckGo)
  Top-20     Top-20
    │           │           │
    └───────────┼───────────┘
                ▼
        RRF 倒数排名融合 (k=60)
                │
                ▼
          候选文档集合
                │
        ┌───────┴───────┐
        │  候选 > 10 条  │  先粗排到 10 条
        │  候选 ≤ 10 条  │  直接精排
        └───────┬───────┘
                ▼
        LLM 重排序 (70% LLM 打分 + 30% 向量距离)
                │
                ▼
          最终 Top-5 + [作者, 年份] 引用格式化
```

### 4.4 Prompt 工程架构

5 层分层模板，由 `PromptEngine` 动态组装：

| 层级 | 内容 | 动态性 | 示例 |
|------|------|--------|------|
| Layer 1-2 | 系统基础约束 | **固定** | "强制溯源、禁止幻觉、结构化输出" |
| Layer 3 | 用户画像 | **半静态** | 研究领域、关注方向、写作风格 |
| Layer 4 | 项目状态 | **动态** | 文献数量、已提取字段、当前框架 |
| Layer 5 | 任务 Prompt | **按意图切换** | 提取字段/生成章节/分析对比等 8 套模板 |

核心约束注入到每个 Prompt：
1. **强制溯源** — 所有观点必须引用知识库文献 `[作者, 年份]`
2. **禁止幻觉** — 不得编造论文、数据、方法或结论
3. **结构化输出** — 按要求格式输出
4. **忠实原文** — 提取时忠于原文表述

### 4.5 三层记忆架构

| 层级 | 名称 | 存储 | 持久性 | 内容 | 源文件 |
|------|------|------|--------|------|--------|
| Layer 1 | 全局画像 | JSON 文件 | 永久 | 研究偏好、字段模板、写作风格 | `memory.py` GlobalProfile |
| Layer 2 | 项目记忆 | SQLite (7 张表) | 永久 | 项目/论文/章节/提取/图表/用户/会话 | `memory.py` ProjectMemory |
| Layer 3 | 工作记忆 | AgentState (内存) | 会话级 | 当前任务/焦点论文/对话历史 (10 轮滑动窗口) | `graph_state.py` |

**跨项目复用**：GlobalProfile 提供字段模板和写作偏好的跨项目复用，新项目自动继承。

### 4.6 数据模型

#### SQLite 表结构 (7 张表)

```
projects ──┬── papers ──── figures
           │              extractions
           ├── generated_sections
           ├── chat_sessions ──── chat_messages
           └── users
```

| 表 | 主键 | 核心字段 | 说明 |
|----|------|----------|------|
| projects | `proj_{uuid8}` | name, topic, status | 项目是最高组织单元 |
| papers | `paper_{uuid8}` | title, authors, year, chunk_count, sections_json | 论文元数据 + 全文 |
| figures | `fig_{uuid8}` | paper_id, page, caption, context_before/after | 图表元数据 |
| generated_sections | `sec_{uuid8}` | project_id, section_name, content, citations | AI 生成章节 |
| extractions | `ext_{uuid8}` | paper_id, template_name, fields, confidence | 结构化提取结果 |
| users | `user_{uuid8}` | username, password_hash, api_key | 用户信息 |
| chat_sessions / chat_messages | `sess_{uuid8}` / `msg_{uuid8}` | session_id, role, content, intent | 对话历史 |

#### ChromaDB 向量库

```
Collection: paper_chunks
├── id: chunk_uuid (string)
├── embedding: float[2048] (embedding-3)
├── document: chunk_text
└── metadata: { paper_id, title, authors, year, section_level: L0/L1/L2, section_title, page_num }
```

### 4.7 API 设计

| 模块 | 端点数 | 核心接口 |
|------|--------|----------|
| 认证 | 3 | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` |
| 项目 | 4 | `GET/POST /api/projects`, `GET /api/projects/{id}/state`, `DELETE /api/projects/{id}` |
| 论文 | 5 | `POST /api/papers/upload`, `GET /api/papers`, `GET/DELETE /api/papers/{id}` |
| 对话 | 2 | `POST /api/chat` (SSE 流式), `POST /api/chat/sub` (子对话) |
| 章节 | 5 | `GET/POST/PUT/DELETE /api/sections`, `GET /api/sections/export` |
| 提取 | 4 | `GET/POST /api/fields`, `POST /api/extraction`, `GET /api/extraction/export` |
| 搜索 | 1 | `POST /api/search` |
| API Key | 4 | `GET /api/apikeys/providers`, `POST /api/apikeys/verify`, `POST /api/apikeys/save` |
| 评估 | 3 | `GET /api/eval/metrics`, `GET /api/eval/trends`, `POST /api/eval/rate` |
| 知识图谱 | 1 | `GET /api/knowledge-map` |
| 推荐 | 1 | `GET /api/recommendations` |

**SSE 流式事件类型**：

```
event: agent_start   → {agent: "Researcher", timestamp: "..."}
event: token         → {content: "文本片段"}
event: agent_end     → {agent: "Responder", duration_ms: 1234}
event: sources       → {sources: [{type: "KB", title: "...", authors: "..."}]}
event: done          → 对话完成
event: error         → {message: "错误描述"}
```

### 4.8 前端架构

```
static/
├── index.html           SPA 入口 (1173 行, Tailwind CDN)
├── js/
│   └── app.js           主应用逻辑 (2711 行, 含路由/状态/对话/SSE/论文管理/章节)
├── css/
├── vendor/              第三方库 (animate.css, lucide icons, tailwind fallback)
└── html/                页面模板
```

**核心交互**：
- SSE `EventSource` 接收流式 Token → 实时渲染聊天气泡
- 右侧 Agent Timeline 面板 → 显示 `agent_start`/`agent_end` 事件
- 侧边栏 → 项目/论文/章节管理 + 模型选择器

### 4.9 目录结构

```
CiteWise/
├── run.py                         # 启动入口 (uvicorn, port=5328)
├── requirements.txt               # Python 依赖
├── Dockerfile                     # Docker 容器化
├── render.yaml                    # Render 云部署配置
│
├── api/                           # API 层
│   ├── main.py                    # FastAPI 入口 + 中间件 + 生命周期
│   ├── schemas.py                 # Pydantic 请求/响应模型
│   └── routes/                    # 路由模块 (13 个文件)
│       ├── auth.py                # 认证 (JWT)
│       ├── chat.py                # 对话 (SSE 流式)
│       ├── papers.py              # 论文管理
│       ├── sections.py            # 章节管理
│       ├── extraction.py          # 结构化提取
│       ├── knowledge_map.py       # 知识图谱
│       ├── recommendations.py     # 文献推荐
│       └── ...
│
├── src/                           # 核心业务层
│   ├── core/
│   │   ├── graph.py               # LangGraph StateGraph (367 行)
│   │   ├── async_graph.py         # 异步流式图 (464 行)
│   │   ├── graph_state.py         # AgentState TypedDict (19 字段)
│   │   ├── agents/
│   │   │   ├── router.py          # Supervisor 意图路由 (163 行)
│   │   │   ├── researcher.py      # RAG 检索 Agent
│   │   │   ├── writer.py          # 写作 Agent (152 行)
│   │   │   ├── analyst.py         # 分析 Agent (153 行)
│   │   │   ├── coordinator.py     # 兼容层
│   │   │   └── base.py            # Agent 基类
│   │   ├── retriever.py           # 混合检索引擎 (257 行)
│   │   ├── rag.py                 # PDF 解析 + 层级切片 (631 行)
│   │   ├── file_parser.py         # 统一文件解析器 (282 行)
│   │   ├── advanced_parser.py     # Docling 高级解析 (216 行)
│   │   ├── embedding.py           # Embedding + ChromaDB (185 行)
│   │   ├── llm.py                 # LLM 客户端封装 (180 行)
│   │   ├── prompt.py              # 5 层 Prompt 模板 (281 行)
│   │   ├── memory.py              # 三层记忆系统 (563 行)
│   │   ├── source_annotation.py   # 三色来源标注 (121 行)
│   │   ├── cove.py                # CoVe 验证 (287 行)
│   │   └── recommender.py         # 论文推荐 (190 行)
│   ├── tools/
│   │   └── web_search.py          # DuckDuckGo 搜索 (78 行)
│   └── eval/
│       ├── metrics.py             # AgentEval 5 大指标 (181 行)
│       ├── dashboard.py           # 评估 API (54 行)
│       └── ab_test.py             # A/B 测试框架 (120 行)
│
├── config/
│   └── settings.py                # 环境变量 + 路径 + 参数集中配置
│
├── static/                        # 前端 SPA
│   ├── index.html                 # 主页面 (1173 行)
│   └── js/app.js                  # 完整前端逻辑 (2711 行)
│
├── data/                          # 数据目录 (gitignored)
│   ├── papers/                    # 上传的论文文件
│   ├── figures/                   # 提取的图表
│   └── db/
│       ├── citewise.db            # SQLite 主数据库
│       ├── eval.db                # 评估数据库
│       └── chroma/                # ChromaDB 向量库
│
└── docs/                          # 技术设计文档
```

---

## 5. 技术选型

| 层级 | 技术 | 选型理由 |
|------|------|----------|
| **后端框架** | FastAPI | 异步原生、自动 API 文档、SSE 支持 |
| **Agent 编排** | LangGraph (StateGraph) | 声明式状态图、Supervisor 模式、MemorySaver |
| **LLM** | 智谱 GLM-4.7 / glm-4-flash | 中英双语优秀、分级模型降低成本 |
| **Embedding** | 智谱 embedding-3 (2048 维) | 与 LLM 同生态、中英双语 |
| **向量库** | ChromaDB | 轻量级、本地部署、无需额外服务 |
| **关系数据库** | SQLite (WAL 模式) | 零配置、单文件、适合单机部署 |
| **PDF 解析** | pdfplumber + Docling | pdfplumber 稳定、Docling 高级 fallback |
| **中文分词** | jieba | 中英文混合分词、BM25 检索基础 |
| **前端** | Vanilla JS + Tailwind CSS CDN | 无构建工具、快速迭代 |
| **容器化** | Docker + Render | 一键部署、免费层可用 |

**关键配置参数**：

| 参数 | 值 | 含义 |
|------|-----|------|
| 端口 | 5328 | 避开 Sangfor VPN 代理的 10000 端口 |
| VECTOR_TOP_K | 20 | 向量检索候选数 |
| BM25_TOP_K | 20 | 关键词检索候选数 |
| RERANK_TOP_K | 5 | 最终输出结果数 |
| RRF_K | 60 | RRF 融合常数 |
| CHUNK_TARGET_SIZE | 800 字符 | 目标分块大小 |
| Rate Limit | 30 req/min/IP | 接口限流 |

---

## 6. 安全设计

| 措施 | 实现 |
|------|------|
| 认证 | JWT (HMAC-SHA256), 72h 有效期 |
| 密码存储 | PBKDF2-HMAC-SHA256, 200K 次迭代 + 随机盐 |
| 数据隔离 | 项目级隔离 + user_id 过滤 |
| API Key 管理 | 不入库，localStorage / .env 存储 |
| 输入验证 | Pydantic schema 校验所有 API 入参 |
| 文件上传 | 白名单格式 + 50MB 限制 |
| 限流 | 30 请求/分钟/IP |
| 安全头 | X-Content-Type-Options / X-Frame-Options / Referrer-Policy |
| CORS 白名单 | localhost / vercel.app / onrender.com |
| 隐私 | 论文数据本地存储，不传全文到 LLM |

---

## 7. 风险与 Roadmap

### 7.1 技术风险

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 智谱 API 不可用/限流 | 中 | 高 | 降级到 glm-4-flash；缓存常见查询 |
| 大 PDF 解析超时 | 中 | 中 | 异步处理 + 进度通知；50MB 硬限制 |
| 长对话上下文溢出 | 中 | 中 | 自动摘要压缩；10 轮滑动窗口 |
| LangGraph Breaking Changes | 中 | 中 | 锁定依赖版本；关注 Release Notes |

### 7.2 版本历史

| 版本 | 状态 | 核心能力 |
|------|------|----------|
| V1.0 MVP | ✅ 完成 | 单 Agent 对话 + PDF 上传 + 基础检索 |
| V2.0 多 Agent | ✅ 完成 | LangGraph Supervisor + 4 Agent + 章节管理 |
| V3.0 生产级 | ✅ 完成 | SSE 流式 + Timeline + 三色标注 + AgentEval + 多供应商 |
| V3.1 稳定性 | ✅ 完成 | SSE 兼容修复 + 模型选择器重构 + E2E 测试 |
| V3.2 当前版 | ✅ 完成 | 异步流式 + CoVe 验证 + Docling 解析 + 知识图谱 + 推荐 |

### 7.3 下一步

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P1 | 部署上线 (Render) | 规划中 |
| P1 | 面试 Demo 脚本 | 规划中 |
| P2 | Docker + Render 部署优化 | 规划中 |

---

## 附录 A: 环境配置

```env
# LLM
OPENAI_API_KEY=your_zhipu_api_key
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
LLM_MODEL=glm-4.7

# Embedding
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSION=2048

# Server
PORT=5328
HOST=0.0.0.0
```

## 附录 B: 启动命令

```bash
cd C:/Users/77230/CiteWise && python run.py
# 访问 http://localhost:5328
```

## 附录 C: 术语表

| 术语 | 定义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| RRF | Reciprocal Rank Fusion，倒数排名融合 |
| SSE | Server-Sent Events，服务器推送事件 |
| TTFT | Time To First Token，首 token 延迟 |
| CoVe | Chain of Verification，验证链 |
| Supervisor | 监督者 Agent，负责意图分类和路由 |
| AgentEval | 内置 Agent 评估系统 |
| L0/L1/L2 | 文档分层分块的三个粒度级别 |
