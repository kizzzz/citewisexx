# CiteWise — RAG 检索系统设计

> 版本：V1.0 | 更新：2026-04-02
> 定位：面试展示用，体现对 RAG 的工程化设计能力

---

## 1. 设计目标

RAG 是 CiteWise 的**信任基石**——所有生成内容必须源于知识库，检索质量直接决定输出质量。

核心指标：
- 召回率 ≥ 95%（不漏关键信息）
- 精确率 ≥ 85%（减少无关噪音）
- 引用溯源准确率 ≥ 90%
- 单次检索延迟 ≤ 500ms

---

## 2. 文档处理流水线

### 2.1 PDF 解析

```
PDF 上传
    │
    ├── PyPDF2：提取元数据（标题、作者、年份、DOI）
    │
    ├── pdfplumber：逐页提取文本 + 表格
    │   │
    │   ├── 文本页 → 按标题/章节识别分割
    │   ├── 表格 → 转为 Markdown 表格文本
    │   └── 图片区域 → 提取坐标和图表标题
    │
    └── 多模态模型（Qwen-VL）：对图表区域生成描述
```

### 2.2 层级切片策略

学术论文有天然的结构层次，不能粗暴地按字数切：

```
论文（Paper）
├── 摘要（Abstract）       → 单独一个 chunk
├── 第一章 引言（Intro）
│   ├── 1.1 研究背景       → 单独一个 chunk
│   ├── 1.2 研究问题       → 单独一个 chunk
│   └── 1.3 论文结构       → 单独一个 chunk
├── 第二章 方法（Method）
│   ├── 2.1 数据           → 单独一个 chunk
│   ├── 2.2 模型           → 单独一个 chunk
│   └── 2.3 实验           → 单独一个 chunk
├── ...
└── 参考文献               → 不入库
```

**切片规则**：

| 层级 | 粒度 | 大小范围 | 适用场景 |
|------|------|----------|----------|
| L0 论文级 | 整篇论文元数据 | 200-500字 | 论文概览、筛选 |
| L1 章节级 | 一个完整章节 | 500-2000字 | 理解方法全貌 |
| L2 段落级 | 一个小节/段落 | 200-500字 | 精确检索具体信息 |

**关键设计——保留元数据**：

```json
{
  "chunk_id": "paper_03_sec_2_1",
  "paper_id": "paper_03",
  "paper_title": "From gas to gigawatts...",
  "authors": "Hu et al.",
  "year": 2025,
  "section_title": "2.1 数据来源",
  "section_level": "L2",
  "text": "本研究使用了中国336个城市的面板数据...",
  "has_figure": false,
  "has_table": true,
  "figure_ids": [],
  "table_ids": ["table_03_2"]
}
```

### 2.3 Embedding 策略

| 组件 | 选型 | 说明 |
|------|------|------|
| Embedding 模型 | BGE-large-zh-v1.5 | 中文学术场景优化，1024维 |
| 向量库 | Chroma | 轻量本地部署，支持过滤查询 |
| 索引类型 | HNSW | 平衡速度和精度 |

**特殊处理**：
- 图表描述单独 embedding，标记 `content_type: "figure"`
- 表格转 Markdown 文本后 embedding，标记 `content_type: "table"`
- 摘要单独 embedding，权重加倍（摘要信息密度最高）

---

## 3. 混合检索架构

### 3.1 为什么需要混合检索

| 检索方式 | 擅长 | 不擅长 |
|----------|------|--------|
| 向量检索 | 语义相似、模糊匹配 | 精确关键词匹配（如"MGWR"、"mAP@50"） |
| BM25 | 精确关键词、专业术语 | 语义理解（"空间异质性" ≈ "空间差异"） |

**结论**：学术论文场景两者互补，必须混合。

### 3.2 检索流程

```
用户查询："哪些论文使用了 MGWR 方法分析空间异质性？"
                    │
         ┌──────────┴──────────┐
         │                     │
    ┌────▼─────┐         ┌─────▼────┐
    │ 向量检索  │         │  BM25    │
    │ top-20   │         │ top-20   │
    └────┬─────┘         └─────┬────┘
         │                     │
         └──────────┬──────────┘
                    │
            ┌───────▼────────┐
            │  Reciprocal     │
            │  Rank Fusion    │  ← 融合两路结果
            │  (RRF)          │
            └───────┬────────┘
                    │
            ┌───────▼────────┐
            │  BGE-reranker   │  ← 精排 top-20
            │  重排序          │
            └───────┬────────┘
                    │
            ┌───────▼────────┐
            │  输出 top-5     │
            │  带元数据       │
            └────────────────┘
```

### 3.3 RRF 融合公式

