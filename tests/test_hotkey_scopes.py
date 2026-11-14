"""Shortcut scope, persistence and pause/resume contracts (no OS hooks or AI)."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget

from app.core.hotkey_actions import (
    DEFAULT_HOTKEYS, LEGACY_ITEMS, get_hotkey_actions, normalize_combo,
    read_hotkeys, write_hotkeys,
)
from app.core.selection_actions_config import default_selection_actions
from app.core.selection_uia import SelectionStatus
import app.core.hotkey_manager as manager_module
import app.ui.selection_controller as selection_module
import app.ui.screenshot_overlay as screenshot_module
import app.ui.screenshot_controller as capture_module
import app.ui.settings_pages.hotkeys_page as page_module


class ShortcutConfig:
    hotkeyBindings = "bindings"
    selectionActions = "selection_actions"

    def __init__(self):
        self.values = {"bindings": {}, "selection_actions": default_selection_actions()}
        for action, attr in LEGACY_ITEMS.items():
            setattr(self, attr, action)
            self.values[action] = DEFAULT_HOTKEYS[action]

    def get(self, key):
        return self.values[key]

    def set(self, key, value):
        self.values[key] = value


class Keyboard:
    def __init__(self):
        self.bindings = {}
        self.counter = 0

    def add_hotkey(self, combo, callback, **kwargs):
        assert kwargs == {"suppress": False, "trigger_on_release": True}
        self.counter += 1
        self.bindings[self.counter] = (combo, callback)
        return self.counter

    def remove_hotkey(self, handle):
        del self.bindings[handle]

    def combos(self):
        return {combo for combo, _ in self.bindings.values()}

    def is_pressed(self, key):
        return False


@pytest.fixture
def shortcuts(qapp, monkeypatch):
    config = ShortcutConfig()
    keyboard = Keyboard()
    monkeypatch.setattr(manager_module, "_kb", keyboard)
    monkeypatch.setattr(manager_module, "_KB_OK", True)
    monkeypatch.setattr(manager_module, "read_hotkeys", lambda: read_hotkeys(config))
    monkeypatch.setattr(manager_module, "get_hotkey_actions", lambda: get_hotkey_actions(config))
    manager = manager_module.HotkeyManager()
    yield config, manager, keyboard
    manager.stop()


def test_legacy_keys_are_preserved_and_cleared_keys_stay_disabled(shortcuts):
    config, manager, keyboard = shortcuts
    config.values["screenshot"] = "ctrl+shift+f9"
    write_hotkeys({"new_note": "", "notes:new": "ctrl+alt+shift+n"}, config)
    manager.start()
    assert "ctrl+shift+f9" in keyboard.combos()
    assert DEFAULT_HOTKEYS["new_note"] not in keyboard.combos()
    assert "ctrl+alt+shift+n" in keyboard.combos()
    assert read_hotkeys(config)["new_note"] == ""


def test_built_in_actions_have_defaults_without_overriding_user_bindings(shortcuts):
    config, manager, keyboard = shortcuts
    bindings = read_hotkeys(config)
    assert all(bindings[key] == combo for key, combo in DEFAULT_HOTKEYS.items())
    config.values["new_note"] = "alt+ctrl+x"
    config.values["bindings"] = {"notes:new": "", "chat:new": "ctrl+shift+f9"}
    bindings = read_hotkeys(config)
    assert bindings["new_note"] == "alt+ctrl+x"
    assert bindings["selection:explain"] == ""  # A default cannot displace a user binding.
    assert bindings["notes:new"] == ""
    assert bindings["chat:new"] == "ctrl+shift+f9"
    assert bindings["screenshot:ocr"] == "ctrl+alt+o"
    assert bindings["selection:continue_explain"] == ""


def test_screenshot_actions_are_never_registered_globally(shortcuts):
    config, manager, keyboard = shortcuts
    write_hotkeys({"screenshot:ocr": "ctrl+alt+o", "selection:explain": "ctrl+alt+x"}, config)
    manager.start()
    assert "ctrl+alt+o" not in keyboard.combos()
    assert "ctrl+alt+x" in keyboard.combos()
    assert "ctrl+alt+a" in keyboard.combos()  # Global capture entrance.


def test_pause_keeps_recovery_key_and_nested_suspensions_reject_old_callbacks(shortcuts):
    config, manager, keyboard = shortcuts
    write_hotkeys({"system:pause": "ctrl+alt+shift+space"}, config)
    received = []
    manager.action_triggered.connect(received.append)
    manager.start()
    previous = list(keyboard.bindings.values())[0][1]
    manager.set_paused(True)
    assert keyboard.combos() == {"ctrl+alt+shift+space"}
    previous()
    assert received == []
    manager.suspend("screenshot")
    manager.suspend("recording")
    assert keyboard.combos() == set()
    manager.resume("recording")
    assert keyboard.combos() == set()
    manager.resume("screenshot")
    assert keyboard.combos() == {"ctrl+alt+shift+space"}
    next(iter(keyboard.bindings.values()))[1]()
    assert received == ["system:pause"]
    manager.set_paused(False)
    assert "ctrl+alt+a" in keyboard.combos()


def test_deleted_custom_selection_action_loses_executable_binding(shortcuts):
    config, manager, keyboard = shortcuts
    selection = config.values["selection_actions"]
    selection["custom"].append({"id": "custom:summary", "name": "Summary",
        "prompt": "Summarize {text}", "mode": "oneshot"})
    selection["order"].append("custom:summary")
    write_hotkeys({"selection:custom:summary": "ctrl+alt+u"}, config)
    manager.start()
    assert "ctrl+alt+u" in keyboard.combos()
    selection["custom"] = [a for a in selection["custom"] if a["id"] != "custom:summary"]
    manager.reload()
    assert "ctrl+alt+u" not in keyboard.combos()


def test_global_hooks_resume_only_after_capture_modifiers_are_released(shortcuts, monkeypatch):
    config, manager, keyboard = shortcuts
    manager.start()
    manager.suspend("screenshot")
    monkeypatch.setattr(keyboard, "is_pressed", lambda key: key == "ctrl")
    manager.resume("screenshot")
    assert keyboard.combos() == set()
    manager.reload()
    assert keyboard.combos() == set()
    monkeypatch.setattr(keyboard, "is_pressed", lambda _: False)
    manager._resume_when_released()
    assert "ctrl+alt+a" in keyboard.combos()


def test_settings_shortcut_uses_keyboard_comma_name(shortcuts):
    config, manager, keyboard = shortcuts
    write_hotkeys({"system:settings": "ctrl+alt+,"}, config)
    manager.start()
    assert "ctrl+alt+comma" in keyboard.combos()


def test_capture_entrance_is_single_and_native_close_restores_global_hooks(shortcuts, qtbot, monkeypatch):
    config, manager, keyboard = shortcuts
    overlays = []

    class Overlay(QObject):
        captured = pyqtSignal(QPixmap, str, str, QPoint)
        closed = pyqtSignal()

        def __init__(self, **kwargs):
            super().__init__()
            overlays.append(self)

        def show(self):
            pass

        def activateWindow(self):
            pass

    monkeypatch.setattr(capture_module, "ScreenshotOverlay", Overlay)
    window = QWidget()
    qtbot.addWidget(window)
    controller = capture_module.ScreenshotController(window, ocr_engine_service=Mock())
    controller.capture_state_changed.connect(
        lambda active: manager.suspend("screenshot") if active else manager.resume("screenshot"))
    manager.start()
    controller.start()
    controller.start()
    assert controller.active
    assert keyboard.combos() == set()
    qtbot.waitUntil(lambda: len(overlays) == 1)
    assert controller.active
    overlays[0].closed.emit()
    assert not controller.active
    assert "ctrl+alt+a" in keyboard.combos()


@pytest.fixture
def selection(qtbot, monkeypatch):
    window = QWidget()
    qtbot.addWidget(window)
    controller = selection_module.SelectionController(window, note_mgr=Mock())
    # Keep the real controller's dispatch, but replace all visible/AI effects.
    popup = controller._popup
    bubble = controller._bubble
    controller._popup = Mock()
    controller._bubble = Mock()
    monkeypatch.setattr(selection_module, "foreground_window", lambda: 123)
    capture = Mock(return_value="whole editor line without a selection")
    monkeypatch.setattr(selection_module, "capture_selection", capture)
    yield controller, capture
    popup.hide()
    bubble.cleanup()


@pytest.mark.parametrize("status", [SelectionStatus.EMPTY_SELECTION, SelectionStatus.NO_FOCUS,
    SelectionStatus.NO_TEXT_PATTERN, SelectionStatus.UNAVAILABLE])
def test_selection_shortcuts_without_confirmed_text_are_inert(selection, monkeypatch, status):
    controller, capture = selection
    controller._captured = "stale selection from another application"
    monkeypatch.setattr(selection_module.selection_uia, "query_selection_at_cursor", lambda: (status, ""))
    assert not controller.trigger_shortcut("explain")
    assert not controller.trigger_shortcut()
    controller._bubble.show_oneshot.assert_not_called()
    controller._popup.show_at.assert_not_called()
    controller._notes.create.assert_not_called()
    capture.assert_not_called()


def test_selection_shortcut_uses_fresh_text_without_clipboard(selection, monkeypatch):
    controller, capture = selection
    controller._captured = "stale text"
    monkeypatch.setattr(selection_module.selection_uia, "query_selection_at_cursor",
                        lambda: (SelectionStatus.HAS_TEXT, "current selected text"))
    assert controller.trigger_shortcut("explain")
    assert controller._bubble.show_oneshot.call_args.args[2:] == ("current selected text", "explain")
    capture.assert_not_called()


def test_selection_shortcut_rejects_selection_if_foreground_changes(selection, monkeypatch):
    controller, capture = selection
    identities = iter([123, 456])
    monkeypatch.setattr(selection_module, "foreground_window", lambda: next(identities))
    monkeypatch.setattr(selection_module.selection_uia, "query_selection_at_cursor",
                        lambda: (SelectionStatus.HAS_TEXT, "previous window text"))
    assert not controller.trigger_shortcut("note")
    controller._notes.create.assert_not_called()
    capture.assert_not_called()


def test_screenshot_shortcuts_only_fire_on_visible_selected_overlay(qtbot, monkeypatch):
    config = ShortcutConfig()
    write_hotkeys({"screenshot:ocr": "ctrl+alt+o"}, config)
    monkeypatch.setattr(screenshot_module, "read_hotkeys", lambda: read_hotkeys(config))
    monkeypatch.setattr(screenshot_module.ScreenshotOverlay, "_capture_frozen", lambda _: None)
    overlay = screenshot_module.ScreenshotOverlay(ocr_engine_service=Mock())
    qtbot.addWidget(overlay)
    action = Mock()
    monkeypatch.setattr(overlay, "_on_action", action)
    assert not overlay.trigger_shortcut("screenshot:ocr")
    overlay.show()
    assert not overlay.trigger_shortcut("screenshot:ocr")  # No selected region.
    overlay._start, overlay._end = QPoint(10, 10), QPoint(100, 100)
    overlay._state = "SELECTED"
    overlay.activateWindow()
    qtbot.waitUntil(overlay.isActiveWindow)
    qtbot.keyClick(overlay, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert action.call_args.args == ("ocr",)
    action.reset_mock()
    overlay._state = "OCR_EDIT"
    assert not overlay.trigger_shortcut("screenshot:ocr")
    overlay._state = "SELECTED"
    overlay.hide()
    assert not overlay.trigger_shortcut("screenshot:ocr")
    action.assert_not_called()


def test_settings_scope_conflicts_and_clearing(shortcuts, qtbot, monkeypatch):
    config, manager, keyboard = shortcuts
    monkeypatch.setattr(page_module, "cfg", config)
    page = page_module.HotkeysPage(manager)
    qtbot.addWidget(page)
    widget = page._widget
    rows = {row.action: row for row in widget._rows}
    rows["new_note"].reset_combo("alt+ctrl+n")
    assert widget._find_conflict("selection:explain", "Control+Alt+N")
    assert widget._find_conflict("screenshot:ocr", "Control+Alt+N") is None
    rows["new_note"]._clear_combo()
    widget.save()
    manager.start()
    assert "ctrl+alt+n" not in keyboard.combos()
    widget._pivot.setCurrentItem("screenshot")
    rows["screenshot:ocr"]._clear_combo()
    widget._reset_defaults("screenshot")
    widget.save()
    assert read_hotkeys(config)["screenshot:ocr"] == "ctrl+alt+o"
    assert "ctrl+alt+o" not in keyboard.combos()
    widget._search.setText("OCR")
    assert not widget._containers["screenshot:ocr"].isHidden()
    assert widget._containers["new_note"].isHidden()
    rows["toggle_window"].reset_combo("ctrl+alt+shift+space")
    rows["system:pause"].reset_combo("ctrl+alt+space")
    widget._reset_defaults("system")
    assert rows["toggle_window"].current_combo == DEFAULT_HOTKEYS["toggle_window"]
    assert rows["system:pause"].current_combo == DEFAULT_HOTKEYS["system:pause"]


def test_recorder_uses_only_local_qt_events_and_cancels_cleanly(shortcuts, qtbot, monkeypatch):
    config, manager, keyboard = shortcuts
    monkeypatch.setattr(page_module, "cfg", config)
    page = page_module.HotkeysPage(manager)
    qtbot.addWidget(page)
    page.show()
    page._widget._pivot.setCurrentItem("screenshot")
    row = page._widget._rows[0]
    manager.start()
    row._on_modify()
    assert keyboard.combos() == set()
    qtbot.keyClick(row, Qt.Key.Key_F8, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert row.current_combo == "ctrl+shift+f8"
    assert not row._capturing
    assert keyboard.combos()
    row._on_modify()
    qtbot.keyClick(row, Qt.Key.Key_Escape)
    assert row.current_combo == "ctrl+shift+f8"
    assert not row._capturing
    assert keyboard.combos()
