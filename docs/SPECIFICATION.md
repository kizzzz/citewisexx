# CiteWise V2 技术规范文档

> 版本: v2.0 | 最后更新: 2026-04-07
> 项目仓库: https://github.com/kizzzz/CiteWise
> 在线 Demo: Streamlit Cloud（点击可用）
> 升级: 语义切块 + 多Agent协同 + 图表索引 + 前端重构

---

## 1. 项目概述

### 1.1 定位

CiteWise 是一个 AI 驱动的学术研究助手，覆盖**从文献梳理到论文产出的全流程**。面向学术研究者，提供 PDF 文献解析、知识库检索、结构化总结、章节级生成、引用校验等功能。

### 1.2 核心差异化

| 能力 | 实现方式 |
|------|----------|
| Prompt 工程 | 5 层动态 Prompt 模板（固定基础→角色→项目→任务→工作记忆） |
| RAG 检索 | 混合检索（BM25 + 向量 + RRF 融合 + 重排序） |
| Agent 架构 | ReAct 意图路由 + 9 类意图识别 + 思考过程透明化 |
| 上下文工程 | 5 层上下文架构 + 滑动窗口摘要 + 章节间上下文传递 |
| 记忆工程 | 三层记忆（Global Profile → Project Memory → Working Memory） |

### 1.3 技术栈

```
前端:      Streamlit (Python)
LLM:       智谱 GLM-4-flash (OpenAI 兼容接口)
Embedding: 智谱 embedding-3 (2048 维)
向量库:    ChromaDB (cosine similarity)
全文检索:  rank-bm25 + jieba 分词
数据库:    SQLite (项目/论文/提取/章节)
PDF 解析:  pdfplumber + PyPDF2
部署:      Streamlit Community Cloud + GitHub
```

---

## 2. 项目结构

```
~/CiteWise/
├── app.py                          # Streamlit 前端（主对话 + 子对话）
├── config/
│   └── settings.py                 # 全局配置（API/路径/切片/检索参数）
├── src/
│   ├── core/
│   │   ├── llm.py                  # LLM 调用层（chat + chat_json）
│   │   ├── rag.py                  # PDF 解析 + 语义切片（L0/L1/L2）
│   │   ├── embedding.py            # Embedding 生成 + Chroma 向量库管理
│   │   ├── retriever.py            # 混合检索（BM25+向量+RRF+重排序）
│   │   ├── prompt.py               # 5 层动态 Prompt 引擎
│   │   ├── memory.py               # 三层记忆系统
│   │   └── agent.py                # ReAct Agent + 意图路由 + 来源标注
│   └── tools/
│       └── web_search.py           # 联网搜索（DuckDuckGo API）
├── data/
│   ├── db/
│   │   ├── citewise.db             # SQLite 数据库
│   │   └── chroma/                 # ChromaDB 向量数据
│   └── papers/                     # 上传的 PDF 文件
├── docs/                           # 技术设计文档（10 篇）
├── requirements.txt                # Python 依赖
├── runtime.txt                     # Streamlit Cloud Python 版本
└── .streamlit/
    └── config.toml                 # Streamlit 配置
```

---

## 3. 模块规范

### 3.1 配置层 — `config/settings.py`

**职责**: 集中管理所有可配置参数

#### API 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `OPENAI_API_KEY` | (从 st.secrets) | 智谱 API 密钥 |
| `OPENAI_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4/` | API 基础 URL |
| `LLM_MODEL` | `glm-4-flash` | 大模型名称 |
| `EMBEDDING_MODEL` | `embedding-3` | Embedding 模型 |
| `EMBEDDING_DIMENSION` | `2048` | 向量维度 |

**密钥管理**: 优先级 `Streamlit secrets` > `环境变量`

#### 切片配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `CHUNK_MIN_SIZE` | 200 | 最小 chunk 字符数 |
| `CHUNK_MAX_SIZE` | 1500 | 最大 chunk 字符数 |
| `CHUNK_TARGET_SIZE` | 800 | 目标 chunk 大小（滑动窗口趋近） |
| `SENTENCE_OVERLAP_COUNT` | 2 | 相邻 chunk 重叠的句子数 |

#### 检索配置

