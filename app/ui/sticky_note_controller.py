"""Sticky note window controller for the main window."""

import logging
import json

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from app.i18n import t
from app.storage.note_manager import NoteManager
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
        self._by_id = {}
        notes_panel._sticky_controller = self
        self._shutting_down = False
        app = QApplication.instance()
        app.screenAdded.connect(self._watch_screen)
        app.screenRemoved.connect(self._screens_changed)
        for screen in app.screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._screens_changed)
        screen.geometryChanged.connect(self._screens_changed)
        self._screens_changed()

    def _screens_changed(self, *_):
        # Screen removal is finalized after the signal is delivered.
        QTimer.singleShot(0, self._reposition_windows)

    def _reposition_windows(self):
        for window in self._windows:
            window._edge_restore()
            screen = QApplication.screenAt(window.geometry().center()) or QApplication.primaryScreen()
            if screen is None:
                continue
            work = screen.availableGeometry()
            window.resize(min(window.width(), work.width()), min(window.height(), work.height()))
            x, y = self._clamp_to_screen(window.x(), window.y(), window.width(), window.height())
            window.move(x, y)
            window._save_position()

    def reconcile(self):
        for key, window in list(self._by_id.items()):
            note = self._notes.get(key)
            if not note:
                self.remove_window(key)
            else:
                window.update_content(note.title, note.content)

    def create_note(self, source="empty"):
        self._notes_panel._flush_current()
        from app.ui.components.sticky_editor import StickyEditor
        editor = StickyEditor()
        settings = {}
        if source == "clipboard":
            editor.insertFromMimeData(QApplication.clipboard().mimeData())
        elif source.startswith("template:"):
            key = source.split(":", 1)[1]
            editor.setPlainText(t("sticky.template." + key + "Body"))
            if key in ("today", "shopping"):
                editor.append("")
                editor.insert_todo()
        elif source.startswith("saved:"):
            record = next((r for r in self._notes.get_sticky_templates() if str(r["id"]) == source.split(":", 1)[1]), None)
            if record:
                editor.load_content(record["content"])
                editor.reset_completed()
                settings = json.loads(record["settings"])
        content = editor.toHtml() if not editor.document().isEmpty() else ""
        editor.deleteLater()
        note = self._notes.create(title=t("notes.defaultSticky"), content=content, note_type="sticky")
        self._notes.set_sticky_settings(note.id, **settings)
        x, y = self._screen_center(280, 260)
        offset = len(self._windows) % 8 * 22
        self._notes.pin_note(note.id, x + offset, y + offset)
        win = self._show_window(note, x + offset, y + offset)
        self._notes_panel.refresh()
        return win

    def create_from_hotkey(self):
        return self.create_note()

    def restore_pinned(self):
        """Restore all sticky note windows that were pinned on the desktop."""
        for note in self._notes.get_pinned_notes():
            try:
                x = note.pin_position_x if note.pin_position_x is not None else 100
                y = note.pin_position_y if note.pin_position_y is not None else 100
                x, y = self._clamp_to_screen(x, y, 180, 120)
                self._show_window(note, x, y, visible=self._notes.get_sticky_settings(note.id)["visible"])
            except Exception:
                logger.exception("Failed to restore pinned note %s", note.id)

    def toggle_visibility(self):
        """Hide/show all desktop note windows without closing or unpinning them."""
        windows = list(dict.fromkeys(self._windows + self._notes_panel._pin_windows))
        visible = not any(window.isVisible() for window in windows)
        for window in windows:
            window.show_note() if visible else window.hide_note()

    def sync_note_update(self, note_id: int, title: str, content: str):
        """Apply note edits from other surfaces to matching sticky windows."""
        for win in self._windows:
            if getattr(win, "_note_id", None) == note_id:
                win.update_content(title, content)

    def _show_window(self, note: Note, x: int, y: int, visible=True):
        existing = self._by_id.get(note.id)
        if existing:
            if visible:
                existing.show_note()
            return existing
        win = StickyNoteWindow(
            note_id=note.id,
            title=note.title,
            content=note.content,
            note_mgr=self._notes,
        )
        x, y = self._clamp_to_screen(x, y, win.width(), win.height())
        win.move(x, y)
        if visible:
            win.show()
        win._settings["visible"] = visible
        self._by_id[note.id] = win
        self._windows.append(win)
        win.closed.connect(lambda w=win: self._on_closed(w))
        win.content_changed.connect(self.note_updated)
        win.delete_requested.connect(lambda _: self._notes_panel.refresh())
        win.new_requested.connect(self.create_note)
        win.duplicate_requested.connect(self.duplicate)
        win.manager_requested.connect(self.open_manager)
        win.reminder_requested.connect(self.edit_reminder)
        win.settings_changed.connect(self._settings_changed)
        win._content_edit.editing_started.connect(lambda key=note.id: self._prepare_window_edit(key))
        return win

    def _prepare_window_edit(self, note_id):
        if self._notes_panel._flush_current() is False:
            return
        note = self._notes.get(note_id)
        window = self._by_id.get(note_id)
        if note and window:
            window.update_content(note.title, note.content)

    def prepare_library_edit(self, note_id):
        window = self._by_id.get(note_id)
        if window and window._flush() is not False:
            self._notes_panel.refresh_note(note_id)

    def show_note(self, note_id):
        self._notes_panel._flush_current()
        note = self._notes.get(note_id)
        if not note:
            return
        if not note.is_pinned:
            x, y = self._screen_center(280, 260)
            self._notes.pin_note(note.id, x, y)
            note = self._notes.get(note.id)
        self._notes.set_sticky_settings(note.id, visible=True)
        return self._show_window(note, note.pin_position_x if note.pin_position_x is not None else 100,
                                 note.pin_position_y if note.pin_position_y is not None else 100)

    def hide_note(self, note_id):
        if note_id in self._by_id:
            self._by_id[note_id].hide_note()
        else:
            self._notes.set_sticky_settings(note_id, visible=False)

    def remove_window(self, note_id):
        window = self._by_id.get(note_id)
        if window:
            window.dispose()

    def duplicate(self, note_id):
        self._notes_panel._flush_current()
        if note_id in self._by_id:
            self._by_id[note_id]._flush()
        note = self._notes.get(note_id)
        if not note:
            return
        new = self._notes.create(title=t("notes.copyName", title=note.title), content=note.content, note_type=note.note_type)
        settings = self._notes.get_sticky_settings(note.id)
        self._notes.set_sticky_settings(new.id, **{k: settings[k] for k in ("color", "opacity", "width", "height", "font_family", "font_size")})
        if note.note_type == "sticky":
            self.show_note(new.id)
        self._notes_panel.refresh()
        return new

    def open_manager(self):
        parent = self.parent()
        if parent and hasattr(parent, "_switch_view"):
            parent._switch_view(1)
            parent._show_window()
        self._notes_panel._pivot.setCurrentItem("sticky")
        self._notes_panel.refresh()

    def edit_reminder(self, note_id):
        from app.ui.sticky_reminders import StickyReminderDialog
        service = getattr(self, "reminders", None)
        if service:
            dialog = StickyReminderDialog(service, note_id, self._by_id.get(note_id) or self._notes_panel)
            dialog.exec()
            dialog.deleteLater()
            self._settings_changed(note_id)

    def _settings_changed(self, note_id):
        window = self._by_id.get(note_id)
        if window:
            window.refresh_reminder()
        self._notes_panel._refresh_sticky_metadata()
        if self._notes_panel._current_note_id == note_id:
            locked = self._notes.get_sticky_settings(note_id)["locked"]
            self._notes_panel._sticky_edit.setReadOnly(locked)
            self._notes_panel._title_edit.setReadOnly(locked)

    def shutdown(self):
        self._shutting_down = True
        for window in self._windows[:]:
            window.dispose()

    def _on_closed(self, win: StickyNoteWindow):
        if win in self._windows:
            self._windows.remove(win)
        note_id = getattr(win, "_note_id", None)
        self._by_id.pop(note_id, None)

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
        from PyQt6.QtCore import QPoint
        target = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
        screen = target.availableGeometry()
        x = max(screen.x(), min(x, screen.x() + screen.width() - min(min_visible_width, screen.width())))
        y = max(screen.y(), min(y, screen.y() + screen.height() - min(min_visible_height, screen.height())))
        return x, y
