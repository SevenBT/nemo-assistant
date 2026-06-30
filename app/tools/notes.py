"""
笔记工具 — 用单个 NoteTool 按 action 区分读取与创建。

合并自早期的 read_notes / create_note / summarize_session_as_note 三个工具：
  - action=list   读取笔记列表
  - action=create 创建笔记（对话总结存笔记也走这里，模型自己生成 content）

依赖注入示例：通过覆盖 create(ctx) 从 ToolContext 获取 note_mgr，
create 操作还需要 events.note_created 回调来触发 UI 刷新笔记列表。
"""
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params
from app.i18n import t

if TYPE_CHECKING:
    from app.core.note_manager import NoteManager
    from app.tools.context import ToolContext


class NoteTool(BuiltinTool):
    """笔记读写工具，按 action 分发 list / create。"""

    def __init__(self, note_mgr: "NoteManager", on_created: Callable | None = None):
        self._notes = note_mgr
        # 笔记创建后的回调，用于通知 UI 刷新笔记列表
        self._on_created = on_created

    @classmethod
    def create(cls, ctx: "ToolContext") -> "NoteTool":
        """从上下文获取笔记管理器和创建回调。"""
        return cls(note_mgr=ctx.note_mgr, on_created=ctx.events.note_created)

    @property
    def name(self) -> str:
        return "note"

    @property
    def description(self) -> str:
        return t("tool.note.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",
            action=Str(t("tool.note.param.action"), enum=["list", "create"]),
            title=Str(t("tool.note.param.title")),
            content=Str(t("tool.note.param.content")),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "")
        if action == "list":
            return self._list()
        if action == "create":
            return self._create(params)
        return {
            "status": "error",
            "data": {"message": t("tool.note.msg.unknown_action", action=action)},
        }

    def _list(self) -> dict[str, Any]:
        previews = self._notes.get_preview_list()
        return {"status": "success", "data": {"notes": previews, "count": len(previews)}}

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        content = params.get("content")
        if not title or content is None:
            return {"status": "error", "data": {"message": t("tool.note.msg.create_needs_title_content")}}
        try:
            note = self._notes.create(title=title, content=content)
            # 触发 UI 刷新（通过 Qt 信号机制）
            if self._on_created:
                self._on_created()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
