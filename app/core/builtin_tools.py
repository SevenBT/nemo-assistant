"""
内置工具定义与处理器。

包含定时任务、笔记操作、计算器、剪贴板等内置工具的 schema 和执行逻辑。
从 main_window.py 中抽离，保持 UI 代码专注于界面。
"""
import math
from typing import Callable

from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager

BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_scheduled_task",
            "description": "创建一个定时任务，定期执行某个工具脚本或提醒用户",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"},
                    "tool_name": {"type": "string", "description": "要执行的工具名称"},
                    "params": {"type": "object", "description": "工具参数，JSON对象"},
                    "trigger_type": {
                        "type": "string",
                        "enum": ["cron", "interval", "date"],
                        "description": "触发器类型",
                    },
                    "trigger_config": {
                        "type": "object",
                        "description": "触发器配置，如 {hour:9, minute:0} 或 {hours:1}",
                    },
                    "description": {"type": "string", "description": "任务描述"},
                },
                "required": ["name", "tool_name", "trigger_type", "trigger_config"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_tasks",
            "description": "列出所有当前定时任务",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_scheduled_task",
            "description": "删除一个定时任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID"}
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "读取用户所有笔记的列表，包含标题、内容预览和更新时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "创建一条新笔记，保存标题和正文内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题，简明扼要"},
                    "content": {"type": "string", "description": "笔记正文内容"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_session_as_note",
            "description": "将当前会话的对话内容总结，并作为笔记保存",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题（简要概括本次对话主题）"},
                    "summary": {"type": "string", "description": "对话内容的总结文本"},
                },
                "required": ["title", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，支持四则运算、幂次、三角函数、对数、常数 pi/e 等",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的数学表达式，如 '2**10'、'sin(pi/4)'、'log(100, 10)'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard",
            "description": "读取或写入系统剪贴板。action=get 读取当前内容，action=set 将 content 写入剪贴板",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set"],
                        "description": "操作类型：get（读取剪贴板）或 set（写入剪贴板）",
                    },
                    "content": {
                        "type": "string",
                        "description": "当 action=set 时，要写入剪贴板的文本内容",
                    },
                },
                "required": ["action"],
            },
        },
    },
]


class BuiltinToolHandler:
    """内置工具执行器，与 UI 解耦，可独立测试。"""

    _CALC_ALLOWED: dict = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    _CALC_ALLOWED.update({"abs": abs, "round": round, "int": int, "float": float,
                           "pow": pow, "sum": sum, "min": min, "max": max})

    def __init__(
        self,
        scheduler: SchedulerManager,
        note_mgr: NoteManager,
        on_note_created: Callable,
    ):
        self._scheduler = scheduler
        self._notes = note_mgr
        self._on_note_created = on_note_created

    def get_handlers(self) -> dict:
        return {
            "create_scheduled_task": self._handle_create_task,
            "list_scheduled_tasks": self._handle_list_tasks,
            "delete_scheduled_task": self._handle_delete_task,
            "read_notes": self._handle_read_notes,
            "create_note": self._handle_create_note,
            "summarize_session_as_note": self._handle_summarize_as_note,
            "calculator": self._handle_calculator,
            "clipboard": self._handle_clipboard,
        }

    # ── 定时任务工具 ───────────────────────────────────────────────

    def _handle_create_task(self, args: dict) -> dict:
        """创建定时任务，支持 cron/interval/date 三种触发方式。"""
        try:
            job_id = self._scheduler.add_job(
                name=args.get("name", "未命名任务"),
                tool_name=args.get("tool_name", ""),
                params=args.get("params", {}),
                trigger_type=args["trigger_type"],
                trigger_config=args["trigger_config"],
                description=args.get("description", ""),
            )
            return {"status": "success", "data": {"job_id": job_id, "name": args.get("name")}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    def _handle_list_tasks(self, _args: dict) -> dict:
        """列出所有当前定时任务。"""
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

    def _handle_delete_task(self, args: dict) -> dict:
        """删除指定 ID 的定时任务。"""
        job_id = args.get("job_id", "")
        self._scheduler.remove_job(job_id)
        return {"status": "success", "data": {"deleted": job_id}}

    # ── 笔记工具 ────────────────────────────────────────────────────

    def _handle_read_notes(self, _args: dict) -> dict:
        """读取用户所有笔记的预览列表，包含标题和内容预览。"""
        previews = self._notes.get_preview_list()
        return {"status": "success", "data": {"notes": previews, "count": len(previews)}}

    def _handle_create_note(self, args: dict) -> dict:
        """创建新笔记，保存标题和正文内容。"""
        try:
            note = self._notes.create(
                title=args.get("title", "新笔记"),
                content=args.get("content", ""),
            )
            self._on_note_created()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    def _handle_summarize_as_note(self, args: dict) -> dict:
        """将当前会话对话内容总结，保存为笔记。"""
        try:
            note = self._notes.create(
                title=args.get("title", "会话总结"),
                content=args.get("summary", ""),
            )
            self._on_note_created()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    # ── 实用工具 ─────────────────────────────────────────────────

    def _handle_calculator(self, args: dict) -> dict:
        """安全计算数学表达式，支持四则运算、三角函数、对数等。"""
        expr = args.get("expression", "").strip()
        if not expr:
            return {"status": "error", "data": {"message": "expression is required"}}
        try:
            result = eval(expr, {"__builtins__": {}}, self._CALC_ALLOWED)  # noqa: S307
            if isinstance(result, complex):
                serialized: object = {"real": result.real, "imag": result.imag, "str": str(result)}
            else:
                serialized = result
            return {"status": "success", "data": {"expression": expr, "result": serialized}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e), "expression": expr}}

    def _handle_clipboard(self, args: dict) -> dict:
        """读取或写入系统剪贴板。action=get 读取，action=set 写入。"""
        action = args.get("action", "get")
        content = args.get("content", "")
        try:
            import pyperclip
            if action == "get":
                text = pyperclip.paste()
                return {"status": "success", "data": {"content": text, "length": len(text)}}
            else:
                pyperclip.copy(content)
                return {"status": "success", "data": {"message": f"已复制 {len(content)} 字符到剪贴板"}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
