# CiteWise — 评估体系

> 版本：V1.0 | 更新：2026-04-02

---

## 1. 评估维度

| 维度 | 评估什么 | 目标值 | 方法 |
|------|----------|--------|------|
| 检索质量 | 召回率、精确率 | 召回 ≥ 95%, 精确 ≥ 85% | 人工标注 + 自动计算 |
| 字段提取 | 准确率、完整率 | 准确 ≥ 85% | 人工比对 |
| 引用溯源 | 引用准确率 | ≥ 90% | 自动校验 + 人工抽查 |
| 生成质量 | 连贯性、学术性 | 人工评分 ≥ 4/5 | 人工评估 |
| 端到端 | 用户满意度 | 满意度 ≥ 80% | 用户反馈 |

---

## 2. 自动化评估

### 2.1 检索质量评估

```python
def evaluate_retrieval(
    queries: list[dict],  # {query, relevant_chunk_ids}
    search_fn,
    top_k: int = 5
) -> dict:
    """评估检索质量"""
    results = {"recall": [], "precision": [], "mrr": []}

    for q in queries:
        retrieved = search_fn(q["query"], top_k=top_k)
        retrieved_ids = {r["chunk_id"] for r in retrieved}
        relevant_ids = set(q["relevant_chunk_ids"])

        # 召回率
        recall = len(retrieved_ids & relevant_ids) / len(relevant_ids) if relevant_ids else 0
        results["recall"].append(recall)

        # 精确率
        precision = len(retrieved_ids & relevant_ids) / len(retrieved_ids) if retrieved_ids else 0
        results["precision"].append(precision)

        # MRR
        for rank, r in enumerate(retrieved, 1):
            if r["chunk_id"] in relevant_ids:
                results["mrr"].append(1.0 / rank)
                break
        else:
            results["mrr"].append(0)

    return {
        "avg_recall": sum(results["recall"]) / len(results["recall"]),
        "avg_precision": sum(results["precision"]) / len(results["precision"]),
        "avg_mrr": sum(results["mrr"]) / len(results["mrr"])
    }
```

### 2.2 引用校验评估

```python
def evaluate_citations(
    test_cases: list[dict]  # {generated_text, valid_references}
) -> dict:
    """评估生成文本中的引用准确性"""
    results = {"accuracy": [], "coverage": [], "hallucination_rate": []}

    for case in test_cases:
        # 提取生成文本中的引用
        citations = extract_citations(case["generated_text"])
        valid_refs = set(case["valid_references"])

        # 引用准确率：生成的引用中有多少是有效的
        if citations:
            valid_count = sum(1 for c in citations if c in valid_refs)
            accuracy = valid_count / len(citations)
            hallucination = 1 - accuracy
        else:
            accuracy = 0
            hallucination = 0

        # 引用覆盖率：有效引用中有多少被使用
        coverage = len(set(citations) & valid_refs) / len(valid_refs) if valid_refs else 0

        results["accuracy"].append(accuracy)
        results["coverage"].append(coverage)
        results["hallucination_rate"].append(hallucination)

    return {
        "citation_accuracy": sum(results["accuracy"]) / len(results["accuracy"]),
        "citation_coverage": sum(results["coverage"]) / len(results["coverage"]),
        "hallucination_rate": sum(results["hallucination_rate"]) / len(results["hallucination_rate"])
    }
```

### 2.3 字段提取评估

```python
def evaluate_extraction(
    test_cases: list[dict]  # {paper_id, fields, ground_truth}
) -> dict:
    """评估字段提取准确率"""
    total_fields = 0
    correct_fields = 0
    partial_fields = 0

    for case in test_cases:
        extracted = case["extracted_fields"]
        truth = case["ground_truth"]

        for field in truth:
            total_fields += 1
            if field in extracted and extracted[field] == truth[field]:
                correct_fields += 1
            elif field in extracted and partial_match(extracted[field], truth[field]):
                partial_fields += 1

    return {
        "exact_accuracy": correct_fields / total_fields,
        "partial_accuracy": (correct_fields + partial_fields * 0.5) / total_fields,
        "total_fields": total_fields
    }
```

---

## 3. 人工评估

### 3.1 生成质量评分表

| 评分项 | 1分 | 3分 | 5分 |
|--------|-----|-----|-----|
| 学术性 | 口语化，非学术表达 | 基本学术，偶有不规范 | 学术规范，术语准确 |
| 逻辑性 | 论点混乱，无过渡 | 基本清晰，过渡生硬 | 逻辑严密，过渡自然 |
| 引用充分 | 无引用或引用错误 | 有引用但不全面 | 引用充分且准确 |
| 信息密度 | 空洞泛泛 | 有信息但不聚焦 | 信息密集，重点突出 |
| 整体可用 | 不可用，需全部重写 | 需要大幅修改 | 小幅修改即可使用 |

### 3.2 评估测试集

```json
{
  "test_set": {
    "papers": [
      {"id": "p01", "title": "论文A", "domain": "交通", "pages": 25},
      {"id": "p02", "title": "论文B", "domain": "交通", "pages": 30},
      {"id": "p03", "title": "论文C", "domain": "能源", "pages": 20},
      {"id": "p04", "title": "论文D", "domain": "环境", "pages": 35},
      {"id": "p05", "title": "论文E", "domain": "交通", "pages": 28}
    ],
    "test_fields": ["研究方法", "数据集", "核心指标", "主要发现", "创新点"],
    "ground_truth": {
      "p01": {
        "研究方法": "MGWR",
        "数据集": "336个城市面板数据",
        "核心指标": "EV采用率",
        "主要发现": "充电基础设施密度与EV采用率正相关",
        "创新点": "多尺度空间分析方法"
      }
    },
    "test_queries": [
      {"query": "哪些论文使用了空间分析方法", "relevant": ["p01", "p03"]},
      {"query": "电动汽车政策效果", "relevant": ["p01", "p05"]}
    ]
  }
}
```

---

## 4. 评估报告模板

```markdown
# CiteWise MVP 评估报告

## 1. 检索质量
- 平均召回率：{recall}
- 平均精确率：{precision}
- MRR：{mrr}
- 结论：{conclusion}

## 2. 字段提取
- 精确匹配准确率：{accuracy}
- 部分匹配准确率：{partial_accuracy}
- 常见错误类型：{error_types}

## 3. 引用溯源
- 引用准确率：{citation_accuracy}
- 幻觉率：{hallucination_rate}
- 引用覆盖率：{coverage}

## 4. 生成质量（人工评估）
- 平均评分：{avg_score}/5
- 各维度评分：{dimension_scores}
- 典型问题：{issues}

## 5. 改进方向
- {improvement_1}
- {improvement_2}
```

---

## 5. 面试展示要点

| 展示点 | 话术 |
|--------|------|
| 多维度评估 | "检索、提取、引用、生成各有独立指标，不是笼统说'好'或'不好'" |
| 自动+人工 | "能自动化的指标自动化，生成质量用人工评分表标准化" |
| 数据驱动 | "有测试集、有 ground truth、有评分标准，可量化可对比" |
