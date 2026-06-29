"""
Unified tool registry — the single execution entry point of the tool system.

Responsibilities:
  1. Register/unregister tool instances
  2. Query tools (by name, all, or enabled-only)
  3. Emit the tool list in OpenAI function-calling format
  4. Execute tools: cast -> validate -> execute, with error classification
     and automatic retry
  5. Format execution results (error-type-specific hints + length truncation)

Error classification:
  TOOL_NOT_FOUND  tool missing, not retryable
  PARAM_INVALID   validation failed, not retryable (LLM passed bad args; let
                  the LLM correct itself)
  TIMEOUT         execution timed out, retryable (retry_safe tools only)
  NETWORK         network/external-service error, retryable (retry_safe only)
  PERMISSION      permission/security error, not retryable, fatal
  RUNTIME         other runtime error, cautiously retryable (retry_safe only)

统一工具注册中心 — 工具系统的唯一执行入口。

职责：
  1. 注册/注销工具实例
  2. 查询工具（按名称、全部、仅启用的）
  3. 生成 OpenAI function calling 格式的工具列表
  4. 执行工具：cast → validate → execute，含错误分类和自动重试
  5. 格式化执行结果（按错误类型定制提示 + 超长截断）

错误分类：
  TOOL_NOT_FOUND  工具不存在，不可重试
  PARAM_INVALID   参数校验失败，不可重试（LLM 传参有误，让 LLM 自行修正）
  TIMEOUT         执行超时，可重试（仅 retry_safe 工具）
  NETWORK         网络/外部服务错误，可重试（仅 retry_safe 工具）
  PERMISSION      权限/安全错误，不可重试，致命
  RUNTIME         其他运行时异常，可谨慎重试（仅 retry_safe 工具）
"""
from __future__ import annotations

import errno
import json
import logging
import time
from enum import Enum
from typing import Any

from app.tools.base import BuiltinTool

logger = logging.getLogger(__name__)

# 高风险内置工具：有副作用或安全影响（执行命令、运行代码、写文件），
# 允许用户在能力面板中关闭。其余内置工具默认常驻、不提供开关。
HIGH_RISK_TOOLS = frozenset({"exec", "run_python", "save_file"})

_MAX_RESULT_CHARS = 8000


class ToolErrorType(Enum):
    TOOL_NOT_FOUND = "tool_not_found"
    PARAM_INVALID  = "param_invalid"
    TIMEOUT        = "timeout"
    NETWORK        = "network"
    PERMISSION     = "permission"
    RUNTIME        = "runtime"


# 各错误类型的重试配置：(最大尝试次数, 间隔秒数)
# 不可重试的类型不在此表中
_RETRY_CONFIG: dict[ToolErrorType, tuple[int, float]] = {
    ToolErrorType.TIMEOUT:  (3, 1.0),
    ToolErrorType.NETWORK:  (2, 1.0),
    ToolErrorType.RUNTIME:  (2, 0.5),
}

# 各错误类型回传给 LLM 的提示语
_ERROR_HINTS: dict[ToolErrorType, str] = {
    ToolErrorType.TOOL_NOT_FOUND: "\n\n[工具不存在，请检查工具名称。]",
    ToolErrorType.PARAM_INVALID:  "\n\n[参数有误，请检查参数格式和必填项后重新调用。]",
    ToolErrorType.TIMEOUT:        "\n\n[工具执行超时，外部服务暂时不可用，可稍后重试或换用其他方式。]",
    ToolErrorType.NETWORK:        "\n\n[网络或外部服务错误，可稍后重试或换用其他方式。]",
    ToolErrorType.PERMISSION:     "\n\n[权限不足，请勿重试此操作。]",
    ToolErrorType.RUNTIME:        "\n\n[工具执行出错，请分析错误原因，尝试不同的参数或方法。]",
}


def _classify(exc: Exception) -> ToolErrorType:
    """根据异常类型判断错误分类。"""
    if isinstance(exc, TimeoutError):
        return ToolErrorType.TIMEOUT

    # requests / httpx 网络异常（可选依赖，用字符串匹配避免硬依赖）
    exc_type = type(exc).__name__
    exc_module = type(exc).__module__ or ""
    if isinstance(exc, ConnectionError) or "requests" in exc_module or "httpx" in exc_module:
        return ToolErrorType.NETWORK

    if isinstance(exc, PermissionError):
        return ToolErrorType.PERMISSION
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        return ToolErrorType.PERMISSION

    # subprocess 超时
    if exc_type == "TimeoutExpired":
        return ToolErrorType.TIMEOUT

    return ToolErrorType.RUNTIME


def _make_error(error_type: ToolErrorType, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "data": {
            "message": message,
            "error_type": error_type.value,
            "retryable": error_type in _RETRY_CONFIG,
        },
    }


def _coerce_error_type(value: Any) -> ToolErrorType:
    try:
        return ToolErrorType(value)
    except ValueError:
        return ToolErrorType.RUNTIME


def _normalize_result(result: Any) -> dict[str, Any]:
    """Normalize arbitrary tool output into the standard result shape."""
    if not isinstance(result, dict):
        return {"status": "success", "data": {"result": result}}

    status = result.get("status")
    if status == "success":
        result.setdefault("data", {})
        return result

    if status != "error":
        return {"status": "success", "data": result}

    data = result.get("data")
    if not isinstance(data, dict):
        data = {"message": str(data)}
        result["data"] = data

    error_type = _coerce_error_type(data.get("error_type", ToolErrorType.RUNTIME.value))
    data["error_type"] = error_type.value
    data.setdefault("message", "")
    data.setdefault("retryable", error_type in _RETRY_CONFIG)
    return result


