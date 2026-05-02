from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.models.message import Message, MessageRole
from app.ui.tool_card import ToolCard


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
    """Renders one message (user or assistant). Supports inline tool cards."""

    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self._is_user = message.role == MessageRole.USER
        self._tool_cards: dict[str, ToolCard] = {}
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

        for tc in message.tool_calls:
            card = ToolCard(tc.name, tc.arguments, tc.result)
            self._tool_cards[tc.id] = card
            layout.addWidget(card)

    # ------------------------------------------------------------------ update
    def set_content(self, text: str):
        self._content.set_text(text)

    def add_tool_card(self, call_id: str, tool_name: str, params: dict) -> ToolCard:
        card = ToolCard(tool_name, params)
        self._tool_cards[call_id] = card
        self.layout().addWidget(card)
        return card

    def update_tool_card(self, call_id: str, result: dict):
        card = self._tool_cards.get(call_id)
        if card:
            card.update_result(result)


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

    # ------------------------------------------------------------------ public
    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self._bubbles.append(bubble)
        self._layout.addWidget(bubble)
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def last_bubble(self) -> MessageBubble | None:
        return self._bubbles[-1] if self._bubbles else None

    def clear(self):
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles.clear()

    def load_session(self, messages: list[Message]):
        self.clear()
        for msg in messages:
            if msg.role == "tool":
                continue  # tool-result messages are context-only, not displayed
            self.add_message(msg)
        QTimer.singleShot(80, self._scroll_bottom)

    def scroll_bottom(self):
        QTimer.singleShot(30, self._scroll_bottom)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
