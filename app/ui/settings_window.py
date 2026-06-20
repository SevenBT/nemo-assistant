"""
Settings window — PyCharm-style left nav + right stacked pages.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import cfg


class SettingsWindow(QDialog):
    """Main settings dialog with left navigation and right content area."""

    _PAGES = [
        ("外观", "appearance"),
        ("编辑器", "editor"),
        ("API 连接", "api"),
        ("工具", "tools"),
        ("快捷键", "hotkeys"),
        ("窗口", "window"),
        ("划词", "selection"),
        ("归档会话", "archived"),
    ]

    def __init__(
        self,
        hotkey_mgr=None,
        registry=None,
        session_mgr=None,
        on_sessions_changed=None,
        parent=None,
    ):
        super().__init__(parent)
        self._hotkey_mgr = hotkey_mgr
        self._registry = registry
        self._session_mgr = session_mgr
        self._on_sessions_changed = on_sessions_changed
        self.setWindowTitle("设置")
        self.setMinimumSize(640, 480)
        self.resize(cfg.get(cfg.settingsWidth), cfg.get(cfg.settingsHeight))
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        body = QHBoxLayout()

        # Left nav
        self._nav = QListWidget()
        self._nav.setFixedWidth(140)
        self._nav.setSpacing(2)
        for label, _ in self._PAGES:
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().__class__(140, 36))
            self._nav.addItem(item)

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        body.addWidget(self._nav)

        # Right content
        self._stack = QStackedWidget()
        self._create_pages()
        body.addWidget(self._stack)

        root.addLayout(body)

        # Bottom buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Select last used page
        self._nav.setCurrentRow(cfg.get(cfg.settingsPage))

    def _create_pages(self):
        from app.ui.settings_pages.appearance_page import AppearancePage
        from app.ui.settings_pages.editor_page import EditorPage
        from app.ui.settings_pages.api_page import ApiPage
        from app.ui.settings_pages.tools_page import ToolsPage
        from app.ui.settings_pages.hotkeys_page import HotkeysPage
        from app.ui.settings_pages.window_page import WindowPage
        from app.ui.settings_pages.selection_page import SelectionPage
        from app.ui.settings_pages.archived_page import ArchivedPage

        self._stack.addWidget(AppearancePage(self))
        self._stack.addWidget(EditorPage(self))
        self._stack.addWidget(ApiPage(self))
        self._stack.addWidget(ToolsPage(self._registry, self))
        self._stack.addWidget(HotkeysPage(self._hotkey_mgr, self))
        self._stack.addWidget(WindowPage(self))
        self._selection_page = SelectionPage(self)
        self._stack.addWidget(self._selection_page)
        self._stack.addWidget(
            ArchivedPage(self._session_mgr, self._on_sessions_changed, self)
        )

    def _on_nav_changed(self, index: int):
        self._stack.setCurrentIndex(index)

    def accept(self):
        self._selection_page.save()
        cfg.save()
        super().accept()

    def closeEvent(self, event):
        self._selection_page.save()
        cfg.set(cfg.settingsWidth, self.width())
        cfg.set(cfg.settingsHeight, self.height())
        cfg.set(cfg.settingsPage, self._nav.currentRow())
        cfg.save()
        super().closeEvent(event)
