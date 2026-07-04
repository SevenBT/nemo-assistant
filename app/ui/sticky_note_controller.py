"""Sticky note window controller for the main window."""

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from app.core.note_manager import NoteManager
from app.models.note import Note
from app.ui.notes_dialog import NotesPanel
from app.ui.sticky_note_window import StickyNoteWindow

logger = logging.getLogger(__name__)


class StickyNoteController(QObject):
    """Creates, restores, and synchronizes desktop sticky note windows."""

    note_updated = pyqtSignal(int, str, str)

    def __init__(
        self,
        note_mgr: NoteManager,
        notes_panel: NotesPanel,
        parent=None,
    ):
        super().__init__(parent)
        self._notes = note_mgr
        self._notes_panel = notes_panel
        self._windows: list[StickyNoteWindow] = []

    def create_from_hotkey(self):
        note = self._notes.create()
        x, y = self._screen_center(240, 200)
        self._notes.pin_note(note.id, x, y)
        self._show_window(note, x, y)

    def restore_pinned(self):
        """Restore all sticky note windows that were pinned on the desktop."""
        for note in self._notes.get_pinned_notes():
            try:
                x = note.pin_position_x or 100
                y = note.pin_position_y or 100
                x, y = self._clamp_to_screen(x, y, 180, 120)
                self._show_window(note, x, y)
            except Exception:
                logger.exception("Failed to restore pinned note %s", note.id)

    def sync_note_update(self, note_id: int, title: str, content: str):
        """Apply note edits from other surfaces to matching sticky windows."""
        for win in self._windows:
            if getattr(win, "_note_id", None) == note_id:
                win.update_content(title, content)

    def _show_window(self, note: Note, x: int, y: int):
        win = StickyNoteWindow(
            note_id=note.id,
            title=note.title,
            content=note.content,
            note_mgr=self._notes,
        )
        win.move(x, y)
        win.show()
        self._windows.append(win)
        win.closed.connect(lambda w=win: self._on_closed(w))
        win.content_changed.connect(self.note_updated)
        win.delete_requested.connect(lambda _: self._notes_panel.refresh())

    def _on_closed(self, win: StickyNoteWindow):
        if win in self._windows:
            self._windows.remove(win)
        note_id = getattr(win, "_note_id", None)
        if note_id:
            try:
                self._notes.unpin_note(note_id)
            except Exception:
                logger.exception("Failed to unpin note %s", note_id)

    def _screen_center(self, width: int, height: int) -> tuple[int, int]:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - width) // 2
        y = screen.y() + (screen.height() - height) // 2
        return x, y

    def _clamp_to_screen(
        self,
        x: int,
        y: int,
        min_visible_width: int,
        min_visible_height: int,
    ) -> tuple[int, int]:
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.x(), min(x, screen.x() + screen.width() - min_visible_width))
        y = max(screen.y(), min(y, screen.y() + screen.height() - min_visible_height))
        return x, y
