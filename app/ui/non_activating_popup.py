"""不抢焦点的浮窗基础设施 —— 划词浮标 / 结果气泡 / tooltip 共用。

划词相关的所有浮窗都有一条铁律：**绝不能抢前台焦点**。一旦焦点被夺走，
源应用（浏览器/Word）的选区就清空了，随后的 Ctrl+C 取词必然失败。

只设 WA_ShowWithoutActivating 不够（它只管 show 时不激活，不管点击）。
Windows 上必须再给窗口加 WS_EX_NOACTIVATE 扩展样式：这样点击其上的控件
也不会把前台焦点从源应用夺走（屏幕键盘、工具提示都靠这个）。按 CLAUDE.md
经验，此类 Win32 样式必须在 showEvent 里用 ctypes 设置才稳。

本模块把这套机制收口到一处：
  - ``apply_no_activate(widget)``：在 showEvent 中调用的自由函数，供 QLabel
    等不便继承基类的控件直接使用（如 FloatTooltip）。
  - ``NonActivatingPopup``：QFrame 基类，统一窗口标志与不激活属性，子类只需
    继承即可获得正确的焦点行为。
"""
from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QWidget

logger = logging.getLogger(__name__)

# Win32 扩展样式常量（用于 WS_EX_NOACTIVATE，让窗口点击不抢焦点）。
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

# 不抢焦点浮窗统一的窗口标志：工具窗、无边框、置顶、无投影。
NO_ACTIVATE_WINDOW_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.NoDropShadowWindowHint
)


def apply_no_activate(widget: QWidget) -> None:
    """给窗口加 WS_EX_NOACTIVATE，使点击其上控件也不抢前台焦点。

    必须在 widget 已有原生句柄后调用（即 showEvent 内），否则 winId() 拿不到
    有效 hwnd。非 Windows 平台直接返回。失败仅记日志、不抛出——抢焦点是体验
    问题，不该让浮窗崩掉。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_NOACTIVATE)
    except Exception:
        logger.warning(
            "%s: WS_EX_NOACTIVATE 设置失败，弹窗点击可能抢夺焦点",
            type(widget).__name__,
            exc_info=True,
        )


class NonActivatingPopup(QFrame):
    """不抢焦点、无边框、置顶的浮窗基类。

    统一了三件事，子类继承即获得正确焦点行为，无需各自重复：
      - 窗口标志（NO_ACTIVATE_WINDOW_FLAGS）
      - WA_ShowWithoutActivating（show 时不激活）
      - WA_TranslucentBackground（透明背景，配合圆角自绘）
      - showEvent 中调 apply_no_activate（WS_EX_NOACTIVATE）

    子类如需额外属性（如自绘背景的 WA_StyledBackground）可在自身 __init__
    里追加；如需在 show 时做额外工作（如安装点击监听），重写 showEvent 时
    务必先调 ``super().showEvent(event)`` 以保证不激活样式先生效。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(NO_ACTIVATE_WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def showEvent(self, event):
        super().showEvent(event)
        apply_no_activate(self)
