import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional


class MemoryCategory:
    PERSONALITY = "personality"  # AI 人设/行为风格
    USER = "user"               # 用户身份/偏好/习惯
    PROJECT = "project"         # 项目决策/技术选型/架构
    FACT = "fact"               # 具体事实
    ARCHIVE = "archive"         # Consolidator 生成的对话摘要（Dream 的输入）


class MemoryScope:
    GLOBAL = "global"    # 所有 session 共享
    SESSION = "session"  # 仅特定 session 可见


@dataclass
class Memory:
    id: Optional[int] = None
    content: str = ""
    category: str = MemoryCategory.FACT
    scope: str = MemoryScope.GLOBAL
    session_id: Optional[str] = None
    source: str = "tool"          # dream | consolidator | tool
    importance: int = 5           # 1-10
    is_processed: bool = False    # Dream 是否已处理（仅 archive 类型用）
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "scope": self.scope,
            "session_id": self.session_id,
            "source": self.source,
            "importance": self.importance,
            "is_processed": self.is_processed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Memory":
        return cls(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            scope=row["scope"],
            session_id=row["session_id"],
            source=row["source"],
            importance=row["importance"],
            is_processed=bool(row["is_processed"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