| 参数 | 值 | 说明 |
|------|-----|------|
| `VECTOR_TOP_K` | 20 | 向量检索召回数量 |
| `BM25_TOP_K` | 20 | BM25 检索召回数量 |
| `RERANK_TOP_K` | 5 | 最终重排序输出数量 |
| `RRF_K` | 60 | RRF 融合常数 |

#### 路径配置

所有路径基于 `_PROJECT_ROOT` 自动计算（项目根目录），不使用硬编码绝对路径。

---

### 3.2 LLM 调用层 — `src/core/llm.py`

**职责**: 统一封装 LLM API 调用

#### 类: `LLMClient`

```python
class LLMClient:
    def chat(messages, temperature=0.7, max_tokens=4000) -> str
    def chat_json(messages, temperature=0.3, max_tokens=4000, max_retries=2) -> dict
```

**`chat()`** — 基础对话接口
- 输入: OpenAI 格式 messages 列表
- 输出: 纯文本字符串
- 错误处理: 捕获异常，返回 `[错误] LLM 调用失败: ...`

**`chat_json()`** — 结构化输出接口
- 自动从响应中提取 JSON（支持 ` ```json ``` ` 代码块）
- 最多重试 `max_retries` 次，追加修正提示
- 最终失败返回 `{"error": "format_failed", "raw": text}`

**JSON 提取策略** (`_extract_json`):
1. 匹配 ` ```json ... ``` ` 代码块
2. 直接尝试 `{` 或 `[` 开头的文本
3. 原样返回

---

### 3.3 PDF 解析与切片 — `src/core/rag.py`

**职责**: PDF 解析 + 层级切片（语义边界感知 + 句子级 overlap）

#### 公共接口

```python
def parse_pdf(pdf_path: str) -> dict       # PDF → 结构化数据
def chunk_paper(paper_data: dict) -> list   # 结构化数据 → chunk 列表
```

#### `parse_pdf()` 解析流程

```
PDF 文件
  ├── PyPDF2: 提取元数据（title/authors/year/page_count）
  ├── 文件名解析: "Author 等 - 2025 - Title.pdf" → 补充缺失元数据
  ├── pdfplumber: 逐页提取文本
  │   ├── 章节标题检测: 正则 ^(\d+(?:\.\d+)*)\s+([A-Z][^\n]{2,80})
  │   ├── 表格提取: extract_tables() → Markdown
  │   └── 构建章节列表 [{title, text, tables}]
  └── 输出: {paper_id, title, authors, year, sections, raw_text}
```

#### `chunk_paper()` 切片管道

```
解析后的论文数据
  │
  ├── Stage 1: L0 论文级
  │   └── 改进的摘要提取 → 1 个 L0 chunk
  │
  ├── Stage 2: L1/L2 章节/段落级
  │   ├── 短章节 (≤800字) → L1 chunk（整体保留）
  │   └── 长章节 (>800字) → 语义切片管道 → 多个 L2 chunk
  │       ├── _split_sentences()      中英文混合句子分割
  │       ├── _merge_sentences_to_chunks()  滑动窗口合并
  │       └── _add_sentence_overlap()       句子级 overlap
  │
  └── Stage 3: 表格级
      └── 表格 + 前后段落上下文 → 表格 chunk (has_table=True)
```

#### Chunk 数据结构

```json
{
  "chunk_id": "paper_abc123_L2_def45678",
  "paper_id": "paper_abc123",
  "paper_title": "论文标题",
  "authors": "Zhang et al.",
  "year": 2025,
  "section_title": "2.1 Methods",
  "section_level": "L0 | L1 | L2",
  "text": "实际文本内容...",
  "has_figure": false,
  "has_table": false
}
```

#### 关键算法

**`_split_sentences()`** — 中英文混合句子分割
- 英文: `. ! ?` 后跟空格或行尾
- 中文: `。！？` 直接分割
- 保护机制: 编号行（`1.2.3`）、缩写（`Fig.`, `et al.`, `e.g.`）不被误切

**`_merge_sentences_to_chunks()`** — 滑动窗口合并
- 累积句子直到接近 `CHUNK_TARGET_SIZE`（800）
- 单句超 `CHUNK_MAX_SIZE`（1500）时在语义边界截断
- 尾部不足 `CHUNK_MIN_SIZE`（200）时合并到上一个 chunk

**`_add_sentence_overlap()`** — 句子级 overlap
- 相邻 chunk 间共享末尾 `SENTENCE_OVERLAP_COUNT`（2）个句子
- 保证跨 chunk 检索时的上下文连续性

