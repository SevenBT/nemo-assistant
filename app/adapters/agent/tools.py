"""Reuse the application's tool execution gates, retries and formatting."""
from __future__ import annotations

import copy

from app.agent.contracts import (
    ToolDescriptor, ToolExecutionContext, ToolFailureKind, ToolResult,
)
from app.tools.registry import ToolRegistry


class RegistryToolRuntime:
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def definitions(self) -> list[dict]:
        return self._registry.get_openai_functions()

    def describe(self, name: str) -> ToolDescriptor | None:
        tool = self._registry.get(name)
        return ToolDescriptor(name, tool.read_only) if tool is not None else None

    def execute(
        self, name: str, arguments: dict, context: ToolExecutionContext,
    ) -> ToolResult:
        # Legacy tools receive session metadata only in their execution copy.
        params = copy.deepcopy(arguments)
        if context.session_id:
            params["_session_id"] = context.session_id
        result = self._registry.execute(name, params)
        if result.get("status") == "error":
            result = copy.deepcopy(result)
            data = result.setdefault("data", {})
            try:
                data["error_type"] = ToolFailureKind(data.get("error_type")).value
            except (ValueError, TypeError):
                data["error_type"] = ToolFailureKind.RUNTIME.value
        return result

    def format_result(self, result: ToolResult) -> str:
        return ToolRegistry.format_result(result)
