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
    sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from qfluentwidgets import FluentIcon

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

def test_text_actions_contains_expected_presets():
    keys = {a.key for a in TEXT_ACTIONS}
    assert keys == {
        "explain",
        "continue_explain",
        "new_continue_explain",
        "polish",
        "translate_inplace",
        "fix_grammar",
        "note",
    }, f"动作集不符: {keys}"


def test_rewrite_actions_are_rewrite_mode():
    for key in ("polish", "translate_inplace", "fix_grammar"):
        action = get_text_action(key)
        assert action is not None
        assert action.mode == "rewrite"
        assert action.is_rewrite is True
        assert action.is_compose is False
        assert action.goes_to_ai is True, "改写动作有提示词，应走 AI"
        assert "{text}" in action.default_prompt


def test_non_rewrite_actions_not_rewrite():
    for key in ("explain", "continue_explain", "new_continue_explain", "note"):
        assert get_text_action(key).is_rewrite is False


def test_get_text_action_lookup():
    action = get_text_action("explain")
    assert action is not None
    assert action.key == "explain"
    assert get_text_action("nonexistent") is None


def test_explain_goes_to_ai():
    assert get_text_action("explain").goes_to_ai is True


def test_explain_is_oneshot_not_compose():
    explain = get_text_action("explain")
    assert explain.mode == "oneshot"
    assert explain.is_compose is False
    assert explain.forces_new_reading is False


def test_continue_is_compose_no_prompt():
    cont = get_text_action("continue_explain")
    assert cont.mode == "compose"
    assert cont.is_compose is True
    assert cont.forces_new_reading is False
    # 续入会话不预设提示词（意图由用户自己输入：解释/润色/答问题…）
    assert cont.default_prompt == ""
    assert cont.goes_to_ai is False


def test_new_session_compose_forces_new():
    new = get_text_action("new_continue_explain")
    assert new.mode == "compose_new"
    assert new.is_compose is True
    assert new.forces_new_reading is True
    assert new.default_prompt == ""


def test_only_explain_uses_explain_prompt():
    # 仅「解释」用预设/自定义提示词；续入/新建无提示词
    explain = get_text_action("explain")
    assert "{text}" in explain.default_prompt
    assert get_text_action("continue_explain").default_prompt == ""
    assert get_text_action("new_continue_explain").default_prompt == ""


def test_note_is_local_not_ai():
    note = get_text_action("note")
    assert note.goes_to_ai is False, "存便签不应走 AI"
    assert note.default_prompt == "", "存便签 prompt 应为空"
    assert note.mode == "local"
    assert note.is_compose is False


def test_render_fills_text_placeholder():
    action = TextAction("x", FluentIcon.DICTIONARY, "X", "前缀：{text} 后缀", "标题")
    assert action.render("内容") == "前缀：内容 后缀"


def test_render_appends_when_no_placeholder():
    action = TextAction("x", FluentIcon.DICTIONARY, "X", "无占位提示词", "标题")
    assert action.render("内容") == "无占位提示词\n\n内容"


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


# ── selection_monitor: is_drag_selection（按住期间真实轨迹判定）──────────────

def test_drag_with_enough_path_and_moves():
    # 按住期间走了 50px 轨迹、有 move 事件 → 拖选
    assert is_drag_selection(path_len=50, move_count=5, duration=0.3) is True


def test_click_with_zero_moves_rejected():
    # 纯点击：按住期间 0 个 move → 必非拖选（无论 up 坐标毛刺多大）
    assert is_drag_selection(path_len=0, move_count=0, duration=0.3) is False


def test_coordinate_glitch_without_moves_rejected():
    # up 时刻坐标毛刺：起落点差几百 px，但按住期间无 move、轨迹为 0 → 不误判
    assert is_drag_selection(path_len=0, move_count=0, duration=0.078) is False


def test_short_path_rejected():
    # 有几次 move 但轨迹太短（手抖）→ 不是拖选
    assert is_drag_selection(path_len=5, move_count=3, duration=0.3) is False


def test_fast_drag_accepted_regardless_of_duration():
    # 快速划词：耗时极短但轨迹够长、有 move → 仍判为拖选（修复「选太快不弹」）
    assert is_drag_selection(path_len=200, move_count=8, duration=0.05) is True


def test_drag_too_slow_rejected():
    # 按住 10 秒 → 多半是拖窗/拖文件，非选字
    assert is_drag_selection(path_len=200, move_count=20, duration=10.0) is False


