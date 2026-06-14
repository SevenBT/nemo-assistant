"""Mini mode panel: a compact, always-on-top desktop companion.

Layout:
  ┌─ MiniToolBar  [+][⤢][─][✕] ─┐   draggable (startSystemMove)
  ├────────────────────────────┤
  │  MiniChatView (latest turn)  │   reused ChatWidget, only last exchange
  ├────────────────────────────┤
  │  InputWidget (reparented in) │   shared instance from normal mode
  └────────────────────────────┘

The same ChatSessionController drives this view via bind_targets(); MiniChatView
subclasses ChatWidget and overrides load_session() to render only the most recent
user + assistant exchange, keeping the page uncluttered. All streaming/tool/cancel
behaviour is inherited unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    TransparentToolButton,
    ToolTipFilter,
    ToolTipPosition,
)

from app.models.message import Message, MessageRole
from app.ui.chat_widget import ChatWidget

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


class MiniChatView(ChatWidget):
    """ChatWidget that renders only the latest user+assistant exchange.

    Mini mode shows a single Q&A turn to keep the small window readable.
    Live streaming still appends to the last bubble via the inherited API,
    so no other controller logic changes.
    """

    def load_session(self, messages: list[Message]):
        # Keep only the trailing exchange: the last user message and everything
        # after it (the assistant reply, possibly spanning tool-loop turns).
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == MessageRole.USER:
                last_user_idx = i
                break
        trimmed = messages if last_user_idx is None else messages[last_user_idx:]
        super().load_session(trimmed)


class MiniPanel(QWidget):
    """Compact panel hosting the mini toolbar, latest-reply view and input."""

    new_session_requested = pyqtSignal()
    exit_mini_requested = pyqtSignal()
    minimize_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._win = window
        self.setObjectName("miniPanel")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar (draggable) ───────────────────────────────────────
        self._toolbar = _MiniToolBar(self._win)
        self._toolbar.setObjectName("miniToolBar")
        self._toolbar.setFixedHeight(36)

        bar = QHBoxLayout(self._toolbar)
        bar.setContentsMargins(6, 0, 4, 0)
        bar.setSpacing(0)
        bar.addStretch()

        self._new_btn = self._make_btn(FluentIcon.ADD, "新建会话", self.new_session_requested.emit)
        bar.addWidget(self._new_btn)
        self._normal_btn = self._make_btn(
            FluentIcon.ZOOM_IN, "切回正常模式", self.exit_mini_requested.emit
        )
        bar.addWidget(self._normal_btn)
        self._min_btn = self._make_btn(
            FluentIcon.MINIMIZE, "最小化", self.minimize_requested.emit
        )
        bar.addWidget(self._min_btn)
        self._close_btn = self._make_btn(
            FluentIcon.CLOSE, "关闭到托盘", self.close_requested.emit
        )
        bar.addWidget(self._close_btn)

        root.addWidget(self._toolbar)

        # ── Latest-reply view ─────────────────────────────────────────
        self._chat = MiniChatView()
        root.addWidget(self._chat, stretch=1)

        # ── Input slot (InputWidget injected by MainWindow) ───────────
        self._input_slot = QVBoxLayout()
        self._input_slot.setContentsMargins(0, 0, 0, 0)
        self._input_slot.setSpacing(0)
        root.addLayout(self._input_slot)

    def _make_btn(self, icon: FluentIcon, tooltip: str, slot) -> TransparentToolButton:
        btn = TransparentToolButton(icon)
        btn.setFixedSize(30, 30)
        btn.setToolTip(tooltip)
        btn.installEventFilter(
            ToolTipFilter(btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        btn.clicked.connect(slot)
        return btn

    # -- public API ----------------------------------------------------

    @property
    def chat(self) -> MiniChatView:
        return self._chat

    def set_input_widget(self, widget: QWidget):
        """Insert the (reparented) shared InputWidget into the input slot."""
        self._input_slot.addWidget(widget)

    def apply_font_size(self, size: int):
        """Apply mini-specific font size to the reply view only."""
        self._chat.setStyleSheet(
            f"#aiBubble, #userBubble {{ font-size: {size}px; }}"
        )


class _MiniToolBar(QWidget):
    """Draggable toolbar strip — left-drag moves the frameless mini window."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._win = window

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._win._snap_mgr is not None:
                self._win._snap_mgr.cancel_animation()
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()
