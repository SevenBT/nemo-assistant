"""Selection action persistence, user ordering, UI and replacement boundaries."""
from copy import deepcopy
import json
import time

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QWidget
from qfluentwidgets import FluentIcon

from app.config.config import cfg
from app.config.config_migrate import _migrate_selection_actions
from app.desktop.selection_actions_config import (
    BUILTIN_IDS, DEFAULT_ORDER, default_selection_actions, normalize_selection_actions,
)
from app.i18n import t
from app.ui.selection_icons import selection_icon
from app.ui.text_actions import get_active_text_actions, get_all_text_actions, get_text_action


@pytest.fixture
def actions_config(monkeypatch):
    old = deepcopy(cfg.get(cfg.selectionActions))
    old_prompt = cfg.get(cfg.selectionExplainPrompt)
    monkeypatch.setattr(cfg, "save", lambda: None)
    cfg.set(cfg.selectionActions, default_selection_actions(), save=False)
    import app.ui.global_click_watcher as watcher
    monkeypatch.setattr(watcher, "_MOUSE_OK", False)
    yield
    cfg.set(cfg.selectionActions, old, save=False)
    cfg.set(cfg.selectionExplainPrompt, old_prompt, save=False)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def custom_record(key="custom_test", *, mode="oneshot"):
    return {"id": key, "name": "settings.title", "icon": "CODE",
            "prompt": 'Process {text}; preserve {"name": "value"}', "mode": mode}


def install_custom(*, mode="oneshot"):
    config = default_selection_actions()
    config["custom"].append(custom_record(mode=mode))
    config["order"].insert(0, "custom_test")
    cfg.set(cfg.selectionActions, config)
    return config


def test_migration_preserves_prompts_visibility_and_runs_only_once():
    data = {"Selection": {"TranslatePrompt": "Translate {text} precisely",
                          "FixGrammarPrompt": "Fix {text}", "RewriteEnabled": False,
                          "ContinueExplainEnabled": False}}
    _migrate_selection_actions(data)
    actions = data["Selection"]["Actions"]
    assert actions["custom"][0]["prompt"] == "Translate {text} precisely"
    assert actions["custom"][1]["prompt"] == "Fix {text}"
    assert actions["order"] == list(DEFAULT_ORDER)
    assert all(not actions["buttons"][key]["enabled"] for key in
               ("translate_inplace", "fix_grammar", "polish", "continue_explain", "new_continue_explain"))
    actions["custom"] = []
    actions["order"] = list(reversed(BUILTIN_IDS))
    before = deepcopy(actions)
    _migrate_selection_actions(data)
    assert data["Selection"]["Actions"] == before
    assert normalize_selection_actions(json.loads(json.dumps(actions)))["custom"] == []


def test_normalization_retains_manual_order_and_rejects_conflicting_records():
    config = default_selection_actions()
    config["custom"].extend([custom_record(), custom_record(), custom_record("note"), None])
    config["order"] = ["note", "custom_test", "explain", "note", "unknown", {}]
    config["buttons"]["note"] = {"enabled": False, "pinned": False}
    before = deepcopy(config)
    normalized = normalize_selection_actions(config)
    assert normalized["order"][:3] == ["note", "custom_test", "explain"]
    assert len(normalized["custom"]) == 3
    assert normalized["buttons"]["note"] == {"enabled": False, "pinned": False}
    assert normalize_selection_actions(normalized) == normalized
    assert config == before


@pytest.mark.parametrize("mode", ["oneshot", "rewrite"])
def test_custom_actions_use_literal_labels_prompts_and_mode(actions_config, mode):
    install_custom(mode=mode)
    action = get_text_action("custom_test")
    assert action.label == "settings.title"  # user input never passes through i18n
    assert action.goes_to_ai
    assert action.is_rewrite == (mode == "rewrite")
    assert action.icon == FluentIcon.CODE
    assert 'Process selected; preserve {"name": "value"}' in action.render("selected")
    assert (t("textaction.rewrite.constraint") in action.render("selected")) == (mode == "rewrite")


def test_missing_placeholder_appends_text_and_unknown_icon_has_fallback(actions_config):
    config = install_custom()
    config["custom"][-1].update(prompt="Summarize", icon="removed_icon")
    cfg.set(cfg.selectionActions, config)
    action = get_text_action("custom_test")
    assert action.render("selected") == "Summarize\n\nselected"
    assert action.icon == FluentIcon.ROBOT == selection_icon("removed_icon")


