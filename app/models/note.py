import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Note:
    """笔记模型，支持多种类型（笔记、待办、日记）和桌面固定功能。"""

    id: Optional[int] = None
    title: str = "新笔记"
    content: str = ""
    note_type: str = "note"  # note | todo | daily
    priority: Optional[str] = None  # P1 | P2 | P3
    due_date: Optional[str] = None
    recurrence: Optional[str] = None
    is_completed: bool = False
    is_deleted: bool = False
    is_pinned: bool = False
    pin_position_x: Optional[int] = None
    pin_position_y: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        """初始化时设置默认时间戳。"""
        now = datetime.now().isoformat()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    def to_dict(self) -> dict:
        """转换为字典格式，用于 JSON 序列化或 API 响应。"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "note_type": self.note_type,
            "priority": self.priority,
            "due_date": self.due_date,
            "recurrence": self.recurrence,
            "is_completed": self.is_completed,
            "is_deleted": self.is_deleted,
            "is_pinned": self.is_pinned,
            "pin_position_x": self.pin_position_x,
            "pin_position_y": self.pin_position_y,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        """从字典创建 Note 对象，用于 JSON 反序列化。"""
        return cls(
            id=d.get("id"),
            title=d.get("title", "新笔记"),
            content=d.get("content", ""),
            note_type=d.get("note_type", "note"),
            priority=d.get("priority"),
            due_date=d.get("due_date"),
            recurrence=d.get("recurrence"),
            is_completed=d.get("is_completed", False),
            is_deleted=d.get("is_deleted", False),
            is_pinned=d.get("is_pinned", False),
            pin_position_x=d.get("pin_position_x"),
            pin_position_y=d.get("pin_position_y"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            deleted_at=d.get("deleted_at"),
            tags=d.get("tags", []),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Note":
        """从数据库行创建 Note 对象。"""
        return cls(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            note_type=row["note_type"],
            priority=row["priority"],
            due_date=row["due_date"],
            recurrence=row["recurrence"],
            is_completed=bool(row["is_completed"]),
            is_deleted=bool(row["is_deleted"]),
            is_pinned=bool(row["is_pinned"]),
            pin_position_x=row["pin_position_x"],
            pin_position_y=row["pin_position_y"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
            tags=[],  # 标签需要单独查询
        )
