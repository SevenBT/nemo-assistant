"""
定时任务工具 — 创建、列出、删除定时任务。

这是"多工具共享依赖"的示例：
  - 三个工具类都依赖 SchedulerManager
  - 每个类独立覆盖 create(ctx) 获取 scheduler
  - 一个文件定义三个工具，loader 自动发现并注册全部

定时任务执行机制：
  SchedulerManager 内部使用 APScheduler，到时间后调用
  registry.execute(tool_name, params) 执行指定工具。
  这就是为什么 MainWindow 中有 scheduler.set_tool_manager(registry)。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Obj, Str, tool_params

if TYPE_CHECKING:
    from app.core.scheduler import SchedulerManager
    from app.tools.context import ToolContext


class CreateScheduledTaskTool(BuiltinTool):
    """创建定时任务工具。"""

    def __init__(self, scheduler: "SchedulerManager"):
        self._scheduler = scheduler

    @classmethod
    def create(cls, ctx: "ToolContext") -> "CreateScheduledTaskTool":
        return cls(scheduler=ctx.scheduler)

    @property
    def name(self) -> str:
        return "create_scheduled_task"

    @property
    def description(self) -> str:
        return "创建一个定时任务，定期执行某个工具脚本或提醒用户"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "name", "tool_name", "trigger_type", "trigger_config",
            name=Str("任务名称"),
            tool_name=Str("要执行的工具名称"),
            params=Obj("工具参数，JSON对象"),
            trigger_type=Str("触发器类型", enum=["cron", "interval", "date"]),
            trigger_config=Obj("触发器配置，如 {hour:9, minute:0} 或 {hours:1}"),
            description=Str("任务描述"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            job_id = self._scheduler.add_job(
                name=params.get("name", "未命名任务"),
                tool_name=params.get("tool_name", ""),
                params=params.get("params", {}),
                trigger_type=params["trigger_type"],
                trigger_config=params["trigger_config"],
                description=params.get("description", ""),
            )
            return {"status": "success", "data": {"job_id": job_id, "name": params.get("name")}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}


class ListScheduledTasksTool(BuiltinTool):
    """列出所有定时任务工具。"""

    def __init__(self, scheduler: "SchedulerManager"):
        self._scheduler = scheduler

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ListScheduledTasksTool":
        return cls(scheduler=ctx.scheduler)

    @property
    def name(self) -> str:
        return "list_scheduled_tasks"

    @property
    def description(self) -> str:
        return "列出所有当前定时任务"

    @property
    def parameters(self) -> dict[str, Any]:
        # 无参数
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        """查询操作，无副作用。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
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


class DeleteScheduledTaskTool(BuiltinTool):
    """删除定时任务工具。"""

    def __init__(self, scheduler: "SchedulerManager"):
        self._scheduler = scheduler

    @classmethod
    def create(cls, ctx: "ToolContext") -> "DeleteScheduledTaskTool":
        return cls(scheduler=ctx.scheduler)

    @property
    def name(self) -> str:
        return "delete_scheduled_task"

    @property
    def description(self) -> str:
        return "删除一个定时任务"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "job_id",
            job_id=Str("任务ID"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        job_id = params.get("job_id", "")
        self._scheduler.remove_job(job_id)
        return {"status": "success", "data": {"deleted": job_id}}
