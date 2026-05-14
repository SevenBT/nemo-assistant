"""Test: verify DWM border fix and shadow effect impact on RoundMenu."""
import sys
import ctypes
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QColor
from qfluentwidgets import RoundMenu, Action, FluentIcon, setTheme, Theme

app = QApplication(sys.argv)
setTheme(Theme.LIGHT)

w = QWidget()
w.setWindowTitle('Menu Test')
w.resize(400, 200)

def show_menu_normal():
    """Normal RoundMenu - should show the 'two windows' issue."""
    menu = RoundMenu(parent=w)
    menu.addAction(Action(FluentIcon.SETTING, 'Normal Menu'))
    menu.addAction(Action(FluentIcon.CLOSE, 'Item 2'))
    print('\n--- Normal RoundMenu ---')
    menu.exec(w.mapToGlobal(QPoint(50, 50)))

def show_menu_no_shadow():
    """RoundMenu without shadow effect."""
    menu = RoundMenu(parent=w)
    menu.addAction(Action(FluentIcon.SETTING, 'No Shadow'))
    menu.addAction(Action(FluentIcon.CLOSE, 'Item 2'))
    # Remove shadow and reduce margins
    menu.view.setGraphicsEffect(None)
    menu.layout().setContentsMargins(4, 4, 4, 4)
    print('\n--- RoundMenu without shadow ---')
    menu.exec(w.mapToGlobal(QPoint(150, 50)))

def show_menu_dwm_fix():
    """RoundMenu with DWM border removal applied via showEvent override."""
    class FixedMenu(RoundMenu):
        def showEvent(self, event):
            super().showEvent(event)
            try:
                hwnd = int(self.winId())
                print(f'  HWND: {hwnd} (0x{hwnd:X})')
                if hwnd:
                    dwmapi = ctypes.windll.dwmapi
                    # Remove border
                    color_none = ctypes.c_uint(0xFFFFFFFE)
                    r1 = dwmapi.DwmSetWindowAttribute(
                        hwnd, 34, ctypes.byref(color_none), ctypes.sizeof(color_none))
                    print(f'  DWMWA_BORDER_COLOR result: {r1}')
                    # Don't round corners at system level
                    corner = ctypes.c_int(1)
                    r2 = dwmapi.DwmSetWindowAttribute(
                        hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
                    print(f'  DWMWA_CORNER_PREFERENCE result: {r2}')
            except Exception as e:
                print(f'  DWM fix error: {e}')

    menu = FixedMenu(parent=w)
    menu.addAction(Action(FluentIcon.SETTING, 'DWM Fixed'))
    menu.addAction(Action(FluentIcon.CLOSE, 'Item 2'))
    print('\n--- RoundMenu with DWM fix ---')
    menu.exec(w.mapToGlobal(QPoint(250, 50)))

btn1 = QPushButton('Normal')
btn1.clicked.connect(show_menu_normal)
btn2 = QPushButton('No Shadow')
btn2.clicked.connect(show_menu_no_shadow)
btn3 = QPushButton('DWM Fix')
btn3.clicked.connect(show_menu_dwm_fix)

layout = QVBoxLayout(w)
layout.addWidget(btn1)
layout.addWidget(btn2)
layout.addWidget(btn3)
w.show()

# Auto-test sequence
QTimer.singleShot(500, show_menu_normal)
QTimer.singleShot(2000, show_menu_no_shadow)
QTimer.singleShot(4000, show_menu_dwm_fix)
QTimer.singleShot(7000, app.quit)
app.exec()
