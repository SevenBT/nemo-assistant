import json
import time
from pathlib import Path
from typing import Optional

from app.core.config import NOTES_DIR, TRASH_DIR
from app.models.note import Note


class NoteManager:
    def __init__(self):
        self._notes: dict[str, Note] = {}
        self._trash: dict[str, Note] = {}
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        self._load_all()
        self._load_trash()

    # ------------------------------------------------------------------ load
    def _load_all(self):
        for path in NOTES_DIR.glob("*.json"):
            try:
                note = Note.from_dict(json.loads(path.read_text(encoding="utf-8")))
                self._notes[note.id] = note
            except Exception as e:
                print(f"[NoteManager] Failed to load {path.name}: {e}")

    def _load_trash(self):
        for path in TRASH_DIR.glob("*.json"):
            try:
                note = Note.from_dict(json.loads(path.read_text(encoding="utf-8")))
                self._trash[note.id] = note
            except Exception as e:
                print(f"[NoteManager] Failed to load trash {path.name}: {e}")

    # ------------------------------------------------------------------ paths
    def _path(self, note_id: str) -> Path:
        return NOTES_DIR / f"{note_id}.json"

    def _trash_path(self, note_id: str) -> Path:
        return TRASH_DIR / f"{note_id}.json"

    def _save(self, note: Note):
        self._path(note.id).write_text(
            json.dumps(note.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ notes CRUD
    def get_notes(self) -> list[Note]:
        return sorted(self._notes.values(), key=lambda n: n.updated_at, reverse=True)

    def get(self, note_id: str) -> Optional[Note]:
        return self._notes.get(note_id)

    def create(self, title: str = "新笔记", content: str = "") -> Note:
        note = Note(title=title, content=content)
        self._notes[note.id] = note
        self._save(note)
        return note

    def update(self, note_id: str, title: str, content: str) -> Optional[Note]:
        note = self._notes.get(note_id)
        if not note:
            return None
        note.title = title
        note.content = content
        note.updated_at = time.time()
        self._save(note)
        return note

    def delete(self, note_id: str):
        """将笔记移入回收站（不永久删除）。"""
        note = self._notes.pop(note_id, None)
        if not note:
            return
        p = self._path(note_id)
        if p.exists():
            p.unlink()
        note.updated_at = time.time()
        self._trash[note_id] = note
        self._trash_path(note_id).write_text(
            json.dumps(note.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ trash CRUD
    def get_trash(self) -> list[Note]:
        return sorted(self._trash.values(), key=lambda n: n.updated_at, reverse=True)

    def trash_count(self) -> int:
        return len(self._trash)

    def restore(self, note_id: str) -> bool:
        """从回收站恢复笔记。"""
        note = self._trash.pop(note_id, None)
        if not note:
            return False
        tp = self._trash_path(note_id)
        if tp.exists():
            tp.unlink()
        self._notes[note_id] = note
        self._save(note)
        return True

    def purge(self, note_id: str):
        """永久删除回收站中的笔记。"""
        self._trash.pop(note_id, None)
        p = self._trash_path(note_id)
        if p.exists():
            p.unlink()

    def purge_all(self):
        """清空整个回收站。"""
        for note_id in list(self._trash.keys()):
            self.purge(note_id)

    # ------------------------------------------------------------------ ai helpers
    def get_preview_list(self, max_preview: int = 100) -> list[dict]:
        return [
            {
                "id": n.id,
                "title": n.title,
                "preview": n.content[:max_preview].replace("\n", " "),
                "updated_at": n.updated_at,
            }
            for n in self.get_notes()
        ]
