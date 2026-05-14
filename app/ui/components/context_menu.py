"""Context menu that removes the Windows 11 system border on popup."""
import ctypes
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import RoundMenu


class ContextMenu(RoundMenu):
    """RoundMenu subclass that suppresses the Windows 11 rectangular system border."""

    def __init__(self, title="", parent: QWidget | None = None):
        super().__init__(title, parent)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            self._remove_system_border()

    def _remove_system_border(self):
        """Remove the Windows 11 DWM border that creates a 'two windows' look."""
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            dwmapi = ctypes.windll.dwmapi
            # DWMWA_BORDER_COLOR = 34, DWMWA_COLOR_NONE = 0xFFFFFFFE
            color_none = ctypes.c_uint(0xFFFFFFFE)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(color_none), ctypes.sizeof(color_none)
            )
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_DONOTROUND = 1
            corner_pref = ctypes.c_int(1)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref)
            )
        except Exception:
            pass