def test_migrated_preset_can_be_renamed_and_change_result_use(actions_config):
    config = default_selection_actions({"TranslatePrompt": "Translate exactly: {text}"})
    cfg.set(cfg.selectionActions, config)
    assert "Translate exactly: selected" in get_text_action("translate_inplace").render("selected")
    config["custom"][0].update(name="My translation", mode="oneshot", prompt="Translate freely", icon="MAIL")
    cfg.set(cfg.selectionActions, config)
    action = get_text_action("translate_inplace")
    assert action.label == "My translation" and not action.is_rewrite
    assert action.render("selected") == "Translate freely\n\nselected"
    assert action.icon == FluentIcon.MAIL


def test_deleted_presets_do_not_resolve_or_reappear(actions_config):
    config = default_selection_actions()
    config["custom"] = []
    cfg.set(cfg.selectionActions, config)
    assert get_text_action("translate_inplace") is None
    assert get_text_action("fix_grammar") is None
    assert {a.key for a in get_all_text_actions()} == set(BUILTIN_IDS)


def test_pinned_more_hidden_and_manual_order_survive_repeated_use(actions_config):
    config = install_custom()
    config["buttons"]["explain"] = {"enabled": True, "pinned": False}
    config["buttons"]["polish"] = {"enabled": False, "pinned": True}
    cfg.set(cfg.selectionActions, config)
    before = deepcopy(cfg.get(cfg.selectionActions))
    assert get_active_text_actions(pinned=True)[0].key == "custom_test"
    assert [a.key for a in get_active_text_actions(pinned=False)] == ["explain"]
    assert "polish" not in {a.key for a in get_active_text_actions()}
    for _ in range(3):
        get_text_action("custom_test").render("selected")
        get_active_text_actions()
    assert cfg.get(cfg.selectionActions) == before


def test_settings_create_reorder_and_change_placement(qapp, actions_config):
    from app.ui.settings_pages.selection_page import SelectionPage

    page = SelectionPage()
    page._insert(custom_record())
    assert cfg.get(cfg.selectionActions)["order"][-1] == "custom_test"
    page._move(-1)
    expected = cfg.get(cfg.selectionActions)["order"]
    assert expected[-2] == "custom_test"
    page._placement.setCurrentIndex(1)
    assert cfg.get(cfg.selectionActions)["buttons"]["custom_test"] == {"enabled": True, "pinned": False}
    reopened = SelectionPage()
    assert reopened._config["order"] == expected
    assert reopened._config["buttons"]["custom_test"]["pinned"] is False
    page.deleteLater()
    reopened.deleteLater()


def test_action_editor_validates_and_selects_icon(qapp, actions_config):
    from app.ui.settings_pages.selection_page import ActionEditor

    dialog = ActionEditor()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not dialog._error.isHidden()
    dialog._name.setText("Summary")
    dialog._prompt.setPlainText("Summarize")
    dialog._select_icon("DOCUMENT")
    dialog._mode.setCurrentIndex(1)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    record = dialog.record()
    assert record["icon"] == "DOCUMENT" and record["mode"] == "rewrite"
    assert record["id"].startswith("custom_")
    dialog.deleteLater()


def test_more_expands_without_activating_or_recapturing_selection(qapp, actions_config):
    from app.ui.text_action_popup import TextActionPopup

    config = install_custom()
    config["buttons"] = {key: {"enabled": True, "pinned": False} for key in config["order"]}
    cfg.set(cfg.selectionActions, config)
    popup = TextActionPopup()
    chosen = []
    popup.action_chosen.connect(chosen.append)
    popup.show_at(400, 300)
    assert popup._row.count() == 1  # More is available even when nothing is pinned
    popup._row.itemAt(0).widget().click()
    qapp.processEvents()
    assert popup._more_panel.isVisible()
    assert popup.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert popup.windowFlags() & Qt.WindowType.Tool
    assert popup._cached_geo.size() == popup.size()
    popup._row.itemAt(0).widget().click()
    assert not popup._more_panel.isVisible()
    popup._row.itemAt(0).widget().click()
    assert popup._more_panel.isVisible()
    button = popup._more_layout.itemAt(0).widget()
    assert button.text() == "settings.title"
    assert button._action_key == "custom_test"
    button.click()
    assert chosen == ["custom_test"]
    assert not popup.isVisible()
    popup.deleteLater()


@pytest.mark.parametrize("hide_between", [False, True])
def test_popup_keeps_button_size_when_quickly_reselected(qapp, actions_config, hide_between):
    from app.ui.text_action_popup import TextActionPopup

    config = install_custom()
    config["buttons"]["explain"] = {"enabled": True, "pinned": False}
    cfg.set(cfg.selectionActions, config)
    popup = TextActionPopup()
    try:
        initial_size = None
        for attempt in range(20):
            if hide_between:
                popup.hide()  # 新拖选会请求隐藏，但下一次 show 可能紧接着到达
            popup.show_at(400 + attempt, 300)
            qapp.processEvents()
            if initial_size is None:
                initial_size = popup.size()
            assert popup.size() == initial_size
            assert popup._cached_geo.size() == popup.size()
            for index in range(popup._row.count()):
                button = popup._row.itemAt(index).widget()
                if button is not None and hasattr(button, "iconSize"):
                    assert button.size() == QSize(28, 28)
                    assert button.minimumSize() == button.maximumSize() == QSize(28, 28)
                    assert button.iconSize() == QSize(14, 14)
    finally:
        popup.hide()
        popup.deleteLater()