```python
def reciprocal_rank_fusion(vector_results, bm25_results, k=60):
    """RRF 融合向量检索和 BM25 结果"""
    scores = {}
    for rank, doc in enumerate(vector_results):
        scores[doc.id] = scores.get(doc.id, 0) + 1.0 / (k + rank + 1)
    for rank, doc in enumerate(bm25_results):
        scores[doc.id] = scores.get(doc.id, 0) + 1.0 / (k + rank + 1)

    # 按融合分数排序
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_id for doc_id, _ in ranked[:20]]
```

### 3.4 BGE-reranker 重排序

```python
from FlagEmbedding import FlagReranker

reranker = FlagReranker('BAAI/bge-reranker-large', use_fp16=True)

def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """对候选文档重排序"""
    pairs = [[query, doc["text"]] for doc in candidates]
    scores = reranker.compute_score(pairs)

    # 按重排分数排序
    scored_docs = list(zip(candidates, scores))
    scored_docs.sort(key=lambda x: x[1], reverse=True)

    return [
        {**doc, "rerank_score": score}
        for doc, score in scored_docs[:top_k]
    ]
```

---

## 4. 多种检索场景

### 4.1 场景一：字段提取检索

**目标**：从特定论文中提取用户自定义字段。

```
检索策略：
1. 精确过滤：paper_id = 目标论文ID
2. 在该论文的 chunks 中搜索字段相关内容
3. 优先检索摘要 + 方法 + 结果章节

示例：
  查询: "骨干网络"
  过滤: paper_id = "paper_05"
  范围: section_title ∈ ["摘要", "方法", "实验"]
```

### 4.2 场景二：综述写作检索

**目标**：根据当前章节主题，从所有论文中检索相关内容。

```
检索策略：
1. 无过滤：检索所有论文
2. 向量检索 query = 章节主题 + 写作要点
3. 返回 top-10，按论文去重（每篇最多 2 个 chunk，避免偏向）

示例：
  章节: "2.1 电动汽车充电基础设施的空间分布"
  查询: "电动汽车 充电设施 空间分布 不均衡"
  结果: 来自 5 篇论文的 10 个相关段落
```

### 4.3 场景三：图表检索

**目标**：找到与某主题相关的图表。

```
检索策略：
1. 过滤: content_type = "figure" 或 "table"
2. 向量检索 query = 图表主题描述
3. 返回图表描述 + 原始位置信息

示例：
  查询: "各城市 EV 采用率对比"
  结果: paper_03 的 figure_2（336个城市 EV 采用率热力图）
```

---

## 5. 检索增强策略

### 5.1 Query 改写

用户原始 query 往往模糊，需要 LLM 改写为更好的检索 query：

```python
QUERY_REWRITE_PROMPT = """
将用户的查询改写为更适合学术文献检索的关键词组合。

用户查询: {original_query}
研究背景: {research_field}

输出格式：
{
  "rewritten_queries": ["改写后的查询1", "改写后的查询2", "改写后的查询3"],
  "key_terms": ["关键术语1", "关键术语2"],
  "filters": {"section_type": "method/result"}
}
"""
```

**示例**：

| 原始查询 | 改写后 |
|----------|--------|
| "这些论文用了什么方法" | "研究方法 | 分析框架 | 模型 | 方法论" |
| "效果怎么样" | "实验结果 | 性能指标 | 准确率 | mAP | F1" |
| "哪个数据集最好" | "数据集对比 | benchmark | dataset | 评估数据" |

### 5.2 父文档检索（Parent Document Retrieval）

检索用小 chunk（精确），生成用大 chunk（完整上下文）：

```
检索命中: L2 chunk（段落级，300字）
    ↓ 回溯
返回给 LLM: L1 chunk（章节级，1500字）
    ↓ 附带
元数据: 论文标题、作者、年份、章节标题
```

### 5.3 引用信息注入

检索结果返回时，自动拼接引用信息：

```python
def format_chunks_with_citations(chunks: list[dict]) -> str:
    """为每个检索片段添加引用标注"""
    formatted = []
    for i, chunk in enumerate(chunks, 1):
        citation = f"[{chunk['authors']}, {chunk['year']}]"
        header = f"--- 文献 {i}: {chunk['paper_title']} {citation} | 章节: {chunk['section_title']} ---"
        formatted.append(f"{header}\n{chunk['text']}")
    return "\n\n".join(formatted)
```

---

## 6. Chroma 向量库实现

### 6.1 集合设计

```python
import chromadb

client = chromadb.PersistentClient(path="./citewise_db")

# 论文 chunks 集合
paper_collection = client.get_or_create_collection(
    name="paper_chunks",
    metadata={"hnsw:space": "cosine"}
)

# 图表集合
figure_collection = client.get_or_create_collection(
    name="figures",
    metadata={"hnsw:space": "cosine"}
)
```

### 6.2 索引与检索

