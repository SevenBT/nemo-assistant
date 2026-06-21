"""测试 SelectionController 的动作分发逻辑。

需要 QApplication（控制器在 __init__ 里构建真实的浮标/气泡控件），但不触发
任何系统钩子或网络请求：构造后把取词、气泡、回调都替换成测试替身，只验证
_on_action_bubble 的分流与 _get_text 的兜底链。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication, QWidget

import app.ui.selection_controller as sc_mod
from app.ui.selection_controller import SelectionController


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeNotes:
    def __init__(self):
        self.created = []

    def create(self, *, title, content, note_type):
        self.created.append((title, content, note_type))


def _make_controller(qapp, *, captured="", capture_return=""):
    """构造控制器并把所有副作用替换成可观测的替身。

    captured: UIA 预取文字（模拟浮标路径已取到）。
    capture_return: Ctrl+C 兜底返回的文字（captured 为空时才会被调用）。
    """
    window = QWidget()
    notes = _FakeNotes()
    composed = []
    toasts = []
    note_saved = []

    controller = SelectionController(
        window,
        note_mgr=notes,
        compose_callback=lambda text, *, force_new: composed.append(
            (text, force_new)
        ),
        notify=lambda title, body: toasts.append((title, body)),
        on_note_saved=lambda: note_saved.append(True),
    )

    # 替换气泡为替身，记录 show_oneshot 调用，避免真发起 LLM 请求。
    oneshots = []
    controller._bubble = type(
        "FakeBubble", (), {
            "show_oneshot": lambda self, x, y, text, key: oneshots.append(
                (x, y, text, key)
            )
        }
    )()

    # 替换主窗还原，避免动真窗口。
    controller._restore_window = lambda: None

    # 兜底取词：monkeypatch 模块级 capture_selection。
    sc_mod.capture_selection = lambda: capture_return

    controller._captured = captured

    return controller, {
        "notes": notes,
        "composed": composed,
        "toasts": toasts,
        "note_saved": note_saved,
        "oneshots": oneshots,
    }


def test_get_text_prefers_uia_prefetch(qapp):
    controller, obs = _make_controller(
        qapp, captured="预取的词", capture_return="不该用到"
    )
    assert controller._get_text() == "预取的词"


def test_get_text_falls_back_to_ctrl_c(qapp):
    controller, obs = _make_controller(
        qapp, captured="", capture_return="兜底取到的词"
    )
    assert controller._get_text() == "兜底取到的词"


def test_get_text_toasts_when_nothing_selected(qapp):
    controller, obs = _make_controller(qapp, captured="", capture_return="")
    assert controller._get_text() == ""
    assert obs["toasts"] == [("划词", "未检测到选中的文字")]


def test_oneshot_action_shows_bubble(qapp):
    controller, obs = _make_controller(qapp, captured="光合作用")
    controller._on_action_bubble("explain")
    assert len(obs["oneshots"]) == 1
    assert obs["oneshots"][0][2] == "光合作用"
    assert obs["oneshots"][0][3] == "explain"


def test_local_action_saves_note(qapp):
    controller, obs = _make_controller(qapp, captured="待存的便签内容")
    controller._on_action_bubble("note")
    assert len(obs["notes"].created) == 1
    title, content, note_type = obs["notes"].created[0]
    assert content == "待存的便签内容"
    assert note_type == "note"
    assert obs["note_saved"] == [True]


def test_compose_action_calls_compose_callback(qapp):
    controller, obs = _make_controller(qapp, captured="续入的文字")
    controller._on_action_bubble("continue_explain")
    assert obs["composed"] == [("续入的文字", False)]


def test_compose_new_forces_new_session(qapp):
    controller, obs = _make_controller(qapp, captured="新建会话的文字")
    controller._on_action_bubble("new_continue_explain")
    assert obs["composed"] == [("新建会话的文字", True)]


def test_unknown_action_is_ignored(qapp):
    controller, obs = _make_controller(qapp, captured="x")
    controller._on_action_bubble("does_not_exist")
    assert obs["oneshots"] == []
    assert obs["composed"] == []
    assert obs["notes"].created == []


def test_no_action_when_nothing_selected(qapp):
    controller, obs = _make_controller(qapp, captured="", capture_return="")
    controller._on_action_bubble("explain")
    assert obs["oneshots"] == []
