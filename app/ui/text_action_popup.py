"""划词浮标 — 选区下方弹出的一排紧凑图标按钮。

与截图工具栏（screenshot_overlay.py）共享深色圆角视觉。两种触发路径
共用同一个弹窗：
  - 划词浮标：鼠标拖选后在选区下方弹出
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

—— 交互规则 ——
- 显示后任意左/右键点击浮标以外区域 → 立即消失
- 点击浮标背景（非按钮区域）→ 立即消失
- 鼠标移入重置自动消失计时（2s），移出重新倒计时
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
)

from app.ui.text_actions import TEXT_ACTIONS

logger = logging.getLogger(__name__)

try:
    import mouse as _mouse

    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False

# 紧凑无文字浮标：图标 15px，内边距 3px 起。
_POPUP_STYLE = """
    #textActionBar {
        background: #2D2D2D;
        border-radius: 6px;
        border: 1px solid #3D3D3D;
    }
    #textActionBar QPushButton {
        background: transparent;
        border: none;
        color: #FFFFFF;
        font-size: 15px;
        padding: 3px 5px;
        border-radius: 4px;
        min-width: 26px;
        min-height: 26px;
    }
    #textActionBar QPushButton:hover {
        background: #3D3D3D;
    }
"""

# 浮标与选区之间的间距（px）。
_GAP_PX = 4

# 鼠标移开后自动消失的延迟（ms）。
_AUTO_HIDE_MS = 2000

# Win32 扩展样式常量（用于 WS_EX_NOACTIVATE，让窗口点击不抢焦点）。
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


class TextActionPopup(QFrame):
    """无边框、不抢焦点的划词动作条。"""

    action_chosen = pyqtSignal(str)  # 选中的动作 key
    _hide_requested = pyqtSignal()   # 内部：从 mouse hook 线程请求关闭

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_geo: QRect | None = None
        self._mouse_hook: Callable | None = None
        self._build_window()
        self._build_buttons()
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)
        self._hide_requested.connect(self._on_hide_requested)

    # ── 窗口设置 ────────────────────────────────────────────────────────

    def _build_window(self):
        self.setObjectName("textActionBar")
        self.setStyleSheet(_POPUP_STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
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
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(1)
        for action in TEXT_ACTIONS:
            btn = QPushButton(action.icon)
            btn.setToolTip(action.label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked, k=action.key: self._on_clicked(k)
            )
            row.addWidget(btn)

    # ── Win32 防激活 ────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_no_activate()
        self._install_click_watcher()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._remove_click_watcher()

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
            logger.warning(
                "WS_EX_NOACTIVATE 设置失败，弹窗点击可能抢夺焦点",
                exc_info=True,
            )

    # ── 全局点击监听（mouse hook 线程 → pyqtSignal → 主线程） ──────────

    def _on_hide_requested(self):
        """主线程 slot：收到 hook 线程的关闭请求后执行实际 hide。"""
        self.hide()

    def _install_click_watcher(self):
        """安装全局 mouse hook，监听弹窗外的点击以便立即关闭。"""
        if not _MOUSE_OK:
            return
        if self._mouse_hook is not None:
            return
        try:
            self._mouse_hook = _mouse.hook(self._on_global_event)
        except Exception:
            logger.warning("mouse hook 安装失败，点击弹窗外部将无法关闭",
                           exc_info=True)

    def _remove_click_watcher(self):
        if self._mouse_hook is None:
            return
        try:
            _mouse.unhook(self._mouse_hook)
        except Exception:
            logger.warning("mouse hook 卸载失败", exc_info=True)
            return  # 保留引用，避免下次 show 时重复安装导致泄漏
        self._mouse_hook = None

    def _on_global_event(self, event):
        """mouse hook 回调（在 hook 线程执行）。

        右键任意位置 → 立即关闭。
        左键点弹窗以外区域 → 关闭；点在弹窗内（按钮 / 背景）→ 不干涉，
        由 Qt 事件循环在主线处理：按钮 clicked → _on_clicked → hide，
        背景 mousePressEvent → hide。
        """
        event_type = getattr(event, "event_type", None)
        if event_type != "down":
            return
        button = getattr(event, "button", None)
        if button == _mouse.RIGHT:
            self._hide_requested.emit()
            return
        if button == _mouse.LEFT:
            geo = self._cached_geo  # 抓本地引用，避免跨线程竞争
            if geo is not None:
                x, y = _mouse.get_position()
                if not geo.contains(x, y):
                    self._hide_requested.emit()

    # ── 动作处理 ────────────────────────────────────────────────────────

    def _on_clicked(self, key: str):
        self._auto_hide.stop()
        self.hide()
        self.action_chosen.emit(key)

    def mousePressEvent(self, event):
        """点击浮标背景（非按钮区域）立即关闭；按钮有其自己的 clicked 处理。"""
        super().mousePressEvent(event)
        self.hide()

    # ── 定位 ────────────────────────────────────────────────────────────

    def show_at(self, x: int, y: int):
        """在屏幕坐标紧贴选区下方弹出。

        Args:
            x: 选区末行水平中心（UIA 路径），或鼠标 X（热键回退路径）。
            y: 选区底边（UIA 路径），或鼠标 Y（热键回退路径）。

        浮标居中对齐 x，顶边紧贴 y 下方 _GAP_PX 处。
        屏幕底边空间不足时自动翻到选区上方，左右超屏则贴边。
        """
        self.adjustSize()
        w, h = self.width(), self.height()
        px = x - w // 2         # 水平居中
        py = y + _GAP_PX        # 紧贴选区下方

        # ★ 用目标坐标查屏幕，不能用 mapToGlobal(self.rect().center())——
        # 此时弹窗尚未 move，其当前全局位置是 show 前残留的旧位置，
        # 用旧位置 screenAt 可能拿到错误的屏幕 → wrong availableGeometry
        # → 边缘修正把弹窗推到奇怪位置（表现就是「位置随机」）。
        screen = QApplication.screenAt(QPoint(px + w // 2, py)) \
            or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            if px + w > geo.right():
                px = geo.right() - w
            if px < geo.left():
                px = geo.left()
            if py + h > geo.bottom():
                py = y - h - _GAP_PX  # 翻到选区上方
            if py < geo.top():
                py = geo.top()

        self._cached_geo = QRect(px, py, w, h)
        self.move(px, py)
        self.show()
        self.raise_()
        self._auto_hide.start(_AUTO_HIDE_MS)

    # ── 鼠标悬停计时 ────────────────────────────────────────────────────

    def leaveEvent(self, event):
        self._auto_hide.start(_AUTO_HIDE_MS)
        super().leaveEvent(event)

    def enterEvent(self, event):
        self._auto_hide.stop()
        super().enterEvent(event)
