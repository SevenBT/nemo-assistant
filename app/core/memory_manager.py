"""
记忆管理器 — 负责 memories 表的 CRUD 和生命周期管理。
"""
from __future__ import annotations

import time
from typing import Optional

from app.core.db_manager import DatabaseManager
from app.models.memory import Memory, MemoryCategory, MemoryScope


class MemoryManager:
    """记忆的持久化管理，基于 SQLite。"""

    def __init__(self, db: DatabaseManager):
        self._db = db
        self._ensure_table()

    def _ensure_table(self):
        with self._db.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'fact',
                    scope TEXT NOT NULL DEFAULT 'global',
                    session_id TEXT,
                    source TEXT NOT NULL DEFAULT 'tool',
                    importance INTEGER NOT NULL DEFAULT 5,
                    is_processed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories(scope, session_id);
                CREATE INDEX IF NOT EXISTS idx_memories_category
                    ON memories(category);
                CREATE INDEX IF NOT EXISTS idx_memories_is_processed
                    ON memories(is_processed);
            """)
            conn.commit()

    # ─── CRUD ───────────────────────────────────────────────

    def add(
        self,
        content: str,
        category: str = MemoryCategory.FACT,
        scope: str = MemoryScope.GLOBAL,
        session_id: Optional[str] = None,
        importance: int = 5,
        source: str = "tool",
    ) -> Memory:
        now = time.time()
        with self._db.get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO memories
                   (content, category, scope, session_id, source, importance,
                    is_processed, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (content, category, scope, session_id, source, importance, now, now),
            )
            conn.commit()
            memory_id = cur.lastrowid
        return Memory(
            id=memory_id,
            content=content,
            category=category,
            scope=scope,
            session_id=session_id,
            source=source,
            importance=importance,
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        memory_id: int,
        content: Optional[str] = None,
        category: Optional[str] = None,
        importance: Optional[int] = None,
        is_processed: Optional[bool] = None,
    ) -> bool:
        fields = []
        values = []
        if content is not None:
            fields.append("content = ?")
            values.append(content)
        if category is not None:
            fields.append("category = ?")
            values.append(category)
        if importance is not None:
            fields.append("importance = ?")
            values.append(importance)
        if is_processed is not None:
            fields.append("is_processed = ?")
            values.append(int(is_processed))
        if not fields:
            return False
        fields.append("updated_at = ?")
        values.append(time.time())
        values.append(memory_id)
        with self._db.get_connection() as conn:
            conn.execute(
                f"UPDATE memories SET {', '.join(fields)} WHERE id = ?", values
            )
            conn.commit()
        return True

    def delete(self, memory_id: int) -> bool:
        with self._db.get_connection() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_by_id(self, memory_id: int) -> Optional[Memory]:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            return Memory.from_row(row) if row else None

    # ─── 查询 ──────────────────────────────────────────────

    def get_global(self, category: Optional[str] = None) -> list[Memory]:
        """获取所有全局记忆。"""
        sql = "SELECT * FROM memories WHERE scope = 'global'"
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY importance DESC, updated_at DESC"
        with self._db.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [Memory.from_row(r) for r in rows]

    def get_for_session(self, session_id: str) -> list[Memory]:
        """获取特定 session 的局部记忆。"""
        sql = """SELECT * FROM memories
                 WHERE scope = 'session' AND session_id = ?
                 ORDER BY importance DESC, updated_at DESC"""
        with self._db.get_connection() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
            return [Memory.from_row(r) for r in rows]

    def get_context_memories(self, session_id: str) -> list[Memory]:
        """获取注入 system prompt 的记忆：全局 + 当前 session 局部。
        排除 archive 类型（那是 Dream 的原料，不直接注入）。"""
        sql = """SELECT * FROM memories
                 WHERE category != 'archive'
                   AND (scope = 'global' OR (scope = 'session' AND session_id = ?))
                 ORDER BY importance DESC, updated_at DESC"""
        with self._db.get_connection() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
            return [Memory.from_row(r) for r in rows]

    def get_unprocessed_archives(self) -> list[Memory]:
        """获取未被 Dream 处理的 archive 记忆。"""
        sql = """SELECT * FROM memories
                 WHERE category = 'archive' AND is_processed = 0
                 ORDER BY created_at ASC"""
        with self._db.get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [Memory.from_row(r) for r in rows]

    def mark_archives_processed(self, ids: list[int]):
        """标记 archive 记忆为已处理。"""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._db.get_connection() as conn:
            conn.execute(
                f"UPDATE memories SET is_processed = 1, updated_at = ? "
                f"WHERE id IN ({placeholders})",
                [time.time()] + ids,
            )
            conn.commit()

    def purge_processed_archives(self, max_age_days: int = 7) -> int:
        """删除已被 Dream 处理且超过保留期的 archive 摘要。

        archive 经 Dream 提炼成结构化记忆后，原始摘要已无保留价值，
        定期清理避免 memories 表单调膨胀。返回删除行数。"""
        cutoff = time.time() - max_age_days * 86400
        with self._db.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM memories "
                "WHERE category = 'archive' AND is_processed = 1 AND updated_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    def build_memory_context(self, session_id: str, max_chars: int = 4000) -> str:
        """构建注入 system prompt 的记忆文本块。"""
        memories = self.get_context_memories(session_id)
        if not memories:
            return ""
        lines = []
        total = 0
        for m in memories:
            line = f"- [{m.category}] {m.content}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        if not lines:
            return ""
        return "## 长期记忆\n\n" + "\n".join(lines)

    # ─── 维护 ──────────────────────────────────────────────

    def count(self, scope: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM memories"
        params: list = []
        if scope:
            sql += " WHERE scope = ?"
            params.append(scope)
        with self._db.get_connection() as conn:
            return conn.execute(sql, params).fetchone()[0]
