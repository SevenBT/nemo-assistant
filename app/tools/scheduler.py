"""
定时任务工具 — 单个工具通过 action 分发创建、列出、删除三种操作。

设计沿用本项目"多操作单实体"惯例（同 memory 的 save/recall/forget、
note 的 list/create、clipboard 的 get/set）：一个工具用 action 枚举分派，
用户在能力面板里一个开关即可整体开关定时任务能力，不会出现"能查不能建"
的割裂状态。

依赖：SchedulerManager（经 create(ctx) 从 ctx.scheduler 注入）。

定时任务执行机制：
  SchedulerManager 内部使用 APScheduler，到时间后调用
  registry.execute(tool_name, params) 执行指定工具（如 reminder）。
  这就是为什么 MainWindow 中有 scheduler.set_tool_manager(registry)。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Obj, Str, tool_params
from app.i18n import t

if TYPE_CHECKING:
    from app.core.scheduler import SchedulerManager
    from app.tools.context import ToolContext


class ScheduledTaskTool(BuiltinTool):
    """定时任务工具：create / list / delete 三种操作合一。"""

    def __init__(self, scheduler: "SchedulerManager"):
        self._scheduler = scheduler

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ScheduledTaskTool":
        return cls(scheduler=ctx.scheduler)

    @property
    def name(self) -> str:
        return "scheduled_task"

    @property
    def description(self) -> str:
        return t("tool.scheduled_task.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",
            action=Str(t("tool.scheduled_task.param.action"), enum=["create", "list", "delete"]),
            # create 专用
            name=Str(t("tool.scheduled_task.param.name")),
            tool_name=Str(t("tool.scheduled_task.param.tool_name")),
            params=Obj(t("tool.scheduled_task.param.params")),
            trigger_type=Str(t("tool.scheduled_task.param.trigger_type"), enum=["cron", "interval", "date"]),
            trigger_config=Obj(t("tool.scheduled_task.param.trigger_config")),
            description=Str(t("tool.scheduled_task.param.description")),
            # delete 专用
            job_id=Str(t("tool.scheduled_task.param.job_id")),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "")
        if action == "create":
            return self._create(params)
        if action == "list":
            return self._list()
        if action == "delete":
            return self._delete(params)
        return {
            "status": "error",
            "data": {"message": t("tool.scheduled_task.msg.bad_action", action=action)},
        }

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        # create 需要 trigger_type/trigger_config，缺失时给出明确错误而非崩溃
        missing = [k for k in ("trigger_type", "trigger_config") if not params.get(k)]
        if missing:
            return {
                "status": "error",
                "data": {"message": t("tool.scheduled_task.msg.missing", fields="; ".join(missing))},
            }
        try:
            job_id = self._scheduler.add_job(
                name=params.get("name", t("tool.scheduled_task.msg.unnamed")),
                tool_name=params.get("tool_name", ""),
                params=params.get("params", {}),
                trigger_type=params["trigger_type"],
                trigger_config=params["trigger_config"],
                description=params.get("description", ""),
            )
            return {"status": "success", "data": {"job_id": job_id, "name": params.get("name")}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    def _list(self) -> dict[str, Any]:
        jobs = self._scheduler.get_jobs()
        return {
            "status": "success",
            "data": {
                "jobs": [
                    {"id": j["id"], "name": j["name"], "trigger_type": j["trigger_type"]}
                    for j in jobs
                ]
            },
        }

    def _delete(self, params: dict[str, Any]) -> dict[str, Any]:
        job_id = params.get("job_id", "")
        if not job_id:
            return {
                "status": "error",
                "data": {"message": t("tool.scheduled_task.msg.missing", fields="job_id")},
            }
        self._scheduler.remove_job(job_id)
        return {"status": "success", "data": {"deleted": job_id}}
