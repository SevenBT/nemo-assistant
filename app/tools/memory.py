"""
记忆工具 — 让 AI 能主动保存、检索、删除记忆。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params

if TYPE_CHECKING:
    from app.core.memory_manager import MemoryManager
    from app.tools.context import ToolContext


class SaveMemoryTool(BuiltinTool):
    """保存一条记忆。"""

    def __init__(self, memory_mgr: "MemoryManager"):
        self._mem = memory_mgr

    @classmethod
    def create(cls, ctx: "ToolContext") -> "SaveMemoryTool":
        return cls(memory_mgr=ctx.extra["memory_mgr"])

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return (
            "保存一条长期记忆。用于记住用户偏好、项目决策、重要事实等信息，"
            "这些信息会在后续对话中自动提供给你作为上下文。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "content", "category",
            content=Str("记忆内容，简洁明确的一句话描述"),
            category=Str(
                "记忆分类",
                enum=["personality", "user", "project", "fact"],
            ),
            scope=Str(
                "记忆范围：global=所有会话可见，session=仅当前会话可见",
                enum=["global", "session"],
            ),
            importance=Int("重要性 1-10，默认 5", minimum=1, maximum=10),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params["content"]
        category = params["category"]
        scope = params.get("scope", "global")
        importance = params.get("importance", 5)
        session_id = params.get("_session_id")  # 由 AgentLoop 注入

        memory = self._mem.add(
            content=content,
            category=category,
            scope=scope,
            session_id=session_id if scope == "session" else None,
            importance=importance,
            source="tool",
        )
        return {
            "status": "success",
            "data": {"id": memory.id, "message": f"已保存记忆: {content[:50]}"},
        }


class RecallMemoryTool(BuiltinTool):
    """检索记忆。"""

    def __init__(self, memory_mgr: "MemoryManager"):
        self._mem = memory_mgr

    @classmethod
    def create(cls, ctx: "ToolContext") -> "RecallMemoryTool":
        return cls(memory_mgr=ctx.extra["memory_mgr"])

    @property
    def name(self) -> str:
        return "recall_memory"

    @property
    def description(self) -> str:
        return "检索已保存的记忆，查看当前记住了哪些信息"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            category=Str(
                "按分类过滤，不传则返回所有",
                enum=["personality", "user", "project", "fact"],
            ),
            scope=Str("按范围过滤", enum=["global", "session"]),
        )

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        category = params.get("category")
        scope = params.get("scope")
        session_id = params.get("_session_id")

        if scope == "session" and session_id:
            memories = self._mem.get_for_session(session_id)
            if category:
                memories = [m for m in memories if m.category == category]
        elif scope == "global" or not scope:
            memories = self._mem.get_global(category=category)
        else:
            memories = self._mem.get_global(category=category)

        items = [
            {"id": m.id, "content": m.content, "category": m.category,
             "scope": m.scope, "importance": m.importance}
            for m in memories
        ]
        return {"status": "success", "data": {"memories": items, "count": len(items)}}


class ForgetMemoryTool(BuiltinTool):
    """删除一条记忆。"""

    def __init__(self, memory_mgr: "MemoryManager"):
        self._mem = memory_mgr

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ForgetMemoryTool":
        return cls(memory_mgr=ctx.extra["memory_mgr"])

    @property
    def name(self) -> str:
        return "forget_memory"

    @property
    def description(self) -> str:
        return "删除一条已保存的记忆（通过 ID）"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "memory_id",
            memory_id=Int("要删除的记忆 ID"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        memory_id = params["memory_id"]
        deleted = self._mem.delete(memory_id)
        if deleted:
            return {"status": "success", "data": {"message": f"已删除记忆 #{memory_id}"}}
        return {"status": "error", "data": {"message": f"记忆 #{memory_id} 不存在"}}
