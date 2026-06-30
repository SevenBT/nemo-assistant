"""
记忆工具 — 让 AI 能主动保存、检索、删除记忆。

单个 MemoryTool 用 action 参数区分三种操作（save / recall / forget），
替代早期拆分的 save_memory / recall_memory / forget_memory 三个工具，
减少发给模型的工具数量。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params
from app.i18n import t

if TYPE_CHECKING:
    from app.core.memory_manager import MemoryManager
    from app.tools.context import ToolContext


class MemoryTool(BuiltinTool):
    """长期记忆读写工具，按 action 分发 save / recall / forget。"""

    def __init__(self, memory_mgr: "MemoryManager"):
        self._mem = memory_mgr

    @classmethod
    def create(cls, ctx: "ToolContext") -> "MemoryTool":
        return cls(memory_mgr=ctx.extra["memory_mgr"])

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return t("tool.memory.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",
            action=Str(t("tool.memory.param.action"), enum=["save", "recall", "forget"]),
            content=Str(t("tool.memory.param.content")),
            category=Str(
                t("tool.memory.param.category"),
                enum=["personality", "user", "project", "fact"],
            ),
            scope=Str(
                t("tool.memory.param.scope"),
                enum=["global", "session"],
            ),
            importance=Int(t("tool.memory.param.importance"), minimum=1, maximum=10),
            memory_id=Int(t("tool.memory.param.memory_id")),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "")
        if action == "save":
            return self._save(params)
        if action == "recall":
            return self._recall(params)
        if action == "forget":
            return self._forget(params)
        return {
            "status": "error",
            "data": {"message": t("tool.memory.msg.unknown_action", action=action)},
        }

    def _save(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params.get("content")
        if not content:
            return {"status": "error", "data": {"message": t("tool.memory.msg.save_needs_content")}}
        category = params.get("category")
        if not category:
            return {"status": "error", "data": {"message": t("tool.memory.msg.save_needs_category")}}
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
            "data": {"id": memory.id, "message": t("tool.memory.msg.saved", content=content[:50])},
        }

    def _recall(self, params: dict[str, Any]) -> dict[str, Any]:
        category = params.get("category")
        scope = params.get("scope")
        session_id = params.get("_session_id")

        if scope == "session" and session_id:
            memories = self._mem.get_for_session(session_id)
            if category:
                memories = [m for m in memories if m.category == category]
        else:
            memories = self._mem.get_global(category=category)

        items = [
            {"id": m.id, "content": m.content, "category": m.category,
             "scope": m.scope, "importance": m.importance}
            for m in memories
        ]
        return {"status": "success", "data": {"memories": items, "count": len(items)}}

    def _forget(self, params: dict[str, Any]) -> dict[str, Any]:
        memory_id = params.get("memory_id")
        if memory_id is None:
            return {"status": "error", "data": {"message": t("tool.memory.msg.forget_needs_id")}}
        deleted = self._mem.delete(memory_id)
        if deleted:
            return {"status": "success", "data": {"message": t("tool.memory.msg.deleted", memory_id=memory_id)}}
        return {"status": "error", "data": {"message": t("tool.memory.msg.not_found", memory_id=memory_id)}}
