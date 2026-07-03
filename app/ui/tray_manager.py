from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from app.core.config import ASSETS_DIR
from app.i18n import t

_ICON_PATH = str(ASSETS_DIR / "app_icon.png")


class TrayManager(QObject):
    show_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(QIcon(_ICON_PATH))
        self._tray.setToolTip("Nemo Assistant")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _build_menu(self):
        self._menu = QMenu()
        # Fixed style — tray menu should not follow app theme
        self._menu.setStyleSheet("""
            QMenu {
                background: #FFFFFF;
                color: #1E293B;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #F1F5F9;
            }
            QMenu::separator {
                height: 1px;
                background: #E2E8F0;
                margin: 4px 8px;
            }
        """)
        menu = self._menu
        show_act = QAction(t("tray.show"), menu)
        show_act.triggered.connect(self.show_requested)
        menu.addAction(show_act)

        snap_act = QAction(t("tray.screenshot"), menu)
        snap_act.triggered.connect(self.screenshot_requested)
        menu.addAction(snap_act)

        menu.addSeparator()

        settings_act = QAction(t("tray.settings"), menu)
        settings_act.triggered.connect(self.settings_requested)
        menu.addAction(settings_act)

        menu.addSeparator()

        quit_act = QAction(t("tray.quit"), menu)
        quit_act.triggered.connect(self.quit_requested)
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

