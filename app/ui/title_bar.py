"""TitleBar widget for the frameless floating window.

Extracted from main_window.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QMenu, QPushButton, QWidget

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


class TitleBar(QWidget):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._win = window
        self.setObjectName("titleBar")
        self.setFixedHeight(42)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)

        # Session panel toggle button
        self._toggle_btn = QPushButton("☰")
        self._toggle_btn.setObjectName("toggleBtn")
        self._toggle_btn.setFixedSize(64, 36)
        self._toggle_btn.setToolTip("显示/隐藏会话列表")
        self._toggle_btn.clicked.connect(self._win._toggle_session_panel)
        layout.addWidget(self._toggle_btn)

        layout.addStretch()

        # View-switcher buttons (exclusive, checkable)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for i, (text, tip) in enumerate([
            ("聊天", "AI 对话"),
            ("笔记", "笔记管理"),
            ("定时", "定时任务"),
        ]):
            btn = QPushButton(text)
            btn.setObjectName("viewBtn")
            btn.setFixedSize(56, 30)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            self._btn_group.addButton(btn, i)
            layout.addWidget(btn)
        self._btn_group.button(0).setChecked(True)
        self._btn_group.idClicked.connect(self._win._switch_view)

        snap_btn = QPushButton("截图")
        snap_btn.setObjectName("iconBtn")
        snap_btn.setFixedSize(44, 28)
        snap_btn.setToolTip("截图")
        snap_btn.clicked.connect(self._win._start_screenshot)
        layout.addWidget(snap_btn)

        min_btn = QPushButton("─")
        min_btn.setObjectName("iconBtn")
        min_btn.setFixedSize(32, 28)
        min_btn.setToolTip("最小化到托盘")
        min_btn.clicked.connect(self._win._minimize)
        layout.addWidget(min_btn)

        max_btn = QPushButton("⬜")
        max_btn.setObjectName("iconBtn")
        max_btn.setFixedSize(32, 28)
        max_btn.setToolTip("最大化/还原")
        max_btn.clicked.connect(self._win._toggle_maximize)
        layout.addWidget(max_btn)

        # × hides to tray; real quit is in the tray menu
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(32, 28)
        close_btn.setToolTip("最小化到托盘 (从托盘右键退出)")
        close_btn.clicked.connect(self._win._minimize)
        layout.addWidget(close_btn)

    def set_active_view(self, index: int):
        self._btn_group.button(index).setChecked(True)
        # Session panel toggle only makes sense on chat view
        self._toggle_btn.setVisible(index == 0)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.globalPosition().toPoint())
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            # 最大化状态下不在单击时还原，避免双击最大化后单击立即缩小
            # 还原操作统一由双击 mouseDoubleClickEvent 触发
            if not self._win.isMaximized():
                if self._win._snap_mgr is not None:
                    self._win._snap_mgr.cancel_animation()
                handle = self._win.windowHandle()
                if handle:
                    handle.startSystemMove()

    def _show_context_menu(self, global_pos):
        from PyQt6.QtCore import QPoint
        menu = QMenu(self)

        screenshot_act = menu.addAction("截图")
        settings_act = menu.addAction("设置")
        menu.addSeparator()

        is_top = bool(self._win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        top_act = menu.addAction("始终置顶")
        top_act.setCheckable(True)
        top_act.setChecked(is_top)

        minimize_act = menu.addAction("最小化到托盘")
        menu.addSeparator()
        quit_act = menu.addAction("退出")

        action = menu.exec(global_pos)
        if action == screenshot_act:
            self._win._start_screenshot()
        elif action == settings_act:
            self._win._open_settings()
        elif action == top_act:
            flags = self._win.windowFlags()
            if is_top:
                self._win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            else:
                self._win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self._win.show()
        elif action == minimize_act:
            self._win._minimize()
        elif action == quit_act:
            self._win._on_quit()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        """双击标题栏切换最大化/还原"""
        if e.button() == Qt.MouseButton.LeftButton:
            self._win._toggle_maximize()
            e.accept()
