"""测试 OCR 版面重建：还原图中文字的行/列结构。

RapidOCR 按文本框返回结果，同一视觉行常被切成多个框。
这里验证 _reconstruct_layout 能按坐标把它们重新组织成正确的行。
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ui.screenshot_overlay import _reconstruct_layout


def _box(left, top, right, bottom):
    """构造 RapidOCR 风格的四点框。"""
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def _entry(left, top, right, bottom, text):
    return [_box(left, top, right, bottom), text, 0.99]


def test_same_line_split_boxes_merge_into_one_line():
    """同一视觉行被切成两个框时，应合并回一行。"""
    # 两个框 y 范围基本一致（同一行），中间有正常字间隔
    result = [
        _entry(10, 100, 60, 130, "Hello"),
        _entry(70, 102, 130, 132, "World"),
    ]

    text = _reconstruct_layout(result)

    assert "\n" not in text, f"同一行不应被拆成多行，实际: {text!r}"
    assert "Hello" in text and "World" in text


def test_distinct_rows_stay_separate():
    """垂直分开的两行应保持为两行。"""
    result = [
        _entry(10, 100, 80, 130, "第一行"),
        _entry(10, 160, 80, 190, "第二行"),
    ]

    text = _reconstruct_layout(result)
    lines = text.split("\n")

    assert len(lines) == 2, f"应为两行，实际: {lines!r}"
    assert "第一行" in lines[0]
    assert "第二行" in lines[1]


def test_rows_ordered_top_to_bottom():
    """乱序输入应按从上到下重排。"""
    result = [
        _entry(10, 300, 80, 330, "底部"),
        _entry(10, 100, 80, 130, "顶部"),
        _entry(10, 200, 80, 230, "中间"),
    ]

    lines = _reconstruct_layout(result).split("\n")

    assert lines == ["顶部", "中间", "底部"], f"行序错误: {lines!r}"


def test_row_ordered_left_to_right():
    """同一行内的框应按从左到右排列。"""
    result = [
        _entry(200, 100, 260, 130, "C"),
        _entry(10, 100, 60, 130, "A"),
        _entry(100, 100, 160, 130, "B"),
    ]

    text = _reconstruct_layout(result)

    assert text.index("A") < text.index("B") < text.index("C")


def test_wide_gap_inserts_space():
    """同一行内有明显间隔（如分栏）时应插入空格分隔。"""
    result = [
        _entry(10, 100, 60, 130, "Name"),
        _entry(400, 100, 480, 130, "Value"),
    ]

    text = _reconstruct_layout(result)

    assert "\n" not in text
    assert "Name" in text and "Value" in text
    # 大间隔应产生多个空格
    between = text[text.index("Name") + len("Name"): text.index("Value")]
    assert between.strip() == "" and len(between) >= 1


def test_indentation_preserved():
    """缩进的行应保留前导空格。"""
    # 第一行顶格，第二行明显右移（缩进）
    result = [
        _entry(10, 100, 200, 130, "def foo():"),
        _entry(70, 160, 260, 190, "return 1"),
    ]

    lines = _reconstruct_layout(result).split("\n")

    assert len(lines) == 2
    assert not lines[0].startswith(" "), f"首行不应缩进: {lines[0]!r}"
    assert lines[1].startswith(" "), f"次行应有缩进: {lines[1]!r}"


def test_empty_result():
    assert _reconstruct_layout([]) == ""


def test_skips_empty_text_boxes():
    result = [
        _entry(10, 100, 60, 130, "A"),
        _entry(70, 100, 130, 130, ""),
        _entry(140, 100, 200, 130, "B"),
    ]

    text = _reconstruct_layout(result)

    assert "A" in text and "B" in text


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