**`_extract_abstract()`** — 多策略摘要提取
1. 正则匹配 `Abstract/ABSTRACT/摘要` → `Introduction/Keywords`
2. 搜索首页首个长段落（>150字）
3. 兜底: 前 800 字符

**`_build_table_context()`** — 表格上下文构建
- 提取表格所属章节的前后段落作为上下文
- 格式: `[上下文] ... [表格内容] ... [后续内容] ...`

---

### 3.4 向量库管理 — `src/core/embedding.py`

**职责**: Embedding 生成 + Chroma 向量库管理

#### 类: `EmbeddingManager`

```python
class EmbeddingManager:
    def embed(texts: list[str]) -> list[list[float]]
```

- 使用智谱 embedding-3 模型
- 通过 OpenAI 兼容接口调用
- 空输入返回空列表

#### 类: `VectorStore`

```python
class VectorStore:
    def index_chunks(chunks: list[dict])                    # 批量索引
    def vector_search(query, top_k=20, where=None) -> list  # 向量检索
    def get_all_chunks() -> list[dict]                       # 获取全部
    def delete_paper(paper_id: str)                          # 按论文删除
    def get_stats() -> dict                                  # 统计信息
```

**索引流程** (`index_chunks`):
1. 提取 texts/ids/metadata
2. 按 16 条/批调用 embedding API
3. `upsert` 到 Chroma `paper_chunks` collection（cosine 空间）

**Chroma 元数据 Schema**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `paper_id` | str | 论文唯一标识 |
| `paper_title` | str | 论文标题 |
| `authors` | str | 作者 |
| `year` | int | 发表年份 |
| `section_title` | str | 章节标题 |
| `section_level` | str | L0/L1/L2 |
| `has_table` | bool | 是否含表格 |

**全局单例**: `vector_store`, `embedding_manager`

---

### 3.5 混合检索 — `src/core/retriever.py`

**职责**: BM25 + 向量 + RRF 融合 + 重排序

#### 类: `BM25Index`

```python
class BM25Index:
    def build_index(chunks: list[dict])       # 构建索引
    def search(query: str, top_k=20) -> list  # BM25 检索
```

- 分词: 英文正则 `[a-zA-Z]+` + 中文 `jieba.cut()`
- 索引存储: 内存 dict `chunk_map`

#### 检索管道

```python
def hybrid_search(query, top_k=5, where=None) -> list[dict]
```

```
用户查询
  │
  ├── 向量检索 (top_k=20)
  │   └── vector_store.vector_search()
  │
  ├── BM25 检索 (top_k=20)
  │   └── bm25_index.search()
  │
  ├── RRF 融合
  │   └── reciprocal_rank_fusion()  score = 1/(k + rank + 1)
  │
  ├── 候选收集
  │   └── fused_ids → id_to_doc 映射
  │
  ├── 重排序
  │   └── rerank_by_relevance()  向量距离 + 关键词匹配加分
  │
  └── 格式化输出 (带引用信息)
      └── 每条结果附带 citation, paper_title, section_title
```

#### 辅助函数

**`format_chunks_with_citations(chunks)`** — 为 Prompt 注入格式化引用
```
--- 文献 1: 论文标题 [Author, 2025] | 章节: 2.1 Methods ---
文献文本内容...
```

**`validate_citations(text, chunks)`** — 引用校验
- 提取生成文本中的 `[Author, Year]` 格式引用
- 与检索结果中的 authors+year 比对
- 返回: `{total_citations, verified, unverified, verification_rate}`

---

### 3.6 Prompt 引擎 — `src/core/prompt.py`

**职责**: 5 层动态 Prompt 模板组装

#### 层级结构

```
Layer 1: 固定基础 (SYSTEM_PROMPT_BASE)
  └── 角色、能力描述、输出约束

Layer 2: 用户画像层
  └── 研究领域、写作风格、偏好字段

Layer 3: 项目状态层
  └── 论文数量、已生成章节、提取字段

Layer 4: 任务指令层
  └── 结构化总结 / 章节生成 / 框架推荐 / 图表 / 改写

Layer 5: 工作记忆层
  └── 当前任务、前文摘要、对话历史
```

#### 核心方法

