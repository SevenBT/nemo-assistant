import pytest


@pytest.fixture
def notes(tmp_path):
    from app.storage.db_manager import DatabaseManager
    from app.storage.note_manager import NoteManager

    return NoteManager(DatabaseManager(tmp_path / "notes.db"))


@pytest.fixture
def notebook(notes, qapp):
    """Dispose desktop windows before their panel and signal receivers."""
    from PyQt6.QtCore import QEvent
    from app.ui.notes_dialog import NotesPanel
    from app.ui.sticky_note_controller import StickyNoteController

    panel = NotesPanel(notes)
    controller = StickyNoteController(notes, panel, parent=panel)
    controller.note_updated.connect(panel.refresh_note)
    panel.note_updated.connect(controller.sync_note_update)
    yield notes, panel, controller
    controller.shutdown()
    panel.close()
    panel.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
