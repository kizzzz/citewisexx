"""正文内联引用核验测试

参考文献区已有核验，但正文里的 (Smith, 2023) / [3] 这类内联引用仍可能是编造的。
这些用例锁定：真引用不被误标、假引用必须标 ⚠、编号悬挂必须标 ⚠、幂等可重入。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.source_annotation import (  # noqa: E402
    UNVERIFIED_MARK,
    annotate_sources,
    check_inline_citations,
    strip_unverified_marks,
    verify_inline_citations,
    kb_papers_from_meta,
)

KB = kb_papers_from_meta([
    {"title": "Attention Is All You Need", "authors": "Vaswani, Shazeer", "year": 2017},
    {"title": "深度学习在医学影像中的应用", "authors": "张伟, 李明", "year": 2021},
])

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"{'PASS' if cond else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))


# 1. 知识库中存在的引用 → 不标记
text = "Transformer 完全基于注意力机制 (Vaswani, 2017)，摆脱了循环结构。"
out, rep = verify_inline_citations(text, KB)
check("真实英文引用不被误标", UNVERIFIED_MARK not in out and rep["verified"] == 1, out)

# 2. 知识库中不存在的引用 → 标 ⚠
text = "后续工作进一步验证了该结论 (Smith, 2023)。"
out, rep = verify_inline_citations(text, KB)
check("虚构引用被标记", f"(Smith, 2023){UNVERIFIED_MARK}" in out and rep["unverified"] == 1, out)

# 3. 中文引用：真实 / 虚构
out, rep = verify_inline_citations("如张伟等（2021）所述，该方法有效。", KB)
check("真实中文引用不被误标", UNVERIFIED_MARK not in out, out)
out, rep = verify_inline_citations("王强等（2019）提出了另一种思路。", KB)
check("虚构中文引用被标记", UNVERIFIED_MARK in out, out)

# 4. 叙述式 Author (year)
out, _ = verify_inline_citations("Vaswani et al. (2017) 提出该架构。", KB)
check("真实叙述式引用不被误标", UNVERIFIED_MARK not in out, out)
out, _ = verify_inline_citations("Johnson et al. (2022) 报告了相反结果。", KB)
check("虚构叙述式引用被标记", UNVERIFIED_MARK in out, out)

# 5. 编号式引用：能对应到参考文献条目则通过，越界则标记
doc = (
    "该模型显著提升了翻译质量 [1]，但推理成本较高 [5]。\n\n"
    "## 参考文献\n\n"
    "[1] Vaswani et al. Attention Is All You Need. NeurIPS, 2017.\n"
)
out, rep = verify_inline_citations(doc, KB)
check("有效编号引用保留", f"[1]{UNVERIFIED_MARK}" not in out, out.split("\n")[0])
check("悬挂编号引用被标记", f"[5]{UNVERIFIED_MARK}" in out, out.split("\n")[0])

# 6. 参考文献区自身不被追加标记
check("参考文献区不被标记", UNVERIFIED_MARK not in out.split("## 参考文献")[1], out)

# 7. 幂等：重复核验不会叠加标记
once, _ = verify_inline_citations("结论如此 (Smith, 2023)。", KB)
twice, _ = verify_inline_citations(once, KB)
check("重复核验不叠加", twice == once and twice.count(UNVERIFIED_MARK) == 1, twice)
check("strip 可还原", strip_unverified_marks(twice) == "结论如此 (Smith, 2023)。", strip_unverified_marks(twice))

# 8. 代码块内不标记
code_doc = "```python\ncite = (Smith, 2023)\n```"
out, rep = verify_inline_citations(code_doc, KB)
check("代码块内不标记", UNVERIFIED_MARK not in out, out)

# 9. 联网结果可作为核验来源（答案来自 WEB 时不误伤）
web = [{"title": "Smith 2023 survey on RAG", "snippet": "Smith, 2023 published a survey."}]
out, _ = verify_inline_citations("最新综述指出 (Smith, 2023)。", KB, None, web)
check("web 来源引用不被误标", UNVERIFIED_MARK not in out, out)

# 10. 未核验引用不再驱动 [KB] 标记
chunks = [{
    "text": "Transformer 完全基于自注意力机制，在 WMT14 英德翻译上取得 28.4 BLEU。",
    "metadata": {"title": "Attention Is All You Need", "authors": "Vaswani", "year": "2017"},
}]
annotated = annotate_sources("这一结论已被后续研究证实 [Smith, 2023]。", chunks, [])
first = annotated.strip().split("\n")[0]
check("未核验引用段落不标 KB", "[KB]" not in first and UNVERIFIED_MARK in first, first)

# 11. 真实引用段落仍标 KB
annotated = annotate_sources(
    "Transformer 在 WMT14 英德翻译上取得 28.4 BLEU [Vaswani, 2017]。", chunks, []
)
first = annotated.strip().split("\n")[0]
check("真实引用段落仍标 KB", "[KB]" in first and UNVERIFIED_MARK not in first, first)

# 12. check_inline_citations 无项目时退化用 chunk 核验
out, rep = check_inline_citations("结论如此 (Smith, 2023)，另见 (Vaswani, 2017)。", "", chunks)
check("退化核验可用", rep["unverified"] == 1 and rep["verified"] == 1, str(rep))

# 13. 无引用文本不受影响
plain = "本节介绍研究背景与方法设计，不含任何引用。"
out, rep = verify_inline_citations(plain, KB)
check("无引用文本不被改写", out == plain and rep["total"] == 0, out)

# 14. 作者字段为「名 姓」顺序时，姓氏引用也必须能核验（真实上传文献的常见格式）
KB_GIVEN_FIRST = kb_papers_from_meta([
    {"title": "Attention Is All You Need", "authors": "Ashish Vaswani, Noam Shazeer", "year": 2017},
])
out, rep = verify_inline_citations("该架构完全基于注意力机制 (Vaswani, 2017)。", KB_GIVEN_FIRST)
check("名姓顺序作者也能核验", UNVERIFIED_MARK not in out and rep["verified"] == 1, out)

failed = [n for n, ok, _ in results if not ok]
print(f"\ntotal={len(results)} pass={len(results) - len(failed)} fail={len(failed)}")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