```python
class PromptEngine:
    def build_system_prompt(user_profile, project_state) -> str
    def build_extract_prompt(fields, text) -> str
    def build_section_prompt(section_name, section_topic, ...) -> str
    def build_framework_prompt(summary_data, ...) -> str
    def build_chart_prompt(table_data, chart_requirement) -> str
    def build_rewrite_prompt(instruction, target_paragraph, ...) -> str
```

---

### 3.7 记忆系统 — `src/core/memory.py`

**职责**: 三层记忆架构

#### Layer 1: GlobalProfile（全局用户画像）

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | str | 用户标识 |
| `research_field` | str | 研究领域 |
| `focus_areas` | list | 关注方向 |
| `field_preferences` | list | 偏好字段 |
| `field_templates` | list | 字段模板（可跨项目复用） |
| `writing_style` | str | 写作风格 |

**持久化**: JSON 文件 (`data/user_profile.json`)

#### Layer 2: ProjectMemory（项目记忆 — SQLite）

**表结构**:

```sql
-- 项目
projects (id, name, topic, status, config, created_at)

-- 论文
papers (id, project_id, title, authors, year, filename, chunk_count, metadata, indexed_at)

-- 提取结果
extractions (id, project_id, paper_id, template_name, fields, confidence, created_at)

-- 生成章节
generated_sections (id, project_id, section_name, content, word_count, citations, generated_at)
```

**去重策略**:
- 章节去重: `get_unique_sections()` — 同名只保留最新
- 提取去重: `get_extractions()` — 每篇论文只计最新一次

#### Layer 3: WorkingMemory（工作记忆 — 内存）

| 字段 | 说明 |
|------|------|
| `current_project_id` | 当前项目 |
| `current_task` | 当前任务类型 |
| `focus_paper` | 聚焦论文 |
| `section_summaries` | 滑动窗口摘要列表 |
| `dialogue_history` | 对话历史 |
| `max_summary_tokens` | 2000 — 超长时压缩早期摘要 |

**全局单例**: `global_profile`, `project_memory`, `working_memory`

---

### 3.8 Agent 核心 — `src/core/agent.py`

**职责**: ReAct Agent — 意图路由、任务执行、来源标注

#### 意图路由

```python
INTENT_MAP = {
    "summarize":  ["总结", "提取", "梳理", "对比", "字段", "表格", "结构化"],
    "generate":   ["写", "生成", "撰写", "帮我写", "文章", "论文", "章节"],
    "framework":  ["框架", "思路", "大纲", "怎么写", "结构"],
    "modify":     ["修改", "调整", "改写", "重写", "换"],
    "explore":    ["有哪些", "什么方法", "怎么样", "分析", "讨论", "什么"],
    "upload":     ["上传", "导入", "添加论文", "导入PDF"],
    "export":     ["导出", "下载", "保存", "输出"],
    "chart":      ["图表", "柱状图", "饼图", "可视化", "绘图"],
    "websearch":  ["最新", "新闻", "最近", "当前", "联网", "搜索"],
}
```

**路由规则**:
1. 问句（含 `？`）→ 直接走 `explore`
2. 按关键词匹配计算分数，`framework`/`export` 加权 +2
3. `generate` 必须比 `explore` 分数更高才触发

#### 处理器

| 意图 | 处理器 | RAG | LLM | 联网 |
|------|--------|-----|-----|------|
| explore | `_handle_explore` | ✓ | ✓ | - |
| websearch | `_handle_websearch` | ✓ | ✓ | ✓ |
| summarize | `_handle_summarize` | ✓ | ✓ | - |
| generate | `_handle_generate` | ✓ | ✓ | - |
| framework | `_handle_framework` | - | ✓ | - |
| modify | `_handle_modify` | ✓ | ✓ | - |
| export | `_handle_export` | - | - | - |
| chart | `_handle_chart` | - | ✓ | - |

#### 来源标注（程序化后处理）

```python
def _annotate_sources(content, rag_chunks, web_results) -> str
```

**机制**: 遍历每一段落，根据引用和关键词匹配判断来源类型：

| 标记 | 条件 | 颜色 |
|------|------|------|
| 📖 知识库文献 | 段落含 `[Author, Year]` 且匹配 RAG 引用 | 蓝色 |
| 🌐 联网搜索 | 段落含 URL 或匹配 ≥2 个网络来源关键词 | 绿色 |
| 🧠 大模型推理 | 以上均不匹配 | 紫色 |

