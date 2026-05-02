import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "新会话"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list = field(default_factory=list)  # list[Message]
    system_prompt: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "system_prompt": self.system_prompt,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        from app.models.message import Message

        messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            title=d.get("title", "新会话"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            messages=messages,
            system_prompt=d.get("system_prompt", ""),
        )