def test_view_result_can_copy_and_edited_result_does_not_request_ai(qapp, actions_config):
    from app.ui.result_bubble import ResultBubble

    bubble = ResultBubble()
    # Completion enables copying for view mode, including when a previous action
    # used rewrite mode. Redisplay is entirely local.
    bubble._mode = "oneshot"
    bubble._full_text = "Summary"
    bubble._content.setPlainText("Summary")
    now = time.perf_counter()
    bubble._on_stream_done(bubble._stream_generation, now, now)
    assert bubble._copy_btn.isEnabled()
    bubble.show_rewrite_result(400, 300, "original", "edited")
    assert bubble._full_text == "edited"
    assert bubble._replace_btn.isEnabled() and bubble._edit_btn.isEnabled()
    assert bubble._stream_thread is None
    bubble.hide()
    bubble.deleteLater()


@pytest.mark.parametrize("accepted", [True, False])
def test_edit_dialog_restores_source_and_requires_verification_even_when_cancelled(
    qapp, actions_config, monkeypatch, accepted
):
    from PyQt6.QtWidgets import QPlainTextEdit
    import app.ui.selection_controller as module

    parent = QWidget()
    controller = module.SelectionController(parent, note_mgr=None)
    controller._rewrite_original = "original"
    controller._source_window = 42
    restored = []

    def edit(dialog):
        dialog.findChild(QPlainTextEdit).setPlainText("edited")
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(module.QDialog, "exec", edit)
    monkeypatch.setattr(module, "restore_foreground_window", restored.append)
    controller._on_edit_requested("generated")
    assert restored == [42]
    assert controller._rewrite_needs_verification
    assert controller._bubble._full_text == ("edited" if accepted else "generated")
    assert controller._bubble._stream_thread is None
    controller._bubble.hide()
    parent.deleteLater()


@pytest.mark.parametrize("mode", ["oneshot", "rewrite"])
def test_controller_dispatches_custom_modes(qapp, actions_config, monkeypatch, mode):
    from app.ui.selection_controller import SelectionController

    install_custom(mode=mode)
    window = QWidget()
    controller = SelectionController(window, note_mgr=None)
    controller._captured = "selected"
    calls = []
    monkeypatch.setattr(controller, "_show_oneshot", lambda *args: calls.append(("view", args)))
    monkeypatch.setattr(controller, "_show_rewrite", lambda *args: calls.append(("rewrite", args)))
    controller._on_action_bubble("custom_test")
    assert calls == [("rewrite" if mode == "rewrite" else "view", ("selected", "custom_test"))]
    window.deleteLater()


@pytest.mark.parametrize("current,window", [("", 42), ("changed", 42), ("original", 99)])
def test_edited_result_never_pastes_without_matching_window_and_selection(
    qapp, actions_config, monkeypatch, current, window
):
    import app.ui.selection_controller as module

    parent = QWidget()
    controller = module.SelectionController(parent, note_mgr=None)
    controller._rewrite_original = "original"
    controller._source_window = 42
    controller._rewrite_needs_verification = True
    copied, pasted = [], []
    monkeypatch.setattr(module, "foreground_window", lambda: window)
    monkeypatch.setattr(module, "capture_selection", lambda: current)
    monkeypatch.setattr(module, "replace_selection", lambda *args, **kwargs: pasted.append(args) or True)
    monkeypatch.setattr(controller, "_copy_to_clipboard", copied.append)
    controller._on_replace_requested("edited")
    assert pasted == [] and copied == ["edited"]
    parent.deleteLater()


def test_edited_result_replaces_only_after_selection_confirmation(qapp, actions_config, monkeypatch):
    import app.ui.selection_controller as module

    parent = QWidget()
    controller = module.SelectionController(parent, note_mgr=None)
    controller._rewrite_original = "original"
    controller._source_window = 42
    controller._rewrite_needs_verification = True
    pasted = []
    monkeypatch.setattr(module, "foreground_window", lambda: 42)
    monkeypatch.setattr(module, "capture_selection", lambda: "original")
    monkeypatch.setattr(module, "replace_selection", lambda result, **kwargs: pasted.append((result, kwargs)) or True)
    controller._on_replace_requested("edited")
    assert pasted == [("edited", {"original": "original", "verify": False})]
    parent.deleteLater()
