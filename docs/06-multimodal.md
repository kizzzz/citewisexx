# CiteWise — 多模态图表处理

> 版本：V1.0 | 更新：2026-04-02

---

## 1. 处理流程

```
PDF 上传
    │
    ├── 文本提取（PyPDF2 + pdfplumber）
    │
    ├── 图片区域检测
    │     ├── pdfplumber 提取图片坐标和边界框
    │     ├── 关联最近的图表标题（Figure 1: ... / Table 2: ...）
    │     └── 截取图片区域，保存为 PNG
    │
    ├── 多模态描述生成（Qwen-VL）
    │     ├── 输入：图片 + 图表标题
    │     ├── 输出：结构化描述
    │     └── 描述包含：图表类型、坐标轴、数据趋势、关键数值
    │
    └── 入库
          ├── 图表描述 → 向量化（BGE-large-zh）→ Chroma figures 集合
          ├── 图表元数据 → SQLite
          └── 关联到论文 chunk 的元数据中
```

---

## 2. 图表描述生成 Prompt

```python
FIGURE_DESC_PROMPT = """
分析这张学术论文中的图表，生成结构化描述。

图表标题：{figure_caption}
论文标题：{paper_title}

请按以下格式输出：
```json
{
  "chart_type": "柱状图/折线图/散点图/饼图/热力图/表格/其他",
  "title": "图表标题",
  "x_axis": "X轴含义（如适用）",
  "y_axis": "Y轴含义（如适用）",
  "data_summary": "数据概况（100字以内）",
  "key_findings": ["关键发现1", "关键发现2"],
  "trend": "上升/下降/波动/无趋势",
  "spatial_pattern": "空间分布特征（如适用）"
}
```
"""
```

---

## 3. 图表索引

### 3.1 数据结构

```json
{
  "figure_id": "paper_03_fig_2",
  "paper_id": "paper_03",
  "figure_number": 2,
  "caption": "Figure 2: Spatial distribution of EV adoption rates across 336 Chinese cities",
  "description": "热力图，展示中国336个城市EV采用率的空间分布。东部沿海城市采用率普遍高于西部...",
  "chart_type": "热力图",
  "image_path": "./figures/paper_03_fig_2.png",
  "page_number": 8,
  "embedding": [0.123, ...]
}
```

### 3.2 图表检索

```python
def search_figures(query: str, top_k: int = 5) -> list[dict]:
    """检索与查询相关的图表"""
    results = figure_collection.query(
        query_texts=[query],
        n_results=top_k
    )
    return [
        {
            "figure_id": id,
            "caption": meta["caption"],
            "description": doc,
            "chart_type": meta["chart_type"],
            "paper_title": meta["paper_title"],
            "relevance_score": distance
        }
        for id, meta, doc, distance in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["documents"][0],
            results["distances"][0]
        )
    ]
```

---

## 4. 输出时图表嵌入

### 4.1 嵌入流程

```
生成论文章节
    │
    ├── LLM 生成正文中标注 [图表: {描述}]
    │
    ├── 后处理解析标注
    │     ├── 检索匹配的图表
    │     ├── 生成编号（Figure 1, Figure 2...）
    │     └── 替换标注为正式引用
    │
    └── 用户确认
          ├── 确认 → 正式嵌入
          └── 修改 → 重新生成图表或替换
```

### 4.2 图表生成（从数据）

```python
def generate_chart_from_data(
    table_data: list[dict],
    chart_type: str,
    title: str
) -> str:
    """从表格数据生成 matplotlib 图表代码"""
    CHART_PROMPT = f"""
    根据以下数据生成 {chart_type} 图表的 Python matplotlib 代码。

    数据：
    {json.dumps(table_data, ensure_ascii=False, indent=2)}

    标题：{title}

    要求：
    1. 使用学术风格（无网格、清晰标签）
    2. 中文显示用 SimHei 字体
    3. 保存为 PNG，dpi=300
    4. 颜色使用学术配色
    """
    code = llm.generate(CHART_PROMPT)
    return code
```

---

## 5. MVP 阶段简化

| 完整版 | MVP 版 | 理由 |
|--------|--------|------|
| 多模态模型生成详细描述 | Qwen-VL 生成简单描述（类型+标题+趋势） | 降低成本和复杂度 |
| 自动嵌入图表到文章 | 用户手动确认后嵌入 | 避免错误嵌入 |
| 复杂图表理解 | 仅识别图表类型和基本数据 | MVP 验证流程即可 |

---

## 6. 面试展示要点

| 展示点 | 话术 |
|--------|------|
| 双向处理 | "输入时解析图表生成描述可检索，输出时从数据生成图表可嵌入" |
| 图表可检索 | "图表不是黑箱，有描述有向量，能被语义检索命中" |
| 用户确认 | "图表嵌入前需用户确认，AI 不自作主张" |
