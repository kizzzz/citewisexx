# CiteWise — Bad Case 处理

> 版本：V1.0 | 更新：2026-04-02

---

## 1. Bad Case 分类与应对

### 1.1 幻觉（Hallucination）

| 子类型 | 表现 | 检测方法 | 应对策略 |
|--------|------|----------|----------|
| 编造引用 | 引用不存在的论文或数据 | 引用校验：比对知识库 | System Prompt 强约束 + 后处理校验 |
| 张冠李戴 | 把 A 论文的方法归属给 B | 交叉验证：引用与 chunk 比对 | 元数据追踪：每个 chunk 标注论文来源 |
| 过度推断 | 超出原文范围的结论 | confidence 自评估 | Prompt 要求低置信度时标注"推断" |

**防御链**：

```
预防层（Prompt）
  → System Prompt 强制要求引用
  → 检索结果标注来源论文

检测层（后处理）
  → 正则提取所有 [作者, 年份] 引用
  → 与检索结果比对验证
  → 无依据引用标记 [未验证]

兜底层（用户反馈）
  → 引用可点击查看原文
  → 用户可标记错误引用
  → 标记数据用于优化
```

### 1.2 字段提取错误

| 子类型 | 表现 | 原因 | 应对策略 |
|--------|------|------|----------|
| 遗漏 | 字段值为空但原文有 | 检索未命中 | 放宽检索条件重试 |
| 误提取 | 提取了不相关的信息 | 语义模糊 | confidence 标记，低分人工审核 |
| 粒度不一致 | 有的详细有的简略 | LLM 输出不稳定 | few-shot 示例控制粒度 |

**处理流程**：

```python
def handle_extraction_failure(result: dict, field: str) -> dict:
    """处理字段提取失败"""
    if result["fields"][field] == "未提及":
        # 放宽条件重试：扩大检索范围
        broader_chunks = search_papers(
            query=field,
            filters={},  # 移除过滤
            top_k=10
        )
        if broader_chunks:
            return retry_extraction(field, broader_chunks)

    elif result["confidence"][field] == "low":
        # 标记低置信度，提示用户
        return {
            **result,
            "fields": {**result["fields"], field: f"{result['fields'][field]} [低置信度]"},
            "needs_review": True
        }

    return result
```

### 1.3 检索偏差

| 子类型 | 表现 | 原因 | 应对策略 |
|--------|------|------|----------|
| 论文偏向 | 某篇论文被过度引用 | 向量相似度偏差 | 每篇论文最多贡献 2 个 chunk |
| 章节偏向 | 只检索到摘要和方法 | 检索 query 偏向 | 强制要求覆盖 result/discussion 章节 |
| 时序偏差 | 优先引用最新/最旧论文 | 检索无时间维度 | 可选按时间均匀采样 |

### 1.4 长文档连贯性问题

| 子类型 | 表现 | 原因 | 应对策略 |
|--------|------|------|----------|
| 重复论述 | 多个章节重复相同观点 | 滑动窗口丢失前文 | 生成前检查前文摘要是否已提及 |
| 前后矛盾 | 前文说A后文说非A | 独立生成无全局视图 | 后处理一致性检查 |
| 过渡生硬 | 章节间缺少衔接 | 分节生成天然问题 | 生成后添加过渡段 |

```python
async def check_consistency(article: dict) -> list[dict]:
    """检查文章内部一致性"""
    contradictions = []
    all_claims = []

    for section in article["sections"]:
        claims = extract_claims(section["content"])
        for claim in claims:
            for prev in all_claims:
                if is_contradictory(claim, prev):
                    contradictions.append({
                        "claim_1": prev,
                        "claim_2": claim,
                        "section_1": prev["section"],
                        "section_2": claim["section"]
                    })
            all_claims.append(claim)

    return contradictions
```

### 1.5 图表处理失败

| 子类型 | 表现 | 应对策略 |
|--------|------|----------|
| 图表类型误判 | 柱状图识别为折线图 | 标题辅助判断 + 用户确认 |
| 数据提取失败 | 图表内容无法读取 | 回退到仅保留标题和位置信息 |
| 嵌入位置错误 | 图表插入到不相关段落 | 用户确认机制 |

---

## 2. 通用防御策略

### 2.1 多层防护

```
Layer 1: Prompt 约束
  → 角色定义中明确禁止幻觉
  → 要求 LLM 标注置信度
  → 不确定时回复"需要更多信息"

Layer 2: 结构化输出
  → JSON Schema 校验格式
  → 缺少必要字段时重试

Layer 3: 后处理校验
  → 引用验证
  → 一致性检查
  → 置信度过滤

Layer 4: 人机协作
  → 低置信度结果标记人工审核
  → 关键步骤用户确认
  → 用户反馈收集
```

### 2.2 用户沟通模板

```python
UNCERTAINTY_TEMPLATES = {
    "no_reference": "该内容超出了您当前知识库的范围，无法提供引用支撑。建议补充相关文献。",
    "low_confidence": "该信息的提取置信度为低，建议人工核实。原文出处：{source}",
    "extraction_failed": "字段 '{field}' 在该文献中未找到明确提及，可能需要手动补充。",
    "format_retry": "模型输出格式异常，正在自动修正...",
    "search_empty": "未检索到相关文献，建议尝试不同的关键词或减少过滤条件。"
}
```

---

## 3. 面试展示要点

| 展示点 | 话术 |
|--------|------|
| 多层防护 | "不是靠单一手段防幻觉，是 Prompt 约束 + 后处理校验 + 用户确认三层防御" |
| 自评估 | "让模型自己标注置信度，低分结果自动标记人工审核" |
| 人机协作 | "AI 不确定的时候诚实说，不瞎编，关键操作让用户确认" |
