"""Screenshot workflow controller for the main window."""

from PyQt6.QtCore import QObject, QPoint, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget

from app.ui.pin_window import PinWindow
from app.ui.screenshot_overlay import ScreenshotOverlay


class ScreenshotController(QObject):
    """Owns screenshot overlay state and post-capture actions."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._overlay: ScreenshotOverlay | None = None
        self._pin_windows: list[PinWindow] = []

    def start(self):
        if self._overlay is not None:
            return
        self._window.hide()
        QTimer.singleShot(200, self._show_overlay)

    def _show_overlay(self):
        self._overlay = ScreenshotOverlay()
        self._overlay.captured.connect(self._on_done)
        self._overlay.show()
        self._overlay.activateWindow()

    def _on_done(self, pixmap: QPixmap, action: str, ocr_text: str, pos: QPoint):
        self._overlay = None
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

        if action == "cancel":
            return
        if action == "ocr":
            if ocr_text:
                QApplication.clipboard().setText(ocr_text)
            return
        if pixmap.isNull():
            return

        if action == "pin":
            self._pin_screenshot(pixmap, pos)
        elif action == "copy":
            QApplication.clipboard().setPixmap(pixmap)
        elif action == "save":
            self._save_screenshot(pixmap)

    def _pin_screenshot(self, pixmap: QPixmap, pos: QPoint):
        win = PinWindow(pixmap, pos=pos)
        win.show()
        self._pin_windows.append(win)
        win.closed.connect(
            lambda w=win: self._pin_windows.remove(w)
            if w in self._pin_windows
            else None
        )

    def _save_screenshot(self, pixmap: QPixmap):
        path, _ = QFileDialog.getSaveFileName(
            self._window,
            "保存截图",
            "screenshot.png",
            "PNG (*.png)",
        )
        if path:
            pixmap.save(path, "PNG")
