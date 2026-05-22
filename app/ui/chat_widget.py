import markdown as _md

from PyQt6.QtCore import Qt, QEvent, QSize, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import IndeterminateProgressBar, SmoothScrollArea

from app.models.message import Message, MessageRole
from app.ui.tool_card import ToolSummaryWidget
from app.ui.file_card_widget import FileCardWidget


class TypingIndicator(QWidget):
    """Fluent 风格进度条，表示 AI 正在思考。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)

        self._bar = IndeterminateProgressBar()
        self._bar.setFixedHeight(3)
        layout.addWidget(self._bar)

    def start(self):
        self._bar.start()
        self.show()

    def stop(self):
        self._bar.stop()
        self.hide()


class _MessageText(QTextBrowser):
    """自适应高度的只读文本区域，替代 QLabel 以实现可靠的自动换行。"""

    _MAX_USER_WIDTH = 420  # max content width for user bubbles

    def __init__(self, is_user: bool, parent=None):
        super().__init__(parent)
        self._is_user = is_user
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("userBubble" if is_user else "aiBubble")
        if is_user:
            self.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
        else:
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        self.document().setDocumentMargin(2)

    def set_text(self, text: str):
        if text:
            html = _md.markdown(
                text,
                extensions=["fenced_code", "tables", "nl2br"],
            )
            self.setHtml(html)
        else:
            self.setPlainText("")
        self._fit()

    def _fit(self):
        if self._is_user:
            # Let document flow without constraint to get ideal width
            self.document().setTextWidth(-1)
            ideal_w = int(self.document().idealWidth()) + 4
            use_w = min(ideal_w, self._MAX_USER_WIDTH)
            self.document().setTextWidth(use_w)
            h = int(self.document().size().height()) + 4
            self.setFixedWidth(use_w)
            self.setFixedHeight(max(h, 20))
        else:
            vp_w = max(self.viewport().width(), 60)
            self.document().setTextWidth(vp_w)
            h = int(self.document().size().height()) + 4
            self.setFixedHeight(max(h, 20))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def sizeHint(self) -> QSize:
        self._fit()
        return QSize(super().sizeHint().width(), self.maximumHeight())


class MessageBubble(QFrame):
    """
    渲染单条消息（用户或 AI）。

    AI 气泡支持折叠的工具摘要：
      [工具摘要]  ← 单行 "已调用 N 个工具"，可展开
      [回复文本]  ← 最终回复内容
    """

    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self._is_user = message.role == MessageRole.USER
        self._tool_summary: ToolSummaryWidget | None = None
        self.setObjectName("userMessage" if self._is_user else "aiMessage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if self._is_user:
            self.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
            )
        self._build(message)

    @property
    def is_user(self) -> bool:
        return self._is_user

    def _build(self, message: Message):
        layout = QVBoxLayout(self)
        if self._is_user:
            layout.setContentsMargins(10, 2, 10, 2)
        else:
            layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Attachments section -- user bubbles only
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

        # Tool summary section -- AI bubbles only
        if not self._is_user:
            self._tool_summary = ToolSummaryWidget()
            layout.addWidget(self._tool_summary)
            # Populate existing tool calls (used by load_session)
            for tc in message.tool_calls:
                self._tool_summary.add_tool(tc.id, tc.name)
                if tc.result is not None:
                    self._tool_summary.update_tool(tc.id, tc.result)
            self._tool_summary.setVisible(bool(message.tool_calls))

        self._content = _MessageText(self._is_user)
        self._content.set_text(message.content or "")
        # 空的 AI 内容先隐藏，有文本到达时再显示
        if not self._is_user and not message.content:
            self._content.hide()
        layout.addWidget(self._content)

    # -- 内部 --------------------------------------------------------

    # -- 公开 API -------------------------------------------------------

    def add_tool_card(self, call_id: str, name: str, params: dict):
        """向摘要组件添加一个待处理的工具调用。"""
        if self._is_user or not self._tool_summary:
            return
        self._tool_summary.add_tool(call_id, name)
        self._tool_summary.show()

    def update_tool_card(self, call_id: str, result: dict):
        """更新工具调用的最终结果。"""
        if self._tool_summary:
            self._tool_summary.update_tool(call_id, result)

    def clear_text(self):
        """清空并隐藏文本区域（工具调用开始时调用）。"""
        if self._is_user:
            return
        self._content.set_text("")
        self._content.hide()

    def set_content(self, text: str):
        """设置回复文本内容，根据是否有内容自动显示/隐藏。"""
        self._content.set_text(text)
        if not self._is_user:
            self._content.setVisible(bool(text))


class ChatWidget(QWidget):
    """可滚动的消息列表，支持拖放文件附件。"""

    file_attached = pyqtSignal(list)  # Emits list[Attachment]

    _MAX_CONTENT_WIDTH = 760  # content column max width; centered when viewport is wider

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bubbles: list[MessageBubble] = []
        self.setAcceptDrops(True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._scroll = SmoothScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setObjectName("chatScroll")
        self._scroll.viewport().setStyleSheet("background: transparent;")

        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(16)
        self._layout.setContentsMargins(16, 20, 16, 20)

        self._scroll.setWidget(self._inner)
        self._scroll.viewport().installEventFilter(self)
        root.addWidget(self._scroll)

        # Typing indicator at bottom (outside scroll area)
        self._typing = TypingIndicator()
        root.addWidget(self._typing)
        self._typing.hide()

    # -- public ----------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._update_inner_margins(event.size().width())
        return super().eventFilter(obj, event)

    def _update_inner_margins(self, viewport_width: int):
        """Keep content centered with equal side margins when viewport > max width."""
        side = max(16, (viewport_width - self._MAX_CONTENT_WIDTH) // 2)
        self._layout.setContentsMargins(side, 20, side, 20)

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self._bubbles.append(bubble)
        if bubble.is_user:
            self._layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignRight)
        else:
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
        从会话消息重建聊天界面。

        连续的 assistant 消息（多轮工具循环产生）合并为一个气泡：
          - 链中所有消息的工具调用 → 工具卡片
          - 最后一条有文本的消息 → 回复内容
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
        """将连续的 assistant 消息合并为单个气泡，收集所有工具调用。"""
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
        """显示输入指示器并滚动到底部。"""
        self._typing.start()
        QTimer.singleShot(30, self._scroll_bottom)

    def stop_typing(self):
        """隐藏输入指示器。"""
        self._typing.stop()

    # -- 拖放 ---------------------------------------------------

    def dragEnterEvent(self, event):
        """接受包含文件 URL 的拖放事件。"""
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
                continue

        if attachments:
            self.file_attached.emit(attachments)
            event.acceptProposedAction()
        else:
            event.ignore()
