"""Ports consumed by the execution loop; no application services are imported."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Literal, NotRequired, Protocol, TypedDict

from app.runtime.cancellation import CancellationToken


class TextEvent(TypedDict):
    type: Literal["text"]
    delta: str


class ToolCallEvent(TypedDict):
    type: Literal["tool_call"]
    id: str
    name: str
    arguments: dict[str, Any]
    extra_content: NotRequired[dict[str, Any]]


class ErrorEvent(TypedDict):
    type: Literal["error"]
    message: str


class DoneEvent(TypedDict):
    type: Literal["done"]
    reasoning_content: NotRequired[str | None]
    provider_state: NotRequired[dict[str, Any]]


ModelEvent = TextEvent | ToolCallEvent | ErrorEvent | DoneEvent


class ModelStream(Protocol):
    def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None, *,
        cancel_token: CancellationToken | None = None,
        trace_id: str = "", seq: int = 0,
    ) -> Iterator[ModelEvent]: ...


class ToolFailureKind(Enum):
    TOOL_NOT_FOUND = "tool_not_found"
    PARAM_INVALID = "param_invalid"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PERMISSION = "permission"
    RUNTIME = "runtime"


class ToolResult(TypedDict):
    status: Literal["success", "error"]
    data: Any


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    read_only: bool = False


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    trace_id: str
    call_id: str
    cancel_token: CancellationToken


class ToolRuntime(Protocol):
    def definitions(self) -> list[dict]: ...
    def describe(self, name: str) -> ToolDescriptor | None: ...
    def execute(
        self, name: str, arguments: dict, context: ToolExecutionContext,
    ) -> ToolResult: ...
    def format_result(self, result: ToolResult) -> str: ...


@dataclass(frozen=True)
class CheckpointSnapshot:
    messages: list[dict]
    assistant_msg: dict
    completed_results: list[dict]
    pending_tool_calls: list[dict]


class CheckpointStore(Protocol):
    def save(self, session_id: str, snapshot: CheckpointSnapshot) -> None: ...
    def clear(self, session_id: str) -> None: ...


class NullCheckpointStore:
    def save(self, session_id: str, snapshot: CheckpointSnapshot) -> None:
        pass

    def clear(self, session_id: str) -> None:
        pass


class TraceSink(Protocol):
    def start_trace(self, trace_id: str, session_id: str) -> None: ...
    def record_state_trace(self, trace_id: str, data: list[dict]) -> None: ...
    def finish_trace(
        self, trace_id: str, *, status: str, turn_count: int,
        duration_ms: float, error: str | None = None,
    ) -> None: ...
    def record_tool_call(
        self, trace_id: str, *, call_id: str, name: str,
        arguments: dict, result: dict | None, duration_ms: float,
    ) -> None: ...


class NullTraceSink:
    def start_trace(self, trace_id: str, session_id: str) -> None:
        pass

    def record_state_trace(self, trace_id: str, data: list[dict]) -> None:
        pass

    def finish_trace(
        self, trace_id: str, *, status: str, turn_count: int,
        duration_ms: float, error: str | None = None,
    ) -> None:
        pass

    def record_tool_call(
        self, trace_id: str, *, call_id: str, name: str,
        arguments: dict, result: dict | None, duration_ms: float,
    ) -> None:
        pass
