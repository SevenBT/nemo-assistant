"""
SQLite 数据库管理器。

负责数据库连接、表结构创建、索引和触发器管理。
"""

import sqlite3
from pathlib import Path
from typing import Optional

from app.core.config import DATA_DIR


class DatabaseManager:
    """SQLite 数据库管理器，提供连接和表结构初始化。"""

    def __init__(self, db_path: Optional[Path] = None):
        """
        初始化数据库管理器。

        Args:
            db_path: 数据库文件路径，默认为 DATA_DIR / "notes.db"
        """
        self.db_path = db_path or (DATA_DIR / "notes.db")
        self._ensure_schema()

    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接。

        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        conn = sqlite3.Connection(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        """确保数据库表结构存在，如果不存在则创建。"""
        with self.get_connection() as conn:
            self._create_tables(conn)
            self._create_indexes(conn)
            self._create_triggers(conn)

    def _create_tables(self, conn: sqlite3.Connection):
        """创建所有表结构。"""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '新笔记',
                content TEXT NOT NULL DEFAULT '',
                note_type TEXT NOT NULL DEFAULT 'note',
                priority TEXT,
                due_date TEXT,
                recurrence TEXT,
                is_completed INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                is_pinned INTEGER NOT NULL DEFAULT 0,
                pin_position_x INTEGER,
                pin_position_y INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS note_tags (
                note_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (note_id, tag_id),
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()

    def _create_indexes(self, conn: sqlite3.Connection):
        """创建索引以优化查询性能。"""
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_notes_is_deleted ON notes(is_deleted);
            CREATE INDEX IF NOT EXISTS idx_notes_is_pinned ON notes(is_pinned);
            CREATE INDEX IF NOT EXISTS idx_notes_note_type ON notes(note_type);
            CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notes_due_date ON notes(due_date);
            CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
            CREATE INDEX IF NOT EXISTS idx_attachments_note_id ON attachments(note_id);
            """
        )
        conn.commit()

    def _create_triggers(self, conn: sqlite3.Connection):
        """创建触发器以自动更新时间戳。"""
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS update_notes_timestamp
            AFTER UPDATE ON notes
            FOR EACH ROW
            BEGIN
                UPDATE notes SET updated_at = datetime('now') WHERE id = NEW.id;
            END;
            """
        )
        conn.commit()

