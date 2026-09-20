"""source_annotation 来源标记与占位引用清理的回归测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.source_annotation import annotate_sources, _strip_existing_tag


def test_strip_inline_tag_in_list_item():
    declared, para = _strip_existing_tag("- **[WEB] 文献来源**：见某网页")
    assert declared == "WEB"
    assert "[WEB]" not in para


def test_strip_leading_tag():
    declared, para = _strip_existing_tag("[KB] 自注意力机制的公式为 softmax(QK^T)V")
    assert declared == "KB"
    assert para.startswith("自注意力")


def test_no_kb_tag_without_chunks():
    """无知识库片段时，即使模型自称 [KB] 也不能输出 [KB]"""
    content = "- **[KB] 文献来源**：某篇论文指出自注意力可并行计算"
    out = annotate_sources(content, [], [])
    assert out.count("[KB]") == 0, out
    assert out.count("[AI]") == 1, out


def test_no_web_tag_without_web_results():
    content = "[WEB] 根据网络资料，Transformer 于 2017 年提出"
    out = annotate_sources(content, [], [])
    assert "[WEB]" not in out
    assert out.startswith("[AI]")


def test_single_tag_per_paragraph():
    chunks = [{
        "text": "The Transformer achieves 28.4 BLEU on WMT 2014 English-to-German translation.",
        "metadata": {"authors": "Vaswani", "year": 2017},
    }]
    content = "[KB] 依据 [Vaswani, 2017]，Transformer 在 WMT 2014 上达到 28.4 BLEU。"
    out = annotate_sources(content, chunks, [])
    assert out.count("[KB]") == 1, out
    assert out.count("[AI]") == 0, out


def test_placeholder_reference_dropped():
    content = (
        "## 引言\n"
        "自注意力机制可并行计算。\n"
        "### 本节参考文献\n"
        "- [1] 作者. 标题. 期刊, 年份.\n"
        "- [2] XXX等. XXX. XXX, XXXX.\n"
    )
    out = annotate_sources(content, [], [])
    assert "作者. 标题" not in out, out
    assert "XXXX" not in out, out


def test_real_reference_kept():
    chunks = [{
        "text": "Attention Is All You Need proposes the Transformer.",
        "metadata": {"authors": "Ashish Vaswani", "year": 2017},
    }]
    content = (
        "## 引言\n"
        "Transformer 完全基于注意力机制 [Ashish Vaswani, 2017]。\n"
        "### 本节参考文献\n"
        "- Ashish Vaswani. Attention Is All You Need. NeurIPS, 2017.\n"
    )
    out = annotate_sources(content, chunks, [])
    assert "Attention Is All You Need. NeurIPS, 2017." in out, out


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    print(f"\nfailed={failed}")
    sys.exit(1 if failed else 0)
