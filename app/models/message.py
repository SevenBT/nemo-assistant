import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.models.attachment import Attachment


class MessageRole:
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    result: Optional[dict] = None
    status: str = "pending"  # pending | running | success | error

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCall":
        return cls(
            id=d["id"],
            name=d["name"],
            arguments=d.get("arguments", {}),
            result=d.get("result"),
            status=d.get("status", "pending"),
        )


@dataclass
class Message:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = MessageRole.USER
    content: str = ""
    timestamp: float = field(default_factory=time.time)
    tool_calls: list = field(default_factory=list)  # list[ToolCall]
    tool_call_id: Optional[str] = None  # for role=tool messages
    attachments: list = field(default_factory=list)  # list[Attachment]

    def to_api_dict(self) -> dict:
        d: dict = {"role": self.role, "content": self.content or ""}
        if self.role == MessageRole.ASSISTANT and self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
            if not self.content:
                d["content"] = None
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "attachments": [att.to_dict() for att in self.attachments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        tool_calls = [ToolCall.from_dict(tc) for tc in d.get("tool_calls", [])]
        attachments = [Attachment.from_dict(att) for att in d.get("attachments", [])]
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            role=d["role"],
            content=d.get("content", ""),
            timestamp=d.get("timestamp", time.time()),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            attachments=attachments,
        )
