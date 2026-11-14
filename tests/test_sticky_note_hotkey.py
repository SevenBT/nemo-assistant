"""Hotkey stickies must be persisted and visible in the app's sticky list."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument

from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from app.i18n import current_language, init_language, t
from app.ui.notes_dialog import NotesPanel
from app.ui.sticky_note_controller import StickyNoteController


@pytest.fixture
def sticky_context(qtbot, tmp_path):
    language = current_language()
    manager = NoteManager(DatabaseManager(tmp_path / "notes.db"))
    panel = NotesPanel(manager)
    qtbot.addWidget(panel)
    controller = StickyNoteController(manager, panel)
    # The main window forwards sticky edits to these two surfaces.
    controller.note_updated.connect(controller.sync_note_update)
    controller.note_updated.connect(lambda note_id, *_: panel.refresh_note(note_id))
    yield manager, panel, controller
    controller.shutdown()
    for window in panel._pin_windows[:]:
        window.close()
    controller.deleteLater()
    qtbot.wait(1)
    init_language(language)


def _listed_ids(panel):
    return [
        panel._list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(panel._list.count())
        if panel._list.item(i).data(Qt.ItemDataRole.UserRole + 1) == "note"
    ]


def _plain_text(content):
    document = QTextDocument()
    document.setHtml(content)
    return document.toPlainText()


@pytest.mark.parametrize("language", ["zh", "en"])
def test_hotkey_creates_localized_sticky_and_refreshes_list(sticky_context, language):
    manager, panel, controller = sticky_context
    init_language(language)
    panel._pivot.setCurrentItem("sticky")
    assert _listed_ids(panel) == []

    controller.create_from_hotkey()

    note, = manager.get_notes()
    window, = controller._windows
    assert note.note_type == "sticky"
    assert note.title == t("notes.defaultSticky")
    assert window._title_bar._label.text() == note.title
    assert note.content == ""
    assert note.is_pinned
    assert _listed_ids(panel) == [note.id]
    panel._pivot.setCurrentItem("note")
    assert _listed_ids(panel) == []


@pytest.mark.parametrize("note_type", ["note", "sticky"])
def test_hotkey_refresh_preserves_pending_panel_edits(sticky_context, note_type):
    manager, panel, controller = sticky_context
    panel._on_new(note_type)
    note_id = panel._current_note_id
    panel._title_edit.setText("Pending title")
    editor = panel._sticky_edit if note_type == "sticky" else panel._md_editor
    editor.setPlainText("Pending content")
    assert panel._auto_save_timer.isActive()

    controller.create_from_hotkey()

    note = manager.get(note_id)
    assert note.title == "Pending title"
    content = _plain_text(note.content) if note_type == "sticky" else note.content
    assert content == "Pending content"
    assert editor.toPlainText() == "Pending content"
    assert panel._current_note_id == note_id


def test_hotkey_sticky_auto_saves_and_restores_rich_content(sticky_context, qtbot):
    manager, panel, controller = sticky_context
    controller.create_from_hotkey()
    window, = controller._windows
    note_id = window._note_id
    window._save_timer.setInterval(10)

    with qtbot.waitSignal(controller.note_updated, timeout=1000):
        window._content_edit.setHtml("<p><b>Saved sticky</b></p>")

    saved_content = manager.get(note_id).content
    assert _plain_text(saved_content) == "Saved sticky"
    # A new manager runs startup migrations; stickies must keep their HTML.
    reopened = NoteManager(DatabaseManager(manager.db.db_path))
    assert reopened.get(note_id).content == saved_content
    restored = StickyNoteController(reopened, panel)
    try:
        restored.restore_pinned()
        restored_window, = restored._windows
        assert restored_window._content_edit.toPlainText() == "Saved sticky"
        assert restored_window._content_edit.toHtml() == saved_content
    finally:
        for restored_window in restored._windows[:]:
            restored_window.dispose()

    panel._pivot.setCurrentItem("sticky")
    panel._list.setCurrentRow(0)
    assert panel._sticky_edit.toPlainText() == "Saved sticky"
    window._content_edit.setPlainText("Saved on close")
    assert window._save_timer.isActive()
    window.close()
    assert controller._windows == [window]
    assert not window.isVisible()
    assert reopened.get(note_id).is_pinned
    assert reopened.get_sticky_settings(note_id)["visible"] is False
    assert _plain_text(reopened.get(note_id).content) == "Saved on close"
    assert panel._sticky_edit.toPlainText() == "Saved on close"


@pytest.mark.parametrize("text", ["梯田体坛", "# 标题\n\n**梯田体坛**"])
def test_regular_note_pinned_to_desktop_preserves_markdown_source(sticky_context, text):
    manager, panel, controller = sticky_context
    note = manager.create(title="Regular note")
    controller._show_window(note, 100, 100)
    window, = controller._windows
    window._content_edit.setPlainText(text)

    window.close()

    content = manager.get(note.id).content
    assert content == text
    assert "<html>" not in content


def test_old_hotkey_note_html_is_recovered_on_restart(sticky_context):
    manager, panel, controller = sticky_context
    # Older hotkeys wrote Qt HTML into regular notes. Startup already migrates
    # this content to Markdown so existing text remains readable after restart.
    note = manager.create()
    controller._show_window(note, 100, 100)
    window, = controller._windows
    window._content_edit.setPlainText("梯田体坛")
    manager.update(note.id, note.title, window._content_edit.toHtml())

    reopened = NoteManager(DatabaseManager(manager.db.db_path))

    assert reopened.get(note.id).content == "梯田体坛"


def test_toggle_all_stickies_saves_without_unpinning(sticky_context):
    manager, panel, controller = sticky_context
    controller.create_from_hotkey()
    window, = controller._windows
    regular = manager.create(title="Pinned note")
    panel._pin_note_to_screen(regular.id)
    pinned = controller._by_id[regular.id]
    window._content_edit.setPlainText("Pending sticky content")
    pinned._content_edit.setPlainText("Pending note content")

    controller.toggle_visibility()

    assert not window.isVisible() and not pinned.isVisible()
    assert _plain_text(manager.get(window._note_id).content) == "Pending sticky content"
    assert manager.get(regular.id).content == "Pending note content"
    assert all(note.is_pinned for note in manager.get_notes())
    controller.toggle_visibility()
    assert window.isVisible() and pinned.isVisible()
