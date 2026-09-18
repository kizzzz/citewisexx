"""CoVe (Chain-of-Verification) — 生成内容的事实性校验

流程:
  1. 从生成内容中提取可验证的声明 (claims)
  2. 为每个声明生成验证问题
  3. 用 RAG 检索 + LLM 回答验证问题
  4. 对比原始声明与验证结果，标记置信度
"""
import logging
from typing import Optional

from src.core.llm import llm_client

logger = logging.getLogger(__name__)


def _short_error(e: Exception) -> str:
    """Extract a short human-readable error reason."""
    msg = str(e)
    if "429" in msg or "rate" in msg.lower() or "访问量过大" in msg:
        return "API 限流，验证调用被拒绝"
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return "验证调用超时"
    if "401" in msg or "403" in msg:
        return "API 密钥无效或无权限"
    if "JSON" in msg or "json" in msg:
        return "LLM 返回格式异常"
    return msg[:60]


# ========== Prompt 模板 ==========

EXTRACT_CLAIMS_PROMPT = """## 任务：从文本中提取可验证的事实性声明

### 文本
{content}

### 要求
提取文本中所有包含具体事实、数据、结论的声明（不包括泛泛而谈的过渡句）。
对每个声明标注其是否包含引用（如 [作者, 年份]）。

输出 JSON：
```json
{{
  "claims": [
    {{
      "id": 1,
      "claim": "声明原文",
      "has_citation": true/false,
      "citation": "引用文本或null"
    }}
  ]
}}
```"""

VERIFY_CLAIMS_PROMPT = """## 任务：验证以下声明的准确性

### 声明列表
{claims_text}

### 参考材料（来自知识库检索）
{reference_material}

### 要求
对每个声明，判断：
1. 是否有参考材料支持 (supported / contradicted / unverifiable)
2. 置信度 (high / medium / low)
3. 如果有矛盾，说明具体矛盾点

输出 JSON：
```json
{{
  "verifications": [
    {{
      "claim_id": 1,
      "status": "supported/contradicted/unverifiable",
      "confidence": "high/medium/low",
      "evidence": "支持或反驳的证据摘要",
      "issue": "问题说明（如果有的话）"
    }}
  ],
  "overall_score": 0.0-1.0,
  "summary": "整体验证摘要"
}}
```"""


# ========== 核心函数 ==========

