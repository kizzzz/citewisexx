# CiteWise V3 — 项目设计文档

> **版本**: V3.1
> **更新日期**: 2026-04-13
> **架构模式**: LangGraph Supervisor 多 Agent 协作
> **技术栈**: FastAPI + LangGraph + 智谱 GLM + ChromaDB + Tailwind CSS

---

## 1. 系统架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器 (SPA)                         │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────────┐  │
│  │ 协同中心  │ 文献索引  │ 章节草稿  │ AgentEval │ 设置/API管理 │  │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┴──────┬───────┘  │
│       │          │          │          │            │           │
│       └──────────┴──────────┴──────────┴────────────┘           │
│                         fetch / SSE                              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │    FastAPI 网关层     │
                    │  CORS / 限流 / 认证   │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼───────┐ ┌─────▼──────┐ ┌───────▼────────┐
     │  LangGraph 图   │ │ 文献管理    │ │ 用户/项目管理   │
     │  (Supervisor)   │ │ 上传/解析   │ │ 认证/隔离      │
     └────────┬───────┘ └─────┬──────┘ └───────┬────────┘
              │               │                 │
     ┌────────▼─────────────────▼───────────────▼────────┐
     │                   数据存储层                        │
     │  ┌─────────┐  ┌──────────┐  ┌──────────────────┐  │
     │  │ SQLite  │  │ ChromaDB │  │ 文件系统 (papers) │  │
     │  └─────────┘  └──────────┘  └──────────────────┘  │
     └────────────────────────────────────────────────────┘
              │
     ┌────────▼────────────────────────────────────────────┐
     │                 外部服务层                            │
     │  ┌──────────────┐  ┌────────────┐  ┌─────────────┐ │
     │  │ 智谱 GLM API │  │ Web Search │  │ Embedding   │ │
     │  │ (OpenAI兼容) │  │  (可选)     │  │ embedding-3 │ │
     │  └──────────────┘  └────────────┘  └─────────────┘ │
     └─────────────────────────────────────────────────────┘
```

### 1.2 技术栈选型理由

| 技术 | 选型理由 |
|------|----------|
| **FastAPI** | 异步原生，自动 OpenAPI 文档，高性能，SSE 支持 |
| **LangGraph** | 声明式状态图，内置 checkpoint，条件路由，比 LangChain Agent 更可控 |
| **ChromaDB** | 轻量嵌入式向量库，零运维，适合单机部署，支持持久化 |
| **SQLite** | 零配置事务数据库，适合中小规模，与 Python 天然集成 |
| **Tailwind CSS** | 原子化 CSS，快速原型开发，无需构建工具 |
| **智谱 GLM** | 中文能力优秀，OpenAI 兼容接口，性价比高 |
| **BM25 (rank_bm25)** | 经典关键词检索，与向量检索互补，中文 jieba 分词 |
| **sse-starlette** | FastAPI 原生 SSE 支持，流式输出 |

---

## 2. 数据模型

### 2.1 SQLite 表结构

```sql
-- 用户表
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 项目表
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    topic TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    config TEXT DEFAULT '{}',
    user_id TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 文献表
CREATE TABLE papers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    authors TEXT DEFAULT '',
    year TEXT DEFAULT '',
    filename TEXT,
    abstract TEXT DEFAULT '',
    full_text TEXT DEFAULT '',
    chunk_count INTEGER DEFAULT 0,
    indexed_at TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- 章节表
