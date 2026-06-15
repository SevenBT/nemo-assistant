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
from app.core.selection_monitor import is_drag_selection


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

def test_valid_when_new_content():
    assert is_valid_selection("新选中的文字", "旧剪贴板") is True


def test_invalid_when_empty():
    assert is_valid_selection("", "旧剪贴板") is False


def test_invalid_when_same_as_clipboard():
    # Ctrl+C 没产生新复制（内容与劫持前相同）→ 多半没选中
    assert is_valid_selection("相同内容", "相同内容") is False


def test_invalid_when_same_after_strip():
    assert is_valid_selection("文字", "  文字  ") is False


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
