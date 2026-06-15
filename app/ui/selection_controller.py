"""划词即行动 — 取词、弹窗、分发的统筹控制器。

两条触发路径（全局热键 / 划词浮标）汇聚到这里，复用同一套取词与分发逻辑：

    触发 → 弹出动作条 → 用户点动作 → 取词(Ctrl+C 劫持) → 按 key 分发
        ├─ goes_to_ai：新建会话，连选中文字带预设词发给 LLM
        └─ note：直接写入笔记库（静默，仅 toast 提示）

与 ScreenshotController 平行：那边处理截图后动作，这边处理选中文字后动作。

★ 取词时机：弹窗只在用户点击动作按钮后才调 capture_selection()，
即「只在真要动作时碰一次剪贴板」。弹窗本身不读任何内容。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QCursor

from app.core.selection_capture import capture_selection
from app.ui.text_action_popup import TextActionPopup
from app.ui.text_actions import get_text_action

logger = logging.getLogger(__name__)

# 存便签时用选中文字开头若干字符作为标题。
_NOTE_TITLE_MAX = 20


class SelectionController(QObject):
    """统筹划词动作：弹窗 → 取词 → 分发到 AI 会话或笔记库。"""

    def __init__(
        self,
        window,
        *,
        note_mgr,
        text_session_callback,
        notify=None,
    ):
        """
        Args:
            window: 主窗口，AI 动作需要 show/raise 它。
            note_mgr: NoteManager，用于「存便签」。
            text_session_callback: 形如 start_text_session(text, action)。
            notify: 可选 (title, body) -> None，用于 toast 提示。
        """
        super().__init__(window)
        self._window = window
        self._notes = note_mgr
        self._text_session = text_session_callback
        self._notify = notify

        self._popup = TextActionPopup(window)
        self._popup.action_chosen.connect(self._on_action)
        # UIA 在手势命中时已取到的选中文字（若可用）；点击动作时优先消费它，
        # 取不到才退回 Ctrl+C 兜底。热键路径无此预取，恒为空。
        self._captured = ""

    # ── 触发入口 ────────────────────────────────────────────────────────

    def trigger_at_cursor(self):
        """热键路径：在当前鼠标位置弹出动作条。

        热键无 UIA 预取（无关联的拖选手势），预取文字置空，点击时走 Ctrl+C。
        """
        pos = QCursor.pos()
        self._trigger(pos.x(), pos.y(), captured="")

    def trigger_at(self, x: int, y: int, text: str = ""):
        """浮标路径：拖选松开后在指定屏幕坐标弹出动作条。

        text 为 SelectionMonitor 用 UIA 预取到的选中文字：非空则点击动作时直接
        用它，省去再发 Ctrl+C；为空（UIA 不可用）则点击时退回 Ctrl+C 兜底取词。
        """
        self._trigger(x, y, captured=text)

    def _trigger(self, x: int, y: int, *, captured: str):
        """弹出动作条。取词要么已由 UIA 预取（captured 非空），要么延后到点击时
        用 Ctrl+C 兜底——此处都不主动碰剪贴板。

        弹窗用 WS_EX_NOACTIVATE，点击其上按钮也不抢走源应用焦点，选区始终保留，
        所以兜底取词放到「真要动作」时才发一次 Ctrl+C 也安全。
        """
        self._captured = captured
        self._popup.show_at(x, y)

    # ── 分发 ────────────────────────────────────────────────────────────

    def _on_action(self, key: str):
        action = get_text_action(key)
        if action is None:
            logger.warning("划词：未知动作 %s", key)
            return

        # 优先用 UIA 在手势命中时预取到的文字（浮标路径，多数情况）；为空时
        # （热键路径，或 UIA 不可用/不支持的应用）才退回 Ctrl+C 兜底取词——
        # 弹窗用 WS_EX_NOACTIVATE，点击没抢走源应用焦点，此刻选区仍在。
        text = self._captured or capture_selection()
        if not text:
            self._toast("划词", "未检测到选中的文字")
            return

        if action.goes_to_ai:
            self._dispatch_to_ai(text, action)
        elif key == "note":
            self._save_as_note(text)

    def _dispatch_to_ai(self, text: str, action):
        if self._text_session is None:
            logger.warning("划词：未配置 text_session_callback")
            return
        # 先把窗口带到前台，再交给会话控制器新建会话并发送。
        if not self._window.isVisible():
            self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._text_session(text, action)

    def _save_as_note(self, text: str):
        try:
            title = text[:_NOTE_TITLE_MAX].strip() or "划词便签"
            self._notes.create(title=title, content=text, note_type="note")
            self._toast("已存便签", title)
        except Exception as e:  # pragma: no cover - 防御性
            logger.error("划词存便签失败：%s", e)
            self._toast("划词", "存便签失败")

    def _toast(self, title: str, body: str):
        if self._notify is not None:
            self._notify(title, body)
