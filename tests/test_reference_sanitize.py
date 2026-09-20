"""参考文献区核验（sanitize_reference_block）的回归测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.source_annotation import annotate_sources, sanitize_reference_block

CHUNKS = [{
    "paper_title": "Attention Is All You Need",
    "authors": "Ashish Vaswani, Noam Shazeer",
    "year": 2017,
    "text": "We propose the Transformer, based solely on attention mechanisms.",
}]


def test_fabricated_reference_dropped():
    content = (
        "## 引言\n"
        "自注意力机制支持并行计算。\n"
        "### 本节参考文献\n"
        "- [1] Ashish Vaswani. Attention Is All You Need. NeurIPS, 2017.\n"
        "- [2] 汪涛, 李明, & 刘洋. (2023). Chunking Strategies for Long Scientific "
        "Documents: An Empirical Study. Journal of Natural Language Processing, 12(2), 123-145.\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert "Attention Is All You Need. NeurIPS, 2017." in out, out
    assert "Chunking Strategies" not in out, out


def test_duplicate_reference_dropped():
    content = (
        "### 本节参考文献\n"
        "- Ashish Vaswani. Attention Is All You Need. NeurIPS, 2017.\n"
        "- Ashish Vaswani. Attention Is All You Need. NeurIPS, 2017.\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert out.count("Attention Is All You Need") == 1, out


def test_all_fabricated_gives_hint():
    content = (
        "### 本节参考文献\n"
        "- [1] 张三, 李四. (2021). 某个不存在的研究. 某刊, 3(1), 1-10.\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert "某个不存在的研究" not in out, out
    assert "暂无可核验" in out, out


def test_no_kb_papers_drops_all_entries():
    """知识库为空时，任何参考文献条目都不可核验"""
    content = "### 参考文献\n- [1] Someone. Some Paper. Some Journal, 2020.\n"
    out = sanitize_reference_block(content, [])
    assert "Some Paper" not in out, out
    assert "暂无可核验" in out, out


def test_body_text_untouched():
    content = (
        "## 引言\n"
        "Transformer 在 2017 年提出，彻底改变了序列建模范式。\n"
        "### 本节参考文献\n"
        "- Ashish Vaswani. Attention Is All You Need. NeurIPS, 2017.\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert "彻底改变了序列建模范式" in out, out


def test_pipeline_through_annotate():
    content = (
        "## 引言\n"
        "[KB] 自注意力机制支持并行计算 [Ashish Vaswani, 2017]。\n"
        "### 本节参考文献\n"
        "[KB] - [1] 汪涛. (2023). 虚构的分块策略研究. 虚构期刊, 1(1), 1-2.\n"
    )
    out = annotate_sources(content, CHUNKS, [])
    assert "虚构的分块策略研究" not in out, out
    assert out.count("[KB]") >= 1, out


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
