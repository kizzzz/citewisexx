"""参考文献区「暂无引用」提示行与正常条目不应共存"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.source_annotation import sanitize_reference_block

CHUNKS = [{
    "paper_title": "Attention Is All You Need",
    "authors": "Ashish Vaswani, Noam Shazeer",
    "year": 2017,
    "text": "We propose the Transformer.",
}]


def test_hint_removed_when_real_entry_exists():
    content = (
        "### 本节参考文献\n"
        "- Vaswani, A., Shazeer, N. (2017). Attention is all you need. NeurIPS.\n"
        "\n"
        "本节暂无文献引用（参考材料为空）\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert "Attention is all you need" in out, out
    assert "暂无" not in out, out


def test_hint_kept_when_nothing_verifiable():
    content = (
        "### 本节参考文献\n"
        "- 张三. (2021). 不存在的论文. 某刊.\n"
        "本节暂无文献引用（参考材料为空）\n"
    )
    out = sanitize_reference_block(content, CHUNKS)
    assert "不存在的论文" not in out, out
    assert out.count("暂无") == 1, out


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
