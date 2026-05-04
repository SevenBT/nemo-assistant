from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.models.message import Message, MessageRole


class TypingIndicator(QWidget):
    """Three pulsing dots animation indicating AI is thinking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("typingIndicator")
        self.setFixedHeight(36)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._step = 0

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(5)
        layout.addStretch()

        self._dots: list[QWidget] = []
        for i in range(3):
            dot = QWidget()
            dot.setFixedSize(8, 8)
            dot.setObjectName("typingDot")
            layout.addWidget(dot)
            self._dots.append(dot)
        layout.addStretch()

    def start(self):
        self._step = 0
        self._timer.start(120)
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _animate(self):
        """Pulse each dot sequentially."""
        for i, dot in enumerate(self._dots):
            # Active dot is brighter, others are dimmer
            phase = (self._step - i) % 3
            if phase == 0:
                opacity = 1.0
            elif phase == 1:
                opacity = 0.4
            else:
                opacity = 0.2
            dot.setStyleSheet(
                f"background: rgba(120, 120, 140, {opacity}); border-radius: 4px;"
            )
        self._step += 1


class _MessageText(QTextBrowser):
    """Auto-height read-only text area. Replaces QLabel for reliable word-wrap."""

    def __init__(self, is_user: bool, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("userBubble" if is_user else "aiBubble")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.document().setDocumentMargin(2)

    def set_text(self, text: str):
        self.setPlainText(text)
        self._fit()

    def _fit(self):
        vp_w = max(self.viewport().width(), 60)
        self.document().setTextWidth(vp_w)
        h = int(self.document().size().height()) + 10
        self.setFixedHeight(max(h, 22))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def sizeHint(self) -> QSize:
        self._fit()
        return QSize(super().sizeHint().width(), self.maximumHeight())


class MessageBubble(QFrame):
    """Renders one message (user or assistant). Tool cards are NOT shown here."""

    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self._is_user = message.role == MessageRole.USER
        self._tool_count = len(message.tool_calls)
        self.setObjectName("userMessage" if self._is_user else "aiMessage")
        self._build(message)

    def _build(self, message: Message):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        role_label = QLabel("你" if self._is_user else "AI")
        role_label.setObjectName("userLabel" if self._is_user else "aiLabel")
        layout.addWidget(role_label)

        self._content = _MessageText(self._is_user)
        self._content.set_text(message.content or "")
        layout.addWidget(self._content)

    # ------------------------------------------------------------------ update
    def set_content(self, text: str):
        self._content.set_text(text)


class ChatWidget(QWidget):
    """Scrollable message list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bubbles: list[MessageBubble] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setObjectName("chatScroll")

        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(10, 10, 10, 10)

        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll)

        # Typing indicator at bottom
        self._typing = TypingIndicator()
        root.addWidget(self._typing)
        self._typing.hide()

    # ------------------------------------------------------------------ public
    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self._bubbles.append(bubble)
        self._layout.addWidget(bubble)
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def last_bubble(self) -> MessageBubble | None:
        return self._bubbles[-1] if self._bubbles else None

    def remove_bubble(self, bubble: MessageBubble):
        """Remove a bubble from the layout and tracking list."""
        if bubble in self._bubbles:
            self._bubbles.remove(bubble)
        bubble.setParent(None)
        bubble.deleteLater()

    def clear(self):
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles.clear()

    def load_session(self, messages: list[Message]):
        self.clear()
        for msg in messages:
            if msg.role == "tool":
                continue  # tool-result messages are context-only, not displayed
            # Skip empty AI messages (created during tool calls but never received text)
            if msg.role == "assistant" and not msg.content and not msg.tool_calls:
                continue
            self.add_message(msg)
        QTimer.singleShot(80, self._scroll_bottom)

    def scroll_bottom(self):
        QTimer.singleShot(30, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_typing(self):
        """Show typing indicator and scroll to bottom."""
        self._typing.start()
        QTimer.singleShot(30, self._scroll_bottom)

    def stop_typing(self):
        """Hide typing indicator."""
        self._typing.stop()