# ── selection_monitor: _on_event 物理按键状态机（点击 vs 拖选 vs 钩子故障）────
#
# 新实现不信任 mouse 库的 down/up 标签，改用 GetAsyncKeyState 物理按键状态驱动。
# 测试据此建模：每个事件附一个「此刻按键是否物理按下」的布尔，喂给被 stub 的
# is_left_button_physically_down。事件本身只是「有事发生」的触发器。

class _Ev:
    """带坐标的假事件。kind 仅用于可读性，被测代码不依赖它。"""
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _make_monitor():
    import app.core.selection_monitor as sm

    monitor = sm.SelectionMonitor()
    emitted = []
    monitor._maybe_emit = lambda x, y: emitted.append((x, y))
    return monitor, emitted


def _drive(monkeypatch, monitor, steps):
    """steps: [(event, btn_down_bool), ...]。按顺序投递，每步前设定物理按键状态。"""
    import app.core.selection_monitor as sm

    class _FakeMouse:
        LEFT = "left"

        @staticmethod
        def get_position():
            return (0, 0)

    monkeypatch.setattr(sm, "_mouse", _FakeMouse(), raising=False)
    monkeypatch.setattr(sm, "is_text_cursor", lambda: True)
    clock = {"t": 0.0}

    def _fake_monotonic():
        clock["t"] += 0.3
        return clock["t"]

    monkeypatch.setattr(sm.time, "monotonic", _fake_monotonic)

    btn = {"down": False}
    monkeypatch.setattr(
        sm, "is_left_button_physically_down", lambda: btn["down"]
    )
    for ev, down in steps:
        btn["down"] = down
        monitor._on_event(ev)


def test_drag_with_moves_emits(monkeypatch):
    # 按下 → 持续按住期间几个 move 累积轨迹 → 松开：真实拖选 → 弹
    monitor, emitted = _make_monitor()
    _drive(monkeypatch, monitor, [
        (_Ev(0, 0), True),     # 按下边沿
        (_Ev(20, 0), True),    # 持续按下 + 移动
        (_Ev(40, 0), True),
        (_Ev(60, 0), True),
        (_Ev(60, 0), False),   # 松开边沿
    ])
    assert emitted == [(60, 0)]


def test_click_without_moves_ignored(monkeypatch):
    # 纯点击：按下 → 立刻松开，按住期间无 move（轨迹=0）→ 不弹
    monitor, emitted = _make_monitor()
    _drive(monkeypatch, monitor, [
        (_Ev(100, 100), True),
        (_Ev(100, 100), False),
    ])
    assert emitted == []


def test_dropped_down_recovered_by_first_move(monkeypatch):
    # 钩子丢了 DOWN 事件：第一个仍按着的 move 事件被识别为按下边沿、救回起点。
    # 这是「右向左漏弹」的主因——丢 DOWN 导致旧实现真 up 成孤立 up 被忽略。
    monitor, emitted = _make_monitor()
    _drive(monkeypatch, monitor, [
        # 没有 down 事件；第一个事件就是按住状态下的 move
        (_Ev(1200, 685), True),   # 按下边沿（救回）
        (_Ev(1100, 685), True),
        (_Ev(1000, 685), True),
        (_Ev(1000, 685), False),  # 松开边沿
    ])
    assert emitted == [(1000, 685)]


def test_ghost_up_with_button_still_down_ignored(monkeypatch):
    # 幽灵 UP：钩子吐假释放，但物理键仍按着 → 无松开边沿、继续累积，真松开才判定。
    monitor, emitted = _make_monitor()
    _drive(monkeypatch, monitor, [
        (_Ev(1200, 685), True),   # 按下
        (_Ev(1200, 685), True),   # 幽灵 up：被测代码看到的是「仍按下」→ 不结束
        (_Ev(1100, 685), True),   # 真实拖动 move
        (_Ev(1000, 685), True),
        (_Ev(1000, 685), False),  # 真松开
    ])
    assert emitted == [(1000, 685)]


def test_idle_events_ignored(monkeypatch):
    # 空闲期（按键始终抬起）的杂散 move 不触发任何东西。
    monitor, emitted = _make_monitor()
    _drive(monkeypatch, monitor, [
        (_Ev(100, 0), False),
        (_Ev(200, 0), False),
    ])
    assert emitted == []



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
