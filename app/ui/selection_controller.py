"""划词即行动 — 取词、弹窗、分发的统筹控制器。

两条触发路径（全局热键 / 划词浮标）汇聚到这里，复用同一套取词与分发逻辑：

    触发 → 弹出动作条 → 用户交互：
        点击 AI 动作 → 取词 → ResultBubble 就地显示结果（不建会话）
                       气泡里可再「转主窗」继续深入
        📌 存便签     → 取词 → 直接写入笔记库（静默，仅 toast 提示）

与 ScreenshotController 平行：那边处理截图后动作，这边处理选中文字后动作。

★ 取词时机：弹窗只在用户点击动作按钮后才调 capture_selection()，
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
    """统筹划词动作：弹窗 → 取词 → 分发到气泡/笔记库。"""

    def __init__(
        self,
        window,
        *,
        note_mgr,
        text_session_callback,
        compose_callback=None,
        notify=None,
        on_note_saved=None,
    ):
        """
        Args:
            window: 主窗口，AI 动作需要 show/raise 它。
            note_mgr: NoteManager，用于「存便签」。
            text_session_callback: 形如 start_text_session(text, action)。
                compose 回调缺失时的兜底（新建普通会话 + 主窗）。
            compose_callback: 形如 compose_in_reading(text, *, force_new)。续入/新建
                把选中文填进（激活或新建的）快速会话输入框，等用户手动发。
            notify: 可选 (title, body) -> None，用于 toast 提示。
            on_note_saved: 可选 () -> None，存便签后通知刷新笔记列表。
        """
        super().__init__(window)
        self._window = window
        self._notes = note_mgr
        self._text_session = text_session_callback
        self._compose = compose_callback
        self._notify = notify
        self._on_note_saved = on_note_saved

        self._popup = TextActionPopup(window)
        self._popup.action_chosen.connect(self._on_action_bubble)

        self._bubble = ResultBubble(window)

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
        """单击按钮：按动作 mode 分流——一次性气泡 / 续入会话 / 新建会话 / 存便签。"""
        action = get_text_action(key)
        if action is None:
            logger.warning("划词：未知动作 %s", key)
            return

        if action.mode == "local":
            text = self._get_text()
            if text:
                self._save_as_note(text)
            return

        text = self._get_text()
        if not text:
            return

        if action.is_compose:
            self._compose_in_session(text, action)
        elif action.goes_to_ai:
            self._show_oneshot(text, key)

    def _show_oneshot(self, text: str, action_key: str):
        """一次性解释：气泡自行请求并显示，不落库。"""
        self._bubble.show_oneshot(
            self._popup_x, self._popup_y, text, action_key
        )

    def _compose_in_session(self, text: str, action):
        """续入/新建：唤主窗、切到（激活或新建的）快速会话、把选中文填进输入框。

        不预设提示词、不自动发送——由你在输入框补充指令（解释/润色/答问题…）
        后手动点发送。action.forces_new_reading 为真时强制新建并激活快速会话。
        """
        if self._compose is None:
            logger.warning("划词：未配置 compose_callback，退回一次性")
            self._show_oneshot(text, action.key)
            return
        if not self._window.isVisible():
            self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._compose(text, force_new=action.forces_new_reading)

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
            # 立即刷新笔记列表，否则要等下次无关刷新才出现（表现为延迟十几秒）。
            if self._on_note_saved is not None:
                self._on_note_saved()
        except Exception as e:  # pragma: no cover - 防御性
            logger.error("划词存便签失败：%s", e)
            self._toast("划词", "存便签失败")

    def _toast(self, title: str, body: str):
        if self._notify is not None:
            self._notify(title, body)
