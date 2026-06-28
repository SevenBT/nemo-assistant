"""
定时任务调度器。

基于 APScheduler，支持 cron/interval/date 三种触发方式。
任务配置持久化到 jobs.json，执行时调用 ToolManager 运行对应工具脚本。
"""
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import DATA_DIR

logger = logging.getLogger(__name__)

JOBS_FILE = DATA_DIR / "jobs.json"


class SchedulerManager:
    """定时任务管理器，封装 APScheduler 的生命周期和任务持久化。"""

    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._jobs: dict[str, dict] = {}
        self._tool_manager = None
        self._on_result: Optional[Callable] = None  # (job_id, name, result) -> None

    # ------------------------------------------------------------------ 生命周期
    def set_tool_manager(self, tm):
        """设置工具管理器，用于执行任务关联的工具脚本。"""
        self._tool_manager = tm

    def set_result_callback(self, cb: Callable):
        """设置任务执行结果的回调函数。"""
        self._on_result = cb

    def start(self):
        self._scheduler.start()
        self._load_jobs()

    def stop(self):
        self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------ 任务管理
    def add_job(
        self,
        name: str,
        tool_name: str,
        params: dict,
        trigger_type: str,
        trigger_config: dict,
        description: str = "",
    ) -> str:
        """添加定时任务，返回任务 ID。trigger_type 支持 cron/interval/date。"""
        trigger = self._make_trigger(trigger_type, trigger_config)
        if trigger is None:
            raise ValueError(f"Invalid trigger: {trigger_type} / {trigger_config}")

        job_id = str(uuid.uuid4())
        self._scheduler.add_job(
            func=self._run_job,
            trigger=trigger,
            id=job_id,
            kwargs={"job_id": job_id},
            replace_existing=True,
            misfire_grace_time=60,
        )
        self._jobs[job_id] = {
            "id": job_id,
            "name": name,
            "tool_name": tool_name,
            "params": params,
            "trigger_type": trigger_type,
            "trigger_config": trigger_config,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "enabled": True,
        }
        self._save_jobs()
        return job_id

    def remove_job(self, job_id: str):
        """移除指定任务（从内存和持久化文件中删除）。"""
        self._jobs.pop(job_id, None)
        self._save_jobs()
        # 从 APScheduler 中移除；JobLookupError 可忽略（任务已不存在）
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    def get_jobs(self) -> list[dict]:
        """返回所有任务列表。"""
        return list(self._jobs.values())

    # ------------------------------------------------------------------ 内部实现
    def _make_trigger(self, trigger_type: str, config: dict):
        try:
            if trigger_type == "cron":
                return CronTrigger(**config)
            if trigger_type == "interval":
                return IntervalTrigger(**config)
            if trigger_type == "date":
                return DateTrigger(**config)
        except Exception as e:
            logger.error("[Scheduler] Trigger error: %s", e)
        return None

    def _run_job(self, job_id: str):
        job = self._jobs.get(job_id)
        if not job:
            # 任务已删除但 APScheduler 仍触发了 — 清理残留
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            return
        if not self._tool_manager:
            return
        # 工具执行可能抛异常；不捕获的话 APScheduler 会吞掉、_on_result 永不触发，
        # 用户无从感知失败。包成 error 结果上报，保证回调始终被调用。
        try:
            result = self._tool_manager.execute(job["tool_name"], job["params"])
        except Exception as e:
            logger.exception("[Scheduler] Job '%s' execution failed", job.get("name"))
            result = {"status": "error", "data": {"message": str(e)}}
        if self._on_result:
            self._on_result(job_id, job["name"], result)

    def _save_jobs(self):
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：先写临时文件再替换，避免写一半崩溃损坏 jobs.json 丢失全部任务。
        data = json.dumps(list(self._jobs.values()), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(JOBS_FILE.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, JOBS_FILE)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _load_jobs(self):
        if not JOBS_FILE.exists():
            return
        try:
            with open(JOBS_FILE, encoding="utf-8") as f:
                jobs: list[dict] = json.load(f)
        except Exception as e:
            logger.error("[Scheduler] Load failed: %s", e)
            return

        for job in jobs:
            if not job.get("enabled", True):
                continue
            try:
                trigger = self._make_trigger(job["trigger_type"], job["trigger_config"])
                if trigger:
                    self._scheduler.add_job(
                        func=self._run_job,
                        trigger=trigger,
                        id=job["id"],
                        kwargs={"job_id": job["id"]},
                        replace_existing=True,
                        misfire_grace_time=60,
                    )
                self._jobs[job["id"]] = job
            except Exception as e:
                logger.error("[Scheduler] Restore job '%s' failed: %s", job.get('name'), e)
