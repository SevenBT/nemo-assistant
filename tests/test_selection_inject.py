"""测试划词回填（selection_inject）的纯逻辑层。

只验证不依赖按键/剪贴板/Qt 事件循环的纯函数：
  - strip_ai_preamble：剥离 AI 回复的代码块包裹
  - selection_unchanged：回填前选区未变的判定
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.selection_inject import strip_ai_preamble, selection_unchanged


# ── strip_ai_preamble ─────────────────────────────────────────────────────

def test_strip_plain_text_unchanged():
    assert strip_ai_preamble("润色后的句子。") == "润色后的句子。"


def test_strip_trims_whitespace():
    assert strip_ai_preamble("  结果  \n") == "结果"


def test_strip_empty():
    assert strip_ai_preamble("") == ""
    assert strip_ai_preamble("   ") == ""


def test_strip_code_fence_with_lang():
    text = "```python\nprint(1)\n```"
    assert strip_ai_preamble(text) == "print(1)"


def test_strip_code_fence_no_lang():
    text = "```\nhello world\n```"
    assert strip_ai_preamble(text) == "hello world"


def test_strip_keeps_inner_multiline():
    text = "```\n第一行\n第二行\n```"
    assert strip_ai_preamble(text) == "第一行\n第二行"


def test_strip_does_not_touch_inline_backticks():
    # 非整体包裹的反引号不动（句中代码）
    text = "用 `print` 输出"
    assert strip_ai_preamble(text) == "用 `print` 输出"


# ── selection_unchanged ────────────────────────────────────────────────────

def test_unchanged_when_identical():
    assert selection_unchanged("hello", "hello") is True


def test_unchanged_ignores_surrounding_whitespace():
    assert selection_unchanged("hello", "  hello \n") is True


def test_changed_when_different():
    assert selection_unchanged("hello", "world") is False


def test_changed_when_current_empty():
    # 取不到选区 → 无法确认相等，返回 False（「无法确认」，非「已变」）。
    # 调用方据此只在取到非空且不同的文字时才放弃粘贴，取到空不阻断。
    assert selection_unchanged("hello", "") is False


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
