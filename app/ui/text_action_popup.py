"""划词浮标 — 光标附近弹出的一排动作按钮。

复刻截图工具栏（screenshot_overlay.py）的深色圆角视觉。两种触发路径
共用同一个弹窗：
  - 划词浮标：鼠标拖选后在光标附近弹出
  - 全局热键：在当前鼠标位置弹出

★ 关键约束：弹窗绝不能抢焦点——连「点击按钮」也不能。一旦焦点被夺走，
源应用（浏览器/Word）的选区就清空了，随后的 Ctrl+C 取不到文字。

只设 WA_ShowWithoutActivating 不够（它只管 show 时不激活，不管点击）。
必须在 Windows 上给窗口加 WS_EX_NOACTIVATE 扩展样式：这样点击其上的按钮
也不会把前台焦点从源应用夺走（屏幕键盘、工具提示都靠这个）。按 CLAUDE.md
经验，此类 Win32 样式在 showEvent 里用 ctypes 设置才稳。

正因为不抢焦点，取词才能延后到「点击按钮那一刻」——弹窗本身不碰剪贴板，
只有用户真要动作时才发一次 Ctrl+C，不打扰正常的复制粘贴。

按钮按下后只发 action_chosen(key) 信号，由调用方负责取词与分发。
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
)

from app.ui.text_actions import TEXT_ACTIONS

# 复用截图工具栏的深色调，保持视觉统一。
_POPUP_STYLE = """
    #textActionBar {
        background: #2D2D2D;
        border-radius: 8px;
        border: 1px solid #3D3D3D;
    }
    #textActionBar QPushButton {
        background: transparent;
        border: none;
        color: #FFFFFF;
        font-size: 13px;
        padding: 6px 12px;
        border-radius: 6px;
    }
    #textActionBar QPushButton:hover {
        background: #3D3D3D;
    }
"""

# 浮标相对光标的偏移：落在光标右下方，不挡住选中的文字。
_CURSOR_OFFSET_X = 12
_CURSOR_OFFSET_Y = 16

# 鼠标移开后自动消失的延迟（ms）。
_AUTO_HIDE_MS = 4000

# Win32 扩展样式常量（用于 WS_EX_NOACTIVATE，让窗口点击不抢焦点）。
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


class TextActionPopup(QFrame):
    """无边框、不抢焦点的划词动作条。"""

    action_chosen = pyqtSignal(str)  # 选中的动作 key

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_window()
        self._build_buttons()
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)

    def _build_window(self):
        self.setObjectName("textActionBar")
        self.setStyleSheet(_POPUP_STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # ★ 不抢焦点：保住源应用的选区。
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _build_buttons(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)
        for action in TEXT_ACTIONS:
            btn = QPushButton(f"{action.icon} {action.label}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked, k=action.key: self._on_clicked(k)
            )
            row.addWidget(btn)

    def showEvent(self, event):
        """应用 WS_EX_NOACTIVATE：点击窗口上的按钮也不夺走前台焦点。

        仅靠 WA_ShowWithoutActivating 只能保证 show() 时不激活，点击仍会抢焦点
        （导致随后的 Ctrl+C 发给本 app，取不到源应用选区）。WS_EX_NOACTIVATE
        让窗口自始至终不接受激活，源应用始终保持前台、选区不丢。

        按 CLAUDE.md 经验：Win32 扩展样式须在 showEvent 中用 ctypes 设置。
        """
        super().showEvent(event)
        self._apply_no_activate()

    def _apply_no_activate(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE, ex_style | _WS_EX_NOACTIVATE
            )
        except Exception:
            pass

    def _on_clicked(self, key: str):
        self._auto_hide.stop()
        self.hide()
        self.action_chosen.emit(key)

    def show_at(self, x: int, y: int):
        """在屏幕坐标 (x, y) 的右下方弹出，自动避开屏幕边缘。"""
        self.adjustSize()
        w, h = self.width(), self.height()
        px = x + _CURSOR_OFFSET_X
        py = y + _CURSOR_OFFSET_Y

        # 避免越出屏幕：超右则左移，超下则改到光标上方。
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center())) \
            or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        if px + w > geo.right():
            px = geo.right() - w
        if py + h > geo.bottom():
            py = y - _CURSOR_OFFSET_Y - h
        px = max(px, geo.left())
        py = max(py, geo.top())

        self.move(px, py)
        self.show()
        self.raise_()
        self._auto_hide.start(_AUTO_HIDE_MS)

    def leaveEvent(self, event):
        # 鼠标移出后开始倒计时关闭（给用户移回的机会）。
        self._auto_hide.start(_AUTO_HIDE_MS)
        super().leaveEvent(event)

    def enterEvent(self, event):
        self._auto_hide.stop()
        super().enterEvent(event)
