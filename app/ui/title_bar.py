"""TitleBar widget for the frameless floating window.

Extracted from main_window.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

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
        if e.button() == Qt.MouseButton.LeftButton:
            if self._win._snap_mgr is not None:
                self._win._snap_mgr.cancel_animation()
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()
