"""测试划词即行动的纯逻辑层。

不依赖系统钩子/剪贴板/Qt 事件循环，只验证可单测的纯函数：
  - text_actions 预设查表与 prompt 渲染
  - selection_capture 的文本清洗、截断、有效性判定
  - selection_monitor 的拖选手势判定
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ui.text_actions import (
    TEXT_ACTIONS,
    TextAction,
    get_text_action,
)
from app.core.selection_capture import (
    MAX_SELECTION_CHARS,
    clean_selection,
    is_valid_selection,
)
from app.core.selection_uia import (
    SelectionStatus,
    _selection_via_text_pattern,
)
from app.core.selection_monitor import is_drag_selection, should_emit


# ── text_actions ────────────────────────────────────────────────────────

def test_text_actions_contains_three_presets():
    keys = {a.key for a in TEXT_ACTIONS}
    assert keys == {"explain", "translate", "note"}, f"动作集不符: {keys}"


def test_get_text_action_lookup():
    action = get_text_action("explain")
    assert action is not None
    assert action.key == "explain"
    assert get_text_action("nonexistent") is None


def test_explain_and_translate_go_to_ai():
    assert get_text_action("explain").goes_to_ai is True
    assert get_text_action("translate").goes_to_ai is True


def test_note_is_local_not_ai():
    note = get_text_action("note")
    assert note.goes_to_ai is False, "存便签不应走 AI"
    assert note.prompt == "", "存便签 prompt 应为空"


def test_render_fills_text_placeholder():
    action = TextAction("x", "💡", "X", "前缀：{text} 后缀", "标题")
    assert action.render("内容") == "前缀：内容 后缀"


def test_explain_prompt_embeds_selection():
    rendered = get_text_action("explain").render("Hello World")
    assert "Hello World" in rendered


# ── selection_capture: clean_selection ───────────────────────────────────

def test_clean_strips_whitespace():
    assert clean_selection("  hello  \n") == "hello"


def test_clean_empty_returns_empty():
    assert clean_selection("") == ""
    assert clean_selection("   ") == ""


def test_clean_truncates_overlong():
    long_text = "a" * (MAX_SELECTION_CHARS + 100)
    result = clean_selection(long_text)
    assert len(result) == MAX_SELECTION_CHARS, "超长文本应截断到上限"


def test_clean_keeps_within_limit():
    text = "a" * (MAX_SELECTION_CHARS - 1)
    assert len(clean_selection(text)) == MAX_SELECTION_CHARS - 1


# ── selection_capture: is_valid_selection ─────────────────────────────────

def test_valid_when_content_present():
    # 取词前已 clear()，清空后出现非空内容即说明选中了文字。
    assert is_valid_selection("新选中的文字") is True


def test_invalid_when_empty():
    assert is_valid_selection("") is False


# ── selection_uia: query_selection 三态 ───────────────────────────────────

def test_query_status_enum_members():
    # 五态齐全：取到/真空选区/读不到/无焦点/库不可用
    names = {s.name for s in SelectionStatus}
    assert names == {
        "HAS_TEXT",
        "EMPTY_SELECTION",
        "NO_TEXT_PATTERN",
        "NO_FOCUS",
        "UNAVAILABLE",
    }, f"状态集不符: {names}"


class _FakeRange:
    def __init__(self, text):
        self._text = text

    def GetText(self, _max):
        return self._text


class _FakePattern:
    def __init__(self, ranges):
        self._ranges = ranges

    def GetSelection(self):
        return self._ranges


class _FakeControl:
    """模拟 UIA 焦点控件。pattern=None 表示控件不支持 TextPattern。"""

    def __init__(self, pattern, raises=False):
        self._pattern = pattern
        self._raises = raises

    def GetTextPattern(self):
        if self._raises:
            raise RuntimeError("no pattern")
        return self._pattern


def test_has_text_when_selection_nonempty():
    control = _FakeControl(_FakePattern([_FakeRange("选中的词")]))
    status, text = _selection_via_text_pattern(control)
    assert status is SelectionStatus.HAS_TEXT
    assert text == "选中的词"


def test_empty_selection_when_pattern_but_no_ranges():
    # 支持 TextPattern 但没选区 → 真没选中（切标签/拖滚动条），静默
    control = _FakeControl(_FakePattern([]))
    status, text = _selection_via_text_pattern(control)
    assert status is SelectionStatus.EMPTY_SELECTION
    assert text == ""


def test_empty_selection_when_ranges_yield_blank():
    # 有选区但取出来是空白 → 视为没选中
    control = _FakeControl(_FakePattern([_FakeRange("   ")]))
    status, text = _selection_via_text_pattern(control)
    assert status is SelectionStatus.EMPTY_SELECTION


def test_no_text_pattern_when_pattern_is_none():
    # Canvas 网页/内置 PDF/自绘控件：不支持 TextPattern → 应走 Ctrl+C 兜底
    control = _FakeControl(None)
    status, text = _selection_via_text_pattern(control)
    assert status is SelectionStatus.NO_TEXT_PATTERN
    assert text == ""


def test_no_text_pattern_when_get_pattern_raises():
    control = _FakeControl(None, raises=True)
    status, _ = _selection_via_text_pattern(control)
    assert status is SelectionStatus.NO_TEXT_PATTERN


# ── selection_capture: MimeData 备份还原 ──────────────────────────────────

def test_backup_restore_preserves_all_formats():
    """兜底取词的备份/还原要保住所有格式（text + html），不退化成纯文本。"""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QMimeData
    from app.core.selection_capture import _backup_clipboard, _restore_clipboard

    app = QApplication.instance() or QApplication([])
    clipboard = app.clipboard()

    # 用户原本复制了带格式的富文本（同时含 text 与 html）
    original = QMimeData()
    original.setText("纯文本版本")
    original.setHtml("<b>富文本版本</b>")
    clipboard.setMimeData(original)

    backup = _backup_clipboard(clipboard)

    # 模拟取词过程污染剪贴板
    clipboard.clear()
    clipboard.setText("取词期间的临时内容")

    # 还原后两种格式都应原样回来
    _restore_clipboard(clipboard, backup)
    restored = clipboard.mimeData()
    assert restored.text() == "纯文本版本"
    assert restored.hasHtml() and "富文本版本" in restored.html()


def test_restore_empty_backup_clears_clipboard():
    """原本剪贴板为空时，还原应清空，不残留取词内容。"""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QMimeData
    from app.core.selection_capture import _restore_clipboard

    app = QApplication.instance() or QApplication([])
    clipboard = app.clipboard()
    clipboard.setText("取词残留")

    _restore_clipboard(clipboard, QMimeData())  # 空备份
    assert clipboard.text() == ""


# ── selection_monitor: is_drag_selection ─────────────────────────────────

def test_drag_with_enough_distance_and_time():
    assert is_drag_selection(dx=50, dy=0, duration=0.3) is True


def test_click_too_short_distance_rejected():
    # 几乎没位移 → 点击，不是拖选
    assert is_drag_selection(dx=3, dy=2, duration=0.3) is False


def test_drag_too_fast_rejected():
    # 瞬时抖动 → 过滤
    assert is_drag_selection(dx=50, dy=0, duration=0.01) is False


def test_drag_too_slow_rejected():
    # 拖了 10 秒 → 多半是拖窗/拖文件，非选字
    assert is_drag_selection(dx=50, dy=0, duration=10.0) is False


def test_drag_uses_chebyshev_distance():
    # 纵向位移足够也算（max(|dx|,|dy|)）
    assert is_drag_selection(dx=0, dy=50, duration=0.3) is True


# ── selection_monitor: should_emit（光标门槛防误弹）─────────────────────────

def test_emit_when_has_text_regardless_of_cursor():
    # UIA 确认有选中文字 → 必弹，不受光标门槛限制
    assert should_emit(SelectionStatus.HAS_TEXT, was_text_cursor=True) is True
    assert should_emit(SelectionStatus.HAS_TEXT, was_text_cursor=False) is True


def test_emit_fallback_only_with_text_cursor():
    # 读不到选区时：文本光标才弹（内置 PDF/Canvas），箭头光标静默（拖标题栏/桌面）
    assert should_emit(SelectionStatus.NO_TEXT_PATTERN, was_text_cursor=True) is True
    assert should_emit(SelectionStatus.NO_TEXT_PATTERN, was_text_cursor=False) is False
    assert should_emit(SelectionStatus.UNAVAILABLE, was_text_cursor=True) is True
    assert should_emit(SelectionStatus.UNAVAILABLE, was_text_cursor=False) is False


def test_no_emit_when_empty_or_no_focus():
    # 真没选中 / 无焦点控件 → 无论光标如何都静默
    for status in (SelectionStatus.EMPTY_SELECTION, SelectionStatus.NO_FOCUS):
        assert should_emit(status, was_text_cursor=True) is False
        assert should_emit(status, was_text_cursor=False) is False


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
