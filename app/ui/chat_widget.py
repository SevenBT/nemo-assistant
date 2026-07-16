import re

import markdown as _md

from app.i18n import t as _t

from PyQt6.QtCore import Qt, QEvent, QPoint, QSize, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import IndeterminateProgressBar, SmoothScrollArea, TransparentToolButton, FluentIcon

from app.models.message import Message, MessageRole
from app.ui.anchor_rail import AnchorRail, _AnchorPanel
from app.ui.tool_card import ToolSummaryWidget
from app.ui.file_card_widget import FileCardWidget
from app.ui.image_preview_widget import ImagePreviewWidget


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

    # 模型爱用 --- / *** / ___ 作分段分隔，markdown 渲染成 <hr>。这条 1px 细线
    # 在浮窗气泡里突兀，且分数 DPI 下滚动时抗锯齿相位抖动会闪。段落间本就有间距，
    # 直接删掉 <hr>（匹配渲染后的标签，源码三种写法一并覆盖）。
    _HR_RE = re.compile(r"<hr\s*/?>")

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
            html = self._HR_RE.sub("", html)
            self.setHtml(html)
        else:
            self.setPlainText("")
        self._fit()

    def _fit(self):
        if self._is_user:
            # 让文档自由流动以获取理想宽度
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

    悬停时底部浮现操作条：AI 气泡可复制/重新生成，用户气泡可编辑。
    操作条默认只对「最后一轮」气泡启用（由 ChatWidget 控制），符合
    「只重生/编辑最后一条」的语义，避免改动中间历史。
    """

    # 携带本气泡的 Message，交由上层（控制器）决定如何处理。
    copy_requested = pyqtSignal(object)
    regenerate_requested = pyqtSignal(object)
    edit_requested = pyqtSignal(object)

    def __init__(self, message: Message, parent=None):
        super().__init__(parent)
        self._is_user = message.role == MessageRole.USER
        self._message = message
        self._text = message.content or ""
        self._tool_summary: ToolSummaryWidget | None = None
        self._actions: QWidget | None = None
        self._actions_enabled = False
        # 外层容器透明，只作布局；带背景的气泡本体是内层 self._frame。
        # 操作条放在气泡本体「之外、下方」，悬停显示时不会撑高气泡本身。
        self.setObjectName("bubbleContainer")
        if self._is_user:
            self.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
            )
        self._build(message)

    @property
    def is_user(self) -> bool:
        return self._is_user

    @property
    def message(self) -> Message:
        return self._message

    @property
    def text(self) -> str:
        return self._text

    def _build(self, message: Message):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # 气泡本体：带背景/边框的内层 frame，只装内容，悬停不受操作条影响。
        self._frame = QFrame(self)
        self._frame.setObjectName("userMessage" if self._is_user else "aiMessage")
        self._frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if self._is_user:
            # 用户气泡按内容自适应宽度（右对齐）。
            self._frame.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
            )
        else:
            # AI 气泡撑满内容列宽，否则回复框会被压成半宽。
            self._frame.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        layout = QVBoxLayout(self._frame)
        if self._is_user:
            layout.setContentsMargins(10, 2, 10, 2)
        else:
            layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # 附件区域 — 仅用户消息显示
        if self._is_user and message.attachments:
            attachments_widget = QWidget()
            attachments_widget.setObjectName("attachmentsContainer")
            attachments_layout = QVBoxLayout(attachments_widget)
            attachments_layout.setContentsMargins(0, 4, 0, 4)
            attachments_layout.setSpacing(4)

            for attachment in message.attachments:
                if attachment.is_image():
                    widget = ImagePreviewWidget(attachment)
                else:
                    widget = FileCardWidget(attachment)
                attachments_layout.addWidget(widget)

            layout.addWidget(attachments_widget)

        # 工具摘要区域 — 仅 AI 消息显示
        if not self._is_user:
            self._tool_summary = ToolSummaryWidget()
            layout.addWidget(self._tool_summary)
            # 填充已有的工具调用（load_session 使用）
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

        if self._is_user:
            # 右对齐让用户气泡贴右；AI 气泡不设对齐，撑满内容列宽。
            outer.addWidget(self._frame, alignment=Qt.AlignmentFlag.AlignRight)
        else:
            outer.addWidget(self._frame)

        # 操作条在气泡本体之外、下方。用固定高度容器承托，隐藏时也占位，
        # 悬停显示不引起布局跳动（气泡不再变高）。
        self._actions = self._build_actions()
        self._actions_holder = QWidget(self)
        self._actions_holder.setObjectName("bubbleActionsHolder")
        holder_layout = QHBoxLayout(self._actions_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(0)
        if self._is_user:
            holder_layout.addStretch(1)
            holder_layout.addWidget(self._actions)
        else:
            holder_layout.addWidget(self._actions)
            holder_layout.addStretch(1)
        self._actions_holder.setFixedHeight(22)
        outer.addWidget(self._actions_holder)
        self._actions.hide()

    def _build_actions(self) -> QWidget:
        """底部悬停操作条：AI=复制/重新生成，用户=复制/编辑。"""
        bar = QWidget(self)
        bar.setObjectName("bubbleActions")
        row = QHBoxLayout(bar)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)

        def _btn(icon, tip, slot) -> TransparentToolButton:
            b = TransparentToolButton(icon, bar)
            b.setFixedSize(20, 20)
            b.setIconSize(QSize(12, 12))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self._copy_btn = _btn(
            FluentIcon.COPY, _t("chat.action.copy"), self._on_copy_clicked
        )
        if self._is_user:
            _btn(FluentIcon.EDIT, _t("chat.action.edit"),
                 lambda: self.edit_requested.emit(self._message))
        else:
            _btn(FluentIcon.SYNC, _t("chat.action.regenerate"),
                 lambda: self.regenerate_requested.emit(self._message))
        return bar

    def _on_copy_clicked(self):
        """复制后把按钮图标临时切成对号，短暂后还原——无需弹通知。"""
        self.copy_requested.emit(self._message)
        self._copy_btn.setIcon(FluentIcon.ACCEPT)
        QTimer.singleShot(1500, self._restore_copy_icon)

    def _restore_copy_icon(self):
        # 气泡可能已被销毁（重新生成/切会话），忽略即可。
        try:
            self._copy_btn.setIcon(FluentIcon.COPY)
        except RuntimeError:
            pass

    def set_actions_enabled(self, enabled: bool):
        """是否允许显示操作条（仅最后一轮气泡开启）。"""
        self._actions_enabled = enabled
        if not enabled and self._actions is not None:
            self._actions.hide()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._actions_enabled and self._actions is not None:
            # 空 AI 气泡（还没有内容）不显示操作条。
            if not self._is_user and not self._text:
                return
            self._actions.show()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._actions is not None:
            self._actions.hide()

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
        self._text = text
        # 保持 message.content 与气泡显示同步，供复制/重新生成读取最新文本。
        self._message.content = text
        self._content.set_text(text)
        if not self._is_user:
            self._content.setVisible(bool(text))


class ChatWidget(QWidget):
    """可滚动的消息列表，支持拖放文件附件。"""

    file_attached = pyqtSignal(list)  # 发射 Attachment 列表
    copy_message = pyqtSignal(object)       # 复制某条 AI 回复（Message）
    regenerate_message = pyqtSignal(object)  # 重新生成某条 AI 回复（Message）
    edit_message = pyqtSignal(object)        # 编辑某条用户消息（Message）

    _MAX_CONTENT_WIDTH = 760  # content column max width; centered when viewport is wider
    _PANEL_RAIL_GAP = 6       # 锚点面板与轨道之间的间隙
    _PANEL_CONTENT_GAP = 16   # 锚点面板与对话内容右边缘的最小间隙

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
        # 用 ID 选择器把透明背景限定在 viewport 自身。裸样式（无选择器）会级联到
        # viewport 的所有子控件，覆盖掉气泡的 #userMessage 背景，导致用户气泡底色不可见。
        self._scroll.viewport().setObjectName("chatViewport")
        self._scroll.viewport().setStyleSheet(
            "#chatViewport { background: transparent; }"
        )

        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(16)
        self._layout.setContentsMargins(16, 20, 16, 20)

        self._scroll.setWidget(self._inner)
        self._scroll.viewport().installEventFilter(self)
        root.addWidget(self._scroll)

        # 问题锚点轨道：覆盖在 viewport 右侧（滚动条内侧）
        self._anchor_rail = AnchorRail(self._scroll.viewport())
        self._anchor_rail.anchor_clicked.connect(self._scroll_to_bubble)
        self._anchor_rail.hide()
        self._scroll.verticalScrollBar().valueChanged.connect(
            self._on_scroll_changed
        )

        # 悬停时弹出的问题列表面板（整体框 + 主题背景）
        self._anchor_panel = _AnchorPanel(self._scroll.viewport())
        self._anchor_panel.row_clicked.connect(self._on_panel_row_clicked)
        self._anchor_rail.entered.connect(self._show_anchor_panel)
        self._anchor_rail.left.connect(self._maybe_hide_anchor_panel)
        self._anchor_rail.hover_anchor.connect(self._anchor_panel.set_active)
        self._anchor_panel.entered.connect(self._cancel_hide_panel)
        self._anchor_panel.left.connect(self._maybe_hide_anchor_panel)
        self._hide_panel_timer = QTimer(self)
        self._hide_panel_timer.setSingleShot(True)
        self._hide_panel_timer.setInterval(150)
        self._hide_panel_timer.timeout.connect(self._anchor_panel.hide)

        # 打字指示器在底部（滚动区域外）
        self._typing = TypingIndicator()
        root.addWidget(self._typing)
        self._typing.hide()

    # -- public ----------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._update_inner_margins(event.size().width())
            self._reposition_rail()
        return super().eventFilter(obj, event)

    def _reposition_rail(self):
        """让锚点轨道贴在 viewport 右侧、滚动条内侧。"""
        vp = self._scroll.viewport()
        w = self._anchor_rail.width()
        # 右侧留出滚动条宽度（约 12px）的内边距
        x = vp.width() - w - 12
        self._anchor_rail.setGeometry(x, 0, w, vp.height())
        self._anchor_rail.raise_()
        self._anchor_rail.relayout()
        if self._anchor_panel.isVisible():
            self._position_anchor_panel()

    # -- 锚点面板联动 -----------------------------------------------------

    def _on_scroll_changed(self):
        self._anchor_rail.refresh()
        self._anchor_panel.set_active(self._anchor_rail.active_index())

    def _show_anchor_panel(self):
        self._hide_panel_timer.stop()
        anchors = self._anchor_rail.anchors()
        if not anchors:
            return
        texts = [(t.strip() or _t("chat.emptyMessage")) for _, t in anchors]
        texts = [" ".join(t.split()) for t in texts]
        # 面板宽度受限于「对话内容右边缘」与轨道之间的空隙，留固定间隙不遮盖对话
        vp = self._scroll.viewport()
        side = max(16, (vp.width() - self._MAX_CONTENT_WIDTH) // 2)
        content_right = vp.width() - side
        gap = (self._anchor_rail.x() - self._PANEL_RAIL_GAP) - (
            content_right + self._PANEL_CONTENT_GAP
        )
        max_w = max(self._anchor_panel._MIN_W, gap)
        self._anchor_panel.set_items(
            texts, self._anchor_rail.active_index(), max_w
        )
        self._position_anchor_panel()
        self._anchor_panel.show()
        self._anchor_panel.raise_()

    def _position_anchor_panel(self):
        """面板右边缘贴近轨道左侧，垂直居中于 viewport。"""
        vp = self._scroll.viewport()
        panel = self._anchor_panel
        x = self._anchor_rail.x() - panel.width() - self._PANEL_RAIL_GAP
        y = (vp.height() - panel.height()) // 2
        panel.move(max(4, x), max(4, y))

    def _cancel_hide_panel(self):
        self._hide_panel_timer.stop()

    def _maybe_hide_anchor_panel(self):
        # 延迟隐藏，给鼠标从轨道移到面板的过渡留出时间
        self._hide_panel_timer.start()

    def _on_panel_row_clicked(self, idx: int):
        anchors = self._anchor_rail.anchors()
        if 0 <= idx < len(anchors):
            self._scroll_to_bubble(anchors[idx][0])
            self._anchor_panel.hide()

    def _update_inner_margins(self, viewport_width: int):
        """当视口宽度超过最大内容宽度时，用等距侧边距保持内容居中。"""
        side = max(16, (viewport_width - self._MAX_CONTENT_WIDTH) // 2)
        self._layout.setContentsMargins(side, 20, side, 20)

    def add_message(self, message: Message) -> MessageBubble:
        bubble = MessageBubble(message)
        self._register_bubble(bubble)
        self._bubbles.append(bubble)
        if bubble.is_user:
            self._layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignRight)
        else:
            self._layout.addWidget(bubble)
        self._refresh_action_targets()
        QTimer.singleShot(30, self._scroll_bottom)
        QTimer.singleShot(30, self._rebuild_anchors)
        return bubble

    def _register_bubble(self, bubble: MessageBubble):
        """把气泡的操作信号转发到 ChatWidget 层。"""
        bubble.copy_requested.connect(self.copy_message)
        bubble.regenerate_requested.connect(self.regenerate_message)
        bubble.edit_requested.connect(self.edit_message)

    def _refresh_action_targets(self):
        """只让最后一条用户气泡与最后一条 AI 气泡启用操作条。

        「只限最后一轮」：编辑作用于最后一条用户消息，重新生成/复制作用于
        最后一条 AI 回复；更早的气泡不显示操作条，避免改动中间历史。
        """
        last_user = None
        last_ai = None
        for b in self._bubbles:
            if b.is_user:
                last_user = b
            else:
                last_ai = b
        for b in self._bubbles:
            b.set_actions_enabled(b is last_user or b is last_ai)

    def last_bubble(self) -> MessageBubble | None:
        return self._bubbles[-1] if self._bubbles else None

    def remove_bubble(self, bubble: MessageBubble):
        if bubble in self._bubbles:
            self._bubbles.remove(bubble)
        bubble.setParent(None)
        bubble.deleteLater()
        self._refresh_action_targets()
        self._rebuild_anchors()

    def clear(self):
        for b in self._bubbles:
            b.deleteLater()
        self._bubbles.clear()
        self._rebuild_anchors()

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
        self._refresh_action_targets()
        QTimer.singleShot(80, self._scroll_bottom)
        QTimer.singleShot(80, self._rebuild_anchors)

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
        # 跳过完全空的组
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
        self._register_bubble(bubble)
        self._bubbles.append(bubble)
        self._layout.addWidget(bubble)

    def scroll_bottom(self):
        QTimer.singleShot(30, self._scroll_bottom)

    def _rebuild_anchors(self):
        """收集所有用户问题气泡，刷新锚点轨道。"""
        anchors = [(b, b.text) for b in self._bubbles if b.is_user]
        self._anchor_rail.set_anchors(anchors)
        self._reposition_rail()

    def _scroll_to_bubble(self, bubble: MessageBubble):
        """平滑滚动，使指定气泡顶部对齐视口上沿。"""
        if bubble not in self._bubbles:
            return
        target = bubble.mapTo(self._inner, QPoint(0, 0)).y()
        sb = self._scroll.verticalScrollBar()
        # 留出少许上边距，避免紧贴顶部
        value = max(sb.minimum(), min(target - 12, sb.maximum()))
        delegate = getattr(self._scroll, "delegate", None)
        bar = getattr(delegate, "vScrollBar", None)
        if bar is not None:
            bar.scrollTo(value)  # 带动画平滑滚动
        else:
            sb.setValue(value)
            self._sync_smooth_scroll(value)

    def _scroll_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._sync_smooth_scroll(sb.maximum())
        self._anchor_rail.refresh()

    def _sync_smooth_scroll(self, value: int):
        """同步 qfluentwidgets SmoothScrollBar 的内部累加器。

        SmoothScrollArea 的滚轮走 SmoothScrollBar.scrollValue()，它维护独立的
        __value 累加器作为滚轮真值来源。程序化设置原生 scrollbar 不会更新该累加器，
        导致下次滚轮从陈旧的 __value 起算，出现「滚一格、跳整屏」的大幅跳变。
        每次程序化滚动后用 resetValue() 把累加器对齐到实际位置。
        """
        delegate = getattr(self._scroll, "delegate", None)
        bar = getattr(delegate, "vScrollBar", None)
        if bar is not None:
            bar.resetValue(value)

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
        """处理拖放的文件，解析后附加到聊天。"""
        from app.ui.attachment_intake import attachments_from_mime

        attachments = attachments_from_mime(event.mimeData())
        if attachments:
            self.file_attached.emit(attachments)
            event.acceptProposedAction()
        else:
            event.ignore()
