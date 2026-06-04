from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QTextCharFormat
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QTextEdit, QWidget
from qfluentwidgets import PrimaryPushButton, FluentIcon

from app.ui.style import get_text_color

_MAX_CONTENT_WIDTH = 760  # must match ChatWidget._MAX_CONTENT_WIDTH
_SIDE_MIN = 16
_BOTTOM_MARGIN = 30


class InputWidget(QWidget):
    submitted = pyqtSignal(str)
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inputWidget")
        self._running = False
        self._build()

    def _build(self):
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(_SIDE_MIN, 8, _SIDE_MIN, _BOTTOM_MARGIN)
        self._layout.setSpacing(8)

        self._edit = _TextEdit(self)
        self._edit.setPlaceholderText("输入消息… (Enter 发送，Shift+Enter 换行)")
        self._edit.setMinimumHeight(40)
        self._edit.setMaximumHeight(120)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._edit.submitted.connect(self._submit)
        self._layout.addWidget(self._edit)

        self._btn = PrimaryPushButton(FluentIcon.SEND, "发送")
        self._btn.setFixedWidth(80)
        self._btn.setFixedHeight(36)
        self._btn.clicked.connect(self._on_button_clicked)
        self._layout.addWidget(self._btn)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        side = max(_SIDE_MIN, (self.width() - _MAX_CONTENT_WIDTH) // 2)
        self._layout.setContentsMargins(side, 8, side, _BOTTOM_MARGIN)

    def _submit(self):
        if self._running:
            return
        text = self._edit.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self._edit.clear()

    def _on_button_clicked(self):
        if self._running:
            self.cancel_requested.emit()
        else:
            self._submit()

    def set_running(self, running: bool):
        self._running = running
        self._edit.setEnabled(True)
        self._btn.setEnabled(True)
        if running:
            self._btn.setText("取消")
            self._btn.setIcon(FluentIcon.CLOSE.icon())
        else:
            self._btn.setText("发送")
            self._btn.setIcon(FluentIcon.SEND.icon())

    def set_enabled(self, enabled: bool):
        self._edit.setEnabled(enabled)
        self._btn.setEnabled(enabled)

    def focus(self):
        self._edit.setFocus()


class _TextEdit(QTextEdit):
    submitted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursorWidth(2)

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
