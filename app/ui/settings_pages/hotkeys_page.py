"""快捷键设置页 — 包装现有 HotkeySettingsWidget"""

from PyQt6.QtWidgets import QVBoxLayout, QScrollArea, QWidget

from app.core.config import cfg
from app.ui.hotkey_settings_widget import HotkeySettingsWidget


class _HotkeyConfigAdapter:
    """Adapter to make HotkeySettingsWidget work with new cfg singleton."""

    @property
    def hotkeys(self) -> dict:
        return {
            "screenshot": cfg.get(cfg.hotkeyScreenshot),
            "new_note": cfg.get(cfg.hotkeyNewNote),
            "toggle_window": cfg.get(cfg.hotkeyToggleWindow),
            "quick_ask": cfg.get(cfg.hotkeyQuickAsk),
        }

    def update_hotkeys(self, updates: dict) -> None:
        _MAP = {
            "screenshot": cfg.hotkeyScreenshot,
            "new_note": cfg.hotkeyNewNote,
            "toggle_window": cfg.hotkeyToggleWindow,
            "quick_ask": cfg.hotkeyQuickAsk,
        }
        for action, combo in updates.items():
            if action in _MAP:
                cfg.set(_MAP[action], combo)


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
