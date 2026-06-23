"""
执行 Python 代码工具 — 在隔离的子进程中运行代码片段。

安全模型（v2，子进程隔离）：
  历史上本工具在主进程内 exec()，等于把完整 __builtins__ 和主进程的所有
  环境变量（含 API Key）暴露给 LLM 生成的代码——是绕过 exec 工具一切防护的
  后门。现改为：
    1. 子进程执行：用同一个 Python 解释器起子进程（保留已安装的包），代码
       崩溃/sys.exit/死循环都不波及主进程。
    2. 最小环境变量白名单：只透传运行所必需的系统变量，主动剔除 API Key、
       数据库密码等敏感 env（参考 nanobot _build_env 思路）。
    3. 超时保护 + 输出截断：防止失控代码耗尽资源。

  保留主进程内可访问已安装第三方包的能力（子进程用 sys.executable，site-packages
  一致），但不再共享内存态对象和敏感环境。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT = 32_000  # stdout/stderr 各最大字符数

# 允许透传给子进程的环境变量名（白名单）。刻意排除一切可能含密钥的变量，
# 例如 *_API_KEY / OPENAI_* / 数据库连接串等绝不在此列。
_SAFE_ENV_KEYS_WINDOWS = (
    "SYSTEMROOT", "COMSPEC", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "TEMP", "TMP", "PATHEXT", "PATH", "APPDATA", "LOCALAPPDATA",
    "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
)
_SAFE_ENV_KEYS_UNIX = ("HOME", "LANG", "LC_ALL", "TERM", "PATH", "TMPDIR")


def _build_minimal_env() -> dict[str, str]:
    """构造子进程的最小环境：只含白名单里的系统变量，不继承敏感 env。"""
    keys = _SAFE_ENV_KEYS_WINDOWS if sys.platform == "win32" else _SAFE_ENV_KEYS_UNIX
    env = {k: os.environ[k] for k in keys if k in os.environ}
    # 强制非缓冲，保证 print 输出能完整捕获。
    env["PYTHONUNBUFFERED"] = "1"
    # 避免子进程把当前工作目录/用户 site 注入 sys.path 带来意外。
    env["PYTHONNOUSERSITE"] = "1"
    if sys.platform == "win32" and "SYSTEMROOT" not in env:
        env["SYSTEMROOT"] = r"C:\Windows"
    return env


class RunPythonTool(BuiltinTool):
    """Python 代码执行工具（子进程隔离）。"""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace.resolve() if workspace else None

    @classmethod
    def create(cls, ctx: "ToolContext") -> "RunPythonTool":
        return cls(workspace=getattr(ctx, "workspace", None))

    @property
    def name(self) -> str:
        return "run_python"

    @property
    def description(self) -> str:
        return "在隔离子进程中执行 Python 代码片段，捕获并返回输出。支持已安装的第三方包，使用 print() 输出结果"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "code",
            code=Str("要执行的 Python 代码，使用 print() 输出结果"),
            timeout=Int("超时秒数，默认 30，最大 120", maximum=_MAX_TIMEOUT),
        )

    @property
    def read_only(self) -> bool:
        return False

    @property
    def retry_safe(self) -> bool:
        return False

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "").strip()
        if not code:
            return {"status": "error", "data": {"message": "code is required"}}

        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
        cwd = str(self._workspace) if self._workspace and self._workspace.exists() else None

        try:
            result = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=_build_minimal_env(),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "data": {"message": f"代码执行超时 ({timeout}s)", "timed_out": True},
            }
        except OSError as e:
            return {"status": "error", "data": {"message": f"启动子进程失败: {e}"}}

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        stdout_truncated = len(stdout) > _MAX_OUTPUT
        stderr_truncated = len(stderr) > _MAX_OUTPUT

        if result.returncode != 0:
            return {
                "status": "error",
                "data": {
                    "message": f"代码以非零状态退出 (code={result.returncode})",
                    "output": stdout[:_MAX_OUTPUT],
                    "stderr": stderr[:_MAX_OUTPUT],
                    "return_code": result.returncode,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            }

        return {
            "status": "success",
            "data": {
                "output": stdout[:_MAX_OUTPUT],
                "stderr": stderr[:_MAX_OUTPUT],
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            },
        }
