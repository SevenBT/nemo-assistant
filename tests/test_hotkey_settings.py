"""Hotkey edits must be applied when leaving settings without changing pages."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QWidget

from app.core.config import DEFAULT_HOTKEYS
import app.ui.settings_window as settings_window
import app.ui.settings_pages.hotkeys_page as hotkeys_page


class _Config:
    hotkeyScreenshot = "screenshot"
    hotkeyNewNote = "new_note"
    hotkeyToggleWindow = "toggle_window"
    hotkeyQuickAsk = "quick_ask"
    hotkeySelection = "selection"
    hotkeyBindings = "bindings"
    selectionActions = "selection_actions"
    settingsWidth = "width"
    settingsHeight = "height"
    settingsPage = "page"

    def __init__(self):
        self.values = {
            **DEFAULT_HOTKEYS,
            "screenshot": "ctrl+alt+s",
            "width": 640,
            "height": 480,
            "page": 4,
            "bindings": {},
            "selection_actions": None,
        }
        self.saved = None

    def get(self, item):
        return self.values[item]

    def set(self, item, value):
        self.values[item] = value

    def save(self):
        self.saved = self.values.copy()


@pytest.fixture
def settings(qapp, monkeypatch):
    config = _Config()
    monkeypatch.setattr(settings_window, "cfg", config)
    monkeypatch.setattr(hotkeys_page, "cfg", config)
    manager = SimpleNamespace(stop=Mock(), failed_actions=[])
    registrations = []
    manager.reload = lambda: registrations.append(config.get(config.hotkeyScreenshot))

    def create_pages(window):
        # Keep the actual hotkey page and adapter; unrelated pages need no services.
        window._api_page = SimpleNamespace(save=Mock())
        window._selection_page = SimpleNamespace(save=Mock())
        for _ in range(4):
            window._stack.addWidget(QWidget(window))
        window._hotkeys_page = hotkeys_page.HotkeysPage(manager, window)
        window._stack.addWidget(window._hotkeys_page)
        for _ in range(len(window._PAGES) - 5):
            window._stack.addWidget(QWidget(window))

    monkeypatch.setattr(settings_window.SettingsWindow, "_create_pages", create_pages)
    window = settings_window.SettingsWindow(hotkey_mgr=manager)
    yield window, config, registrations
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("exit_action", ["accept", "close"])
@pytest.mark.parametrize("reset", [False, True], ids=["record", "restore-default"])
def test_hotkeys_saved_without_switching_pages(settings, exit_action, reset):
    window, config, registrations = settings
    widget = window._hotkeys_page._widget
    row = widget._rows[0]
    if reset:
        widget._reset_defaults()
        expected = DEFAULT_HOTKEYS["screenshot"]
    else:
        expected = "ctrl+shift+f9"
        # Simulate completion of the recorder without installing system hooks.
        row._capturing = True
        row._on_captured(expected)

    assert row.current_combo == expected
    assert config.get(config.hotkeyScreenshot) == "ctrl+alt+s"
    if exit_action == "accept":
        window.accept()
    else:
        window.closeEvent(QCloseEvent())

    assert config.get(config.hotkeyScreenshot) == expected
    assert config.saved[config.hotkeyScreenshot] == expected
    assert registrations[-1] == expected


def test_switching_pages_still_applies_hotkeys(settings):
    window, config, registrations = settings
    window._hotkeys_page._widget._rows[0].reset_combo("ctrl+shift+f9")

    window._nav.setCurrentRow(0)

    assert config.get(config.hotkeyScreenshot) == "ctrl+shift+f9"
    assert registrations[-1] == "ctrl+shift+f9"
