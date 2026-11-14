"""快捷键设置页 — 包装现有 HotkeySettingsWidget"""

from PyQt6.QtWidgets import QVBoxLayout, QScrollArea, QWidget

from app.config.config import cfg
from app.desktop.hotkey_actions import get_hotkey_actions, read_hotkeys, write_hotkeys
from app.ui.hotkey_settings_widget import HotkeySettingsWidget


class _HotkeyConfigAdapter:
    """Adapter to make HotkeySettingsWidget work with new cfg singleton."""

    @property
    def hotkeys(self) -> dict:
        return read_hotkeys(cfg)

    @property
    def actions(self):
        return get_hotkey_actions(cfg)

    def update_hotkeys(self, updates: dict) -> None:
        write_hotkeys(updates, cfg)


class HotkeysPage(QScrollArea):
    def __init__(self, hotkey_mgr=None, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        adapter = _HotkeyConfigAdapter()
        self._widget = HotkeySettingsWidget(adapter, hotkey_mgr)
        self.setWidget(self._widget)

    def save(self):
        self._widget.save()

    def showEvent(self, event):
        self._widget.refresh_actions()
        super().showEvent(event)
