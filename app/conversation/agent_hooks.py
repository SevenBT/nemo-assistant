"""Conversation compression adapted to the Agent lifecycle."""
from __future__ import annotations

import json as _json
import logging
from typing import Any

from app.agent.agent_hooks import AgentHook, BeforeTurnContext
from app.models.message import Message

logger = logging.getLogger(__name__)

# ── 工具函数：API dict ↔ Message 转换 ──────────────────────────────────


def _api_dicts_to_messages(api_dicts: list[dict[str, Any]]) -> list["Message"]:
    """将 OpenAI API 格式的 dict 列表转换为 Message 对象列表（供 Consolidator 使用）。"""
    from app.models.message import Message as _Msg, ToolCall

    result: list["Message"] = []
    for d in api_dicts:
        tool_calls = []
        if d.get("tool_calls"):
            for tc in d["tool_calls"]:
                args_str = tc.get("function", {}).get("arguments", "{}")
                args = _json.loads(args_str) if isinstance(args_str, str) else args_str
                tool_calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args,
                                           extra_content=tc.get("extra_content", {})))
        result.append(_Msg(
            role=d["role"],
            content=d.get("content") or "",
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            reasoning_content=d.get("reasoning_content"),
            provider_state=d.get("provider_state", {}),
        ))
    return result


# ── 内置 Hook 实现 ─────────────────────────────────────────────────────


class ConsolidatorHook(AgentHook):
    """将 Consolidator 适配为 AgentHook，在每轮对话前自动压缩旧消息。

    用法::

        from app.conversation.consolidator import Consolidator
        from app.conversation.agent_hooks import ConsolidatorHook

        consolidator = Consolidator(llm_gateway, memory_mgr, model="gpt-4o")
        hook = ConsolidatorHook(consolidator)
        agent = AgentThread(..., hooks=[hook])
    """

    def __init__(self, consolidator):
        from app.conversation.consolidator import Consolidator as _C

        if not isinstance(consolidator, _C):
            raise TypeError(f"Expected Consolidator, got {type(consolidator).__name__}")
        self._consolidator = consolidator

    def before_turn(self, ctx: BeforeTurnContext) -> list[dict[str, Any]] | None:
        messages = _api_dicts_to_messages(ctx.messages)
        compressed = self._consolidator.maybe_consolidate(messages, ctx.session_id)
        if compressed is not messages:
            logger.info(
                "[ConsolidatorHook] Compressed %d → %d messages",
                len(messages), len(compressed),
            )
            return [m.to_api_dict() for m in compressed]
        return None