def extract_claims(content: str) -> tuple[list[dict], Optional[str]]:
    """从生成内容中提取可验证的声明"""
    if not content or len(content) < 50:
        return [], None

    prompt = EXTRACT_CLAIMS_PROMPT.format(content=content[:4000])
    messages = [
        {"role": "system", "content": "你是学术事实核查专家。准确提取声明，不遗漏关键事实。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = llm_client.chat_json(messages, temperature=0.2)
        claims = result.get("claims", [])
        logger.info(f"CoVe 提取到 {len(claims)} 个声明")
        return claims, None
    except Exception as e:
        logger.error(f"CoVe 声明提取失败: {e}")
        return [], f"声明提取失败: {_short_error(e)}"


def verify_claims(claims: list[dict], rag_chunks: list[dict]) -> dict:
    """验证声明的准确性

    Args:
        claims: extract_claims 的输出
        rag_chunks: RAG 检索的原文片段

    Returns:
        验证结果 dict，包含每个声明的状态和整体分数
    """
    if not claims:
        return {"verifications": [], "overall_score": 1.0, "summary": "无可验证声明"}

    # 构建参考材料
    from src.core.retriever import format_chunks_with_citations
    reference = format_chunks_with_citations(rag_chunks) if rag_chunks else "（无参考材料）"

    # 构建声明列表文本
    claims_text = "\n".join(
        f"[{c['id']}] {c['claim']}"
        + (f" (引用: {c.get('citation', '无')})" if c.get('has_citation') else "")
        for c in claims
    )

    prompt = VERIFY_CLAIMS_PROMPT.format(
        claims_text=claims_text,
        reference_material=reference,
    )

    messages = [
        {"role": "system", "content": "你是学术事实核查专家。严格根据参考材料验证声明。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = llm_client.chat_json(messages, temperature=0.2)
        logger.info(f"CoVe 验证完成, overall_score={result.get('overall_score', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"CoVe 验证失败: {e}")
        return {
            "verifications": [],
            "overall_score": 0.0,
            "summary": f"验证过程出错: {str(e)[:100]}",
            "error": f"验证调用失败: {_short_error(e)}",
        }


def run_cove(content: str, rag_chunks: list[dict]) -> dict:
    """完整的 CoVe 流程：提取声明 → 验证 → 返回结果

    Returns:
        {
            "claims": [...],
            "verifications": [...],
            "overall_score": float,
            "summary": str,
            "flagged_claims": [...]  # 有问题的声明
            "error": str or None     # 流程错误信息
        }
    """
    # 1. 提取声明
    claims, extract_error = extract_claims(content)
    if extract_error:
        return {
            "claims": [],
            "verifications": [],
            "overall_score": 0.0,
            "summary": extract_error,
            "flagged_claims": [],
            "error": extract_error,
        }
    if not claims:
        return {
            "claims": [],
            "verifications": [],
            "overall_score": 1.0,
            "summary": "内容过短或无可验证声明",
            "flagged_claims": [],
            "error": None,
        }

    # 2. 验证
    verification = verify_claims(claims, rag_chunks)
    verifications = verification.get("verifications", [])
    verify_error = verification.get("error")

    # 3. 标记有问题的声明
    flagged = []
    for v in verifications:
        if v.get("status") in ("contradicted", "unverifiable") or v.get("confidence") == "low":
            claim = next((c for c in claims if c.get("id") == v.get("claim_id")), None)
            flagged.append({
                "claim": claim.get("claim", "") if claim else "",
                "status": v.get("status"),
                "issue": v.get("issue", v.get("evidence", "")),
            })

    return {
        "claims": claims,
        "verifications": verifications,
        "overall_score": verification.get("overall_score", 0.0),
        "summary": verification.get("summary", ""),
        "flagged_claims": flagged,
        "error": verify_error,
    }


# ========== 异步版本（用于流式管线）==========

async def async_extract_claims(content: str, api_key: str = None, base_url: str = None) -> tuple[list[dict], Optional[str]]:
    """异步提取可验证的声明"""
    if not content or len(content) < 50:
        return [], None

    prompt = EXTRACT_CLAIMS_PROMPT.format(content=content[:4000])
    messages = [
        {"role": "system", "content": "你是学术事实核查专家。准确提取声明，不遗漏关键事实。"},
        {"role": "user", "content": prompt},
    ]

    try:
        # 使用 glm-4-flash 降低成本
        result = await llm_client.achat_json(messages, temperature=0.2, max_tokens=2000)
        claims = result.get("claims", [])
        logger.info(f"CoVe 异步提取到 {len(claims)} 个声明")
        return claims, None
    except Exception as e:
        logger.error(f"CoVe 异步声明提取失败: {e}")
        return [], f"声明提取失败: {_short_error(e)}"


async def async_verify_claims(claims: list[dict], rag_chunks: list[dict]) -> dict:
    """异步验证声明准确性"""
    if not claims:
        return {"verifications": [], "overall_score": 1.0, "summary": "无可验证声明"}

    from src.core.retriever import format_chunks_with_citations
    reference = format_chunks_with_citations(rag_chunks) if rag_chunks else "（无参考材料）"

    claims_text = "\n".join(
        f"[{c['id']}] {c['claim']}"
        + (f" (引用: {c.get('citation', '无')})" if c.get('has_citation') else "")
        for c in claims
    )

    prompt = VERIFY_CLAIMS_PROMPT.format(
        claims_text=claims_text,
        reference_material=reference,
    )

    messages = [
        {"role": "system", "content": "你是学术事实核查专家。严格根据参考材料验证声明。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = await llm_client.achat_json(messages, temperature=0.2, max_tokens=2000)
        logger.info(f"CoVe 异步验证完成, overall_score={result.get('overall_score', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"CoVe 异步验证失败: {e}")
        return {
            "verifications": [],
            "overall_score": 0.0,
            "summary": f"验证过程出错: {str(e)[:100]}",
            "error": f"验证调用失败: {_short_error(e)}",
        }


async def async_run_cove(content: str, rag_chunks: list[dict]) -> dict:
    """异步完整 CoVe 流程

    Returns:
        同 run_cove 的返回格式
    """
    claims, extract_error = await async_extract_claims(content)
    if extract_error:
        return {
            "claims": [],
            "verifications": [],
            "overall_score": 0.0,
            "summary": extract_error,
            "flagged_claims": [],
            "error": extract_error,
        }
    if not claims:
        return {
            "claims": [],
            "verifications": [],
            "overall_score": 1.0,
            "summary": "内容过短或无可验证声明",
            "flagged_claims": [],
            "error": None,
        }

    verification = await async_verify_claims(claims, rag_chunks)
    verifications = verification.get("verifications", [])
    verify_error = verification.get("error")

    flagged = []
    for v in verifications:
        if v.get("status") in ("contradicted", "unverifiable") or v.get("confidence") == "low":
            claim = next((c for c in claims if c.get("id") == v.get("claim_id")), None)
            flagged.append({
                "claim": claim.get("claim", "") if claim else "",
                "status": v.get("status"),
                "issue": v.get("issue", v.get("evidence", "")),
            })

    return {
        "claims": claims,
        "verifications": verifications,
        "overall_score": verification.get("overall_score", 0.0),
        "summary": verification.get("summary", ""),
        "flagged_claims": flagged,
        "error": verify_error,
    }
