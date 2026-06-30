import time
import uuid
from dataclasses import dataclass, field

from app.i18n import t, all_translations

# 会话来源：用于在会话列表里把手动会话与快速会话分开展示。
SOURCE_MANUAL = "manual"        # 主窗手动新建 / 默认
SOURCE_READING = "reading"      # 划词「连续解释」的快速会话（连续上下文）


def default_session_title() -> str:
    """新建会话的默认标题（按当前语言）。"""
    return t("session.defaultTitle")


def is_default_session_title(title: str) -> bool:
    """标题是否仍是「默认标题」——兼容任何语言写入的旧数据（哨兵判断）。"""
    return title in all_translations("session.defaultTitle")


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = field(default_factory=default_session_title)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list = field(default_factory=list)  # list[Message]
    system_prompt: str = ""
    pinned: bool = False  # 是否置顶
    sort_order: int = 0   # 自定义排序序号（越小越靠前）
    source: str = SOURCE_MANUAL  # 会话来源（manual / selection）
    archived: bool = False  # 是否已归档（软删除：不显示在列表，可在设置中恢复）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "system_prompt": self.system_prompt,
            "pinned": self.pinned,
            "sort_order": self.sort_order,
            "source": self.source,
            "archived": self.archived,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        from app.models.message import Message

        messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            title=d.get("title", default_session_title()),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            messages=messages,
            system_prompt=d.get("system_prompt", ""),
            pinned=d.get("pinned", False),
            sort_order=d.get("sort_order", 0),
            source=d.get("source", SOURCE_MANUAL),
            archived=d.get("archived", False),
        )
