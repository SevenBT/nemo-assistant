"""
会话管理器。

负责会话的 CRUD、消息追加、置顶排序，数据以 JSON 文件持久化到 SESSIONS_DIR。
"""
import json
import time
from pathlib import Path
from typing import Optional

from app.core.config import SESSIONS_DIR
from app.models.message import Message
from app.models.session import Session


class SessionManager:
    """会话管理器，管理所有聊天会话的生命周期和持久化。"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._load_all()

    # ------------------------------------------------------------------ 加载/保存
    def _load_all(self):
        """从磁盘加载所有会话 JSON 文件。"""
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

    # ------------------------------------------------------------------ CRUD
    def get_sessions(self) -> list[Session]:
        """返回会话列表：置顶的在前（按 sort_order），其余按 updated_at 降序。"""
        pinned = sorted(
            [s for s in self._sessions.values() if s.pinned],
            key=lambda s: s.sort_order,
        )
        unpinned = sorted(
            [s for s in self._sessions.values() if not s.pinned],
            key=lambda s: s.updated_at,
            reverse=True,
        )
        return pinned + unpinned

    def pin_session(self, session_id: str, pinned: bool):
        """设置/取消置顶。"""
        session = self._sessions.get(session_id)
        if session:
            session.pinned = pinned
            if pinned:
                max_order = max(
                    (s.sort_order for s in self._sessions.values() if s.pinned),
                    default=-1,
                )
                session.sort_order = max_order + 1
            self._save(session)

    def reorder_sessions(self, ordered_ids: list[str]):
        """按给定 ID 顺序更新 sort_order（仅影响置顶会话）。"""
        for i, sid in enumerate(ordered_ids):
            session = self._sessions.get(sid)
            if session and session.pinned:
                session.sort_order = i
                self._save(session)

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def create(self, title: str = "新会话", preset_id: str = "") -> Session:
        session = Session(title=title, preset_id=preset_id)
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

    # ------------------------------------------------------------------ 消息
    def add_message(self, session_id: str, message: Message):
        """向会话追加消息，首条用户消息自动设为会话标题。"""
        session = self._sessions.get(session_id)
        if not session:
            return
        session.messages.append(message)
        session.updated_at = time.time()
        # 从第一条用户消息自动生成标题
        if len(session.messages) == 1 and message.role == "user" and message.content:
            session.title = message.content[:25].strip()
        self._save(session)

    def save_session(self, session_id: str):
        session = self._sessions.get(session_id)
        if session:
            self._save(session)

    def update_system_prompt(self, session_id: str, system_prompt: str, preset_id: str = ""):
        """更新会话的 System Prompt 和预设角色 ID"""
        session = self._sessions.get(session_id)
        if session:
            session.system_prompt = system_prompt
            session.preset_id = preset_id
            self._save(session)