**设计决策**: 不依赖 LLM 加 emoji，纯程序化后处理，保证标注准确性。

---

### 3.9 联网搜索 — `src/tools/web_search.py`

**职责**: DuckDuckGo 搜索 + LLM 知识补充

```python
def web_search(query, top_k=5) -> list[dict]              # DuckDuckGo 搜索
def web_search_with_llm_summary(query) -> dict             # 搜索 + LLM 总结
```

**无外部依赖**: 使用 `urllib.request` 直接调用 DuckDuckGo Instant Answer API。

---

### 3.10 前端 — `app.py`

**职责**: Streamlit 界面 — 主对话 + 子对话体系

#### 页面布局

```
┌──────────────────────────────────────────────────┐
│ 侧边栏                   │ 主区域                │
│                          │                       │
│ 📚 CiteWise              │ CiteWise — 智能研究助手 │
│                          │                       │
│ [项目管理]               │ 主对话/子对话          │
│  - 选择项目              │ ┌─────────────────┐   │
│  - 新建项目              │ │ 来源标注说明      │   │
│                          │ └─────────────────┘   │
│ [文献上传]               │                       │
│  - 上传 PDF              │ [结构化总结 expander] │
│                          │                       │
│ [项目状态]               │ 对话历史               │
│  - 论文/提取/生成 计数    │ ┌─ user ───────────┐ │
│  - 已生成章节列表        │ │ ...              │ │
│  - 新增章节              │ ├─ assistant ──────┤ │
│                          │ │ 💭 思考过程       │ │
│ [快捷操作]               │ │ 📖/🌐/🧠 标注内容 │ │
│  - 重置主对话            │ │ 📎 引用来源面板   │ │
│  - 导出文章              │ └─────────────────┘   │
│                          │                       │
│                          │ [chat_input]           │
└──────────────────────────────────────────────────┘
```

#### 对话体系

| 类型 | 范围 | 上下文 | 用途 |
|------|------|--------|------|
| 主对话 | 全局 | 所有论文 + 全部对话历史 | 探索/总结/生成章节 |
| 子对话 | 章节级 | 继承主对话最近 6 轮 + 章节内容 | 修改/补充特定章节 |

**子对话增强 Prompt**:
```
用户正在撰写论文的「{section_name}」章节。
当前章节内容：{sec_content[:3000]}
主对话上下文：{main_summary}
本子对话历史：{sub_context}
用户最新指令：{prompt}
```

#### 启动初始化

应用启动时自动从 Chroma 向量库构建 BM25 索引：
```python
if "bm25_initialized" not in st.session_state:
    all_chunks = vector_store.get_all_chunks()
    if all_chunks:
        bm25_index.build_index(all_chunks)
    st.session_state.bm25_initialized = True
```

---

## 4. 数据流

### 4.1 文献上传流程

```
用户上传 PDF
  │
  ├── 保存到 data/papers/
  ├── parse_pdf() → {paper_id, title, authors, sections, ...}
  ├── chunk_paper() → [{chunk_id, text, section_level, ...}, ...]
  │   ├── L0: 摘要 chunk
  │   ├── L1/L2: 语义切片（带 overlap）
  │   └── 表格 chunks（带上下文）
  ├── project_memory.add_paper() → SQLite
  ├── vector_store.index_chunks() → Chroma
  └── bm25_index.build_index() → 内存
```

### 4.2 对话查询流程

```
用户输入
  │
  ├── route_intent() → 识别意图
  ├── 记录思考步骤 (thinking_steps)
  │
  ├── [explore/generate]
  │   ├── hybrid_search() → 检索相关文献
  │   │   ├── vector_search() → 向量召回
  │   │   ├── bm25_index.search() → BM25 召回
  │   │   ├── RRF 融合 + 重排序
  │   │   └── top-5 带引用格式
  │   ├── 构建 Prompt (5 层)
  │   ├── llm_client.chat() → 生成回答
  │   ├── _annotate_sources() → 程序化来源标注
  │   └── validate_citations() → 引用校验
  │
  ├── [websearch]
  │   ├── web_search_with_llm_summary() → DuckDuckGo + LLM
  │   ├── hybrid_search() → 同步检索知识库
  │   ├── 多源整合 Prompt
  │   └── 程序化来源标注
  │
  ├── [summarize]
  │   ├── 逐论文 hybrid_search(where={paper_id})
  │   ├── llm_client.chat_json() → 结构化提取
  │   └── 生成对比表格
  │
  └── [generate]
      ├── hybrid_search(top_k=8) → 检索文献
      ├── 构建 section_prompt
      ├── llm_client.chat() → 生成章节
      ├── 程序化来源标注
      ├── project_memory.save_section() → 持久化
      └── working_memory.add_section_summary() → 更新记忆
```

