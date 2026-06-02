"""Build OpenAI-compatible conversation messages from stored chat messages."""

import json
from collections.abc import Callable
from typing import Any

from app.core.config import cfg
from app.core.constants import (
    BUILTIN_TOOLS_INSTRUCTION,
    DEFAULT_USER_PROMPT,
    get_current_datetime_info,
)
from app.models.message import Message, MessageRole


class ConversationPromptBuilder:
    """Compose system prompt, memory context, attachments, and tool results."""

    def __init__(
        self,
        ai_client,
        session_mgr,
        memory_mgr=None,
        config=cfg,
        datetime_info_provider: Callable[[], str] = get_current_datetime_info,
    ):
        self._ai = ai_client
        self._sessions = session_mgr
        self._memory_mgr = memory_mgr
        self._config = config
        self._datetime_info_provider = datetime_info_provider

    def build(self, messages: list[Message], session_id: str | None) -> list[dict]:
        system_prompt = self._build_system_prompt(session_id)
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        merged_messages = self._ai.merge_attachments_to_content(messages)
        for index, message in enumerate(messages):
            result.append(merged_messages[index])
            if message.role == MessageRole.ASSISTANT and message.tool_calls:
                if self._all_tool_calls_done(message):
                    result.extend(self._tool_result_messages(message))
                else:
                    result.pop()

        return result

    def _build_system_prompt(self, session_id: str | None) -> str:
        user_prompt = self._resolve_user_prompt(session_id)
        full_system_prompt = user_prompt + "\n" + BUILTIN_TOOLS_INSTRUCTION

        if session_id and self._memory_mgr is not None:
            memory_context = self._memory_mgr.build_memory_context(session_id)
            if memory_context:
                full_system_prompt += "\n\n" + memory_context

        full_system_prompt += "\n\n" + self._datetime_info_provider()
        return full_system_prompt

    def _resolve_user_prompt(self, session_id: str | None) -> str:
        session = self._sessions.get(session_id) if session_id else None
        if session and session.system_prompt and session.system_prompt.strip():
            return session.system_prompt.strip()

        configured_prompt = self._config.get(self._config.systemPrompt).strip()
        if configured_prompt:
            return configured_prompt

        return DEFAULT_USER_PROMPT

    def _all_tool_calls_done(self, message: Message) -> bool:
        return all(tool_call.result is not None for tool_call in message.tool_calls)

    def _tool_result_messages(self, message: Message) -> list[dict]:
        return [
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_call.result, ensure_ascii=False),
            }
            for tool_call in message.tool_calls
        ]
