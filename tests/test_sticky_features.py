"""Sticky persistence, legacy content compatibility, desktop state and local reminders."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QEvent, Qt, QMimeData, QUrl
from PyQt6.QtGui import QImage, QTextBlockFormat, QTextCursor, QTextDocument

from app.storage.db_manager import DatabaseManager
from app.storage.note_manager import NoteManager
from app.desktop.sticky_reminders import StickyReminderService, next_occurrence
from app.ui.components.sticky_editor import StickyEditor
from app.ui.sticky_reminders import StickyReminderDialog, StickyReminderCard


@pytest.fixture
def desktop(notebook):
    _, panel, controller = notebook
    return panel, controller


@pytest.fixture
def reminder_parent(qapp):
    from PyQt6.QtWidgets import QWidget

    parent = QWidget()
    yield parent
    parent.deleteLater()
    qapp.sendPostedEvents(parent, QEvent.Type.DeferredDelete)


def test_preferences_and_reminders_survive_reload_without_mutating_content(notes):
    note = notes.create("sticky", "untouched", "sticky")
    original = notes.get(note.id).updated_at
    notes.set_sticky_settings(note.id, color="green", width=350, opacity=5, locked=True)
    when = datetime.now(timezone.utc) + timedelta(hours=1)
    notes.set_sticky_reminder(note.id, {"repeat": "once"}, when.isoformat())
    reopened = NoteManager(DatabaseManager(notes.db.db_path))
    assert reopened.get_sticky_settings(note.id)["color"] == "green"
    assert reopened.get_sticky_settings(note.id)["opacity"] == 70
    assert reopened.get_sticky_reminder(note.id)["next_at"] == when.isoformat()
    assert reopened.get(note.id).content == "untouched"
    assert reopened.get(note.id).updated_at == original
    reopened.delete(note.id)
    assert reopened.get_sticky_reminder(note.id)["enabled"] is False
    reopened.restore(note.id)
    assert reopened.get_sticky_reminder(note.id)["enabled"] is False
    reopened.purge(note.id)  # Active notes cannot be purged accidentally.
    assert reopened.get(note.id)
    reopened.delete(note.id)
    reopened.purge(note.id)
    assert reopened.get_sticky_reminder(note.id) is None


@pytest.mark.parametrize("paste", [False, True])
def test_legacy_checklists_become_plain_paragraphs_and_round_trip(qtbot, paste):
    editor = StickyEditor()
    qtbot.addWidget(editor)
    content = ('<p>paragraph</p><ul><li class="checked"><span style="text-decoration:line-through;font-weight:700">done</span></li>'
               '<li class="unchecked">pending<ul><li class="checked"><s>nested</s></li></ul></li></ul>')
    if paste:
        mime = QMimeData()
        mime.setHtml(content)
        editor.insertFromMimeData(mime)
    else:
        editor.load_content(content)
    assert editor.plain_text().splitlines() == ["paragraph", "done", "pending", "nested"]
    block = editor.document().begin()
    while block.isValid():
        assert block.blockFormat().marker() == QTextBlockFormat.MarkerType.NoMarker
        assert QTextCursor(block).currentList() is None
        assert block.isVisible()
        cursor = QTextCursor(block)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        assert not cursor.charFormat().fontStrikeOut()
        block = block.next()
    assert 'font-weight:700' in editor.toHtml()
    assert 'line-through' not in editor.toHtml()
    saved = editor.toHtml()
    if paste:
        editor.undo()
        assert editor.toPlainText() == ""
        editor.redo()
        assert editor.toHtml() == saved
    editor.load_content(saved)
    assert editor.plain_text().splitlines() == ["paragraph", "done", "pending", "nested"]
    assert not editor.document().isUndoAvailable()
    editor.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "next paragraph")
    assert editor.textCursor().currentList() is None
    assert not editor.currentCharFormat().fontStrikeOut()


def test_legacy_conversion_preserves_other_rich_text_and_locked_editor(qtbot, tmp_path):
    editor = StickyEditor(images_dir=tmp_path)
    qtbot.addWidget(editor)
    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.blue)
    image_path = tmp_path / "attachment.png"
    assert image.save(str(image_path))
    editor.load_content('<p><s>manual strike</s></p><ul><li>ordinary list</li></ul>'
                        '<ul><li class="checked"><b>done</b><img src="' + QUrl.fromLocalFile(str(image_path)).toString() + '" /></li></ul>')
    assert '<img ' in editor.toHtml()
    assert 'manual strike' in editor.toPlainText()
    assert 'line-through' in editor.toHtml()  # Ordinary formatting is still supported.
    assert QTextCursor(editor.document().begin().next()).currentList() is not None
    assert QTextCursor(editor.document().lastBlock()).currentList() is None
    editor.selectAll()
    from PyQt6.QtGui import QColor
    editor.setTextColor(QColor("#ff4488"))
    editor.load_content(editor.toHtml())
    editor.selectAll()
    assert editor.currentCharFormat().foreground().color() == QColor("#ff4488")
    editor.setReadOnly(True)
    saved = editor.toHtml()
    mime = QMimeData()
    mime.setHtml('<ul><li class="unchecked">new task</li></ul>')
    editor.insertFromMimeData(mime)
    assert editor.toHtml() == saved


def test_image_paste_and_html_copy_keep_owned_files(qtbot, tmp_path):
    editor = StickyEditor(images_dir=tmp_path / "owned")
    qtbot.addWidget(editor)
    source = tmp_path / "source.png"
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    image.save(str(source))
    mime = QMimeData()
    mime.setHtml('<p>text</p><img src="' + QUrl.fromLocalFile(str(source)).toString() + '"><img src="https://invalid.test/image.png">')
    editor.insertFromMimeData(mime)
    source.unlink()
    assert len(list((tmp_path / "owned").glob("*.png"))) == 1
    assert "invalid.test" not in editor.toHtml()
    assert "source.png" not in editor.toHtml()
    assert "owned" in editor.toHtml()
    literal = "a < b and c > d"
    editor.load_content(literal)
    assert editor.toPlainText() == literal


def test_hide_restart_one_window_and_independent_display_settings(desktop, notes, qtbot):
    panel, controller = desktop
    win = controller.create_note()
    key = win._note_id
    win._content_edit.setPlainText("Keep me")
    win._set_pref("color", "blue")
    win.resize(350, 310)
    win._save_position()
    assert controller.show_note(key) is win
    assert len(controller._windows) == 1
    win.close()
    assert not win.isVisible()
    assert notes.get_sticky_settings(key)["visible"] is False
    assert notes.get(key).is_pinned
    controller.shutdown()
    controller.restore_pinned()
    restored = controller._by_id[key]
    assert not restored.isVisible()
    assert restored.width() == 350
    assert restored._settings["color"] == "blue"
    assert restored._content_edit.toPlainText() == "Keep me"
    restored.show_note()
    restored._set_pref("collapsed", True)
    assert restored.height() <= 40
    restored._set_pref("collapsed", False)
    assert restored.height() == 310
    restored._set_pref("locked", True)
    assert restored._content_edit.isReadOnly()


def test_title_buttons_have_larger_targets_hand_cursor_and_theme_feedback(desktop, qtbot, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QPushButton
    panel, controller = desktop
    win = controller.create_note()
    buttons = win._title_bar.findChildren(QPushButton)
    assert len(buttons) == 3
    for color in ("#26352A", "#E8F5E9"):
        win._set_pref("color", color)
        QApplication.processEvents()
        for button in buttons:
            assert button.size().width() == 32
            assert button.size().height() == 28
            assert button.cursor().shape() == Qt.CursorShape.PointingHandCursor
            assert "font-size:20px" in button.styleSheet()
            assert "QPushButton:hover" in button.styleSheet()
            assert win._title_bar.rect().contains(button.geometry())
            win._apply_resize_cursor(Qt.Edge.RightEdge)
            qtbot.mouseMove(button, button.rect().center())
            assert win._resize_cursor_shape is None
            assert QApplication.overrideCursor() is None
    win._set_pref("collapsed", True)
    QApplication.processEvents()
    assert win.height() == 40
    assert all(button.isVisible() for button in buttons)
    menu = Mock()
    monkeypatch.setattr(win, "show_note_menu", menu)
    qtbot.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
    menu.assert_called_once()
    qtbot.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
    assert len(controller._windows) == 2
    qtbot.mouseClick(buttons[2], Qt.MouseButton.LeftButton)
    assert not win.isVisible()


def test_no_stale_content_overwrite_and_cross_surface_plain_text(desktop, notes):
    panel, controller = desktop
    win = panel._on_new("sticky")
    key = win._note_id
    win._content_edit.setPlainText("first paragraph")
    win._flush()
    assert panel._sticky_edit.toPlainText() == "first paragraph"
    panel._sticky_edit.moveCursor(QTextCursor.MoveOperation.End)
    panel._sticky_edit.insertPlainText(" library edit")
    panel._flush_current()
    assert win._content_edit.toPlainText() == "first paragraph library edit"
    content = notes.get(key).content
    win._flush()
    assert notes.get(key).content == content
    panel._sticky_edit.insertPlainText(" pending panel")
    pending = panel._sticky_edit.toPlainText()
    panel.refresh_note(key)
    assert panel._sticky_edit.toPlainText() == pending
    panel._flush_current()
    assert win._content_edit.toPlainText() == pending


def test_template_and_duplicate_do_not_copy_active_reminders(desktop, notes):
    from app.i18n import t
    panel, controller = desktop
    win = controller.create_note("template:today")
    key = win._note_id
    assert win._content_edit.plain_text() == t("sticky.template.todayBody")
    assert win._content_edit.textCursor().currentList() is None
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    notes.set_sticky_reminder(key, {"repeat": "once"}, future.isoformat())
    duplicate = controller.duplicate(key)
    assert notes.get_sticky_reminder(duplicate.id) is None
    assert duplicate.note_type == "sticky"
    legacy = '<ul><li class="checked"><s>saved template body</s></li></ul>'
    template_id = notes.save_sticky_template("test", legacy, notes.get_sticky_settings(key))
    templated = controller.create_note("saved:" + str(template_id))
    assert templated._content_edit.plain_text() == "saved template body"
    assert 'class="checked"' not in notes.get(templated._note_id).content
    assert 'line-through' not in notes.get(templated._note_id).content
    assert notes.get_sticky_reminder(templated._note_id) is None


def test_filters_and_bulk_actions_use_shared_registry(desktop, notes):
    panel, controller = desktop
    win = panel._on_new("sticky")
    win._content_edit.setPlainText("body")
    win._flush()
    assert panel._sticky_filter.findData("tasks") == -1
    panel._sticky_filter.setCurrentIndex(panel._sticky_filter.findData("visible"))
    assert panel._list.count() == 1
    panel._list.setCurrentRow(0)
    panel._bulk_sticky("hide")
    assert not win.isVisible()
    panel._sticky_filter.setCurrentIndex(panel._sticky_filter.findData("hidden"))
    assert panel._list.count() == 1
    panel._list.setCurrentRow(0)
    panel._bulk_sticky("color", "green")
    assert notes.get_sticky_settings(win._note_id)["color"] == "green"
    assert win._settings["color"] == "green"


def test_reminders_coalesce_persist_snooze_and_stop(notes, qapp):
    now = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
    clock = [now]
    scheduler = SimpleNamespace(_scheduler=Mock())
    service = StickyReminderService(notes, scheduler, now=lambda: clock[0])
    received = []
    service.due.connect(received.append)
    first = notes.create("first", note_type="sticky")
    second = notes.create("second", note_type="sticky")
    service.configure(first.id, now + timedelta(minutes=1), "once")
    service.configure(second.id, now + timedelta(minutes=1), "daily")
    assert all(call.kwargs["id"].startswith("sticky:") for call in scheduler._scheduler.add_job.call_args_list)
    clock[0] += timedelta(days=2)
    service.check_due()
    assert received == [[first.id, second.id]]
    assert not notes.get_sticky_reminder(first.id)["enabled"]
    assert notes.get_sticky_reminder(second.id)["enabled"]
    assert datetime.fromisoformat(notes.get_sticky_reminder(second.id)["next_at"]) > clock[0]
    service.check_due()
    assert len(received) == 1
    service.snooze([first.id])
    assert notes.get_sticky_reminder(first.id)["enabled"]
    assert datetime.fromisoformat(notes.get_sticky_reminder(first.id)["next_at"]) == clock[0] + timedelta(minutes=10)
    notes.delete(first.id)
    clock[0] += timedelta(minutes=11)
    service.check_due()
    assert all(first.id not in batch for batch in received[1:])
    service.stop()
    assert not service._job_ids


def test_weekly_rule_respects_selected_days_and_future_boundary():
    start = datetime(2026, 11, 13, 18, 0, tzinfo=timezone.utc)
    rule = {"repeat": "weekly", "time": "09:30", "weekdays": [0, 2], "timezone": "Asia/Shanghai"}
    next_at = next_occurrence(rule, start)
    assert next_at.weekday() == 0
    assert next_at.strftime("%H:%M") == "09:30"
    assert next_at > start


def test_reminder_settings_and_card_are_actionable(notes, reminder_parent):
    note = notes.create("reminder note", note_type="sticky")
    service = StickyReminderService(notes, None)
    dialog = StickyReminderDialog(service, note.id, parent=reminder_parent)
    dialog.repeat.setCurrentIndex(2)
    assert all(check.isHidden() is False for check in dialog.days)
    dialog.save()
    assert notes.get_sticky_reminder(note.id)["rule"]["repeat"] == "weekly"
    controller = Mock()
    card = StickyReminderCard(service, controller, [note.id], parent=reminder_parent)
    from PyQt6.QtWidgets import QPushButton
    button = next(button for button in card.findChildren(QPushButton) if button.text() == note.title)
    button.click()
    controller.show_note.assert_called_once_with(note.id)
    service.stop()


def test_legacy_checklists_show_plain_text_in_both_editors_and_copy(desktop, notes, qapp):
    panel, controller = desktop
    legacy = '<p>梯田体坛</p><ul><li class="checked"><s>已完成</s></li><li class="unchecked">未完成</li></ul>'
    note = notes.create("saved", legacy, "sticky")
    panel._current_note_id = note.id
    panel._load_note_into_editor(note.id)
    expected = "梯田体坛\n已完成\n未完成"
    assert panel._sticky_edit.toPlainText() == expected
    panel._copy_note_content(note.id)
    assert qapp.clipboard().text() == expected
    win = controller.show_note(note.id)
    assert win._content_edit.toPlainText() == expected
    assert 'line-through' not in win._content_edit.toHtml()
    # Reading legacy content does not mutate the stored note or its timestamp.
    assert notes.get(note.id).content == legacy
    assert notes.get(note.id).updated_at == note.updated_at
    panel._sticky_edit.moveCursor(QTextCursor.MoveOperation.End)
    panel._sticky_edit.insertPlainText(" new text")
    panel._flush_current()
    assert 'class="checked"' not in notes.get(note.id).content
    assert 'line-through' not in notes.get(note.id).content
    assert win._content_edit.toPlainText() == expected + " new text"
    panel._sticky_edit.setPlainText("temporary")
    panel._editor_dirty = False
    panel._load_note_into_editor(note.id)
    assert panel._sticky_edit.toPlainText() == expected + " new text"


def test_context_formatting_remains_available_without_checklist_entry(qtbot):
    from PyQt6.QtGui import QFont
    from app.i18n import t
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.setPlainText("format text")
    editor.selectAll()
    menu = editor.create_edit_menu()
    insert = next(action.menu() for action in menu.actions() if action.text() == t("sticky.insert"))
    assert [action.text() for action in insert.actions()] == [t("sticky.insert." + key) for key in ("image", "divider", "date")]
    formats = next(action.menu() for action in menu.actions() if action.text() == t("sticky.format"))
    next(action for action in formats.actions() if action.text() == t("sticky.format.bold")).trigger()
    assert editor.textCursor().hasSelection()
    assert editor.currentCharFormat().fontWeight() >= QFont.Weight.Bold
    menu.deleteLater()


@pytest.mark.parametrize("reverse", [False, True])
def test_selection_does_not_show_formatting_toolbar(qtbot, reverse):
    from PyQt6.QtWidgets import QToolBar
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.resize(220, 170)
    editor.setPlainText("手动阀手动阀")
    editor.show()
    editor.activateWindow()
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    cursor = editor.textCursor()
    length = len(editor.toPlainText())
    cursor.setPosition(length if reverse else 0)
    cursor.setPosition(0 if reverse else length, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    assert editor.textCursor().selectedText() == "手动阀手动阀"
    assert not editor.findChildren(QToolBar)
    editor.verticalScrollBar().setValue(0)
    editor.resize(180, 120)
    assert not editor.findChildren(QToolBar)


def test_legacy_completed_strike_does_not_leak_to_new_paragraph_or_note(qtbot):
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.load_content('<ul><li class="checked"><s>done</s></li></ul>')
    editor.moveCursor(QTextCursor.MoveOperation.End)
    assert not editor.currentCharFormat().fontStrikeOut()
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "next paragraph")
    assert editor.textCursor().currentList() is None
    assert not editor.currentCharFormat().fontStrikeOut()
    editor.load_content('<p><s>old note</s></p>')
    editor.moveCursor(QTextCursor.MoveOperation.End)
    assert editor.currentCharFormat().fontStrikeOut()
    editor.load_content("")
    qtbot.keyClicks(editor, "clean new note")
    assert not editor.currentCharFormat().fontStrikeOut()


def test_chinese_input_after_completed_task_and_note_switch_is_plain(desktop, notes, qapp):
    from PyQt6.QtGui import QInputMethodEvent
    panel, controller = desktop
    first = notes.create("old task", '<ul><li class="checked"><span style="text-decoration:line-through">done</span></li></ul>', "sticky")
    panel._current_note_id = first.id
    panel._load_note_into_editor(first.id)
    panel._sticky_edit.moveCursor(QTextCursor.MoveOperation.End)
    panel._on_new("sticky")
    editor = panel._sticky_edit
    event = QInputMethodEvent()
    event.setCommitString("新输入没有删除线")
    qapp.sendEvent(editor, event)
    assert editor.toPlainText() == "新输入没有删除线"
    assert not editor.currentCharFormat().fontStrikeOut()
    panel._flush_current()
    panel._load_note_into_editor(panel._current_note_id)
    assert "line-through" not in editor.toHtml()


def test_theme_default_colors_and_explicit_color_roundtrip(qtbot):
    from PyQt6.QtGui import QColor, QPalette, QTextFormat
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.load_content('<p><span style="color:#ffffff">old white</span> <b>bold</b></p>')
    assert "#ffffff" not in editor.toHtml()
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    editor.insertPlainText("new plain ")
    assert not editor.currentCharFormat().hasProperty(QTextFormat.Property.ForegroundBrush)
    editor.apply_text_color("#4a3f35")
    assert editor.palette().color(QPalette.ColorRole.Text) == QColor("#4a3f35")
    editor.selectAll()
    editor.setTextColor(QColor("#ffffff"))
    saved = editor.toHtml()
    editor.load_content(saved)
    editor.selectAll()
    assert editor.currentCharFormat().foreground().color() == QColor("#ffffff")
    assert "nemo-sticky-colors" in editor.toHtml()
    editor.apply_text_color("#eeeeee")
    assert editor.currentCharFormat().foreground().color() == QColor("#ffffff")
    editor.load_content("plain note")
    assert not editor.currentCharFormat().hasProperty(QTextFormat.Property.ForegroundBrush)


def test_notebook_light_theme_and_filter_use_theme_colors(desktop, notes, qapp, monkeypatch):
    from PyQt6.QtGui import QColor, QPalette
    from qfluentwidgets import ComboBox
    from app.ui import style
    panel, controller = desktop
    previous_qss = qapp.styleSheet()
    previous_theme = "warm_night" if style._current_dark_mode else "almond"
    try:
        qapp.setStyleSheet(style.apply_theme("almond"))
        note = notes.create("theme note", '<p><span style="color:#e8e0d6">legacy text</span></p>', "sticky")
        panel._current_note_id = note.id
        panel._load_note_into_editor(note.id)
        panel.refresh_theme()
        assert isinstance(panel._sticky_filter, ComboBox)
        assert panel._sticky_filter.itemData(0) == "all"
        assert panel._sticky_edit.palette().color(QPalette.ColorRole.Text) == QColor(style.get_text_color())
        assert panel._sticky_edit.palette().color(QPalette.ColorRole.Text).lightness() < 128
        assert "#e8e0d6" not in panel._sticky_edit.toHtml()
        qapp.setStyleSheet(style.apply_theme("warm_night"))
        panel.refresh_theme()
        assert panel._sticky_edit.palette().color(QPalette.ColorRole.Text).lightness() > 128
    finally:
        style.apply_theme(previous_theme)
        qapp.setStyleSheet(previous_qss)


def test_full_document_image_and_text_export(desktop, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    panel, controller = desktop
    win = controller.create_note()
    win._content_edit.setPlainText("\n".join("line " + str(i) for i in range(70)))
    path = tmp_path / "long.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(path), ""))
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    win._export(True)
    assert not warning.called
    assert QImage(str(path)).height() > win.height() * 2
    win._content_edit.load_content('<ul><li class="checked"><s>task</s></li></ul>')
    path = tmp_path / "note.txt"
    win._export(False)
    assert path.read_text(encoding="utf-8").split("\n\n", 1)[1] == "task"


def test_menus_templates_and_edge_edit_guards(desktop, qapp, qtbot):
    from PyQt6.QtCore import QRect
    from app.i18n import t
    panel, controller = desktop
    win = controller.create_note()
    menu = win.create_note_menu()
    new = next(action.menu() for action in menu.actions() if action.text() == t("sticky.new"))
    templates = next(action.menu() for action in new.actions() if action.text() == t("sticky.template"))
    next(action for action in templates.actions() if action.text() == t("sticky.template.shopping")).trigger()
    assert len(controller._windows) == 2
    assert controller._windows[-1]._content_edit.plain_text() == t("sticky.template.shoppingBody")
    assert controller._windows[-1]._content_edit.textCursor().currentList() is None
    insert = next(action.menu() for action in menu.actions() if action.text() == t("sticky.insert"))
    assert len(insert.actions()) == 3
    display = next(action.menu() for action in menu.actions() if action.text() == t("sticky.display"))
    assert [action.text() for action in display.actions()] == [t("sticky." + key) for key in ("top", "collapse", "lock", "edge")]
    menu.deleteLater()
    win._set_pref("edge", True)
    work = win.screen().availableGeometry()
    win.move(work.left() + 80, work.top())
    win.activateWindow()
    win._content_edit.setFocus()
    qtbot.waitUntil(win._content_edit.hasFocus)
    win._edge_hide()
    assert win._edge_geometry is None
    win._content_edit.clearFocus()
    win._menu_open = True
    win._edge_hide()
    assert win._edge_geometry is None
    win._menu_open = False
    before = QRect(win.geometry())
    win._edge_hide()
    assert win._edge_geometry == before
    assert win.y() < work.top()
    win._save_position()
    assert controller._notes.get(win._note_id).pin_position_y == before.y()
    win._edge_restore()
    assert win.geometry() == before


def test_screen_recovery_external_deletion_and_failed_save(desktop, notes, monkeypatch):
    panel, controller = desktop
    win = controller.create_note()
    win.move(-40000, -40000)
    controller._reposition_windows()
    assert qapp_screen_contains(win)
    win._content_edit.setPlainText("unsaved")
    with monkeypatch.context() as patch:
        patch.setattr(notes, "update", Mock(side_effect=OSError("disk full")))
        assert win.dispose() is False
        assert win.isVisible()
        assert win._dirty
    win._flush()
    notes.delete(win._note_id)
    panel.refresh()
    assert win._note_id not in controller._by_id


def qapp_screen_contains(window):
    from PyQt6.QtWidgets import QApplication
    return any(screen.availableGeometry().contains(window.geometry()) for screen in QApplication.screens())


def test_invalid_display_settings_and_pause_old_reminder(notes, reminder_parent):
    note = notes.create("bad settings", note_type="sticky")
    settings = notes.set_sticky_settings(note.id, color=None, width="oops", locked="false", opacity=None)
    assert settings["color"] == "auto"
    assert settings["width"] == 280
    assert settings["locked"] is False
    assert settings["opacity"] == 100
    now = datetime.now(timezone.utc)
    service = StickyReminderService(notes, None)
    service.configure(note.id, now - timedelta(days=1), enabled=False)
    dialog = StickyReminderDialog(service, note.id, parent=reminder_parent)
    dialog.save()
    assert not notes.get_sticky_reminder(note.id)["enabled"]
    service.stop()


def test_real_scheduler_delivers_on_qt_thread_and_restart_coalesces(notes, qtbot):
    from apscheduler.schedulers.background import BackgroundScheduler
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication
    note = notes.create("real timer", note_type="sticky")
    scheduler = BackgroundScheduler(timezone="UTC")
    service = StickyReminderService(notes, SimpleNamespace(_scheduler=scheduler))
    received = []
    threads = []
    service.due.connect(lambda ids: (received.append(ids), threads.append(QThread.currentThread())))
    scheduler.start()
    try:
        service.configure(note.id, datetime.now(timezone.utc) + timedelta(milliseconds=150))
        qtbot.waitUntil(lambda: bool(received), timeout=4000)
        assert received == [[note.id]]
        assert threads == [QApplication.instance().thread()]
        service.stop()
        notes.set_sticky_reminder(note.id, {"repeat": "once"}, (datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
        service.start()
        service.check_due()
        assert received == [[note.id], [note.id]]
    finally:
        service.stop()
        scheduler.shutdown(wait=True)


def test_focus_handoff_and_filter_changes_preserve_pending_edits(desktop, notes):
    panel, controller = desktop
    win = panel._on_new("sticky")
    panel._sticky_edit.setPlainText("library edit")
    controller._prepare_window_edit(win._note_id)
    assert win._content_edit.toPlainText() == "library edit"
    win._content_edit.insertPlainText(" desktop edit")
    controller.prepare_library_edit(win._note_id)
    assert panel._sticky_edit.toPlainText() == win._content_edit.toPlainText()
    panel._sticky_edit.insertPlainText(" before filtering")
    expected = panel._sticky_edit.toPlainText()
    panel._sticky_filter.setCurrentIndex(panel._sticky_filter.findData("hidden"))
    document = QTextDocument()
    document.setHtml(notes.get(win._note_id).content)
    assert document.toPlainText() == expected


def test_edge_does_not_hide_into_adjacent_monitor(desktop, monkeypatch):
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QApplication
    panel, controller = desktop
    win = controller.create_note()
    win._set_pref("edge", True)
    win._content_edit.clearFocus()
    first = SimpleNamespace(geometry=lambda: QRect(0, 0, 1000, 800), availableGeometry=lambda: QRect(0, 0, 1000, 800))
    second = SimpleNamespace(geometry=lambda: QRect(1000, 0, 1000, 800))
    monkeypatch.setattr(win, "screen", lambda: first)
    monkeypatch.setattr(QApplication, "screens", lambda: [first, second])
    win.move(1000 - win.width(), 100)
    win._edge_hide()
    assert win._edge_geometry is None
    monkeypatch.setattr(QApplication, "screens", lambda: [first])
    win._edge_hide()
    assert win._edge_geometry is not None
    win._edge_restore()


def test_library_trash_preserves_pending_desktop_text(desktop, notes, monkeypatch):
    panel, controller = desktop
    win = panel._on_new("sticky")
    key = win._note_id
    win._content_edit.setPlainText("pending before trash")
    monkeypatch.setattr(panel, "_confirm", lambda *_: True)
    panel._on_delete_by_id(key)
    assert notes.get(key) is None
    assert key not in controller._by_id
    notes.restore(key)
    editor = StickyEditor()
    editor.load_content(notes.get(key).content)
    assert editor.toPlainText() == "pending before trash"
    editor.deleteLater()


def test_legacy_fold_setting_is_ignored_and_independent_todos_are_unchanged(notes):
    import json
    note = notes.create("sticky", "body", "sticky")
    with notes.db.get_connection() as conn:
        conn.execute("INSERT INTO sticky_settings(note_id,settings) VALUES(?,?)",
                     (note.id, json.dumps({"hide_completed": True, "color": "green"})))
        conn.commit()
    assert "hide_completed" not in notes.get_sticky_settings(note.id)
    assert notes.get_sticky_settings(note.id)["color"] == "green"
    assert "hide_completed" not in notes.set_sticky_settings(note.id, hide_completed=True)
    todo = notes.create("independent todo", "body", "todo")
    notes.update(todo.id, todo.title, todo.content, priority="high", due_date="2026-11-20", recurrence="daily")
    assert notes.toggle_todo_completed(todo.id)
    saved = notes.get(todo.id)
    assert saved.note_type == "todo"
    assert saved.is_completed
    assert saved.priority == "high"
    assert saved.due_date == "2026-11-20"
    assert saved.recurrence == "daily"
