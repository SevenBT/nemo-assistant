"""
笔记工具 — 读取、创建、总结。

这是"需要依赖注入"的工具示例：
  - 三个工具类都需要 NoteManager 依赖
  - 通过覆盖 create(ctx) 从 ToolContext 获取 note_mgr
  - CreateNoteTool 和 SummarizeSessionTool 还需要 events.note_created 回调
    （用于触发 UI 刷新笔记列表）

一个 .py 文件中可以定义多个工具类，loader 会自动发现并注册所有类。
"""
from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params

if TYPE_CHECKING:
    from app.core.note_manager import NoteManager
    from app.tools.context import ToolContext


class ReadNotesTool(BuiltinTool):
    """读取用户笔记列表工具。"""

    def __init__(self, note_mgr: "NoteManager"):
        self._notes = note_mgr

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ReadNotesTool":
        """从上下文获取笔记管理器。"""
        return cls(note_mgr=ctx.note_mgr)

    @property
    def name(self) -> str:
        return "read_notes"

    @property
    def description(self) -> str:
        return "读取用户所有笔记的列表，包含标题、内容预览和更新时间"

    @property
    def parameters(self) -> dict[str, Any]:
        # 无参数工具：properties 为空对象
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        """只读操作，可并发执行。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        previews = self._notes.get_preview_list()
        return {"status": "success", "data": {"notes": previews, "count": len(previews)}}


class CreateNoteTool(BuiltinTool):
    """创建新笔记工具。"""

    def __init__(self, note_mgr: "NoteManager", on_created: Callable | None = None):
        self._notes = note_mgr
        # 笔记创建后的回调，用于通知 UI 刷新笔记列表
        self._on_created = on_created

    @classmethod
    def create(cls, ctx: "ToolContext") -> "CreateNoteTool":
        """从上下文获取笔记管理器和创建回调。"""
        return cls(note_mgr=ctx.note_mgr, on_created=ctx.events.note_created)

    @property
    def name(self) -> str:
        return "create_note"

    @property
    def description(self) -> str:
        return "创建一条新笔记，保存标题和正文内容"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "title", "content",  # 两个都是必填参数
            title=Str("笔记标题，简明扼要"),
            content=Str("笔记正文内容"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            note = self._notes.create(
                title=params.get("title", "新笔记"),
                content=params.get("content", ""),
            )
            # 触发 UI 刷新（通过 Qt 信号机制）
            if self._on_created:
                self._on_created()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}


class SummarizeSessionTool(BuiltinTool):
    """将对话内容总结为笔记的工具。"""

    def __init__(self, note_mgr: "NoteManager", on_created: Callable | None = None):
        self._notes = note_mgr
        self._on_created = on_created

    @classmethod
    def create(cls, ctx: "ToolContext") -> "SummarizeSessionTool":
        """从上下文获取笔记管理器和创建回调。"""
        return cls(note_mgr=ctx.note_mgr, on_created=ctx.events.note_created)

    @property
    def name(self) -> str:
        return "summarize_session_as_note"

    @property
    def description(self) -> str:
        return "将当前会话的对话内容总结，并作为笔记保存"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "title", "summary",
            title=Str("笔记标题（简要概括本次对话主题）"),
            summary=Str("对话内容的总结文本"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            note = self._notes.create(
                title=params.get("title", "会话总结"),
                content=params.get("summary", ""),
            )
            if self._on_created:
                self._on_created()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
