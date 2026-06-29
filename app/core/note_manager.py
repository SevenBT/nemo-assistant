"""
Note manager backed by SQLite.

Provides note CRUD, trash management, tag management, and desktop-pin support.

笔记管理器，使用 SQLite 存储。
提供笔记的 CRUD 操作、回收站管理、标签管理和桌面固定功能。
"""

import sqlite3
from datetime import datetime
from typing import Optional, Union

from app.core.db_manager import DatabaseManager
from app.models.note import Note, Folder


class NoteManager:
    """笔记管理器，负责笔记的增删改查和回收站管理。"""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        初始化笔记管理器。

        Args:
            db_manager: 数据库管理器实例，默认创建新实例
        """
        self.db = db_manager or DatabaseManager()
        self.migrate_html_to_markdown()

    @staticmethod
    def _normalize_id(note_id: Union[str, int]) -> int:
        """
        规范化笔记 ID，支持 str 和 int 类型。

        Args:
            note_id: 笔记 ID（str 或 int）

        Returns:
            int: 整数类型的笔记 ID

        Raises:
            ValueError: 如果 ID 无法转换为整数
        """
        try:
            return int(note_id)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid note_id: {note_id}") from e

    # ------------------------------------------------------------------ notes CRUD
    def get_notes(self) -> list[Note]:
        """获取所有未删除的笔记，按 sort_order 排列。"""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM notes
                WHERE is_deleted = 0
                ORDER BY sort_order ASC, updated_at DESC
                """
            )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    def get(self, note_id: Union[str, int]) -> Optional[Note]:
        """
        根据 ID 获取单个笔记。

        Args:
            note_id: 笔记 ID（支持 str 或 int）

        Returns:
            Optional[Note]: 笔记对象，不存在则返回 None
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM notes WHERE id = ? AND is_deleted = 0",
                (note_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            note = Note.from_row(row)
            note.tags = self._get_note_tags(conn, note.id)
            return note

    def create(self, title: str = "新笔记", content: str = "", note_type: str = "note", folder_id: int | None = None) -> Note:
        """
        创建新笔记。

        Args:
            title: 笔记标题
            content: 笔记内容
            note_type: 笔记类型（note | sticky | todo | daily）

        Returns:
            Note: 创建的笔记对象
        """
        note = Note(title=title, content=content, note_type=note_type, folder_id=folder_id)
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (title, content, note_type, folder_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (note.title, note.content, note.note_type, note.folder_id, note.created_at, note.updated_at),
            )
            note.id = cursor.lastrowid
            conn.commit()
        return note

    def update(
        self,
        note_id: Union[str, int],
        title: str,
        content: str,
        tags: list[str] | None = None,
        priority: str | None = None,
        due_date: str | None = None,
        recurrence: str | None = None,
    ) -> Optional[Note]:
        """
        更新笔记内容。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
            title: 新标题
            content: 新内容
            tags: 标签列表（可选）
            priority: 优先级（可选，仅待办）
            due_date: 截止日期（可选，仅待办）
            recurrence: 重复设置（可选，仅待办）

        Returns:
            Optional[Note]: 更新后的笔记对象，不存在则返回 None
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """
                UPDATE notes
                SET title = ?, content = ?, priority = ?, due_date = ?,
                    recurrence = ?, updated_at = ?
                WHERE id = ? AND is_deleted = 0
                """,
                (title, content, priority, due_date, recurrence, now, note_id),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return None

            # 更新标签
            if tags is not None:
                self._set_note_tags(conn, note_id, tags)

            conn.commit()
        return self.get(note_id)

    def delete(self, note_id: Union[str, int]):
        """
        将笔记移入回收站（软删除）。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE notes
                SET is_deleted = 1, deleted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, note_id),
            )
            conn.commit()

    # ------------------------------------------------------------------ trash CRUD
    def get_trash(self) -> list[Note]:
        """
        获取回收站中的所有笔记，按更新时间倒序排列。

        Returns:
            list[Note]: 回收站笔记列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM notes
                WHERE is_deleted = 1
                ORDER BY updated_at DESC
                """
            )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    def trash_count(self) -> int:
        """
        获取回收站中的笔记数量。

        Returns:
            int: 回收站笔记数量
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM notes WHERE is_deleted = 1")
            return cursor.fetchone()[0]

    def restore(self, note_id: Union[str, int]) -> bool:
        """
        从回收站恢复笔记。

        Args:
            note_id: 笔记 ID（支持 str 或 int）

        Returns:
            bool: 恢复成功返回 True，笔记不存在返回 False
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE notes
                SET is_deleted = 0, deleted_at = NULL
                WHERE id = ? AND is_deleted = 1
                """,
                (note_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def purge(self, note_id: Union[str, int]):
        """
        永久删除回收站中的笔记。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()

    def purge_all(self):
        """清空整个回收站。"""
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM notes WHERE is_deleted = 1")
            conn.commit()

    # ------------------------------------------------------------------ pinned notes
    def get_pinned_notes(self) -> list[Note]:
        """
        获取所有钉到桌面的笔记。

        Returns:
            list[Note]: 固定笔记列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM notes
                WHERE is_pinned = 1 AND is_deleted = 0
                ORDER BY updated_at DESC
                """
            )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    def pin_note(self, note_id: Union[str, int], x: int, y: int):
        """
        将笔记钉到桌面。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
            x: 浮窗 X 坐标
            y: 浮窗 Y 坐标
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET is_pinned = 1, pin_position_x = ?, pin_position_y = ?
                WHERE id = ?
                """,
                (x, y, note_id),
            )
            conn.commit()

    def unpin_note(self, note_id: Union[str, int]):
        """
        取消笔记的桌面固定。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET is_pinned = 0, pin_position_x = NULL, pin_position_y = NULL
                WHERE id = ?
                """,
                (note_id,),
            )
            conn.commit()

    def update_pin_position(self, note_id: Union[str, int], x: int, y: int):
        """
        更新固定笔记的浮窗位置。

        Args:
            note_id: 笔记 ID（支持 str 或 int）
            x: 新的 X 坐标
            y: 新的 Y 坐标
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET pin_position_x = ?, pin_position_y = ?
                WHERE id = ? AND is_pinned = 1
                """,
                (x, y, note_id),
            )
            conn.commit()

    # ------------------------------------------------------------------ ai helpers
    def get_preview_list(self, max_preview: int = 100) -> list[dict]:
        """
        获取笔记预览列表，用于 AI 工具调用。

        Args:
            max_preview: 内容预览的最大字符数

        Returns:
            list[dict]: 包含 id、title、preview、updated_at 的字典列表
        """
        notes = self.get_notes()
        return [
            {
                "id": n.id,
                "title": n.title,
                "preview": n.content[:max_preview].replace("\n", " "),
                "updated_at": n.updated_at,
            }
            for n in notes
        ]

    # ------------------------------------------------------------------ tags helpers
    def _get_note_tags(self, conn: sqlite3.Connection, note_id: int) -> list[str]:
        """
        获取笔记的所有标签。

        Args:
            conn: 数据库连接
            note_id: 笔记 ID

        Returns:
            list[str]: 标签名称列表
        """
        cursor = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN note_tags nt ON t.id = nt.tag_id
            WHERE nt.note_id = ?
            ORDER BY t.name
            """,
            (note_id,),
        )
        return [row["name"] for row in cursor.fetchall()]

    def _attach_tags(self, conn: sqlite3.Connection, notes: list[Note]) -> None:
        """批量为一组笔记填充 tags，单次查询替代 N+1（每条笔记一次查询）。"""
        if not notes:
            return
        ids = [n.id for n in notes]
        placeholders = ",".join("?" * len(ids))
        cursor = conn.execute(
            f"""
            SELECT nt.note_id, t.name FROM tags t
            JOIN note_tags nt ON t.id = nt.tag_id
            WHERE nt.note_id IN ({placeholders})
            ORDER BY t.name
            """,
            ids,
        )
        tags_by_note: dict[int, list[str]] = {}
        for row in cursor.fetchall():
            tags_by_note.setdefault(row["note_id"], []).append(row["name"])
        for note in notes:
            note.tags = tags_by_note.get(note.id, [])

    def get_all_tags(self) -> list[str]:
        """
        获取所有标签名称。

        Returns:
            list[str]: 标签名称列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT name FROM tags ORDER BY name")
            return [row["name"] for row in cursor.fetchall()]

    def get_tag_count(self, tag_name: str) -> int:
        """
        获取标签下的笔记数量。

        Args:
            tag_name: 标签名称

        Returns:
            int: 笔记数量
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(DISTINCT n.id) FROM notes n
                JOIN note_tags nt ON n.id = nt.note_id
                JOIN tags t ON nt.tag_id = t.id
                WHERE t.name = ? AND n.is_deleted = 0
                """,
                (tag_name,),
            )
            return cursor.fetchone()[0]

    def get_all_tags_with_count(self) -> list[tuple[str, int]]:
        """
        获取所有标签及其笔记数量。

        Returns:
            list[tuple[str, int]]: (标签名, 笔记数量) 元组列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT t.name, COUNT(DISTINCT n.id) as count
                FROM tags t
                LEFT JOIN note_tags nt ON t.id = nt.tag_id
                LEFT JOIN notes n ON nt.note_id = n.id AND n.is_deleted = 0
                GROUP BY t.id, t.name
                ORDER BY t.name
                """
            )
            return [(row["name"], row["count"]) for row in cursor.fetchall()]

    def search_by_tag(self, tag_name: str) -> list[Note]:
        """
        根据标签搜索笔记。

        Args:
            tag_name: 标签名称

        Returns:
            list[Note]: 笔记列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT n.* FROM notes n
                JOIN note_tags nt ON n.id = nt.note_id
                JOIN tags t ON nt.tag_id = t.id
                WHERE t.name = ? AND n.is_deleted = 0
                ORDER BY n.updated_at DESC
                """,
                (tag_name,),
            )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    def _set_note_tags(self, conn: sqlite3.Connection, note_id: int, tags: list[str]):
        """
        设置笔记的标签（内部方法）。

        Args:
            conn: 数据库连接
            note_id: 笔记 ID
            tags: 标签名称列表
        """
        # 删除现有标签关联
        conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))

        # 添加新标签
        for tag_name in tags:
            tag_name = tag_name.strip()
            if not tag_name:
                continue

            # 获取或创建标签
            cursor = conn.execute(
                "SELECT id FROM tags WHERE name = ?",
                (tag_name,),
            )
            row = cursor.fetchone()
            if row:
                tag_id = row["id"]
            else:
                now = datetime.now().isoformat()
                cursor = conn.execute(
                    "INSERT INTO tags (name, created_at) VALUES (?, ?)",
                    (tag_name, now),
                )
                tag_id = cursor.lastrowid

            # 创建关联
            conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
                (note_id, tag_id),
            )

    # ------------------------------------------------------------------ todo helpers
    def get_notes_by_type(self, note_type: str) -> list[Note]:
        """
        按类型获取笔记。

        Args:
            note_type: 笔记类型（note | todo | daily）

        Returns:
            list[Note]: 笔记列表
        """
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM notes
                WHERE note_type = ? AND is_deleted = 0
                ORDER BY
                    CASE WHEN is_completed = 1 THEN 1 ELSE 0 END,
                    CASE priority
                        WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2
                        WHEN 'P3' THEN 3
                        ELSE 4
                    END,
                    due_date ASC NULLS LAST,
                    updated_at DESC
                """,
                (note_type,),
            )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    def toggle_todo_completed(self, note_id: Union[str, int]) -> bool:
        """
        切换待办的完成状态。

        Args:
            note_id: 笔记 ID（支持 str 或 int）

        Returns:
            bool: 新的完成状态
        """
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            # 获取当前状态
            cursor = conn.execute(
                "SELECT is_completed FROM notes WHERE id = ? AND note_type = 'todo'",
                (note_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            new_state = not bool(row["is_completed"])
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE notes
                SET is_completed = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(new_state), now, note_id),
            )
            conn.commit()
            return new_state

    # ------------------------------------------------------------------ migration
    def migrate_html_to_markdown(self):
        """一次性将旧 HTML 格式的 note 类型笔记内容迁移为 Markdown。"""
        try:
            import html2text
        except ImportError:
            return

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = False
        converter.body_width = 0  # no line wrapping

        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, content FROM notes WHERE note_type = 'note' AND is_deleted = 0"
            )
            rows = cursor.fetchall()
            for row in rows:
                content = row["content"]
                # Detect HTML: contains tags like <p>, <div>, <br>, <b>, etc.
                if content and ("</" in content or "<br" in content):
                    md = converter.handle(content).strip()
                    conn.execute(
                        "UPDATE notes SET content = ? WHERE id = ?",
                        (md, row["id"]),
                    )
            conn.commit()

    def search_notes(
        self,
        keyword: str,
        tags: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        note_types: list[str] | None = None,
    ) -> list[Note]:
        """
        全文搜索笔记（标题 + 内容）。

        Args:
            keyword: 搜索关键词（空格分隔多个关键词）
            tags: 标签过滤列表（可选）
            start_date: 开始日期（可选，ISO 格式）
            end_date: 结束日期（可选，ISO 格式）
            note_types: 笔记类型过滤列表（可选）

        Returns:
            list[Note]: 搜索结果，按相关性排序（标题匹配优先）
        """
        # 空关键词且无其他过滤条件，返回所有笔记
        if not keyword and not tags and not start_date and not end_date and not note_types:
            return self.get_notes()

        with self.db.get_connection() as conn:
            # 构建查询条件
            conditions = ["n.is_deleted = 0"]
            params = []

            # 关键词搜索（不区分大小写，支持多个关键词）
            if keyword:
                keywords = keyword.strip().split()
                keyword_conditions = []
                for kw in keywords:
                    kw_pattern = f"%{kw}%"
                    keyword_conditions.append(
                        "(LOWER(n.title) LIKE LOWER(?) OR LOWER(n.content) LIKE LOWER(?))"
                    )
                    params.extend([kw_pattern, kw_pattern])
                if keyword_conditions:
                    conditions.append(f"({' AND '.join(keyword_conditions)})")

            # 标签过滤
            if tags:
                tag_placeholders = ",".join("?" * len(tags))
                conditions.append(
                    f"""
                    n.id IN (
                        SELECT DISTINCT nt.note_id FROM note_tags nt
                        JOIN tags t ON nt.tag_id = t.id
                        WHERE t.name IN ({tag_placeholders})
                    )
                    """
                )
                params.extend(tags)

            # 日期范围过滤
            if start_date:
                conditions.append("n.created_at >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("n.created_at <= ?")
                params.append(end_date)

            # 笔记类型过滤
            if note_types:
                type_placeholders = ",".join("?" * len(note_types))
                conditions.append(f"n.note_type IN ({type_placeholders})")
                params.extend(note_types)

            # 构建完整查询
            where_clause = " AND ".join(conditions)

            # 如果有关键词，按相关性排序（标题匹配优先）
            # 注意：ORDER BY 的参数必须追加在所有 WHERE 参数之后（SQL 中 ORDER BY 在 WHERE 之后）
            order_params: list = []
            if keyword:
                keywords = keyword.strip().split()
                # 计算标题匹配分数（关键词参数化，避免 SQL 注入）
                title_match_cases = []
                for kw in keywords:
                    title_match_cases.append(
                        "(CASE WHEN LOWER(n.title) LIKE LOWER(?) THEN 1 ELSE 0 END)"
                    )
                    order_params.append(f"%{kw}%")
                title_match_score = " + ".join(title_match_cases)
                order_clause = f"({title_match_score}) DESC, n.updated_at DESC"
            else:
                order_clause = "n.updated_at DESC"

            query = f"""
                SELECT DISTINCT n.* FROM notes n
                WHERE {where_clause}
                ORDER BY {order_clause}
            """

            cursor = conn.execute(query, params + order_params)
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

    # ------------------------------------------------------------------ folder CRUD
    def get_folders(self) -> list[Folder]:
        """获取所有文件夹，按 sort_order 排序。"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM folders ORDER BY sort_order, name")
            return [Folder.from_row(row) for row in cursor.fetchall()]

    def create_folder(self, name: str, parent_id: int | None = None) -> Folder:
        """创建文件夹。"""
        folder = Folder(name=name, parent_id=parent_id)
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO folders (name, parent_id, sort_order, created_at) VALUES (?, ?, ?, ?)",
                (folder.name, folder.parent_id, folder.sort_order, folder.created_at),
            )
            folder.id = cursor.lastrowid
            conn.commit()
        return folder

    def rename_folder(self, folder_id: int, name: str) -> bool:
        """重命名文件夹。"""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE folders SET name = ? WHERE id = ?", (name, folder_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_folder(self, folder_id: int, move_notes_to: int | None = None):
        """删除文件夹。笔记移到 move_notes_to 文件夹，或置为无文件夹（None）。"""
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE notes SET folder_id = ? WHERE folder_id = ?",
                (move_notes_to, folder_id),
            )
            conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
            conn.commit()

    def move_note_to_folder(self, note_id: int | str, folder_id: int | None):
        """将笔记移入文件夹（folder_id=None 表示移出文件夹）。"""
        note_id = self._normalize_id(note_id)
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE notes SET folder_id = ? WHERE id = ?", (folder_id, note_id)
            )
            conn.commit()

    def reorder_notes(self, ordered_ids: list[int], folder_id: int | None):
        """
        按给定顺序更新同一 folder_id 下笔记的 sort_order，
        同时将这些笔记的 folder_id 设为 folder_id。
        ordered_ids 是该 folder（或顶层）内笔记的完整有序列表。
        """
        with self.db.get_connection() as conn:
            for idx, note_id in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE notes SET sort_order = ?, folder_id = ? WHERE id = ?",
                    (idx, folder_id, note_id),
                )
            conn.commit()

    def get_notes_in_folder(self, folder_id: int | None) -> list[Note]:
        """获取指定文件夹内的笔记，按 sort_order 排列。"""
        with self.db.get_connection() as conn:
            if folder_id is None:
                cursor = conn.execute(
                    "SELECT * FROM notes WHERE folder_id IS NULL AND is_deleted = 0 ORDER BY sort_order ASC, updated_at DESC"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM notes WHERE folder_id = ? AND is_deleted = 0 ORDER BY sort_order ASC, updated_at DESC",
                    (folder_id,),
                )
            notes = [Note.from_row(row) for row in cursor.fetchall()]
            self._attach_tags(conn, notes)
            return notes

