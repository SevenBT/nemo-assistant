"""划词即行动 — 取词、弹窗、分发的统筹控制器。

两条触发路径（全局热键 / 划词浮标）汇聚到这里，复用同一套取词与分发逻辑：

    触发 → 弹出动作条 → 用户交互：
        单击（气泡快查）→ 取词 → ResultBubble 就地显示结果（不建会话）
        长按（小窗深入）→ 取词 → 小窗接管，可追问
        📌 存便签        → 取词 → 直接写入笔记库（静默，仅 toast 提示）

与 ScreenshotController 平行：那边处理截图后动作，这边处理选中文字后动作。

★ 取词时机：弹窗只在用户点击/长按动作按钮后才调 capture_selection()，
即「只在真要动作时碰一次剪贴板」。弹窗本身不读任何内容。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QPoint
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication

from app.core.selection_capture import capture_selection
from app.ui.result_bubble import ResultBubble
from app.ui.text_action_popup import TextActionPopup
from app.ui.text_actions import get_text_action

logger = logging.getLogger(__name__)

# 存便签时用选中文字开头若干字符作为标题。
_NOTE_TITLE_MAX = 20


class SelectionController(QObject):
    """统筹划词动作：弹窗 → 取词 → 分发到气泡/小窗/笔记库。"""

    def __init__(
        self,
        window,
        *,
        note_mgr,
        text_session_callback,
        mini_session_callback=None,
        notify=None,
    ):
        """
        Args:
            window: 主窗口，AI 动作需要 show/raise 它。
            note_mgr: NoteManager，用于「存便签」。
            text_session_callback: 形如 start_text_session(text, action)。
                用于"在小窗继续"升级为正式会话（长按直接走小窗也用这个）。
            mini_session_callback: 形如 dispatch_to_mini(text, action_key)。
                长按时直接把查询发到小窗。若为 None，退回到 text_session_callback。
            notify: 可选 (title, body) -> None，用于 toast 提示。
        """
        super().__init__(window)
        self._window = window
        self._notes = note_mgr
        self._text_session = text_session_callback
        self._mini_session = mini_session_callback
        self._notify = notify

        self._popup = TextActionPopup(window)
        self._popup.action_chosen.connect(self._on_action_bubble)
        self._popup.long_press_chosen.connect(self._on_action_mini)

        self._bubble = ResultBubble(window)
        self._bubble.continue_in_mini.connect(self._on_bubble_continue)

        # UIA 在手势命中时已取到的选中文字（若可用）；点击动作时优先消费它，
        # 取不到才退回 Ctrl+C 兜底。热键路径无此预取，恒为空。
        self._captured = ""
        # 弹出位置记忆，供气泡定位
        self._popup_x = 0
        self._popup_y = 0

    # ── 触发入口 ────────────────────────────────────────────────────────

    def trigger_at_cursor(self):
        """热键路径：在当前鼠标位置弹出动作条。

        热键无 UIA 预取（无关联的拖选手势），预取文字置空，点击时走 Ctrl+C。
        """
        pos = QCursor.pos()
        self._trigger(pos.x(), pos.y(), captured="")

    def trigger_at(self, x: int, y: int, text: str = ""):
        """浮标路径：拖选松开后在指定屏幕坐标弹出动作条。

        x, y 来自 mouse hook / UIA，是**物理像素**（不受 DPI 缩放影响）。
        Qt 的 move() / screenAt 等接口都使用逻辑像素，因此必须按屏幕缩放比
        换算（150% → ÷1.5，200% → ÷2.0），否则浮标会偏移到错误位置。

        text 为 SelectionMonitor 用 UIA 预取到的选中文字：非空则点击动作时直接
        用它，省去再发 Ctrl+C；为空（UIA 不可用）则点击时退回 Ctrl+C 兜底取词。
        """
        # Convert physical pixels → logical pixels for Qt
        try:
            screen = QApplication.screenAt(QPoint(x, y)) \
                or QApplication.primaryScreen()
            if screen is not None:
                scale = screen.devicePixelRatio()
                if scale > 1.0:
                    x, y = round(x / scale), round(y / scale)
        except Exception:
            pass
        self._trigger(x, y, captured=text)

    def _trigger(self, x: int, y: int, *, captured: str):
        """弹出动作条。取词要么已由 UIA 预取（captured 非空），要么延后到点击时
        用 Ctrl+C 兜底——此处都不主动碰剪贴板。

        弹窗用 WS_EX_NOACTIVATE，点击其上按钮也不抢走源应用焦点，选区始终保留，
        所以兜底取词放到「真要动作」时才发一次 Ctrl+C 也安全。
        """
        self._captured = captured
        self._popup_x = x
        self._popup_y = y
        self._popup.show_at(x, y)

    # ── 取词辅助 ────────────────────────────────────────────────────────

    def _get_text(self) -> str:
        """获取选中文字：优先 UIA 预取，兜底 Ctrl+C。"""
        text = self._captured or capture_selection()
        if not text:
            self._toast("划词", "未检测到选中的文字")
        return text

    # ── 单击 → 气泡快查 ────────────────────────────────────────────────

    def _on_action_bubble(self, key: str):
        """单击按钮：气泡就地显示结果，或存便签。"""
        action = get_text_action(key)
        if action is None:
            logger.warning("划词：未知动作 %s", key)
            return

        text = self._get_text()
        if not text:
            return

        if action.goes_to_ai:
            self._show_bubble(text, key)
        elif key == "note":
            self._save_as_note(text)

    def _show_bubble(self, text: str, action_key: str):
        """在弹出位置显示结果气泡。"""
        self._bubble.show_result(
            self._popup_x, self._popup_y, text, action_key
        )

    # ── 长按 → 小窗深入 ────────────────────────────────────────────────

    def _on_action_mini(self, key: str):
        """长按按钮：直接发到小窗（走完整会话流程，可追问）。"""
        action = get_text_action(key)
        if action is None:
            logger.warning("划词：未知动作 %s", key)
            return

        text = self._get_text()
        if not text:
            return

        if action.goes_to_ai:
            self._dispatch_to_mini(text, action)
        elif key == "note":
            self._save_as_note(text)

    def _dispatch_to_mini(self, text: str, action):
        """将请求发送到小窗模式。"""
        if self._mini_session is not None:
            self._mini_session(text, action)
        else:
            # 退回到原始行为：新建会话 + 主窗口
            self._dispatch_to_ai(text, action)

    # ── 气泡 "在小窗继续" ──────────────────────────────────────────────

    def _on_bubble_continue(self, source_text: str, llm_reply: str, action_key: str):
        """气泡中点击"在小窗继续"：将已有问答注入小窗会话。"""
        action = get_text_action(action_key)
        if action is None:
            return
        if self._mini_session is not None:
            self._mini_session(source_text, action, prefill_reply=llm_reply)
        else:
            self._dispatch_to_ai(source_text, action)

    # ── 原始行为（兜底） ──────────────────────────────────────────────

    def _dispatch_to_ai(self, text: str, action):
        """原始行为：新建会话，主窗口显示。"""
        if self._text_session is None:
            logger.warning("划词：未配置 text_session_callback")
            return
        if not self._window.isVisible():
            self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._text_session(text, action)

    # ── 存便签 ────────────────────────────────────────────────────────

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
