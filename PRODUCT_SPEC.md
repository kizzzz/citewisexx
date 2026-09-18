# CiteWise -- 智能研究助手 产品规格说明书

> **版本**: V3.1
> **更新日期**: 2026-04-09
> **产品定位**: AI 驱动的学术文献管理与智能写作平台
> **目标场景**: 学术研究全流程辅助（文献管理 -> 知识检索 -> AI 写作 -> 结构化分析）

---

## 目录

1. [产品概述](#1-产品概述)
2. [目标用户](#2-目标用户)
3. [功能架构](#3-功能架构)
4. [技术架构](#4-技术架构)
5. [数据模型](#5-数据模型)
6. [API 接口](#6-api-接口)
7. [用户流程](#7-用户流程)
8. [部署方案](#8-部署方案)
9. [安全设计](#9-安全设计)
10. [后续规划](#10-后续规划)

---

## 1. 产品概述

### 1.1 产品愿景

CiteWise 是一款面向中文学术用户的 AI 研究助手，旨在解决学术写作中的三大核心痛点：

- **信息过载**: 研究者需要阅读大量论文，难以高效提取关键信息
- **写作低效**: 文献综述、论文撰写需要反复查阅和整理材料
- **引用困难**: 跨论文引用的准确性和一致性难以保证

CiteWise 通过多 Agent 协作架构，将 RAG（检索增强生成）、多供应商 LLM、结构化提取等能力整合为一个端到端的学术研究平台。

### 1.2 核心价值主张

| 维度 | 描述 |
|------|------|
| **效率提升** | 从数小时的文献整理缩短至数分钟的结构化提取和综述生成 |
| **准确性保障** | RAG + 引用校验机制，确保 AI 生成内容的可追溯性和引用准确性 |
| **全流程覆盖** | 从论文上传、知识检索、AI 写作到文档导出的一站式解决方案 |
| **模型灵活性** | 支持智谱 GLM、DeepSeek、OpenAI、通义千问等多个 LLM 供应商 |

### 1.3 产品形态

- **前端**: 基于 Tailwind CSS 的单页应用（SPA），无需构建工具
- **后端**: FastAPI 提供 RESTful API + SSE 流式输出
- **部署**: Docker 容器化，支持 Render 云部署和本地运行

---

## 2. 目标用户

### 2.1 主要用户画像

| 画像 | 描述 | 核心需求 |
|------|------|----------|
| **研究生** | 硕博在读，需要撰写文献综述和论文 | 快速理解多篇论文、辅助撰写综述、管理参考文献 |
| **青年学者** | 高校教师、研究院研究员 | 批量文献管理、结构化提取、研究趋势分析 |
| **科研团队** | 需要协作管理研究项目的团队 | 项目级文献管理、知识库共享、研究进展追踪 |

### 2.2 使用场景

1. **文献综述撰写**: 上传 10-20 篇相关论文 -> CiteWise 自动解析入库 -> 通过对话式交互让 AI 生成综述章节
2. **论文深度理解**: 针对单篇论文提问（如"这篇论文的研究方法是什么"），AI 基于 RAG 提供有引用依据的回答
3. **结构化信息提取**: 批量提取论文中的研究方法、核心算法、数据集、主要结论等字段，导出为 Excel
4. **跨论文分析**: 让 AI 对比分析多篇论文的异同，生成对比表格或图表

---

## 3. 功能架构

### 3.1 功能模块总览

```
CiteWise
├── 用户管理
│   ├── 注册 / 登录（JWT 认证）
│   ├── 多供应商 API Key 管理
│   └── 用户数据隔离
├── 项目管理
│   ├── 创建 / 删除项目
│   ├── 项目状态总览
│   └── 项目级资源隔离
├── 文献管理
│   ├── 多格式文件上传（PDF/DOCX/MD/TXT/XLSX）
│   ├── PDF 智能解析（元数据/章节/表格/图表）
│   ├── 层级切片与向量化入库
│   ├── 论文详情查看（章节级内容展示）
│   └── 论文删除与索引清理
├── 智能对话（Multi-Agent）
│   ├── 意图识别与路由
│   ├── RAG 知识库检索（向量 + BM25 混合检索）
│   ├── 联网搜索集成
│   ├── Token 级 SSE 流式输出
│   ├── 引用校验与来源标注
│   └── Agent Timeline 实时可视化
├── 章节写作
│   ├── AI 辅助章节生成
│   ├── 章节内容改写 / 修改
│   ├── 章节框架推荐
│   ├── 文档导出（Markdown）
│   └── 子对话编辑
├── 结构化提取
│   ├── 自定义提取字段
│   ├── 批量论文信息提取
│   └── 提取结果导出（Excel）
├── 数据分析
│   ├── 项目级分析洞察
│   └── 可视化图表生成
└── 评估看板（Agent Eval）
    ├── 任务成功率追踪
    ├── 引用准确率监控
    ├── 幻觉率检测
    ├── 响应时间趋势
    └── 自动优化建议
```

### 3.2 模块详细说明

#### 3.2.1 用户管理

**认证机制**: 基于 JWT（JSON Web Token）的无状态认证，纯 Python 实现，无需外部依赖。

- **注册**: 用户名 + 密码，密码使用 PBKDF2-HMAC-SHA256（200,000 次迭代）+ 随机盐值哈希存储
- **登录**: 验证后返回 JWT Token，有效期 72 小时
- **API Key 管理**: 支持配置多个 LLM 供应商的 API Key（智谱、DeepSeek、OpenAI、Moonshot、通义千问、自定义），通过调用供应商的 /models 接口验证有效性

#### 3.2.2 项目管理

项目是 CiteWise 中最高层级的组织单元，所有论文、章节、提取记录都归属于特定项目。

- **项目创建**: 设置项目名称和研究主题
- **项目状态**: 聚合展示论文数量、提取字段、已完成章节、图表数量等信息
- **项目删除**: 级联删除关联的论文、图表、提取记录和生成章节

#### 3.2.3 文献管理

**多格式解析**:

| 格式 | 解析方式 | 支持内容 |
|------|----------|----------|
| PDF | pdfplumber + PyPDF2 | 元数据、章节、表格、图表 |
| DOCX | python-docx | 元数据、段落、表格 |
| MD/TXT | 文本读取 + Markdown 标题解析 | 章节切分 |
| XLSX | openpyxl | 工作表转 Markdown 表格 |

**PDF 智能解析**:
- 从 PDF 元数据和文件名中提取标题、作者、年份
- 章节检测：支持数字编号（1.2.3 Title）和中文编号（一、引言 / 第一章 引言）
- 表格提取：自动将表格转为 Markdown 格式
- 图表元数据提取：图片位置、尺寸、caption、前后段落上下文

**层级切片策略**:
- **L0 论文级**: 摘要单独提取，作为论文级检索单元
- **L1 章节级**: 短章节（<= 800 字符）整体作为一个 chunk
- **L2 段落级**: 长章节通过语义切块（embedding-based）或规则切分
- **句子级 Overlap**: 相邻 chunk 之间有 2 句重叠，保证上下文连贯

#### 3.2.4 智能对话（Multi-Agent 核心）

CiteWise 的核心交互通过多 Agent 协作实现，详见第 4 节技术架构。

**支持意图类型**:

| 意图 | 关键词示例 | 处理 Agent |
|------|-----------|-----------|
| explore（探索问答） | 问句（?？） | Researcher -> Responder |
| summarize（总结） | 总结、梳理、对比 | Researcher -> Responder |
| websearch（联网搜索） | 最新、新闻、搜索 | Researcher -> Responder |
| generate（生成） | 写、生成、撰写 | Researcher -> Writer |
| modify（改写） | 修改、调整、重写 | Researcher -> Writer |
| framework（框架） | 框架、大纲、思路 | Researcher -> Writer |
| export（导出） | 导出、下载、保存 | Writer |
| chart（图表） | 图表、可视化 | Researcher -> Analyst |
| analyze（分析） | 分析、洞察、建议 | Researcher -> Analyst |

#### 3.2.5 结构化提取

用户可自定义提取字段（如研究方法、核心算法、数据集、主要结论），CiteWise 对项目内论文批量提取结构化信息。

- 默认字段: 研究方法、核心算法、数据集、主要结论
- 支持自定义字段，最多 10 个
- 提取结果可导出为 Excel 文件

#### 3.2.6 评估看板（Agent Eval）

基于 5 大核心指标的 Agent 性能评估系统：

| 指标 | 说明 |
|------|------|
| 任务成功率 | Agent 成功完成任务的比率 |
| 引用准确率 | 生成内容中引用的准确性 |
| 幻觉率 | 检测到的幻觉内容占比 |
| 平均响应时间 | 从请求到响应的耗时 |
| 成本估算 | LLM API 调用费用估算 |

系统会根据指标自动生成优化建议（如成功率低于 85% 建议优化路由，幻觉率超过 10% 建议增强 RAG 检索质量等）。

---

## 4. 技术架构

### 4.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                      前端 (SPA)                          │
│          Vanilla JS + Tailwind CSS + Lucide Icons        │
│    ┌─────────┐  ┌──────────┐  ┌──────────┐              │
│    │ 项目管理 │  │ 文献管理  │  │ AI 对话   │              │
│    └─────────┘  └──────────┘  └──────────┘              │
│    ┌─────────┐  ┌──────────┐  ┌──────────┐              │
│    │ 章节编辑 │  │ 提取分析  │  │ 评估看板  │              │
│    └─────────┘  └──────────┘  └──────────┘              │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼─────────────────────────────────┐
│                  FastAPI (API Layer)                      │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │ Auth │ │Projec│ │Paper │ │ Chat │ │Sectio│ │Extrac│  │
│  │      │ │  ts  │ │  s   │ │      │ │  ns  │ │ tion │  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ │
│  ┌──────┐ ┌──────┐ ┌──────┐                             │
│  │Search│ │APIKey│ │ Eval │  中间件: CORS / 限流 / 安全头│
│  └──────┘ └──────┘ └──────┘                             │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│             LangGraph Multi-Agent Pipeline                │
│                                                          │
│   START ──► [Supervisor] ──► (路由决策)                   │
│                 │                                        │
│       ┌─────────┼──────────────┐                         │
│       ▼         ▼              ▼                         │
│  [Researcher]  [Writer]   (export 直接)                  │
│       │                                        │         │
│  ┌────┼────┐                                  │         │
│  ▼    ▼    ▼                                  │         │
│ Writer Analyst Responder                       │         │
│  │    │    │                                   │         │
│  ▼    ▼    ▼                                   ▼         │
│  END  END  END                                 END       │
│                                                          │
│  状态管理: AgentState (TypedDict) + MemorySaver          │
└────────────┬───────────────────┬─────────────────────────┘
             │                   │
    ┌────────▼────────┐  ┌──────▼───────┐
    │  检索引擎 (RAG)  │  │  LLM 供应商   │
    │                 │  │              │
    │ ┌─────────────┐│  │ 智谱 GLM-4.7 │
    │ │ ChromaDB    ││  │ DeepSeek     │
    │ │ (向量检索)   ││  │ OpenAI       │
    │ └─────────────┘│  │ Moonshot     │
    │ ┌─────────────┐│  │ 通义千问     │
    │ │ BM25        ││  │ 自定义       │
    │ │ (关键词检索) ││  │              │
    │ └─────────────┘│  └──────────────┘
    │ ┌─────────────┐│
    │ │ RRF 融合    ││   ┌──────────────┐
    │ │ + 重排序    ││   │ Embedding    │
    │ └─────────────┘│   │ 智谱 embedding-3│
    └─────────────────┘  │ (2048 维)     │
                         └──────────────┘
    ┌─────────────────────────────────────────┐
    │              数据存储层                   │
    │                                         │
    │  ┌──────────┐  ┌──────────┐  ┌───────┐ │
    │  │  SQLite   │  │ ChromaDB │  │ 文件  │ │
    │  │ (业务数据) │  │ (向量库)  │  │ 系统  │ │
    │  └──────────┘  └──────────┘  └───────┘ │
    └─────────────────────────────────────────┘
```

### 4.2 Agent Pipeline 详解

#### Supervisor 模式

CiteWise 采用 LangGraph 的 Supervisor 模式构建多 Agent 协作图。整个流程是一个声明式的有向状态图（StateGraph），所有节点共享 `AgentState` 状态。

**完整流程**:

```
用户输入
    │
    ▼
[Supervisor 节点]
    │  RouterAgent 进行意图识别
    │  返回: intent + target_agent
    │
    ├── intent == "export"
    │       │
    │       ▼
    │   [Writer 节点] ──► END
    │
    └── 其他所有意图
            │
            ▼
        [Researcher 节点]
            │  执行 RAG 检索 + 联网搜索
            │  返回: chunks + rag_content + web_results
            │
            ├── target_agent == "writer"
            │       │
            │       ▼
            │   [Writer 节点] ──► END
            │
            ├── target_agent == "analyst"
            │       │
            │       ▼
            │   [Analyst 节点] ──► END
            │
            └── 其他 (responder)
                    │
                    ▼
                [Responder 节点] ──► END
```

**各 Agent 职责**:

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **RouterAgent** | 意图识别，决定任务分配给哪个 Agent | user_input | intent, target_agent |
| **ResearchAgent** | RAG 知识库检索 + 联网搜索 | user_input, project_id, intent | chunks, rag_content, web_results, sources |
| **WriterAgent** | 章节生成、内容改写、文档导出 | research_result + 写作指令 | content, response_type, section_name |
| **AnalystAgent** | 项目分析、可视化图表、洞察建议 | project_id + 分析指令 | analysis/charts/insights |
| **ResponderAgent** | 探索性问答，基于 RAG/联网结果生成回答 | chunks + user_input | content, citations, sources |

#### AgentState 状态结构

```python
class AgentState(TypedDict, total=False):
    # 输入
    user_input: str               # 用户原始输入
    project_id: str               # 当前项目 ID

    # 路由
    intent: str                   # 识别的意图
    next_agent: str               # 路由目标 Agent

    # 研究结果
    chunks: list                  # RAG 检索到的文档片段
    rag_content: str              # 格式化的 RAG 内容
    web_results: list             # 联网搜索结果
    sources: list                 # 来源列表

    # 输出
    content: str                  # 最终响应内容
    response_type: str            # 响应类型
    section_name: str             # 章节名
    citations: dict               # 引用验证结果
    content_sources: dict         # 来源标注 {rag, llm, web}
    word_count: int               # 字数

    # 追踪
    thinking_steps: list          # 思考步骤
    agent_events: list            # Agent 事件时间线
```

### 4.3 检索引擎（RAG）

CiteWise 采用 **混合检索 + RRF 融合 + 重排序** 的三阶段检索架构：

```
查询文本
    │
    ├──► 向量检索 (ChromaDB + embedding-3)
    │       top_k = 20
    │
    ├──► BM25 检索 (rank_bm25 + jieba 分词)
    │       top_k = 20
    │
    └──► RRF (Reciprocal Rank Fusion) 融合
            k = 60
            │
            ▼
        候选文档集
            │
            ▼
        重排序 (向量距离 + 关键词匹配)
            top_k = 5
            │
            ▼
        最终结果（带引用标注）
```

**配置参数**:

| 参数 | 值 | 说明 |
|------|-----|------|
| VECTOR_TOP_K | 20 | 向量检索返回数 |
| BM25_TOP_K | 20 | BM25 检索返回数 |
| RERANK_TOP_K | 5 | 最终重排序输出数 |
| RRF_K | 60 | RRF 融合常数 |
| CHUNK_TARGET_SIZE | 800 | 目标 chunk 大小（字符） |
| CHUNK_MIN_SIZE | 200 | 最小 chunk 大小 |
| CHUNK_MAX_SIZE | 1500 | 最大 chunk 大小 |

### 4.4 流式输出机制

CiteWise 使用 SSE（Server-Sent Events）实现 Token 级流式输出：

1. 前端通过 `POST /api/chat` 发起请求
2. 后端通过 `EventSourceResponse` 返回 SSE 流
3. 事件类型:
   - `agent_start`: Agent 开始处理（含 Agent 名称和描述）
   - `agent_end`: Agent 处理完成（含耗时和结果摘要）
   - `token`: 逐字输出内容
   - `thinking`: 思考步骤
   - `error`: 错误信息
4. 前端 `EventSource` 接收事件，实时渲染到聊天气泡和右侧 Timeline 面板

### 4.5 三层记忆架构

| 层级 | 名称 | 存储 | 作用 |
|------|------|------|------|
| Layer 1 | 全局画像 (GlobalProfile) | JSON 文件 | 用户研究兴趣、写作风格偏好、自定义字段模板 |
| Layer 2 | 项目记忆 (ProjectMemory) | SQLite | 项目、论文、章节、提取记录等持久化数据 |
| Layer 3 | 工作记忆 (WorkingMemory) | 内存 | 当前会话上下文、前文摘要滑动窗口 |

---

## 5. 数据模型

### 5.1 SQLite Schema

主数据库文件位于 `data/db/citewise.db`，使用 WAL 模式支持并发读取。

#### projects 表

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,           -- 格式: proj_{uuid8}
    name TEXT NOT NULL,            -- 项目名称
    topic TEXT DEFAULT '',         -- 研究主题
    status TEXT DEFAULT 'active',  -- 项目状态
    config TEXT DEFAULT '{}',      -- 项目配置 (JSON)
    user_id TEXT DEFAULT '',       -- 所属用户 ID
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### papers 表

```sql
CREATE TABLE papers (
    id TEXT PRIMARY KEY,           -- 格式: paper_{uuid8}
    project_id TEXT,               -- 所属项目 ID
    title TEXT,                    -- 论文标题
    authors TEXT,                  -- 作者
    year INTEGER,                  -- 发表年份
    filename TEXT,                 -- 原始文件名
    chunk_count INTEGER DEFAULT 0, -- 切片数量
    metadata TEXT DEFAULT '{}',    -- 额外元数据 (JSON)
    raw_text TEXT DEFAULT '',      -- 全文纯文本
    sections_json TEXT DEFAULT '[]', -- 章节结构 (JSON)
    indexed_at TEXT DEFAULT (datetime('now'))
);
```

#### figures 表

```sql
CREATE TABLE figures (
    id TEXT PRIMARY KEY,           -- 格式: fig_{uuid8}
    paper_id TEXT,                 -- 所属论文 ID
    project_id TEXT,               -- 所属项目 ID
    page INTEGER,                  -- 所在页码
    caption TEXT,                  -- 图表说明
    context_before TEXT DEFAULT '',-- 图表前文上下文
    context_after TEXT DEFAULT '', -- 图表后文上下文
    section_title TEXT DEFAULT '', -- 所属章节
    width REAL DEFAULT 0,         -- 图片宽度
    height REAL DEFAULT 0,        -- 图片高度
    metadata TEXT DEFAULT '{}'    -- 额外元数据
);
```

#### generated_sections 表

```sql
CREATE TABLE generated_sections (
    id TEXT PRIMARY KEY,           -- 格式: sec_{uuid8}
    project_id TEXT,               -- 所属项目 ID
    section_name TEXT,             -- 章节名称
    content TEXT,                  -- 章节内容 (Markdown)
    word_count INTEGER DEFAULT 0,  -- 字数
    citations TEXT DEFAULT '[]',   -- 引用列表 (JSON)
    generated_at TEXT DEFAULT (datetime('now'))
);
```

#### extractions 表

```sql
CREATE TABLE extractions (
    id TEXT PRIMARY KEY,           -- 格式: ext_{uuid8}
    project_id TEXT,               -- 所属项目 ID
    paper_id TEXT,                 -- 所属论文 ID
    template_name TEXT,            -- 提取模板名称
    fields TEXT DEFAULT '{}',      -- 提取结果 (JSON)
    confidence TEXT DEFAULT '{}',  -- 置信度 (JSON)
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### users 表

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,           -- 格式: user_{uuid8}
    username TEXT UNIQUE NOT NULL, -- 用户名（唯一）
    password_hash TEXT NOT NULL,   -- PBKDF2 密码哈希
    password_salt TEXT DEFAULT '', -- 密码盐值
    api_key TEXT DEFAULT '',       -- 加密后的 API Key
    api_key_encrypted TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 5.2 向量库（ChromaDB）

存储路径: `data/db/chroma`

每个文档片段（chunk）在 ChromaDB 中的存储结构:

```python
{
    "chunk_id": "paper_xxx_L0_xxxx",   # 文档 ID
    "paper_id": "paper_xxx",            # 所属论文
    "paper_title": "...",               # 论文标题
    "authors": "...",                   # 作者
    "year": 2024,                       # 年份
    "section_title": "摘要",            # 章节标题
    "section_level": "L0",             # 层级
    "text": "...",                      # 文本内容
    "has_figure": False,               # 是否含图
    "has_table": False,                # 是否含表
}
```

Embedding 配置:
- 模型: 智谱 embedding-3
- 维度: 2048

### 5.3 评估数据库（eval.db）

存储路径: `data/db/eval.db`

```sql
CREATE TABLE eval_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    session_id TEXT,               -- 会话 ID
    project_id TEXT,               -- 项目 ID
    intent TEXT,                   -- 意图类型
    task_type TEXT,                -- 任务类型
    success BOOLEAN,              -- 是否成功
    response_time_ms INTEGER,     -- 响应时间
    token_count INTEGER,          -- Token 消耗
    has_citations BOOLEAN,        -- 是否有引用
    citation_accuracy REAL,       -- 引用准确率
    hallucination_flag BOOLEAN,   -- 是否检测到幻觉
    llm_model TEXT,               -- 使用的模型
    prompt_version TEXT,           -- Prompt 版本
    user_rating INTEGER,          -- 用户评分 (1-5)
    cost_estimate REAL,           -- 成本估算
    metadata TEXT                 -- 额外元数据 (JSON)
);
```

---

## 6. API 接口

所有接口前缀为 `/api`，完整文档可通过 `/docs`（Swagger UI）查看。

### 6.1 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册，返回 JWT Token |
| POST | `/api/auth/login` | 用户登录，返回 JWT Token |
| GET | `/api/auth/me` | 获取当前用户信息（需 Bearer Token） |

### 6.2 项目管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects` | 获取项目列表 |
| POST | `/api/projects` | 创建新项目 |
| GET | `/api/projects/{project_id}/state` | 获取项目完整状态 |
| DELETE | `/api/projects/{project_id}` | 删除项目（级联删除） |

### 6.3 论文管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/papers?project_id=` | 获取项目下的论文列表 |
| POST | `/api/papers/upload` | 上传论文（JSON 响应） |
| POST | `/api/papers/upload/stream` | 上传论文（SSE 流式进度） |
| GET | `/api/papers/{paper_id}` | 获取论文详情（含章节内容） |
| DELETE | `/api/papers/{paper_id}?project_id=` | 删除论文及其索引 |

### 6.4 对话接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 主对话（SSE Token 级流式输出） |
| POST | `/api/chat/sub` | 子对话（章节级编辑） |

### 6.5 章节管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sections?project_id=` | 获取章节列表（去重） |
| POST | `/api/sections` | AI 生成章节 |
| PUT | `/api/sections/{section_id}` | 更新章节内容 |
| DELETE | `/api/sections/{section_id}` | 删除章节 |
| GET | `/api/sections/export?project_id=` | 导出为 Markdown 文档 |

### 6.6 结构化提取接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/fields` | 获取默认提取字段 |
| POST | `/api/fields` | 保存自定义提取字段 |
| POST | `/api/extraction` | 执行结构化提取 |
| GET | `/api/extraction/export?project_id=` | 导出提取结果为 Excel |

### 6.7 搜索接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/search` | 联网搜索（LLM 摘要增强） |

### 6.8 API Key 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/apikeys/providers` | 获取支持的供应商列表 |
| POST | `/api/apikeys/verify` | 验证 API Key 有效性 |
| POST | `/api/apikeys/save` | 保存用户 API Key |
| GET | `/api/apikeys/{user_id}` | 获取用户的 API Key |

### 6.9 评估看板接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/eval/metrics` | 获取评估指标汇总 |
| GET | `/api/eval/trends` | 获取每日趋势数据 |
| POST | `/api/eval/rate` | 提交用户评分 |

---

## 7. 用户流程

### 7.1 新用户上手流程

```
注册账号 → 登录 → 配置 API Key → 创建项目 → 上传论文 → 开始对话
```

详细步骤:

1. **注册**: 在登录页点击注册，输入用户名和密码
2. **配置 API Key**: 在设置页面选择 LLM 供应商（如智谱 GLM），输入 API Key，系统自动验证
3. **创建项目**: 输入项目名称（如"大语言模型在教育领域应用"）和研究主题
4. **上传论文**: 支持拖拽上传多个 PDF/DOCX 文件，系统自动解析并显示进度
5. **开始对话**: 在项目内输入问题或写作指令，AI 实时生成回答

### 7.2 文献综述撰写流程

```
上传文献 → 浏览解析结果 → 对话探索 → 生成章节 → 编辑修改 → 导出文档
```

详细步骤:

1. **上传 10-20 篇相关论文**，系统自动解析为结构化内容并入库
2. **浏览论文详情**，确认解析质量（标题、作者、章节是否正确）
3. **通过对话探索**: "帮我总结这几篇论文的研究方法"，AI 基于 RAG 提供带引用的回答
4. **生成综述章节**: "帮我写文献综述"，AI 根据检索到的文献生成综述初稿
5. **编辑修改**: 在章节编辑器中通过子对话进一步修改（如"增加关于 XXX 的讨论"）
6. **导出文档**: 将所有章节整合为 Markdown 文档下载

### 7.3 结构化提取流程

```
配置提取字段 → 执行批量提取 → 查看结果 → 导出 Excel
```

详细步骤:

1. **配置字段**: 使用默认字段（研究方法、核心算法、数据集、主要结论）或自定义
2. **执行提取**: 系统对每篇论文进行 RAG 检索 + LLM 提取，最多处理 10 篇
3. **查看结果**: 以表格形式展示每篇论文的提取结果
4. **导出 Excel**: 一键下载结构化提取结果

### 7.4 AI 对话交互流程

```
用户输入 → [Supervisor 识别意图]
    │
    ├── 探索问答 ──► [Researcher 检索] ──► [Responder 生成] ──► 流式输出
    ├── 章节生成 ──► [Researcher 检索] ──► [Writer 写作]   ──► 流式输出
    ├── 数据分析 ──► [Researcher 检索] ──► [Analyst 分析]  ──► 流式输出
    └── 文档导出 ──► [Writer 整合] ──► 返回完整文档
```

前端展示:
- 聊天气泡: 实时显示 Token 级流式内容
- 右侧 Timeline 面板: 显示 Agent 处理过程（开始、进度、完成、耗时）
- 来源标注: 标注内容来源（RAG / LLM 知识 / 联网搜索）

---

## 8. 部署方案

### 8.1 容器化部署（推荐）

**Dockerfile**:

```dockerfile
FROM python:3.10-slim
WORKDIR /opt/render/project/src
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data/papers data/figures data/db/chroma
ENV HOST=0.0.0.0
ENV PORT=10000
EXPOSE 10000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "10000"]
```

### 8.2 Render 云部署

**render.yaml 配置**:

```yaml
services:
  - type: web
    name: citewise-backend
    runtime: docker
    plan: free
    envVars:
      - key: OPENAI_API_KEY
        sync: false              # 在 Render Dashboard 中手动设置
      - key: OPENAI_BASE_URL
        value: https://open.bigmodel.cn/api/paas/v4/
      - key: LLM_MODEL
        value: glm-4.7
      - key: EMBEDDING_MODEL
        value: embedding-3
      - key: EMBEDDING_DIMENSION
        value: "2048"
      - key: PORT
        value: "10000"
```

**部署步骤**:

1. 将代码推送到 GitHub 仓库
2. 在 Render 中创建新的 Web Service，连接 GitHub 仓库
3. Render 自动检测 `render.yaml` 配置
4. 设置 `OPENAI_API_KEY` 环境变量（加密存储）
5. Render 自动构建 Docker 镜像并部署
6. 访问 `https://citewise-w9op.onrender.com`

### 8.3 本地开发部署

```bash
# 克隆仓库
git clone <repo-url>
cd CiteWise

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 OPENAI_API_KEY

# 启动服务
python run.py
# 或
uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

### 8.4 前端部署

前端静态文件位于 `static/` 目录，可选择:

- **一体化部署**: 由 FastAPI 直接提供静态文件（默认）
- **Vercel 部署**: 通过 `vercel.json` 配置，将 `static/` 目录部署到 Vercel，API 请求代理到 Render 后端

---

## 9. 安全设计

### 9.1 认证与授权

| 机制 | 实现方式 |
|------|----------|
| 密码存储 | PBKDF2-HMAC-SHA256，200,000 次迭代，每用户独立随机盐值 |
| Token | 自实现 JWT（HMAC-SHA256 签名），72 小时有效期 |
| 数据隔离 | 所有数据按项目隔离，项目关联 user_id |
| API Key 存储 | Base64 编码存储于 SQLite（非生产级加密，适合 MVP） |

### 9.2 网络安全

| 措施 | 配置 |
|------|------|
| CORS 白名单 | 仅允许 localhost:8080、localhost:3000、vercel.app、onrender.com |
| 安全响应头 | X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: strict-origin-when-cross-origin, Permissions-Policy: camera=(), microphone=(), geolocation=() |
| 速率限制 | 每 IP 每 60 秒最多 30 次请求，超过返回 429 |
| HTTPS | Render 平台自动提供 SSL/TLS |

### 9.3 输入验证

| 接口 | 验证规则 |
|------|----------|
| 聊天消息 | 非空，最大 2000 字符 |
| 搜索查询 | 非空，最大 200 字符 |
| 文件上传 | 格式白名单（.pdf/.doc/.docx/.md/.txt/.xlsx/.xls），单文件最大 50MB |
| 提取字段 | 非空列表，最多 10 个字段 |
| 用户名 | 2-50 字符 |
| 密码 | 6-100 字符 |
| Section ID | 正则 `^sec_[0-9a-f]+$` |

### 9.4 数据安全

- SQLite 使用 WAL 模式，防止写入冲突
- 文件名通过 `os.path.basename()` 防止路径遍历
- 敏感配置通过环境变量注入，不硬编码在源代码中
- 前后端分离部署时，API Key 不暴露在客户端

---

## 10. 后续规划

### 10.1 短期（V3.2）

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **LLM 异步流式** | 将 LLM 调用改为完全异步，实现真正的逐字流式输出 | P0 |
| **CoVe 验证** | 实现 Chain-of-Verification，减少幻觉输出 | P0 |
| **Prompt 版本管理** | 支持 A/B 测试不同 Prompt 版本，通过 Eval 看板对比效果 | P1 |
| **错误处理增强** | 统一错误响应格式，避免向用户泄露内部错误信息 | P1 |

### 10.2 中期（V4.0）

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **高级 PDF 解析** | 集成 LlamaParse / Docling，提升表格和公式提取质量 | P0 |
| **多用户协作** | 支持项目共享、多人同时编辑、评论批注 | P1 |
| **知识图谱** | 自动构建论文间的引用关系图和概念关系图 | P1 |
| **引用格式规范** | 支持 APA、MLA、GB/T 7714 等引用格式自动转换 | P2 |
| **写作模板** | 提供开题报告、文献综述、论文各章节的写作模板 | P2 |

### 10.3 长期（V5.0+）

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **多模态支持** | 支持论文中图表的多模态理解和描述 | P1 |
| **实时协作编辑** | 类似 Google Docs 的多人实时编辑 | P2 |
| **插件系统** | 支持第三方插件扩展 Agent 能力 | P2 |
| **企业版部署** | 私有化部署方案，支持 SSO、审计日志 | P3 |
| **API 开放平台** | 提供公开 API，支持第三方集成 | P3 |

### 10.4 性能优化方向

| 方向 | 当前状态 | 目标 |
|------|----------|------|
| 首次响应时间 | ~3-5s（同步 LLM 调用） | < 1s（异步流式） |
| 并发能力 | 单进程 uvicorn | 多 worker + 异步 |
| 向量检索 | ChromaDB 本地 | 支持远程向量库（Pinecone/Milvus） |
| PDF 解析 | pdfplumber | LlamaParse/Docling |
| 缓存 | 无 | 热点查询缓存 + 语义缓存 |

---

## 附录 A: 技术栈清单

| 类别 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | - |
| 数据库 | SQLite | - |
| 向量库 | ChromaDB | - |
| AI 编排 | LangGraph | - |
| LLM | 智谱 GLM-4.7 | - |
| Embedding | 智谱 embedding-3 | 2048 维 |
| PDF 解析 | pdfplumber + PyPDF2 | - |
| DOCX 解析 | python-docx | - |
| XLSX 解析 | openpyxl | - |
| 分词 | jieba | - |
| BM25 | rank_bm25 | - |
| 前端 | Vanilla JS + Tailwind CSS | - |
| 图标 | Lucide Icons | - |
| 容器 | Docker | - |
| 部署 | Render | - |
| Python | 3.10 | - |

## 附录 B: 项目目录结构

```
CiteWise/
├── api/                         # API 层
│   ├── main.py                 # FastAPI 入口 + 中间件
│   ├── schemas.py              # Pydantic 请求/响应模型
│   └── routes/                 # 路由模块
│       ├── auth.py             # 认证
│       ├── chat.py             # 对话（SSE 流式）
│       ├── projects.py         # 项目管理
│       ├── papers.py           # 论文管理
│       ├── sections.py         # 章节管理
│       ├── extraction.py       # 结构化提取
│       ├── search.py           # 联网搜索
│       └── apikeys.py          # API Key 管理
├── config/
│   └── settings.py             # 全局配置
├── src/
│   ├── core/                   # 核心模块
│   │   ├── graph.py            # LangGraph 多 Agent 图
│   │   ├── graph_state.py      # AgentState 定义
│   │   ├── async_graph.py      # 异步流式图
│   │   ├── agents/             # Agent 实现
│   │   │   ├── router.py       # 意图路由
│   │   │   ├── researcher.py   # RAG 检索
│   │   │   ├── writer.py       # 章节写作
│   │   │   ├── analyst.py      # 数据分析
│   │   │   ├── base.py         # Agent 基类
│   │   │   └── coordinator.py  # 兼容层
│   │   ├── retriever.py        # 混合检索（向量 + BM25 + RRF）
│   │   ├── embedding.py        # 向量化（ChromaDB）
│   │   ├── rag.py              # PDF 解析 + 层级切片
│   │   ├── llm.py              # LLM 客户端
│   │   ├── prompt.py           # Prompt 模板
│   │   ├── memory.py           # 三层记忆系统
│   │   ├── source_annotation.py # 来源标注
│   │   └── cove.py             # CoVe 验证（待实现）
│   ├── tools/
│   │   └── web_search.py       # 联网搜索工具
│   ├── eval/                   # 评估系统
│   │   ├── metrics.py          # 5 大评估指标
│   │   ├── dashboard.py        # 评估看板 API
│   │   └── ab_test.py          # A/B 测试（待实现）
│   ├── models/
│   └── utils/
├── static/                      # 前端 SPA
│   ├── index.html
│   ├── js/app.js               # 主应用逻辑
│   ├── css/                    # 样式文件
│   ├── html/                   # 页面模板
│   └── vendor/                 # 第三方库
├── data/                        # 数据目录（gitignored）
│   ├── papers/                 # 上传的论文文件
│   ├── figures/                # 提取的图表
│   └── db/                     # 数据库文件
│       ├── citewise.db         # 主数据库
│       ├── eval.db             # 评估数据库
│       └── chroma/             # 向量库
├── Dockerfile
├── render.yaml
├── requirements.txt
└── run.py                      # 启动入口
```
