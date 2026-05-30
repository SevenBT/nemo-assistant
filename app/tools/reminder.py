"""
提醒工具 — 向用户发送提醒消息。

这是最简单的工具之一：
  - 无外部依赖
  - 无副作用（只返回消息文本）
  - 通常配合定时任务使用：scheduler 到时间后调用 reminder 工具

使用场景：
  用户说"每天早上9点提醒我喝水"
  → LLM 调用 create_scheduled_task，tool_name="reminder"，
    trigger_type="cron"，trigger_config={hour:9}
  → 每天9点 scheduler 自动执行 reminder 工具
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params


class ReminderTool(BuiltinTool):
    """提醒消息工具，配合定时任务使用。"""

    @property
    def name(self) -> str:
        return "reminder"

    @property
    def description(self) -> str:
        return "向用户发送一条提醒消息，适合配合定时任务使用"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "message",
            message=Str("要提醒的内容，例如：该写作业了"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        message = params.get("message", "提醒")
        now = datetime.now().strftime("%H:%M:%S")
        return {"status": "success", "data": {"message": message, "time": now}}
