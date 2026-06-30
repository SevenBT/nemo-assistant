"""
会话管理器。

负责会话的 CRUD、消息追加、置顶排序，数据以 JSON 文件持久化到 SESSIONS_DIR。
"""
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from app.core.config import SESSIONS_DIR
from app.models.message import Message
from app.models.session import is_default_session_title, SOURCE_MANUAL, Session

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器，管理所有聊天会话的生命周期和持久化。"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        # UI 线程与 AgentLoop QThread 可能并发写同一会话文件，加锁串行化写入。
        self._lock = threading.RLock()
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
                logger.warning("[SessionManager] Failed to load %s: %s", path.name, e)

    def _path(self, session_id: str) -> Path:
        return SESSIONS_DIR / f"{session_id}.json"

    def _save(self, session: Session):
        """原子写入：先写同目录临时文件，再 os.replace 替换，避免写一半崩溃损坏 JSON。"""
        data = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        path = self._path(session.id)
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp, path)  # 同目录替换，Windows/POSIX 均原子
            except Exception:
                Path(tmp).unlink(missing_ok=True)
                raise

    # ------------------------------------------------------------------ CRUD
    def get_sessions(self) -> list[Session]:
        """返回活跃会话列表（不含归档）：置顶在前（按 sort_order），其余按 updated_at 降序。"""
        active = [s for s in self._sessions.values() if not s.archived]
        pinned = sorted(
            [s for s in active if s.pinned],
            key=lambda s: s.sort_order,
        )
        unpinned = sorted(
            [s for s in active if not s.pinned],
            key=lambda s: s.updated_at,
            reverse=True,
        )
        return pinned + unpinned

    def get_archived_sessions(self) -> list[Session]:
        """返回已归档会话，按归档前的 updated_at 降序。"""
        return sorted(
            [s for s in self._sessions.values() if s.archived],
            key=lambda s: s.updated_at,
            reverse=True,
        )

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

    def create(self, title: str | None = None, source: str = SOURCE_MANUAL) -> Session:
        session = Session(source=source) if title is None else Session(title=title, source=source)
        self._sessions[session.id] = session
        self._save(session)
        return session

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)
        p = self._path(session_id)
        if p.exists():
            p.unlink()

    def archive(self, session_id: str):
        """归档会话（软删除）：从列表移除但保留数据，可在设置中恢复。

        归档会取消置顶，避免恢复后仍占据置顶序位。
        """
        session = self._sessions.get(session_id)
        if session:
            session.archived = True
            session.pinned = False
            self._save(session)

    def unarchive(self, session_id: str):
        """恢复已归档会话，重新出现在会话列表中。"""
        session = self._sessions.get(session_id)
        if session:
            session.archived = False
            self._save(session)

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
        # 从第一条用户消息自动生成标题（仅当标题仍是默认值时；
        # 识图等场景已设置自定义标题，不应被覆盖）
        if (
            len(session.messages) == 1
            and message.role == "user"
            and message.content
            and is_default_session_title(session.title)
        ):
            session.title = message.content[:25].strip()
        self._save(session)

    def save_session(self, session_id: str):
        session = self._sessions.get(session_id)
        if session:
            self._save(session)

    def update_system_prompt(self, session_id: str, system_prompt: str):
        """更新会话的 System Prompt"""
        session = self._sessions.get(session_id)
        if session:
            session.system_prompt = system_prompt
            self._save(session)

