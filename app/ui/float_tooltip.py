"""划词浮标专用的自建 tooltip。

Qt 原生 setToolTip 在不抢焦点的浮标窗口（Tool + WS_EX_NOACTIVATE +
WA_ShowWithoutActivating）上常不触发，故自绘一个同样不抢焦点的无边框
QLabel：hover 进按钮后延迟显示在按钮下方，移出即隐藏。

约束与浮标一致：绝不抢焦点，否则源应用选区被清、取词失败。Windows 上同样
在 showEvent 用 ctypes 加 WS_EX_NOACTIVATE，并设 WA_TransparentForMouseEvents
避免拦截点击。
"""
from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import QLabel

from app.ui import style

logger = logging.getLogger(__name__)

# hover 多久后才显示 tooltip（ms）。
_SHOW_DELAY_MS = 400
# tooltip 与按钮之间的竖直间距（px）。
_GAP_PX = 4

_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


def _build_style(theme: dict) -> str:
    return f"""
    QLabel {{
        background: {theme["surface_solid"]};
        color: {theme["text"]};
        border: 1px solid {theme["border_solid"]};
        border-radius: 4px;
        padding: 3px 7px;
        font-size: 12px;
    }}
    """


class FloatTooltip(QLabel):
    """不抢焦点的浮动 tooltip，配合 TextActionPopup 的按钮使用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._pending_text = ""
        self._anchor_global = QPoint(0, 0)
        self._anchor_height = 0

    def schedule(self, text: str, btn_global_topleft: QPoint, btn_height: int):
        """安排在延迟后于按钮下方显示 tooltip。"""
        if not text:
            return
        self._pending_text = text
        self._anchor_global = btn_global_topleft
        self._anchor_height = btn_height
        self._timer.start(_SHOW_DELAY_MS)

    def cancel(self):
        """取消未显示的 tooltip 并隐藏已显示的。"""
        self._timer.stop()
        self.hide()

    def _on_timeout(self):
        theme = style.get_current_theme()
        self.setStyleSheet(_build_style(theme))
        self.setText(self._pending_text)
        self.adjustSize()
        x = self._anchor_global.x()
        y = self._anchor_global.y() + self._anchor_height + _GAP_PX
        self.move(x, y)
        self.show()
        self.raise_()

    def showEvent(self, event):
        super().showEvent(event)
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
            logger.warning("FloatTooltip: WS_EX_NOACTIVATE 设置失败", exc_info=True)
