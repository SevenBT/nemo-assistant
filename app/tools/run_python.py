"""
执行 Python 代码工具 — 在当前进程中运行代码片段。

注意事项：
  - 代码在主进程中执行（非子进程），可以访问所有已安装的包
  - 通过重定向 stdout/stderr 捕获输出
  - SystemExit 被静默捕获（防止 sys.exit() 杀死主进程）
  - 其他异常被捕获并格式化为 traceback 返回

安全考虑：
  这个工具允许执行任意 Python 代码，安全性依赖于：
  1. LLM 的行为约束（system prompt 中限制危险操作）
  2. 桌面应用场景下用户对本机有完全控制权
  如果需要更强的隔离，应改用 subprocess 方式（参考 ScriptToolAdapter）
"""
from __future__ import annotations

import io
import sys
import traceback
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params


class RunPythonTool(BuiltinTool):
    """Python 代码执行工具。"""

    @property
    def name(self) -> str:
        return "run_python"

    @property
    def description(self) -> str:
        return "在本地 Python 环境中执行代码片段，捕获并返回输出。支持所有已安装的包"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "code",
            code=Str("要执行的 Python 代码，使用 print() 输出结果"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "").strip()
        if not code:
            return {"status": "error", "data": {"message": "code is required"}}

        # 重定向 stdout/stderr 以捕获代码输出
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        saved_stdout = sys.stdout
        saved_stderr = sys.stderr
        sys.stdout = out_buf
        sys.stderr = err_buf

        # 提供基本的执行环境
        exec_globals = {"__builtins__": __builtins__, "__name__": "__main__"}
        status = "success"
        error_msg = None

        try:
            exec(compile(code, "<run_python>", "exec"), exec_globals)  # noqa: S102
        except SystemExit:
            # 静默捕获 sys.exit()，防止杀死主进程
            pass
        except Exception:
            status = "error"
            error_msg = traceback.format_exc()
        finally:
            # 恢复标准输出（必须在 finally 中，防止异常导致 stdout 永久丢失）
            sys.stdout = saved_stdout
            sys.stderr = saved_stderr

        stdout_val = out_buf.getvalue()
        stderr_val = err_buf.getvalue()

        if status == "error":
            return {
                "status": "error",
                "data": {
                    "message": error_msg,
                    "output": stdout_val,
                    "stderr": stderr_val,
                },
            }

        return {
            "status": "success",
            "data": {
                "output": stdout_val,
                "stderr": stderr_val,
            },
        }
