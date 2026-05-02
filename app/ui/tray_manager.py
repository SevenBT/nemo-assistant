from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    """Generate a simple colored circle icon (no external file needed)."""
    pix = QPixmap(32, 32)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#89b4fa"))
    painter.setPen(QColor("#1e1e2e"))
    painter.drawEllipse(2, 2, 28, 28)
    painter.setPen(QColor("#1e1e2e"))
    painter.setFont(painter.font())
    painter.end()
    return QIcon(pix)


class TrayManager(QObject):
    show_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(_make_icon())
        self._tray.setToolTip("AI Agent")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _build_menu(self):
        self._menu = QMenu()
        menu = self._menu
        show_act = QAction("显示窗口", menu)
        show_act.triggered.connect(self.show_requested)
        menu.addAction(show_act)

        settings_act = QAction("设置", menu)
        settings_act.triggered.connect(self.settings_requested)
        menu.addAction(settings_act)

        menu.addSeparator()

        quit_act = QAction("退出", menu)
        quit_act.triggered.connect(self.quit_requested)
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

    def notify(self, title: str, message: str):
        self._tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 4000
        )
