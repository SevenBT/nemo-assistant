"""TitleBar widget for the frameless floating window.

Uses Fluent Design components: SegmentedWidget for navigation,
TransparentToolButton + FluentIcon for window controls.
Plain QWidget injected into FluentWindow via setTitleBar().
"""
from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    SegmentedWidget,
    TransparentToolButton,
    ToolTipFilter,
    ToolTipPosition,
    Action,
)
from app.ui.components.context_menu import ContextMenu

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


def _remove_tooltip_border(widget):
    """Remove Windows 11 DWM border from a tooltip window."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return
        dwmapi = ctypes.windll.dwmapi
        color_none = ctypes.c_uint(0xFFFFFFFE)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(color_none), ctypes.sizeof(color_none)
        )
        corner_pref = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref)
        )
    except Exception:
        pass


class _BorderlessToolTipFilter(ToolTipFilter):
    """ToolTipFilter that removes the Windows 11 DWM border on the tooltip."""

    def showToolTip(self):
        super().showToolTip()
        if self._tooltip and self._tooltip.isVisible():
            _remove_tooltip_border(self._tooltip)


class _DummyBtn(QWidget):
    """Invisible zero-size placeholder satisfying FluentWindow's titleBar.minBtn/maxBtn/closeBtn contract."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(0, 0)
        super().hide()

    def setState(self, state):
        pass

    def hide(self):
        pass


class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._win = window
        self.setObjectName("titleBar")
        self.setFixedHeight(76)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Row 1: Title / drag area + window controls ────────────────
        top_row = QWidget()
        top_row.setObjectName("titleBarTop")
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(8, 0, 4, 0)
        top_layout.setSpacing(0)
        top_layout.addStretch()

        self._min_btn = self._make_tool_btn(
            FluentIcon.MINIMIZE, "最小化", self._win._minimize
        )
        top_layout.addWidget(self._min_btn)

        self._max_btn = self._make_tool_btn(
            FluentIcon.FULL_SCREEN, "最大化", self._win._toggle_maximize
        )
        top_layout.addWidget(self._max_btn)

        self._close_btn = self._make_tool_btn(
            FluentIcon.CLOSE, "关闭到托盘", self._win._hide_to_tray
        )
        top_layout.addWidget(self._close_btn)

        root.addWidget(top_row)

        # ── Row 2: Navigation bar ─────────────────────────────────────
        nav_row = QWidget()
        nav_row.setObjectName("titleBarNav")
        nav_layout = QHBoxLayout(nav_row)
        nav_layout.setContentsMargins(8, 0, 8, 0)
        nav_layout.setSpacing(0)

        # Sidebar toggle
        self._toggle_btn = TransparentToolButton(FluentIcon.MENU)
        self._toggle_btn.setFixedSize(36, 32)
        self._toggle_btn.setToolTip("显示/隐藏会话列表")
        self._toggle_btn.installEventFilter(
            _BorderlessToolTipFilter(self._toggle_btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        self._toggle_btn.clicked.connect(self._win._toggle_session_panel)
        nav_layout.addWidget(self._toggle_btn)

        nav_layout.addSpacing(8)

        # View-switcher (SegmentedWidget)
        self._nav = SegmentedWidget()
        self._nav.setFixedHeight(32)
        self._nav.addItem("chat", "聊天", icon=FluentIcon.CHAT)
        self._nav.addItem("notes", "笔记", icon=FluentIcon.EDIT)
        self._nav.addItem("workshop", "工坊", icon=FluentIcon.DEVELOPER_TOOLS)
        self._nav.setCurrentItem("chat")
        self._nav.currentItemChanged.connect(self._on_nav_changed)
        nav_layout.addWidget(self._nav)

        # Screenshot button
        nav_layout.addSpacing(8)
        self._screenshot_btn = self._make_tool_btn(
            FluentIcon.CLIPPING_TOOL, "截图", self._win._start_screenshot
        )
        nav_layout.addWidget(self._screenshot_btn)

        nav_layout.addStretch()
        root.addWidget(nav_row)

        # Aliases required by FluentWindow's nativeEvent and setTitleBar internals.
        self.minBtn = _DummyBtn(self)
        self.maxBtn = _DummyBtn(self)
        self.closeBtn = _DummyBtn(self)

    def _make_tool_btn(self, icon: FluentIcon, tooltip: str, slot) -> TransparentToolButton:
        btn = TransparentToolButton(icon)
        btn.setFixedSize(32, 32)
        btn.setToolTip(tooltip)
        btn.installEventFilter(
            _BorderlessToolTipFilter(btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        btn.clicked.connect(slot)
        return btn

    # ── Navigation ────────────────────────────────────────────────────
    _NAV_MAP = {"chat": 0, "notes": 1, "workshop": 2}

    def _on_nav_changed(self, key: str):
        index = self._NAV_MAP.get(key, 0)
        self._win._switch_view(index)

    def set_active_view(self, index: int):
        keys = list(self._NAV_MAP.keys())
        if 0 <= index < len(keys):
            self._nav.setCurrentItem(keys[index])
        # Sidebar toggle only makes sense on chat view
        self._toggle_btn.setVisible(index == 0)

    # ── Drag + right-click ────────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.globalPosition().toPoint())
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._win.isMaximized():
                if self._win._snap_mgr is not None:
                    self._win._snap_mgr.cancel_animation()
                handle = self._win.windowHandle()
                if handle:
                    handle.startSystemMove()

    def _show_context_menu(self, global_pos):
        menu = ContextMenu(parent=self)

        menu.addAction(Action(FluentIcon.CLIPPING_TOOL, "截图", triggered=self._win._start_screenshot))
        menu.addAction(Action(FluentIcon.SETTING, "设置", triggered=self._win._open_settings))
        menu.addSeparator()

        is_top = bool(self._win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        top_act = Action(FluentIcon.PIN if not is_top else FluentIcon.UNPIN, "始终置顶")
        top_act.setCheckable(True)
        top_act.setChecked(is_top)
        top_act.triggered.connect(lambda: self._toggle_always_on_top(is_top))
        menu.addAction(top_act)

        menu.addAction(Action(FluentIcon.MINIMIZE, "最小化到托盘", triggered=self._win._hide_to_tray))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.CLOSE, "退出", triggered=self._win._on_quit))

        menu.exec(global_pos)

    def _toggle_always_on_top(self, currently_on_top: bool):
        if not currently_on_top:
            # 只有窗口宽度小于屏幕一半时才允许置顶
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen and self._win.width() >= screen.availableGeometry().width() // 2:
                return
        self._win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not currently_on_top)
        self._win.show()
    def mouseDoubleClickEvent(self, e: QMouseEvent):
        """双击标题栏切换最大化/还原"""
        if e.button() == Qt.MouseButton.LeftButton:
            self._win._toggle_maximize()
            e.accept()