class ToolRegistry:
    """
    工具注册中心 — 管理所有工具的注册、查询、校验、执行。

    使用方式：
        registry = ToolRegistry()
        registry.register(some_tool)
        result = registry.execute("tool_name", {"param": "value"})
    """

    def __init__(self):
        self._tools: dict[str, BuiltinTool] = {}

    def register(self, tool: BuiltinTool) -> None:
        """注册工具实例，同名覆盖。"""
        self._tools[tool.name] = tool
        logger.info("[Registry] Registered: %s (read_only=%s)", tool.name, tool.read_only)

    def unregister(self, name: str) -> None:
        """注销工具，名称不存在时静默忽略。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> BuiltinTool | None:
        return self._tools.get(name)

    def get_all(self) -> list[BuiltinTool]:
        return list(self._tools.values())

    def get_enabled(self) -> list[BuiltinTool]:
        return [t for t in self._tools.values() if t.enabled]

    def get_openai_functions(self) -> list[dict[str, Any]]:
        return [t.to_openai_function() for t in self._tools.values() if t.enabled]

    def apply_saved_states(self, states: dict[str, bool]) -> None:
        """将持久化的开关状态应用到已注册工具。

        在工具加载完成后调用一次，确保用户上次的开关选择在启动时即生效，
        而不是等到打开能力面板交互时才生效。未在 states 中出现的工具保持
        默认启用。
        """
        for name, enabled in states.items():
            tool = self._tools.get(name)
            if tool is not None:
                tool.enabled = enabled

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def execute(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        执行工具：cast → validate → execute，含错误分类和自动重试。

        返回统一格式：
            成功: {"status": "success", "data": {...}}
            失败: {"status": "error", "data": {"message": ..., "error_type": ..., "retryable": ...}}
        """
        tool = self._tools.get(name)
        if not tool:
            logger.warning("[Registry] Tool not found: %s", name)
            return _make_error(ToolErrorType.TOOL_NOT_FOUND, f"Tool not found: {name}")

        params = tool.cast_params(params)
        errors = tool.validate_params(params)
        if errors:
            return _make_error(ToolErrorType.PARAM_INVALID, f"参数校验失败: {'; '.join(errors)}")

        return self._execute_with_retry(tool, params)

    def _execute_with_retry(self, tool: BuiltinTool, params: dict[str, Any]) -> dict[str, Any]:
        """
        执行工具，对明确可重试的瞬态错误按配置重试。

        借鉴 nanobot 的保守策略：重试不是所有工具的默认行为，而是同时要求
        错误类型可重试、结果未禁止重试、工具声明 retry_safe。内置只读工具默认
        retry_safe=True；用户脚本工具默认 False，需 manifest 显式声明。
        """
        last_result: dict[str, Any] | None = None

        max_attempts = 1
        delay = 0.0

        for attempt in range(1, 10):  # 上限足够大，由每次错误类型控制实际次数
            try:
                result = _normalize_result(tool.execute(params))
            except Exception as e:
                error_type = _classify(e)
                logger.warning(
                    "[Registry] %s attempt %d failed (%s): %s",
                    tool.name, attempt, error_type.value, e,
                )
                result = _make_error(error_type, str(e))

            if result.get("status") != "error":
                return result

            result = _normalize_result(result)
            last_result = result
            data = result.get("data", {})
            error_type = _coerce_error_type(data.get("error_type", ToolErrorType.RUNTIME.value))
            max_attempts, delay = _RETRY_CONFIG.get(error_type, (1, 0.0))
            retryable = bool(data.get("retryable", error_type in _RETRY_CONFIG))
            retry_safe = bool(getattr(tool, "retry_safe", tool.read_only))

            if not (retryable and retry_safe and attempt < max_attempts):
                if attempt >= max_attempts and max_attempts > 1:
                    logger.error("[Registry] %s exhausted retries (%d)", tool.name, max_attempts)
                return result

            logger.warning(
                "[Registry] %s retrying after %s error (%d/%d)",
                tool.name, error_type.value, attempt, max_attempts,
            )
            if delay > 0:
                time.sleep(delay)

        return last_result  # type: ignore[return-value]

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        """
        格式化工具结果为字符串回传给 LLM。

        - 错误结果按 error_type 追加定制提示语
        - 超过 _MAX_RESULT_CHARS 时截断并标注原始长度
        """
        content = json.dumps(result, ensure_ascii=False)

        if result.get("status") == "error":
            error_type_val = result.get("data", {}).get("error_type", ToolErrorType.RUNTIME.value)
            try:
                error_type = ToolErrorType(error_type_val)
            except ValueError:
                error_type = ToolErrorType.RUNTIME
            content += _ERROR_HINTS[error_type]

        if len(content) > _MAX_RESULT_CHARS:
            original_len = len(content)
            content = content[:_MAX_RESULT_CHARS]
            content += f"\n\n[结果已截断，原始长度 {original_len} 字符，显示前 {_MAX_RESULT_CHARS} 字符]"

        return content