```python
def index_paper_chunks(chunks: list[dict]):
    """将论文 chunks 索引到 Chroma"""
    paper_collection.upsert(
        ids=[c["chunk_id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{
            "paper_id": c["paper_id"],
            "paper_title": c["paper_title"],
            "authors": c["authors"],
            "year": c["year"],
            "section_title": c["section_title"],
            "section_level": c["section_level"],
            "has_figure": c.get("has_figure", False),
            "has_table": c.get("has_table", False),
        } for c in chunks]
    )

def hybrid_search(query: str, filters: dict = None, top_k: int = 5) -> list[dict]:
    """混合检索：向量 + BM25"""
    # 向量检索
    vector_results = paper_collection.query(
        query_texts=[query],
        n_results=20,
        where=filters
    )

    # BM25 检索（使用 rank_bm25 库实现）
    bm25_results = bm25_search(query, top_k=20)

    # RRF 融合
    fused_ids = reciprocal_rank_fusion(vector_results, bm25_results)

    # 重排序
    candidates = [get_chunk_by_id(id) for id in fused_ids]
    return rerank(query, candidates, top_k=top_k)
```

### 6.3 BM25 检索实现

```python
from rank_bm25 import BM25Okapi
import jieba

class BM25Index:
    """基于 rank_bm25 的 BM25 索引"""

    def __init__(self):
        self.bm25 = None
        self.chunk_ids: list[str] = []
        self.chunk_texts: list[str] = []

    def build_index(self, chunks: list[dict]):
        """从论文 chunks 构建 BM25 索引"""
        self.chunk_ids = [c["chunk_id"] for c in chunks]
        self.chunk_texts = [c["text"] for c in chunks]

        # 中文分词
        tokenized_corpus = [list(jieba.cut(text)) for text in self.chunk_texts]
        self.bm25 = BM25Okapi(tokenized_corpus)

    def search(self, query: str, top_k: int = 20) -> list[dict]:
        """BM25 检索"""
        tokenized_query = list(jieba.cut(query))
        scores = self.bm25.get_scores(tokenized_query)

        # 按分数降序排序，返回 top_k 结果
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            {"id": self.chunk_ids[i], "text": self.chunk_texts[i], "bm25_score": scores[i]}
            for i in ranked_indices[:top_k]
        ]

# 全局 BM25 索引实例
bm25_index = BM25Index()

def bm25_search(query: str, top_k: int = 20) -> list[dict]:
    """BM25 检索入口函数"""
    return bm25_index.search(query, top_k=top_k)
```

---

## 7. 强制溯源机制

### 7.1 生成时溯源

```
检索结果 (top-5 chunks)
        │
        ▼
Prompt 注入（标注引用来源）
        │
        ▼
LLM 生成（引用 [作者, 年份]）
        │
        ▼
后处理校验：
  ├── 提取生成文本中所有引用
  ├── 与检索结果比对
  ├── 无依据的引用 → 标记为 [未验证]
  └── 缺少引用的段落 → 标记为 [需要引用]
```

### 7.2 引用校验代码

```python
import re

def validate_citations(generated_text: str, retrieved_chunks: list[dict]) -> dict:
    """校验生成文本中的引用是否都有检索依据"""
    # 提取所有引用（英文格式：[Author et al., 2025]；中文格式：[张明等, 2023]）
    en_citations = re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\]', generated_text)
    zh_citations = re.findall(r'\[([\u4e00-\u9fff]+等?,\s*\d{4})\]', generated_text)
    citations_in_text = en_citations + zh_citations

    # 检索结果中的有效引用
    valid_refs = {f"{c['authors']}, {c['year']}" for c in retrieved_chunks}

    # 校验
    unverified = [c for c in citations_in_text if c not in valid_refs]

    return {
        "total_citations": len(citations_in_text),
        "verified": len(citations_in_text) - len(unverified),
        "unverified": unverified,
        "verification_rate": (len(citations_in_text) - len(unverified)) / max(len(citations_in_text), 1)
    }
```

---

## 8. 面试展示要点

| 展示点 | 话术要点 |
|--------|----------|
| 层级切片 | "学术论论文有天然结构，不能粗暴按字数切。我们用三级切片，保留章节元数据" |
| 混合检索 | "向量检索擅长语义，BM25 擅长术语，学术论文场景两者互补" |
| 重排序 | "粗排 top-20 再用 BGE-reranker 精排 top-5，精度提升显著" |
| 强制溯源 | "检索结果带元数据，生成时注入引用标注，生成后再校验引用是否有依据" |
| 父文档 | "检索用小 chunk 精确命中，返回时回溯到大 chunk 给 LLM 完整上下文" |

---

## 9. 与其他模块的协作

```
RAG ←→ Prompt Engine：检索结果注入 Prompt，Prompt 的 query 触发检索
RAG ←→ Agent：Agent 调用检索工具，决定检索策略
RAG ←→ 上下文工程：检索结果作为上下文传递
RAG ←→ 记忆系统：用户偏好影响检索过滤条件
RAG ←→ 多模态：图表描述单独索引，支持图文混合检索
```
