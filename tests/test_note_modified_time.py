"""Reading notes and changing desktop layout must preserve modification time."""
from datetime import datetime
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor

from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from app.ui.notes_dialog import NotesPanel, _ROLE_DATE, _ROLE_ID
from app.ui.sticky_note_controller import StickyNoteController


@pytest.fixture
def notebook(tmp_path, qtbot):
    notes = NoteManager(DatabaseManager(tmp_path / "notes.db"))
    panel = NotesPanel(notes)
    qtbot.addWidget(panel)
    controller = StickyNoteController(notes, panel)
    panel.note_updated.connect(controller.sync_note_update)
    controller.note_updated.connect(lambda key, *_: panel.refresh_note(key))
    yield notes, panel, controller
    controller.shutdown()


def set_old_time(notes, key):
    when = "2025-01-02T03:04:05.123456"
    with notes.db.get_connection() as conn:
        conn.execute("UPDATE notes SET updated_at=? WHERE id=?", (when, key))
    return when


@pytest.mark.parametrize("kind,content", [("note", "# Heading\nbody"), ("sticky", "plain legacy sticky"),
                                          ("sticky", '<p><span style="color:#ffffff">old text</span></p>')])
def test_click_focus_selection_refresh_and_idle_do_not_save(notebook, qtbot, monkeypatch, kind, content):
    notes, panel, controller = notebook
    note = notes.create("read only visit", content, kind)
    before = set_old_time(notes, note.id)
    update = Mock(wraps=notes.update)
    monkeypatch.setattr(notes, "update", update)
    panel._pivot.setCurrentItem(kind)
    panel.refresh()
    panel.resize(850, 500)
    panel.show()
    panel.activateWindow()
    item = next(panel._list.item(i) for i in range(panel._list.count()) if panel._list.item(i).data(_ROLE_ID) == note.id)
    qtbot.mouseClick(panel._list.viewport(), Qt.MouseButton.LeftButton, pos=panel._list.visualItemRect(item).center())
    editor = panel._sticky_edit if kind == "sticky" else panel._md_editor
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    editor.selectAll()
    panel._title_edit.setFocus()
    editor.setFocus()
    panel.refresh_theme()
    panel._flush_current()
    panel.refresh()
    panel.hide()
    assert not update.called
    assert notes.get(note.id).updated_at == before
    assert notes.get(note.id).content == content
    assert item is not None


def test_sticky_subtitle_is_modified_time_even_when_hidden_or_reminded(notebook):
    from datetime import timedelta, timezone
    notes, panel, controller = notebook
    win = controller.create_note()
    key = win._note_id
    before = set_old_time(notes, key)
    win.hide_note()
    notes.set_sticky_reminder(key, {"repeat": "once"}, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    panel._pivot.setCurrentItem("sticky")
    panel.refresh()
    panel._refresh_sticky_metadata()
    item = next(panel._list.item(i) for i in range(panel._list.count()) if panel._list.item(i).data(_ROLE_ID) == key)
    assert item.data(_ROLE_DATE) == "01-02 03:04"
    assert notes.get(key).updated_at == before
    win.show_note()
    win._save_position()
    panel.refresh_note(key)
    assert item.data(_ROLE_DATE) == "01-02 03:04"
    assert notes.get(key).updated_at == before


@pytest.mark.parametrize("kind", ["note", "sticky"])
def test_real_edit_updates_time_and_undo_to_original_does_not(notebook, kind):
    notes, panel, controller = notebook
    note = notes.create("title", "original", kind)
    before = set_old_time(notes, note.id)
    panel._current_note_id = note.id
    panel._load_note_into_editor(note.id)
    editor = panel._sticky_edit if kind == "sticky" else panel._md_editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText(" change")
    editor.undo()
    panel._flush_current()
    assert notes.get(note.id).updated_at == before
    editor.insertPlainText(" actual change")
    panel._flush_current()
    saved = notes.get(note.id)
    assert saved.updated_at != before
    assert datetime.fromisoformat(saved.updated_at).date() == datetime.now().date()
    assert "T" in saved.updated_at
    panel._flush_current()
    assert notes.get(note.id).updated_at == saved.updated_at


def test_legacy_timestamp_trigger_is_removed_and_layout_operations_preserve_time(tmp_path, monkeypatch):
    import app.core.note_manager as module
    db = DatabaseManager(tmp_path / "legacy.db")
    notes = NoteManager(db)
    note = notes.create("title", "body")
    with db.get_connection() as conn:
        conn.executescript("CREATE TRIGGER update_notes_timestamp AFTER UPDATE ON notes BEGIN "
                           "UPDATE notes SET updated_at=datetime('now') WHERE id=NEW.id; END;")
    notes = NoteManager(DatabaseManager(db.db_path))
    before = set_old_time(notes, note.id)
    notes.pin_note(note.id, 0, 0)
    notes.update_pin_position(note.id, 40, 60)
    notes.unpin_note(note.id)
    folder = notes.create_folder("folder")
    notes.move_note_to_folder(note.id, folder.id)
    notes.reorder_notes([note.id], folder.id)
    notes.update(note.id, note.title, note.content)
    assert notes.get(note.id).updated_at == before
    class Clock:
        @staticmethod
        def now():
            return datetime(2026, 11, 13, 16, 20, 30, 123456)
    monkeypatch.setattr(module, "datetime", Clock)
    updated = notes.update(note.id, note.title, "edited")
    assert updated.updated_at == "2026-11-13T16:20:30.123456"


def test_desktop_false_dirty_and_undo_do_not_retimestamp(notebook):
    notes, panel, controller = notebook
    win = controller.create_note()
    key = win._note_id
    before = set_old_time(notes, key)
    win._mark_dirty()
    win._flush()
    assert notes.get(key).updated_at == before
    win._content_edit.insertPlainText("undo")
    win._content_edit.undo()
    win._flush()
    assert notes.get(key).updated_at == before
