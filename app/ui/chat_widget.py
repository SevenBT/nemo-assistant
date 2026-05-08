from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
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
from app.ui.tool_card import ToolCard
from app.ui.file_card_widget import FileCardWidget


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
    """
    Renders one message (user or assistant).

    AI bubbles support inline tool cards (ChatGPT-style):
      [AI label]
      [ToolCard …]  ← collapsed by default, one per tool call
      [answer text] ← only the final response text
    """

    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self._is_user = message.role == MessageRole.USER
        self._tool_cards: dict = {}  # call_id -> ToolCard
        self.setObjectName("userMessage" if self._is_user else "aiMessage")
        self._build(message)

    @property
    def is_user(self) -> bool:
        return self._is_user

    def _build(self, message: Message):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        role_label = QLabel("你" if self._is_user else "AI")
        role_label.setObjectName("userLabel" if self._is_user else "aiLabel")
        layout.addWidget(role_label)

        # Attachments section — user bubbles only
        if self._is_user and message.attachments:
            attachments_widget = QWidget()
            attachments_widget.setObjectName("attachmentsContainer")
            attachments_layout = QVBoxLayout(attachments_widget)
            attachments_layout.setContentsMargins(0, 4, 0, 4)
            attachments_layout.setSpacing(4)

            for attachment in message.attachments:
                file_card = FileCardWidget(attachment)
                attachments_layout.addWidget(file_card)

            layout.addWidget(attachments_widget)

        # Tool cards section — AI bubbles only
        if not self._is_user:
            self._tools_widget = QWidget()
            self._tools_widget.setObjectName("toolsContainer")
            self._tools_layout = QVBoxLayout(self._tools_widget)
            self._tools_layout.setContentsMargins(0, 0, 0, 0)
            self._tools_layout.setSpacing(3)
            layout.addWidget(self._tools_widget)
            # Populate existing tool calls (used by load_session)
            for tc in message.tool_calls:
                self._insert_tool_card(tc.id, tc.name, tc.arguments, tc.result)
            self._tools_widget.setVisible(bool(message.tool_calls))

        self._content = _MessageText(self._is_user)
        self._content.set_text(message.content or "")
        # Hide empty AI content; shown when text actually arrives
        if not self._is_user and not message.content:
            self._content.hide()
        layout.addWidget(self._content)

    # ── internal ────────────────────────────────────────────────────────

    def _insert_tool_card(self, call_id: str, name: str, params: dict, result=None):
        card = ToolCard(name, params, result)
        self._tool_cards[call_id] = card
        self._tools_layout.addWidget(card)

    # ── public API ───────────────────────────────────────────────────────

    def add_tool_card(self, call_id: str, name: str, params: dict):
        """Append a pending tool card during live streaming."""
        if self._is_user:
            return
        self._insert_tool_card(call_id, name, params)
        self._tools_widget.show()

    def update_tool_card(self, call_id: str, result: dict):
        """Update an existing tool card with its final result."""
        card = self._tool_cards.get(call_id)
        if card:
            card.update_result(result)

    def clear_text(self):
        """Hide and clear the text area (called when a tool call starts)."""
        if self._is_user:
            return
        self._content.set_text("")
        self._content.hide()

    def set_content(self, text: str):
        """Set the main answer text; shows or hides the widget accordingly."""
        self._content.set_text(text)
        if not self._is_user:
            self._content.setVisible(bool(text))


class ChatWidget(QWidget):
    """Scrollable message list with drag-and-drop file support."""

    file_attached = pyqtSignal(list)  # Emits list[Attachment]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bubbles: list[MessageBubble] = []
        self.setAcceptDrops(True)
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

        # Typing indicator at bottom (outside scroll area)
        self._typing = TypingIndicator()
        root.addWidget(self._typing)
        self._typing.hide()

    # ── public ──────────────────────────────────────────────────────────

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self._bubbles.append(bubble)
        self._layout.addWidget(bubble)
        QTimer.singleShot(30, self._scroll_bottom)
        return bubble

    def last_bubble(self) -> MessageBubble | None:
        return self._bubbles[-1] if self._bubbles else None

    def remove_bubble(self, bubble: MessageBubble):
        if bubble in self._bubbles:
            self._bubbles.remove(bubble)
        bubble.setParent(None)
        bubble.deleteLater()

    def clear(self):
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles.clear()

    def load_session(self, messages: list[Message]):
        """
        Rebuild the chat from session messages.

        Consecutive assistant messages (produced by multi-turn tool loops) are
        merged into ONE bubble:
          - Tool calls from every message in the chain → tool cards
          - Content of the LAST message with text → answer text
        This prevents intermediate "thinking" text and empty tool-call
        placeholders from appearing as separate reply boxes.
        """
        self.clear()
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.role in (MessageRole.TOOL, MessageRole.SYSTEM):
                i += 1
                continue
            if msg.role == MessageRole.USER:
                self.add_message(msg)
                i += 1
            else:  # ASSISTANT
                group: list[Message] = []
                while i < len(messages) and messages[i].role == MessageRole.ASSISTANT:
                    group.append(messages[i])
                    i += 1
                self._add_assistant_group(group)
        QTimer.singleShot(80, self._scroll_bottom)

    def _add_assistant_group(self, group: list[Message]):
        """
        Collapse a run of consecutive assistant messages into a single bubble.
        Collects all tool_calls across the chain; uses only the last non-empty
        content as the answer text.
        """
        if not group:
            return
        all_tool_calls = []
        for msg in group:
            all_tool_calls.extend(msg.tool_calls)
        final_content = ""
        for msg in reversed(group):
            if msg.content:
                final_content = msg.content
                break
        # Skip entirely empty groups
        if not final_content and not all_tool_calls:
            return
        combined = Message(
            id=group[-1].id,
            role=MessageRole.ASSISTANT,
            content=final_content,
            timestamp=group[-1].timestamp,
            tool_calls=all_tool_calls,
        )
        bubble = MessageBubble(combined)
        self._bubbles.append(bubble)
        self._layout.addWidget(bubble)

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

    # ── drag and drop ───────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        """Accept drag events with file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handle dropped files."""
        from app.core.file_parser import FileParser, FileParseError
        import logging

        logger = logging.getLogger(__name__)
        urls = event.mimeData().urls()
        if not urls:
            return

        parser = FileParser()
        attachments = []

        for url in urls:
            file_path = url.toLocalFile()
            if not file_path:
                continue

            try:
                attachment = parser.parse_file(file_path)
                attachments.append(attachment)
                logger.info(f"成功解析文件: {attachment.file_name}")
            except FileParseError as e:
                logger.warning(f"解析文件失败: {e}")
                # TODO: Show error notification to user
                continue

        if attachments:
            self.file_attached.emit(attachments)
            event.acceptProposedAction()
        else:
            event.ignore()
