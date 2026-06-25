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
        return (
            "管理长期记忆（用户偏好、项目决策、重要事实等），保存的内容会在后续对话中"
            "自动作为上下文提供给你。\n"
            "- action=save：保存一条记忆，需 content + category，可选 scope/importance\n"
            "- action=recall：查看已保存的记忆，可选 category/scope 过滤\n"
            "- action=forget：删除一条记忆，需 memory_id"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",
            action=Str("操作类型", enum=["save", "recall", "forget"]),
            content=Str("action=save 时必填，记忆内容，简洁明确的一句话"),
            category=Str(
                "记忆分类（save 必填，recall 可用于过滤）",
                enum=["personality", "user", "project", "fact"],
            ),
            scope=Str(
                "记忆范围：global=所有会话可见，session=仅当前会话可见（默认 global）",
                enum=["global", "session"],
            ),
            importance=Int("重要性 1-10，默认 5（save 用）", minimum=1, maximum=10),
            memory_id=Int("action=forget 时必填，要删除的记忆 ID"),
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
            "data": {"message": f"未知 action: {action}，应为 save/recall/forget"},
        }

    def _save(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params.get("content")
        if not content:
            return {"status": "error", "data": {"message": "action=save 需要 content"}}
        category = params.get("category")
        if not category:
            return {"status": "error", "data": {"message": "action=save 需要 category"}}
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
            return {"status": "error", "data": {"message": "action=forget 需要 memory_id"}}
        deleted = self._mem.delete(memory_id)
        if deleted:
            return {"status": "success", "data": {"message": f"已删除记忆 #{memory_id}"}}
        return {"status": "error", "data": {"message": f"记忆 #{memory_id} 不存在"}}
