"""Per-run compression views; persisted history always belongs to the Agent loop."""
from __future__ import annotations

import copy
import hashlib
import json

from app.agent.request_context import (
    PreparedRequest, RequestContext, check_cancelled, validate_messages,
)
from app.conversation.agent_hooks import _api_dicts_to_messages
from app.conversation.consolidator import Consolidator


class ConsolidatingRequestPreparer:
    """Reuse a summary until newly generated context crosses the threshold again.

    Instances belong to one run. System/developer messages, the newest user
    message and the newest complete protocol group are mandatory. All surviving
    messages are copied verbatim, including provider metadata and image blocks.
    """

    def __init__(self, consolidator: Consolidator):
        self._consolidator = consolidator
        self._source: list[dict] = []
        self._view: list[dict] | None = None
        self._summaries: dict[str, str] = {}

    def _cost(self, messages: list[dict], tools: list[dict] | None = None) -> int:
        # Include opaque provider fields and tool schemas in the text estimate.
        # Image payloads remain intact; their provider-specific token cost is
        # not inferable locally (the existing context manager is text based).
        def token_view(value):
            if isinstance(value, dict):
                return {k: ("[image]" if k == "image_url" else token_view(v)) for k, v in value.items()}
            if isinstance(value, list):
                return [token_view(v) for v in value]
            return value

        return self._consolidator.context_manager.count_tokens(json.dumps(
            token_view({"messages": messages, "tools": tools}), ensure_ascii=False,
        ))

    @staticmethod
    def _groups(messages: list[dict]) -> list[list[int]]:
        groups = []
        for index, message in enumerate(messages):
            if message["role"] == "tool":
                groups[-1].append(index)
            else:
                groups.append([index])
        return groups

    @staticmethod
    def _view_with_summary(messages: list[dict], kept: set[int], summary: str) -> list[dict]:
        result = [copy.deepcopy(message) for index, message in enumerate(messages) if index in kept]
        # Keep the original leading instructions first.
        position = 0
        while position < len(result) and result[position]["role"] in ("system", "developer"):
            position += 1
        result.insert(position, {"role": "system", "content": "[以下是之前对话的摘要]\n" + summary})
        return result

    def prepare(self, request: RequestContext) -> PreparedRequest:
        check_cancelled(request.cancel_token)
        messages = copy.deepcopy(request.messages)
        validate_messages(messages)
        manager = self._consolidator.context_manager
        threshold = int(manager.usable_tokens * 0.7)
        view = messages
        if self._view is not None and messages[:len(self._source)] == self._source:
            view = copy.deepcopy(self._view) + messages[len(self._source):]
        if self._cost(view, request.tools) <= threshold:
            return PreparedRequest(view, copy.deepcopy(request.tools))

        budget = self._consolidator.target_tokens
        groups = self._groups(messages)
        pinned = {index for index, m in enumerate(messages) if m["role"] in ("system", "developer")}
        user_index = next((i for i in range(len(messages)-1, -1, -1) if messages[i]["role"] == "user"), None)
        if user_index is not None:
            pinned.add(user_index)
        if groups:
            pinned.update(groups[-1])
        # Preserve a group as a unit even if mandatory positions grow later.
        for group in groups:
            if pinned.intersection(group):
                pinned.update(group)
        kept = set(pinned)
        if self._cost(self._view_with_summary(messages, kept, ""), request.tools) >= budget:
            raise ValueError("Mandatory context exceeds the compression budget; start a new conversation or reduce the input")
        reserve = max(1, budget // 5)
        for group in reversed(groups):
            candidate = kept.union(group)
            if self._cost(self._view_with_summary(messages, candidate, ""), request.tools) <= budget-reserve:
                kept = candidate
        dropped = [message for index, message in enumerate(messages) if index not in kept]
        if not dropped:
            raise ValueError("Context exceeds the request budget and has no safely compressible history")
        fingerprint = hashlib.sha256(json.dumps(
            dropped, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        summary = self._summaries.get(fingerprint)
        fresh = summary is None
        if fresh:
            available = budget - self._cost(self._view_with_summary(messages, kept, ""), request.tools)
            summary = self._consolidator.summarize(
                _api_dicts_to_messages(dropped), max_tokens=max(1, available),
                cancel_token=request.cancel_token,
            )
        check_cancelled(request.cancel_token)
        if not summary or not summary.strip():
            raise ValueError("Context summary and fallback are empty")
        # JSON escaping and instruction labels also consume the shared budget.
        summary_tokens = manager.count_tokens(summary)
        while summary_tokens > 0:
            view = self._view_with_summary(messages, kept, manager.truncate_text(summary, summary_tokens))
            over = self._cost(view, request.tools) - budget
            if over <= 0:
                break
            summary_tokens -= max(1, over)
        if summary_tokens <= 0:
            raise ValueError("No room for a valid context summary")
        validate_messages(view)
        check_cancelled(request.cancel_token)
        if fresh:
            self._consolidator.archive(summary, request.session_id, request.cancel_token)
            self._summaries[fingerprint] = summary
        self._source = copy.deepcopy(messages)
        self._view = copy.deepcopy(view)
        return PreparedRequest(view, copy.deepcopy(request.tools))
