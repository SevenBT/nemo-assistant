import json
import time
from pathlib import Path
from typing import Optional

from app.core.config import SESSIONS_DIR
from app.models.message import Message
from app.models.session import Session


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._load_all()

    # ------------------------------------------------------------------ load
    def _load_all(self):
        for path in SESSIONS_DIR.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                session = Session.from_dict(data)
                self._sessions[session.id] = session
            except Exception as e:
                print(f"[SessionManager] Failed to load {path.name}: {e}")

    def _path(self, session_id: str) -> Path:
        return SESSIONS_DIR / f"{session_id}.json"

    def _save(self, session: Session):
        with open(self._path(session.id), "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ crud
    def get_sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def create(self, title: str = "新会话") -> Session:
        session = Session(title=title)
        self._sessions[session.id] = session
        self._save(session)
        return session

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)
        p = self._path(session_id)
        if p.exists():
            p.unlink()

    def rename(self, session_id: str, title: str):
        session = self._sessions.get(session_id)
        if session:
            session.title = title
            self._save(session)

    # ------------------------------------------------------------------ messages
    def add_message(self, session_id: str, message: Message):
        session = self._sessions.get(session_id)
        if not session:
            return
        session.messages.append(message)
        session.updated_at = time.time()
        # Auto-title from first user message
        if len(session.messages) == 1 and message.role == "user" and message.content:
            session.title = message.content[:25].strip()
        self._save(session)

    def save_session(self, session_id: str):
        session = self._sessions.get(session_id)
        if session:
            self._save(session)
