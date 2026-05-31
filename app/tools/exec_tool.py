"""
Shell 命令执行工具 — 在 workspace 内执行系统命令。

安全机制：
  - 工作目录限制在 workspace 内
  - 危险命令匹配 deny_patterns 时触发用户确认
  - 执行超时保护
  - 输出长度截断
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params
from app.tools._path_utils import resolve_safe
from app.tools.exec_security import is_dangerous_command

if TYPE_CHECKING:
    from app.tools.context import ToolContext

_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 300
_MAX_OUTPUT = 32_000  # stdout/stderr 各最大字符数


class ExecTool(BuiltinTool):
    """在工作目录内执行 shell 命令。"""

    def __init__(self, workspace: Path, confirm_action: Callable[[str, str], bool] | None = None):
        self._workspace = workspace.resolve()
        self._confirm_action = confirm_action

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ExecTool":
        return cls(
            workspace=ctx.workspace,
            confirm_action=getattr(ctx, "confirm_action", None),
        )

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "执行 shell 命令，如安装软件、运行脚本、管理文件等。工作目录限制在项目范围内。"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "command",
            command=Str("要执行的 shell 命令"),
            working_dir=Str("工作目录，相对于工作空间，默认工作空间根目录"),
            timeout=Int("超时秒数，默认 60，最大 300", maximum=_MAX_TIMEOUT),
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def retry_safe(self) -> bool:
        return False

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        command = params.get("command", "").strip()
        working_dir_str = params.get("working_dir", ".")
        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)

        if not command:
            return {"status": "error", "data": {"message": "command 不能为空"}}

        # 路径校验
        cwd, err = resolve_safe(working_dir_str, self._workspace)
        if err:
            return {"status": "error", "data": {"message": err}}
        if not cwd.exists() or not cwd.is_dir():
            return {"status": "error", "data": {"message": f"工作目录不存在: {working_dir_str}"}}

        # 安全检查
        dangerous, pattern = is_dangerous_command(command)
        if dangerous:
            if not self._confirm_action:
                return {"status": "error", "data": {"message": f"危险命令被拦截（匹配: {pattern}），无确认机制可用"}}
            if not self._confirm_action("命令确认", f"检测到危险命令:\n\n{command}\n\n是否允许执行？"):
                return {"status": "error", "data": {"message": "用户取消执行"}}

        # 执行
        # Windows 用 cmd，其他用 bash
        if sys.platform == "win32":
            args = ["cmd", "/c", command]
            shell = False
        else:
            args = command
            shell = True

        try:
            result = subprocess.run(
                args,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "data": {"message": f"命令执行超时 ({timeout}s)", "timed_out": True},
            }
        except OSError as e:
            return {"status": "error", "data": {"message": f"执行失败: {e}"}}

        stdout = result.stdout[:_MAX_OUTPUT] if result.stdout else ""
        stderr = result.stderr[:_MAX_OUTPUT] if result.stderr else ""
        stdout_truncated = len(result.stdout) > _MAX_OUTPUT if result.stdout else False
        stderr_truncated = len(result.stderr) > _MAX_OUTPUT if result.stderr else False

        return {
            "status": "success",
            "data": {
                "stdout": stdout,
                "stderr": stderr,
                "return_code": result.returncode,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            },
        }
