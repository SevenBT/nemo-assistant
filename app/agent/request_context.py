"""Per-request context preparation without application or provider dependencies."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from app.runtime.cancellation import CancellationToken


class RequestCancelled(Exception):
    """Cooperative cancellation during request preparation."""


def check_cancelled(token: CancellationToken | None) -> None:
    if token is not None and token.is_cancelled():
        raise RequestCancelled("Agent request cancelled")


@dataclass(frozen=True)
class RequestContext:
    messages: list[dict]
    tools: list[dict] | None
    session_id: str
    trace_id: str
    seq: int
    mode: Literal["normal", "wrap_up"]
    cancel_token: CancellationToken


@dataclass(frozen=True)
class PreparedRequest:
    messages: list[dict]
    tools: list[dict] | None


class RequestPreparer(Protocol):
    def prepare(self, request: RequestContext) -> PreparedRequest: ...


def validate_tool_calls(calls: list[dict]) -> set[str]:
    if not isinstance(calls, list):
        raise ValueError("Tool calls must be a list")
    ids: set[str] = set()
    for call in calls:
        if not isinstance(call, dict):
            raise ValueError("Invalid tool call")
        call_id, function = call.get("id"), call.get("function")
        if not isinstance(call_id, str) or not call_id or call_id in ids:
            raise ValueError("Invalid or duplicate tool call ID")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"]:
            raise ValueError("Tool call is missing its name")
        args = function.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        if not isinstance(args, dict):
            raise ValueError("Tool arguments must be an object")
        ids.add(call_id)
    return ids


def validate_messages(messages: list[dict]) -> None:
    """Validate tool associations without stripping opaque provider extensions."""
    if not isinstance(messages, list):
        raise ValueError("Model messages must be a list")
    pending: set[str] = set()
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in (
            "system", "developer", "user", "assistant", "tool",
        ):
            raise ValueError("Invalid model message role")
        role = message["role"]
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                raise ValueError("Tool result has no matching assistant call")
            pending.remove(call_id)
            continue
        if pending:
            raise ValueError("Tool call group is incomplete")
        calls = message.get("tool_calls")
        if calls is not None:
            if role != "assistant":
                raise ValueError("Tool calls must belong to an assistant message")
            pending = validate_tool_calls(calls)
    if pending:
        raise ValueError("Tool call group is incomplete")


def encode_for_model(messages: list[dict]) -> list[dict]:
    validate_messages(messages)
    return copy.deepcopy(messages)


class IdentityRequestPreparer:
    def prepare(self, request: RequestContext) -> PreparedRequest:
        check_cancelled(request.cancel_token)
        return PreparedRequest(copy.deepcopy(request.messages), copy.deepcopy(request.tools))
