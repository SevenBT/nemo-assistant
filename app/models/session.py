import time
import uuid
from dataclasses import dataclass, field

DEFAULT_SESSION_TITLE = "新会话"

# 会话来源：用于在会话列表里把手动会话与划词速记分开展示。
SOURCE_MANUAL = "manual"        # 主窗手动新建 / 默认
SOURCE_SELECTION = "selection"  # 划词气泡续聊产生


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = DEFAULT_SESSION_TITLE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list = field(default_factory=list)  # list[Message]
    system_prompt: str = ""
    pinned: bool = False  # 是否置顶
    sort_order: int = 0   # 自定义排序序号（越小越靠前）
    source: str = SOURCE_MANUAL  # 会话来源（manual / selection）

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
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        from app.models.message import Message

        messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            title=d.get("title", DEFAULT_SESSION_TITLE),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            messages=messages,
            system_prompt=d.get("system_prompt", ""),
            pinned=d.get("pinned", False),
            sort_order=d.get("sort_order", 0),
            source=d.get("source", SOURCE_MANUAL),
        )
