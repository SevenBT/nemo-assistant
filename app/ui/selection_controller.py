"""划词即行动 — 取词、弹窗、分发的统筹控制器。

两条触发路径（全局热键 / 划词浮标）汇聚到这里，复用同一套取词与分发逻辑：

    触发 → 弹出动作条 → 用户交互：
        点击 AI 动作 → 取词 → ResultBubble 就地显示结果（不建会话）
                       气泡里可再「转主窗」继续深入
        📌 存笔记     → 取词 → 直接写入笔记库（静默，仅 toast 提示）

与 ScreenshotController 平行：那边处理截图后动作，这边处理选中文字后动作。

★ 取词时机：弹窗只在用户点击动作按钮后才调 capture_selection()，
即「只在真要动作时碰一次剪贴板」。弹窗本身不读任何内容。
"""
from __future__ import annotations

import logging
import time

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from app.core.selection_capture import capture_selection
from app.core.selection_inject import (
    foreground_window, replace_selection, restore_foreground_window, selection_unchanged,
)
from app.core.config import cfg
from app.i18n import t
from app.ui.result_bubble import ResultBubble
from app.ui.text_action_popup import TextActionPopup
from app.ui.text_actions import get_text_action

logger = logging.getLogger(__name__)

# 存笔记时用选中文字开头若干字符作为标题。
_NOTE_TITLE_MAX = 20


