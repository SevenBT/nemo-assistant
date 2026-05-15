from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QTextCharFormat
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QTextEdit, QWidget
from qfluentwidgets import PrimaryPushButton, FluentIcon

from app.ui.style import get_text_color


class InputWidget(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inputWidget")
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        self._edit = _TextEdit(self)
        self._edit.setPlaceholderText("输入消息… (Enter 发送，Shift+Enter 换行)")
        self._edit.setMinimumHeight(40)
        self._edit.setMaximumHeight(120)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._edit.submitted.connect(self._submit)
        layout.addWidget(self._edit)

        self._btn = PrimaryPushButton(FluentIcon.SEND, "发送")
        self._btn.setFixedWidth(80)
        self._btn.setFixedHeight(36)
        self._btn.clicked.connect(self._submit)
        layout.addWidget(self._btn)

    def _submit(self):
        text = self._edit.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self._edit.clear()

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
