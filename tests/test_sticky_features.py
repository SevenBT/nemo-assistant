"""Sticky persistence, real Qt checklist editing, desktop state and local reminders."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt, QMimeData, QUrl
from PyQt6.QtGui import QImage, QTextBlockFormat, QTextCursor, QTextDocument

from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from app.core.sticky_reminders import StickyReminderService, next_occurrence
from app.ui.components.sticky_editor import StickyEditor
from app.ui.notes_dialog import NotesPanel
from app.ui.sticky_note_controller import StickyNoteController
from app.ui.sticky_reminders import StickyReminderDialog, StickyReminderCard


@pytest.fixture
def notes(tmp_path):
    return NoteManager(DatabaseManager(tmp_path / "notes.db"))


@pytest.fixture
def desktop(notes, qtbot):
    panel = NotesPanel(notes)
    qtbot.addWidget(panel)
    controller = StickyNoteController(notes, panel)
    controller.note_updated.connect(lambda key, *_: panel.refresh_note(key))
    panel.note_updated.connect(controller.sync_note_update)
    yield panel, controller
    controller.shutdown()


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


def test_checklists_round_trip_mixed_text_enter_undo_and_completion(qtbot):
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.setPlainText("paragraph")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.append("first task")
    editor.insert_todo()
    assert editor.task_counts() == (0, 1)
    editor.toggle_task()
    assert editor.task_counts() == (1, 1)
    editor.hide_completed(True)
    assert not editor.textCursor().block().isVisible()
    html = editor.toHtml()
    assert 'class="checked"' in html
    editor.load_content(html)
    assert editor.task_counts() == (1, 1)
    editor.hide_completed(False)
    editor.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert editor.task_counts() == (1, 2)
    assert editor.textCursor().blockFormat().marker() == QTextBlockFormat.MarkerType.Unchecked
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert editor.textCursor().blockFormat().marker() == QTextBlockFormat.MarkerType.NoMarker
    editor.reset_completed()
    assert editor.task_counts()[0] == 0
    assert editor.plain_text().startswith("paragraph")


def test_multiline_to_checklist_and_locked_editor(qtbot):
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.setPlainText("one\ntwo\nthree")
    editor.selectAll()
    editor.insert_todo()
    assert editor.task_counts() == (0, 3)
    editor.toggle_task()
    editor.undo()
    assert editor.task_counts() == (0, 3)
    editor.setReadOnly(True)
    html = editor.toHtml()
    editor.toggle_task()
    editor.insert_todo()
    assert editor.toHtml() == html


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


def test_no_stale_content_overwrite_and_cross_surface_checklist(desktop, notes):
    panel, controller = desktop
    win = panel._on_new("sticky")
    key = win._note_id
    win._content_edit.setPlainText("first task")
    win._content_edit.insert_todo()
    win._flush()
    assert panel._sticky_edit.task_counts() == (0, 1)
    panel._sticky_edit.toggle_task()
    panel._flush_current()
    assert win._content_edit.task_counts() == (1, 1)
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
    panel, controller = desktop
    win = controller.create_note("template:today")
    key = win._note_id
    assert win._content_edit.task_counts()[1] == 1
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    notes.set_sticky_reminder(key, {"repeat": "once"}, future.isoformat())
    duplicate = controller.duplicate(key)
    assert notes.get_sticky_reminder(duplicate.id) is None
    assert duplicate.note_type == "sticky"
    win._content_edit.toggle_task()
    editor = StickyEditor()
    editor.load_content(win._content_edit.toHtml())
    editor.reset_completed()
    template_id = notes.save_sticky_template("test", editor.toHtml(), notes.get_sticky_settings(key))
    editor.deleteLater()
    templated = controller.create_note("saved:" + str(template_id))
    assert templated._content_edit.task_counts() == (0, 1)
    assert notes.get_sticky_reminder(templated._note_id) is None


def test_filters_and_bulk_actions_use_shared_registry(desktop, notes):
    panel, controller = desktop
    win = panel._on_new("sticky")
    win._content_edit.setPlainText("todo")
    win._content_edit.insert_todo()
    win._flush()
    panel._sticky_filter.setCurrentIndex(panel._sticky_filter.findData("tasks"))
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


def test_reminder_settings_and_card_are_actionable(notes, qtbot):
    note = notes.create("reminder note", note_type="sticky")
    service = StickyReminderService(notes, None)
    dialog = StickyReminderDialog(service, note.id)
    qtbot.addWidget(dialog)
    dialog.repeat.setCurrentIndex(2)
    assert all(check.isHidden() is False for check in dialog.days)
    dialog.save()
    assert notes.get_sticky_reminder(note.id)["rule"]["repeat"] == "weekly"
    controller = Mock()
    card = StickyReminderCard(service, controller, [note.id])
    qtbot.addWidget(card)
    from PyQt6.QtWidgets import QPushButton
    button = next(button for button in card.findChildren(QPushButton) if button.text() == note.title)
    button.click()
    controller.show_note.assert_called_once_with(note.id)
    service.stop()


def test_existing_text_and_checklists_load_on_selection_and_copy(desktop, notes, qapp):
    panel, controller = desktop
    note = notes.create("saved", "梯田体坛", "sticky")
    panel._current_note_id = note.id
    panel._load_note_into_editor(note.id)
    assert panel._sticky_edit.toPlainText() == "梯田体坛"
    panel._sticky_edit.insert_todo()
    panel._sticky_edit.toggle_task()
    panel._flush_current()
    panel._copy_note_content(note.id)
    assert qapp.clipboard().text() == "[x] 梯田体坛"
    panel._sticky_edit.setPlainText("temporary")
    panel._editor_dirty = False
    panel._load_note_into_editor(note.id)
    assert panel._sticky_edit.task_counts() == (1, 1)


def test_marker_mouse_nesting_and_context_formatting(qtbot):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QFont
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.setPlainText("click task")
    editor.insert_todo()
    editor.show()
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    rect = editor.cursorRect()
    qtbot.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.x() - 10, rect.center().y()))
    assert editor.task_counts() == (1, 1)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.textCursor().currentList().format().indent() == 2
    qtbot.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.textCursor().currentList().format().indent() == 1
    editor.selectAll()
    from app.i18n import t
    menu = editor.create_edit_menu()
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


def test_completed_task_strike_does_not_leak_to_new_task_or_note(qtbot):
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.load_content("done")
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insert_todo()
    editor.toggle_task()
    assert editor.currentCharFormat().fontStrikeOut()
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "next")
    assert editor.task_counts() == (1, 2)
    assert not editor.currentCharFormat().fontStrikeOut()
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    qtbot.keyClicks(editor, "paragraph")
    assert editor.textCursor().blockFormat().marker() == QTextBlockFormat.MarkerType.NoMarker
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
    win._content_edit.setPlainText("task")
    win._content_edit.insert_todo()
    path = tmp_path / "note.txt"
    win._export(False)
    assert "[ ] task" in path.read_text(encoding="utf-8")


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
    assert controller._windows[-1]._content_edit.task_counts() == (0, 1)
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


def test_invalid_display_settings_and_pause_old_reminder(notes, qtbot):
    note = notes.create("bad settings", note_type="sticky")
    settings = notes.set_sticky_settings(note.id, color=None, width="oops", locked="false", opacity=None)
    assert settings["color"] == "auto"
    assert settings["width"] == 280
    assert settings["locked"] is False
    assert settings["opacity"] == 100
    now = datetime.now(timezone.utc)
    service = StickyReminderService(notes, None)
    service.configure(note.id, now - timedelta(days=1), enabled=False)
    dialog = StickyReminderDialog(service, note.id)
    qtbot.addWidget(dialog)
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