class SelectionController(QObject):
    """统筹划词动作：弹窗 → 取词 → 分发到气泡/笔记库。"""

    def __init__(
        self,
        window,
        *,
        note_mgr,
        compose_callback=None,
        notify=None,
        on_note_saved=None,
    ):
        """
        Args:
            window: 主窗口，AI 动作需要 show/raise 它。
            note_mgr: NoteManager，用于「存笔记」。
            compose_callback: 形如 compose_in_reading(text, *, force_new)。续入/新建
                把选中文填进（激活或新建的）快速会话输入框，等用户手动发。
            notify: 可选 (title, body) -> None，用于 toast 提示。
            on_note_saved: 可选 () -> None，存笔记后通知刷新笔记列表。
        """
        super().__init__(window)
        self._window = window
        self._notes = note_mgr
        self._compose = compose_callback
        self._notify = notify
        self._on_note_saved = on_note_saved

        self._popup = TextActionPopup(window)
        self._popup.action_chosen.connect(self._on_action_bubble)

        self._bubble = ResultBubble(window)
        self._bubble.replace_requested.connect(self._on_replace_requested)
        self._bubble.copy_requested.connect(self._on_copy_requested)
        self._bubble.edit_requested.connect(self._on_edit_requested)

        # UIA 在手势命中时已取到的选中文字（若可用）；点击动作时优先消费它，
        # 取不到才退回 Ctrl+C 兜底。热键路径无此预取，恒为空。
        self._captured = ""
        # 改写回填：记下当前改写动作的原始选中文字，回填时校验选区未变。
        self._rewrite_original = ""
        self._source_window = 0
        self._rewrite_needs_verification = False
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
        if self._captured:
            text = self._captured
            source = "uia_prefetch"
            elapsed_ms = 0.0
        else:
            started = time.perf_counter()
            text = capture_selection()
            elapsed_ms = (time.perf_counter() - started) * 1000
            source = "clipboard_fallback"
        logger.info(
            "[SelectionTiming] stage=text_ready source=%s elapsed_ms=%.2f chars=%d",
            source,
            elapsed_ms,
            len(text),
        )
        if not text:
            self._toast(t("selection.ctrl.title"), t("selection.ctrl.noSelection"))
        return text

    # ── 单击 → 气泡快查 ────────────────────────────────────────────────

    def _on_action_bubble(self, key: str):
        """单击按钮：按动作 mode 分流——一次性气泡 / 续入会话 / 新建会话 / 存笔记。"""
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
        elif action.is_rewrite:
            self._show_rewrite(text, key)
        elif action.goes_to_ai:
            self._show_oneshot(text, key)

    def _show_oneshot(self, text: str, action_key: str):
        """一次性解释：气泡自行请求并显示，不落库。"""
        self._bubble.show_oneshot(
            self._popup_x, self._popup_y, text, action_key
        )

    def _show_rewrite(self, text: str, action_key: str):
        """改写回填：气泡流式显示改写结果，footer 提供「替换原文 / 复制」。

        记下原始选中文字，供 _on_replace_requested 回填时校验选区未变。
        """
        self._rewrite_original = text
        self._source_window = foreground_window()
        self._rewrite_needs_verification = False
        self._bubble.show_rewrite(
            self._popup_x, self._popup_y, text, action_key
        )

    def _on_replace_requested(self, result: str):
        """气泡「替换原文」：把改写结果写回源应用，覆盖原选区。

        回填前可选校验选区未变（防止等 AI 期间用户点走、粘到错误位置）。
        粘贴成功则静默关闭气泡（结果已写回、肉眼可见，无需通知）；失败/选区
        已变则兜底为复制到剪贴板并 toast 提示手动粘贴——绝不静默失败。
        """
        if not result:
            return
        verify = bool(cfg.get(cfg.selectionRewriteVerify))
        source_matches = not self._source_window or foreground_window() == self._source_window
        ok = False
        if source_matches:
            if self._rewrite_needs_verification:
                # Editing activates a dialog, so an empty/unreadable selection
                # must not be treated as permission to paste at the caret.
                confirmed = bool(self._source_window) and selection_unchanged(
                    self._rewrite_original, capture_selection()
                )
                if confirmed:
                    ok = replace_selection(result, original=self._rewrite_original, verify=False)
            else:
                ok = replace_selection(result, original=self._rewrite_original, verify=verify)
        self._bubble.hide()
        # 成功静默（结果已写回原文，用户肉眼可见，无需打扰）；只在失败走兜底
        # 复制时通知，告知去哪儿找结果、要手动粘贴。
        if not ok:
            self._copy_to_clipboard(result)
            self._toast(t("selection.ctrl.replaceFailed"), t("selection.ctrl.replaceFailedBody"))

    def _on_edit_requested(self, result: str):
        if not result:
            return
        source_focus = QApplication.focusWidget()
        if source_focus is not None and int(source_focus.window().winId()) != self._source_window:
            source_focus = None
        self._bubble.hide()
        dialog = QDialog(self._window)
        dialog.setWindowTitle(t("resultbubble.editTitle"))
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        hint = QLabel(t("resultbubble.editHint"), dialog)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QPlainTextEdit(dialog)
        editor.setPlainText(result)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setEnabled(bool(result.strip()))
        editor.textChanged.connect(lambda: save_button.setEnabled(bool(editor.toPlainText().strip())))
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = editor.toPlainText()
        # Even cancelling the dialog may have affected the source selection.
        self._rewrite_needs_verification = True
        if source_focus is not None and not sip.isdeleted(source_focus):
            source_focus.setFocus()
        restore_foreground_window(self._source_window)
        self._bubble.show_rewrite_result(
            self._popup_x, self._popup_y, self._rewrite_original, result
        )
        dialog.deleteLater()

    def _on_copy_requested(self, result: str):
        """气泡「复制」：把结果复制到剪贴板，关闭气泡。"""
        if not result:
            return
        self._copy_to_clipboard(result)
        self._bubble.hide()
        self._toast(t("selection.ctrl.copied"), t("selection.ctrl.copiedBody"))

    def _copy_to_clipboard(self, text: str):
        try:
            QApplication.clipboard().setText(text)
        except Exception as e:  # pragma: no cover - 防御性
            logger.error("划词：复制改写结果失败 %s", e)

    def _compose_in_session(self, text: str, action):
        """续入/新建：唤主窗、切到（激活或新建的）快速会话、把选中文填进输入框。

        不预设提示词、不自动发送——由你在输入框补充指令（解释/润色/答问题…）
        后手动点发送。action.forces_new_reading 为真时强制新建并激活快速会话。
        """
        if self._compose is None:
            logger.warning("划词：未配置 compose_callback，退回一次性")
            self._show_oneshot(text, action.key)
            return
        self._restore_window()
        self._compose(text, force_new=action.forces_new_reading)

    def _restore_window(self):
        """唤起主窗：最小化时 showNormal 还原，隐藏时 show，再抢焦点。

        Qt 中最小化的窗口 isVisible() 仍为 True，只 raise_/activateWindow
        无法还原，必须先 showNormal()——与 main_window 切换可见性的处理一致。
        """
        if self._window.isMinimized():
            self._window.showNormal()
        elif not self._window.isVisible():
            self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    # ── 存笔记 ────────────────────────────────────────────────────────

    def _save_as_note(self, text: str):
        try:
            title = text[:_NOTE_TITLE_MAX].strip() or t("selection.ctrl.noteTitleFallback")
            self._notes.create(title=title, content=text, note_type="note")
            self._toast(t("selection.ctrl.noteSaved"), title)
            # 立即刷新笔记列表，否则要等下次无关刷新才出现（表现为延迟十几秒）。
            if self._on_note_saved is not None:
                self._on_note_saved()
        except Exception as e:  # pragma: no cover - 防御性
            logger.error("划词存笔记失败：%s", e)
            self._toast(t("selection.ctrl.title"), t("selection.ctrl.noteSaveFailed"))

    def _toast(self, title: str, body: str):
        if self._notify is not None:
            self._notify(title, body)