### 4.3 结构化总结流程

```
用户选择字段 → 点击"提取"
  │
  ├── 逐论文 (最多 10 篇)
  │   ├── hybrid_search(fields, top_k=5, where={paper_id})
  │   ├── format_chunks_with_citations()
  │   ├── llm_client.chat_json() → {fields: {...}, confidence: {...}}
  │   └── project_memory.save_extraction()
  │
  ├── 结果存入 session_state
  ├── st.rerun()
  └── 主区域独立渲染:
      ├── DataFrame 表格
      ├── Excel 下载按钮
      └── 可视化图表 (bar_chart)
```

---

## 5. 设计决策记录

| # | 决策 | 原因 |
|---|------|------|
| 1 | 来源标注用程序化后处理 | 不依赖 LLM 加 emoji，保证准确性和一致性 |
| 2 | 结构化总结结果存 session_state | 避免 expander 嵌套导致 Streamlit 容器错位 |
| 3 | 章节去重：同名只保留最新 | 避免重复生成，DB 层 `get_unique_sections()` |
| 4 | 提取去重：每篇论文只计最新 | `get_extractions()` 内 JOIN 最新记录 |
| 5 | 子对话 augmented prompt 告知章节名 | 让 LLM 知道当前编辑上下文 |
| 6 | 切片用句子级 overlap (2 句) | 比字符级 overlap 更精准，保证语义完整 |
| 7 | API key 通过 st.secrets 管理 | 避免硬编码，支持 Cloud 部署 |
| 8 | 路径基于 `_PROJECT_ROOT` 计算 | 跨环境兼容（本地 / Cloud） |
| 9 | BM25 索引从 Chroma 启动时重建 | 避免额外持久化，利用 Chroma 作为单一数据源 |

---

## 6. 部署规范

### 6.1 环境要求

- Python 3.11（`runtime.txt` 指定）
- Streamlit >= 1.29.0

### 6.2 依赖 (`requirements.txt`)

```
streamlit>=1.29.0          # 前端框架
openai>=1.6.0              # LLM + Embedding API (OpenAI 兼容)
protobuf>=3.20.0,<5.0.0    # 避免 Descriptors TypeError
chromadb>=0.4.22           # 向量数据库
rank-bm25>=0.2.2           # BM25 检索
jieba>=0.42.1              # 中文分词
PyPDF2>=3.0.1              # PDF 元数据
pdfplumber>=0.10.0         # PDF 文本+表格提取
pandas>=2.1.0              # 数据处理
matplotlib>=3.8.0          # 可视化
openpyxl>=3.1.0            # Excel 导出
python-docx>=1.1.0         # Word 导出
```

### 6.3 Secrets 配置

在 Streamlit Cloud → Settings → Secrets 中配置：

```toml
OPENAI_API_KEY = "your-zhipu-api-key"
OPENAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LLM_MODEL = "glm-4-flash"
```

### 6.4 预装数据

- SQLite 数据库 (`data/db/citewise.db`): 6 篇测试论文
- Chroma 向量库 (`data/db/chroma/`): 预构建的向量数据
- 启动时自动从 Chroma 重建 BM25 索引

---

## 7. 已知限制与后续优化

| 方向 | 当前状态 | 计划 |
|------|----------|------|
| Prompt 调优 | 基础模板可用 | 提升生成内容质量和引用准确度 |
| 错误处理 | 基础 try-catch | LLM API 调用失败时优雅降级 |
| 导出格式 | Markdown + Excel | Word/PDF 格式导出 |
| 多轮对话记忆 | 无压缩 | 主对话历史过长时的压缩策略 |
| 语义切片评估 | 功能验证通过 | 对比不同参数的检索效果 |
| 重排序模型 | 关键词匹配（简化版） | 引入 BGE-reranker 提升精度 |
| 持久化存储 | Streamlit Cloud 临时文件 | 考虑外部存储方案 |
