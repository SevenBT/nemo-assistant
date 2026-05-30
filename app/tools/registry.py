"""
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
  TIMEOUT         执行超时，可重试
  NETWORK         网络/外部服务错误，可重试
  PERMISSION      权限/安全错误，不可重试，致命
  RUNTIME         其他运行时异常，可重试（有上限）
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
    ToolErrorType.NETWORK:  (3, 2.0),
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
        """执行工具，对可重试错误按配置自动重试。"""
        last_result: dict[str, Any] | None = None

        for attempt in range(1, 10):  # 上限足够大，由 _RETRY_CONFIG 控制实际次数
            try:
                result = tool.execute(params)
                # 工具内部已捕获异常并返回错误 dict 的情况
                if result.get("status") == "error":
                    error_type = ToolErrorType(
                        result["data"].get("error_type", ToolErrorType.RUNTIME.value)
                    ) if "error_type" in result.get("data", {}) else ToolErrorType.RUNTIME
                    result["data"].setdefault("retryable", error_type in _RETRY_CONFIG)
                return result
            except Exception as e:
                error_type = _classify(e)
                logger.warning(
                    "[Registry] %s attempt %d failed (%s): %s",
                    tool.name, attempt, error_type.value, e,
                )
                last_result = _make_error(error_type, str(e))

                max_attempts, delay = _RETRY_CONFIG.get(error_type, (1, 0))
                if attempt >= max_attempts:
                    logger.error("[Registry] %s exhausted retries (%d)", tool.name, max_attempts)
                    break
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