CREATE TABLE sections (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- 评估指标表
CREATE TABLE eval_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    project_id TEXT,
    intent TEXT,
    task_type TEXT,
    success BOOLEAN,
    response_time_ms INTEGER,
    has_citations BOOLEAN,
    hallucination_count INTEGER DEFAULT 0,
    accuracy_score REAL DEFAULT 0,
    llm_model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 ChromaDB 向量存储

```
Collection: papers
├── 文档 ID: {paper_id}_{chunk_index}
├── 向量维度: 2048 (embedding-3)
├── 元数据:
│   ├── paper_id: str
│   ├── paper_title: str
│   ├── authors: str
│   ├── year: str
│   ├── section_title: str
│   └── level: "L0" | "L1" | "L2"
└── 文档内容: chunk text (200-1500 chars)
```

### 2.3 AgentState 状态定义

```python
class AgentState(TypedDict):
    # 输入
    user_input: str                    # 用户原始输入
    project_id: str                    # 当前项目 ID

    # 路由
    intent: str                        # 识别的意图
    next_agent: str                    # 下一个要调用的 Agent

    # 检索结果
    chunks: list[dict]                 # RAG 检索到的文献片段
    rag_content: str                   # 格式化后的 RAG 内容
    web_results: list[dict]            # 联网搜索结果
    sources: list[dict]                # 来源信息

    # 输出
    content: str                       # 最终生成的内容
    response_type: str                 # text | section | export
    citations: dict                    # 引用验证结果
    content_sources: dict              # 来源标记 {rag, llm, web}

    # 追踪
    thinking_steps: list[str]          # 推理步骤记录
    agent_events: list[dict]           # Agent 事件日志
    framework: list                    # 论文框架
    target_content: str                # 待修改的目标内容
```

---

## 3. API 设计

### 3.1 端点总览

| 方法 | 路径 | 描述 | Content-Type |
|------|------|------|-------------|
| **认证** | | | |
| POST | `/api/auth/register` | 用户注册 | JSON |
| POST | `/api/auth/login` | 用户登录 | JSON |
| GET | `/api/auth/me` | 获取当前用户 | JSON |
| **项目** | | | |
| GET | `/api/projects` | 项目列表 | JSON |
| POST | `/api/projects` | 创建项目 | JSON |
| GET | `/api/projects/{id}/state` | 项目状态 | JSON |
| DELETE | `/api/projects/{id}` | 删除项目 | JSON |
| **文献** | | | |
| GET | `/api/papers?project_id=` | 文献列表 | JSON |
| POST | `/api/papers/upload` | 上传文献 | multipart |
| GET | `/api/papers/{id}` | 文献详情 | JSON |
| DELETE | `/api/papers/{id}` | 删除文献 | JSON |
| **聊天** | | | |
| POST | `/api/chat` | 主对话 | SSE stream |
| POST | `/api/chat/sub` | 子对话(章节编辑) | JSON |
| **章节** | | | |
| GET | `/api/sections?project_id=` | 章节列表 | JSON |
| POST | `/api/sections` | 创建章节 | JSON |
| PUT | `/api/sections/{id}` | 更新章节 | JSON |
| DELETE | `/api/sections/{id}` | 删除章节 | JSON |
| **提取** | | | |
| POST | `/api/extraction` | 执行提取 | JSON |
| **搜索** | | | |
| POST | `/api/search` | 联网搜索 | JSON |
| **API Key** | | | |
| POST | `/api/apikeys/verify` | 验证 API Key | JSON |
| POST | `/api/apikeys/save` | 保存配置 | JSON |
| **评估** | | | |
| GET | `/api/eval/metrics` | 获取指标 | JSON |
| GET | `/api/eval/trends` | 获取趋势 | JSON |
| POST | `/api/eval/rate` | 提交评分 | JSON |

### 3.2 SSE 流式协议

**请求**:
```json
POST /api/chat
{
    "message": "总结文献中 Transformer 的应用",
    "project_id": "proj_xxx",
    "api_key": "",       // 可选，用户自带
    "base_url": "",      // 可选，自定义 URL
    "model": ""          // 可选，指定模型
}
```

**响应** (SSE stream):
```
event: agent_start\r\n
data: {"agent": "Supervisor", "detail": "分析意图..."}\r\n\r\n

event: agent_end\r\n
data: {"agent": "Supervisor", "detail": "意图: explore"}\r\n\r\n

event: agent_start\r\n
data: {"agent": "Researcher", "detail": "检索知识库..."}\r\n\r\n

event: agent_end\r\n
data: {"agent": "Researcher", "detail": "检索完成: 5 文献片段", "duration_ms": 965}\r\n\r\n

event: agent_start\r\n
data: {"agent": "Responder", "detail": "生成回答..."}\r\n\r\n

event: token\r\n
data: {"text": "根据"}\r\n\r\n

event: token\r\n
data: {"text": "文献"}\r\n\r\n

... (逐 token 输出)

event: agent_end\r\n
data: {"agent": "Responder", "detail": "生成 194 字", "duration_ms": 3200}\r\n\r\n

event: content\r\n
data: {"content": "完整回答内容...", "type": "text"}\r\n\r\n

event: citations\r\n
data: {"total_citations": 3, "verified": 2, "unverified": []}\r\n\r\n

event: done\r\n
data: {"type": "text"}\r\n\r\n
```

**事件类型**:

| 事件 | 描述 | 数据格式 |
|------|------|----------|
| `agent_start` | Agent 开始处理 | `{agent, detail}` |
| `agent_end` | Agent 处理完成 | `{agent, detail, duration_ms}` |
| `token` | 流式 Token | `{text}` |
| `content` | 完整内容 | `{content, type}` |
| `citations` | 引用验证 | `{total, verified, unverified}` |
| `sources` | 来源列表 | `[{title, citation}]` |
| `section` | 章节生成事件 | `{section_name}` |
| `error` | 错误 | `{message}` |
| `done` | 完成 | `{type}` |

### 3.3 认证机制

```
注册: POST /api/auth/register {username, password}
      → {token: "jwt_xxx", user: {id, username}}

登录: POST /api/auth/login {username, password}
      → {token: "jwt_xxx", user: {id, username}}

鉴权: Authorization: Bearer <token>
```

- JWT Token 存储：前端 localStorage
- 数据隔离：所有查询按 user_id 过滤

### 3.4 错误处理

| HTTP 状态码 | 场景 | 响应格式 |
|------------|------|----------|
| 400 | 请求参数错误 | `{"detail": "..."}` |
| 401 | 未认证 | `{"detail": "..."}` |
| 422 | 验证失败 (Pydantic) | `{"detail": [...]}` |
| 429 | 速率限制 | `{"detail": "Too many requests"}` |
| 500 | 服务器内部错误 | SSE `error` 事件 |

---

## 4. 核心组件设计

### 4.1 Agent 系统架构

```
                    ┌─────────────────┐
                    │   Supervisor    │
                    │  (intent route) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐     │     ┌────────▼───────┐
     │   Researcher   │     │     │     Writer     │
     │  (RAG + Web)   │     │     │  (section gen) │
     └────────┬───────┘     │     └────────────────┘
              │              │
    ┌─────────┼─────────┐   │
    │         │         │    │
┌───▼───┐ ┌──▼──┐ ┌───▼───▼──┐
│Responder│ │Writer│ │ Analyst  │
│(answer) │ │(gen) │ │(analysis)│
└────────┘ └─────┘ └──────────┘
```

### 4.2 意图路由规则

```python
INTENT_MAP = {
    "summarize":  ["总结", "提取", "梳理", "对比", "字段", "表格", "结构化"],
    "generate":   ["写", "生成", "撰写", "帮我写", "章节"],
    "framework":  ["框架", "思路", "大纲", "怎么写", "结构"],
    "modify":     ["修改", "调整", "改写", "重写", "换", "拆分", "合并"],
    "export":     ["导出", "下载", "保存", "输出"],
    "chart":      ["图表", "柱状图", "饼图", "可视化", "绘图"],
    "websearch":  ["最新", "新闻", "最近", "当前", "联网", "搜索"],
    "figures":    ["图表索引", "图片", "figure", "fig", "图表列表"],
    "analyze":    ["分析", "洞察", "建议", "推荐", "模式"],
}

# 默认意图 (问句 / 无匹配)
# → "explore"
```

**路由决策**:
1. 问句检测 → `explore`
2. 关键词评分 → 最高分意图
3. 平局时优先级: `export > websearch > modify`
4. `generate` 需比 `explore` 分数严格更高
5. 无匹配 → `explore`

### 4.3 混合检索管线

```
用户查询
    │
    ├──→ [向量检索] ChromaDB embedding-3, top-20
    │         │
    ├──→ [BM25 检索] jieba 分词, top-20
    │         │
    └──→ [RRF 融合] k=60
              │
         候选文档集
              │
         [重排序] 向量距离 + 关键词重叠
              │
         Top-5 结果
              │
         添加引用标注 [{作者, 年份}]
```

**RRF 融合公式**:
```
score(doc) = Σ 1/(k + rank_i)
```
- k=60 (标准值，平衡头部和长尾文档)
- 向量检索和 BM25 检索各自返回 top-20
- 融合后取并集，按 RRF 分数降序排列
- 重排序: `1/(1+distance) + 0.1*keyword_overlap`

### 4.4 LLM 调用层

```python
class LLMClient:
    # 同步接口
    chat(messages, temperature=0.7, max_tokens=4000) → str
    chat_json(messages, temperature=0.3, max_retries=2) → dict

    # 异步接口
    achat(messages) → str
    achat_stream(messages, api_key=None, base_url=None, model=None)
        → AsyncGenerator[str, None]  # 逐 token yield
    achat_json(messages) → dict
```

**API Key 优先级链**:
```
请求级 api_key > 环境变量 OPENAI_API_KEY > 报错
```

**JSON 模式重试**:
1. 首次调用 → 解析 JSON
2. 失败 → 追加 "请严格按 JSON 格式输出" → 重试
3. 最多重试 2 次

### 4.5 记忆系统

```
┌──────────────────────────────────────────────┐
│               WorkingMemory                  │
│  章节摘要缓存 → 保证跨章节生成的一致性         │
│  get_previous_summary() → 上一个章节摘要      │
│  add_section_summary(name, summary, length)  │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│              EpisodicMemory                   │
│  对话历史 → 上下文理解                         │
│  (待实现: V4.0 多轮对话)                      │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│              SemanticMemory                   │
│  ChromaDB 向量库 → 语义检索                    │
│  hybrid_search(query) → top-k chunks          │
└──────────────────────────────────────────────┘
```

### 4.6 文献解析管线

```
PDF 文件
    │
    ├──→ [PDF Parser] PyMuPDF / pdfplumber
    │         │
    │    原始文本 (full_text)
    │         │
    ├──→ [Section Splitter] 正则匹配章节标题
    │         │
    │    L0/L1/L2 层级结构
    │         │
    ├──→ [Chunker] 目标 800 字, 重叠 2 句
    │         │
    │    chunks[] (200-1500 chars)
    │         │
    └──→ [Embedding] embedding-3 → 2048 维向量
              │
         ChromaDB 持久化存储
```

---

## 5. 前端架构

### 5.1 SPA 结构

```
index.html (单入口)
├── <aside> 侧边栏
│   ├── Logo + 品牌名
│   ├── 学术核心导航 (协同中心/文献索引/章节草稿)
│   ├── 研究资产导航 (Skill集/工具箱/AgentEval/Agent配置)
│   ├── 子 Agent 状态列表
│   ├── 项目选择器 (下拉菜单)
│   └── 用户信息卡片
│
├── <main> 主内容区
│   ├── chatView      协同中心
│   ├── paperView     文献索引 (列表 + 详情)
│   ├── draftView     章节草稿 (列表 + 编辑器)
│   ├── skillView     Skill 库 (列表 + 详情)
│   ├── toolView      工具箱 (列表 + 详情)
│   ├── evalView      AgentEval 仪表板
│   ├── agentView     Agent 配置 (列表 + 详情)
│   └── settingsView  设置页
│
└── Modals (7 个弹窗)
    ├── summaryModal       提取矩阵
    ├── createAgentModal   创建 Agent
    ├── addAssetModal      安装 Skill
    ├── keyModal           API Key 配置
    ├── authModal          登录/注册
    ├── newDraftModal      新建章节
    └── newProjectModal    新建项目
```

### 5.2 视图切换机制

```javascript
function switchView(id, btn) {
    // 1. 隐藏所有视图
    document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
    // 2. 隐藏所有导航高亮
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    // 3. 显示目标视图
    document.getElementById(id).classList.add('active');
    if (btn) btn.classList.add('active');
    // 4. 关闭所有子视图
    closePaperDetail(); closeDraftEditor(); closeAssetDetail(); ...
}
```

CSS 控制:
```css
.view-section { display: none !important; }
.view-section.active { display: flex !important; flex-direction: column; }
```

### 5.3 SSE 客户端实现

```javascript
// 1. 发起 fetch 请求
const response = await fetch('/api/chat', { method: 'POST', body: ... });

// 2. 获取 ReadableStream reader
const reader = response.body.getReader();
const decoder = new TextDecoder();

// 3. 循环读取 chunk
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // 4. 按 /\r?\n\r?\n/ 分割事件 (兼容 CRLF/LF)
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() || '';

    // 5. 解析每个事件
    for (const part of parts) {
        let eventType = '', data = '';
        for (const line of part.split('\n')) {
            const trimmed = line.replace(/\r$/, '');
            if (trimmed.startsWith('event: ')) eventType = trimmed.slice(7);
            if (trimmed.startsWith('data: ')) data = trimmed.slice(6);
        }
        // 6. 处理事件
        if (eventType === 'agent_start') appendTimelineStep(...);
        if (eventType === 'agent_end') updateTimelineStep(...);
        if (eventType === 'token') appendToken(data.text);
    }
}
```

### 5.4 状态管理

```javascript
// 全局状态 (无框架, 直接变量)
let projects = [];              // 项目列表
let currentProjectId = null;    // 当前项目
let agents = [...];             // Agent 定义
let skills = [...];             // Skill 定义
let tools = [...];              // Tool 定义
let apiKeys = [];               // API Key 列表
let chatBusy = false;           // 聊天锁
let currentUser = null;         // 当前用户 (JWT)

// 持久化: localStorage
// citewise_user → {id, username, token}
// citewise_api_keys → [{provider, apiKey, baseUrl, models, active}]
```

---

## 6. 部署架构

### 6.1 部署拓扑

```
GitHub (main branch)
    │
    ├──→ Vercel 自动部署
    │     │
    │     ▼
    │     cite-wise-mu.vercel.app (前端 SPA)
    │     - static/index.html
    │     - static/js/app.js
    │     - static/css/tailwind.css
    │
    └──→ Render 自动部署
          │
          ▼
          citewise-w9op.onrender.com (FastAPI 后端)
          - Dockerfile → python:3.10-slim
          - uvicorn api.main:app --host 0.0.0.0 --port 10000
          - SQLite + ChromaDB (临时存储)
```

### 6.2 环境变量

| 变量 | 生产值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | (secrets) | LLM API 密钥 |
| `OPENAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4/` | API 地址 |
| `LLM_MODEL` | `glm-4.7` | 模型名称 |
| `EMBEDDING_MODEL` | `embedding-3` | 嵌入模型 |
| `EMBEDDING_DIMENSION` | `2048` | 向量维度 |
| `PORT` | `10000` | 服务端口 |

### 6.3 Docker 配置

```dockerfile
FROM python:3.10-slim
WORKDIR /opt/render/project/src
RUN apt-get update && apt-get install -y build-essential libffi-dev
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data/papers data/figures data/db/chroma
ENV PORT=10000
EXPOSE 10000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "10000"]
```

### 6.4 CI/CD 流程

```
git push origin main
    │
    ├──→ Vercel: 检测变更 → 自动构建 → 部署前端
    │
    └──→ Render: 检测变更 → Docker build → 部署后端
```

---

## 7. 安全设计

### 7.1 CORS 白名单

```python
allow_origins = [
    "http://localhost:5328",      # 本地开发
    "http://127.0.0.1:5328",     # 本地开发
    "http://localhost:10000",     # Docker 本地
    "https://cite-wise-mu.vercel.app",    # Vercel 前端
    "https://citewise-w9op.onrender.com", # Render 后端
]
```

### 7.2 速率限制

```python
# 内存级 IP 限流
RATE_LIMIT_MAX_REQUESTS = 30    # 最大请求数
RATE_LIMIT_WINDOW_SECONDS = 60  # 时间窗口
MAX_TRACKED_IPS = 10000         # 最大追踪 IP 数
```

- 超限返回 HTTP 429
- 滑动窗口算法，自动清理过期记录

### 7.3 输入校验

```python
# Pydantic Schema 校验
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    project_id: str = Field(..., min_length=1)

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
```

### 7.4 安全响应头

```python
# 全局中间件自动添加
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
```

### 7.5 API Key 隔离

- 前端存储：localStorage（用户浏览器本地）
- 后端传输：仅在请求体中传递，不记录到日志
- 多用户支持：每个用户可有独立的 API Key 配置
- 验证机制：保存前调用供应商 API 验证有效性
