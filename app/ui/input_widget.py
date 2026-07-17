from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    PrimaryToolButton,
    TransparentToolButton,
)

from app.ui.style import (
    get_text_color,
    get_accent_text_color,
    get_accent_button_bg,
    get_accent_button_bg_hover,
    get_accent_button_bg_pressed,
)
from app.ui.pending_attachment_bar import PendingAttachmentBar
from app.i18n import t

_MAX_CONTENT_WIDTH = 760  # must match ChatWidget._MAX_CONTENT_WIDTH
_SIDE_MIN = 16
_BOTTOM_MARGIN = 30


class InputWidget(QWidget):
    submitted = pyqtSignal(str)
    edit_submitted = pyqtSignal(str)
    edit_cancel_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inputWidget")
        self._running = False
        self._cancelling = False
        self._editing = False
        self._changing_edit = False
        self._draft_text = ""
        self._draft_attachments: list = []
        self._has_draft_snapshot = False
        self._build()

    def _build(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(_SIDE_MIN, 8, _SIDE_MIN, _BOTTOM_MARGIN)
        self._root.setSpacing(6)

        self._edit_bar = QWidget(self)
        edit_row = QHBoxLayout(self._edit_bar)
        edit_row.setContentsMargins(4, 0, 4, 0)
        edit_row.setSpacing(4)
        edit_row.addWidget(CaptionLabel(t("input.editing"), self._edit_bar))
        edit_row.addStretch()
        self._cancel_edit_btn = TransparentToolButton(
            FluentIcon.CLOSE, self._edit_bar
        )
        self._cancel_edit_btn.setToolTip(t("input.cancelEdit"))
        self._cancel_edit_btn.clicked.connect(self.cancel_edit)
        edit_row.addWidget(self._cancel_edit_btn)
        self._edit_bar.hide()
        self._root.addWidget(self._edit_bar)

        # 待发送附件预览条（拖放/粘贴的图片在发送前显示在这里）。
        # 用左对齐的容器包裹，使预览条只占内容宽度、不与输入框一样宽。
        self._pending_bar = PendingAttachmentBar()
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(0)
        bar_row.addWidget(self._pending_bar)
        bar_row.addStretch()
        self._root.addLayout(bar_row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._edit = _TextEdit(self)
        self._edit.setPlaceholderText(t("input.placeholder"))
        self._edit.setMinimumHeight(40)
        self._edit.setMaximumHeight(120)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._edit.submitted.connect(self._submit)
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.files_dropped.connect(self._on_files_dropped)
        row.addWidget(self._edit)

        # 纯图标按钮：只留箭头，不显示文字。用 ToolButton 而非 PushButton——
        # PrimaryPushButton.paintEvent 的图标 x 依赖 minimumSizeHint（约 83px，
        # 为带文字预留），固定到 44px 宽时算出 x=-8 把箭头推到输入框那侧，首帧
        # 错位、切主题重排才凑巧归位。ToolButton 图标恒居中 (w-iconw)/2，根治。
        self._btn = PrimaryToolButton(FluentIcon.SEND, self)
        self._btn.setFixedWidth(44)
        self._btn.setFixedHeight(36)
        self._btn.clicked.connect(self._on_button_clicked)
        self._btn.setToolTip(t("input.send"))
        row.addWidget(self._btn)
        self._apply_btn_ink()

        self._root.addLayout(row)
        self._side = _SIDE_MIN
        self._pending_bar.changed.connect(self._update_margins)
        self._pending_bar.changed.connect(self._on_pending_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._side = max(_SIDE_MIN, (self.width() - _MAX_CONTENT_WIDTH) // 2)
        self._update_margins()

    def _update_margins(self):
        """Keep the text row from jumping when the preview bar appears.

        The bar adds height above the text row; absorb as much of it as
        possible by shrinking the bottom margin so the text field stays
        close to its original position.
        """
        bottom = _BOTTOM_MARGIN
        if self._pending_bar.has_items():
            absorb = self._pending_bar.sizeHint().height() + self._root.spacing()
            bottom = max(4, _BOTTOM_MARGIN - absorb)
        self._root.setContentsMargins(self._side, 8, self._side, bottom)

    def _submit(self):
        if self._running or self._cancelling:
            return
        text = self._edit.toPlainText().strip()
        # 允许仅附件、无文字时发送（如只拖一张图）。
        if text or self.has_pending_attachments():
            is_editing = self._editing
            self._set_editing(False)
            if is_editing:
                self.edit_submitted.emit(text)
                self._discard_draft_snapshot()
            else:
                self.submitted.emit(text)
            self._edit.clear()

    def _on_button_clicked(self):
        if self._cancelling:
            return
        if self._running:
            self.cancel_requested.emit()
        else:
            self._submit()

    def set_running(self, running: bool):
        self._running = running
        self._cancelling = False
        self._edit.setEnabled(True)
        self._btn.setEnabled(True)
        # 纯图标按钮：不设文本，仅切换图标（在 _apply_btn_ink 内按 _running 决定
        # SEND/CLOSE）；文字提示放 tooltip 保留可达性。
        self._btn.setToolTip(t("input.cancel") if running else t("input.send"))
        self._apply_btn_ink()

    def set_cancelling(self, cancelling: bool) -> None:
        """Keep input locked until a cancelled worker actually exits."""
        self._cancelling = cancelling
        self._running = cancelling or self._running
        self._btn.setEnabled(not cancelling)
        self._btn.setToolTip(
            t("input.cancelling") if cancelling else t("input.cancel")
        )
        self._apply_btn_ink()

    @property
    def is_editing(self) -> bool:
        return self._editing

    def begin_edit(self, text: str, attachments: list) -> None:
        """Replace the current draft and enter explicit edit mode."""
        self._changing_edit = True
        try:
            if not self._editing:
                self._draft_text = self._edit.toPlainText()
                self._draft_attachments = self._pending_bar.take_all()
                self._has_draft_snapshot = True
            else:
                self._pending_bar.clear()
            self.add_pending_attachments(list(attachments))
            self.set_text(text)
            self._set_editing(True)
        finally:
            self._changing_edit = False

    def end_edit(self, *, clear: bool) -> None:
        self._changing_edit = True
        try:
            self._set_editing(False)
            self._pending_bar.clear()
            if clear and self._has_draft_snapshot:
                self.set_text(self._draft_text)
                self.add_pending_attachments(self._draft_attachments)
            elif clear:
                self._edit.clear()
            self._draft_text = ""
            self._draft_attachments = []
            self._has_draft_snapshot = False
        finally:
            self._changing_edit = False

    def cancel_edit(self) -> None:
        if not self._editing:
            return
        self.end_edit(clear=True)
        self.edit_cancel_requested.emit()

    def _discard_draft_snapshot(self) -> None:
        self._draft_text = ""
        self._draft_attachments = []
        self._has_draft_snapshot = False

    def _set_editing(self, editing: bool) -> None:
        self._editing = editing
        self._edit_bar.setVisible(editing)
        self._update_margins()

    def _on_text_changed(self) -> None:
        if self._changing_edit or not self._editing:
            return
        if not self._edit.toPlainText() and not self.has_pending_attachments():
            self.end_edit(clear=False)
            self.edit_cancel_requested.emit()

    def _on_pending_changed(self) -> None:
        if self._changing_edit or not self._editing:
            return
        if not self.has_pending_attachments() and not self._edit.toPlainText():
            self.end_edit(clear=False)
            self.edit_cancel_requested.emit()

    def _apply_btn_ink(self):
        """按主题给发送/取消按钮上色：背景用混淡后的强调色（不那么跳、
        与主题协调），图标前景色按该背景的对比度取黑或白。

        纯图标按钮，无文字。PrimaryToolButton 默认满饱和 accent 底 + 白图标，
        浅色强调色（如 Everforest 的 #A7C080）既跳又看不清。混淡背景 +
        对比前景一并解决。"""
        ink = QColor(get_accent_text_color())
        icon = FluentIcon.CLOSE if self._running else FluentIcon.SEND
        self._btn.setIcon(icon.icon(color=ink))
        bg = get_accent_button_bg()
        hover = get_accent_button_bg_hover()
        pressed = get_accent_button_bg_pressed()
        self._btn.setStyleSheet(
            "PrimaryToolButton {"
            f" background-color: {bg};"
            " border: none; border-radius: 6px; }"
            f" PrimaryToolButton:hover {{ background-color: {hover}; }}"
            f" PrimaryToolButton:pressed {{ background-color: {pressed}; }}"
        )

    def refresh_theme(self):
        """主题切换后重算按钮前景色。"""
        self._apply_btn_ink()

    def set_enabled(self, enabled: bool):
        self._edit.setEnabled(enabled)
        self._btn.setEnabled(enabled)

    def focus(self):
        self._edit.setFocus()

    def set_text(self, text: str):
        """Prefill the input box and place the cursor at the end."""
        self._edit.setPlainText(text)
        self._edit.moveCursor(QTextCursor.MoveOperation.End)
        self._edit.setFocus()

    # -- 待发送附件 -----------------------------------------------------

    def _on_files_dropped(self, attachments: list):
        """拖放/粘贴的附件 → 加入待发预览条。"""
        self.add_pending_attachments(attachments)

    def add_pending_attachments(self, attachments: list):
        """把附件加入待发预览条（截图识图、拖放、粘贴共用，单一来源）。"""
        if not attachments:
            return
        self._pending_bar.add(attachments)

    def take_pending_attachments(self) -> list:
        """取走并清空待发附件（发送时调用）。"""
        return self._pending_bar.take_all()

    def has_pending_attachments(self) -> bool:
        return self._pending_bar.has_items()


class _TextEdit(QTextEdit):
    submitted = pyqtSignal()
    files_dropped = pyqtSignal(list)  # Attachment 列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursorWidth(2)
        self.setAcceptDrops(True)

    def _apply_text_color(self):
        """Force text/cursor color from theme. Called on every focus-in
        to override FluentWindow's stylesheet interference."""
        color = QColor(get_text_color())
        fmt = self.currentCharFormat()
        fmt.setForeground(color)
        self.setCurrentCharFormat(fmt)
        self.setTextColor(color)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._apply_text_color()

    def keyPressEvent(self, event: QKeyEvent):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self.submitted.emit()
        else:
            super().keyPressEvent(event)

    # -- 拖放 / 粘贴：文件和图片走附件管线，不当作文本插入 --------------

    def canInsertFromMimeData(self, source) -> bool:
        # 让带文件 URL 或图片的内容交给 insertFromMimeData 处理（解析为附件），
        # 而不是被 QTextEdit 当作富文本/URL 文本插入。
        if source.hasUrls() or source.hasImage():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if self._try_attach(source):
            return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self._try_attach(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _try_attach(self, mime) -> bool:
        """Parse files/images into attachments. Returns True if handled."""
        from app.ui.attachment_intake import attachments_from_mime

        attachments = attachments_from_mime(mime)
        if attachments:
            self.files_dropped.emit(attachments)
            return True
        return False
