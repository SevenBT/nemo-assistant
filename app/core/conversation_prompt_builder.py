"""Build OpenAI-compatible conversation messages from stored chat messages."""

import json
from collections.abc import Callable
from typing import Any

from app.core.config import cfg
from app.core.constants import (
    BUILTIN_TOOLS_INSTRUCTION,
    DEFAULT_USER_PROMPT,
    get_current_datetime_info,
    get_current_time_hint,
)
from app.models.message import Message, MessageRole


class ConversationPromptBuilder:
    """Compose system prompt, memory context, attachments, and tool results."""

    def __init__(
        self,
        session_mgr,
        memory_mgr=None,
        config=cfg,
        datetime_info_provider: Callable[[], str] = get_current_datetime_info,
        time_hint_provider: Callable[[], str] = get_current_time_hint,
    ):
        self._sessions = session_mgr
        self._memory_mgr = memory_mgr
        self._config = config
        self._datetime_info_provider = datetime_info_provider
        self._time_hint_provider = time_hint_provider

    def build(self, messages: list[Message], session_id: str | None) -> list[dict]:
        system_prompt = self._build_system_prompt(session_id)
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        vision_enabled = self._vision_enabled()
        merged_messages = merge_attachments_to_content(messages, vision_enabled)
        for index, message in enumerate(messages):
            result.append(merged_messages[index])
            if message.role == MessageRole.ASSISTANT and message.tool_calls:
                if self._all_tool_calls_done(message):
                    result.extend(self._tool_result_messages(message))
                else:
                    result.pop()

        # 精确到分钟的时间放在请求最末尾，避免污染前面可缓存的稳定前缀。
        time_hint = self._time_hint_provider()
        if time_hint:
            result.append({"role": "system", "content": time_hint})

        return result

    def _vision_enabled(self) -> bool:
        """Whether the active model can receive image pixels.

        Resolves the user override (visionSupport) or falls back to a
        name heuristic on the LiteLLM default model. Fails safe to False
        (text-only) if config can't be resolved.
        """
        from app.core.config import current_vision_enabled

        try:
            return current_vision_enabled()
        except (AttributeError, KeyError):
            return False

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


def merge_attachments_to_content(
    messages: list[Message], vision_enabled: bool = False
) -> list[dict]:
    """调用模型前，把用户消息的附件并入 content。

    文本附件（文档/文本文件）始终拼成文字。图片附件分两种处理：
    - vision_enabled 且能取到图片数据 → content 变为 OpenAI 多模态 list，
      文字部分 + 每张图一个 image_url，让模型真正"看到"像素。
    - 否则 → 退回纯文本，用图片的 OCR 文字（parsed_content）占位。

    注意：这条"图片像素通道"只服务多模态识图，与用户主动点 OCR 识字
    是两条独立路径（见 docs/TODO_SCREENSHOT_AI.md）。
    """
    api_messages = []
    for msg in messages:
        api_dict = msg.to_api_dict()

        if msg.role == MessageRole.USER and msg.attachments:
            text_atts = [a for a in msg.attachments if not a.is_image()]
            image_atts = [a for a in msg.attachments if a.is_image()]

            text_block = _build_text_block(msg, text_atts, image_atts, vision_enabled)

            image_urls = []
            if vision_enabled:
                for att in image_atts:
                    data_url = att.to_data_url()
                    if data_url:
                        image_urls.append(data_url)

            if image_urls:
                content_parts: list[dict[str, Any]] = []
                if text_block:
                    content_parts.append({"type": "text", "text": text_block})
                for url in image_urls:
                    content_parts.append(
                        {"type": "image_url", "image_url": {"url": url}}
                    )
                api_dict["content"] = content_parts
            else:
                api_dict["content"] = text_block

        api_messages.append(api_dict)

    return api_messages


def _build_text_block(
    msg: Message,
    text_atts: list,
    image_atts: list,
    vision_enabled: bool,
) -> str:
    """Compose the textual portion: text-file contents, image OCR fallback, user text."""
    parts = [f"[文件: {att.file_name}]\n{att.parsed_content}" for att in text_atts]

    # When vision can't carry the pixels, fall back to image OCR text so the
    # model still gets *something*. OCR is computed lazily here (not at intake)
    # so the vision path never pays for it. When vision is on, pixels go through
    # image_url, so we skip OCR entirely.
    if not vision_enabled:
        for att in image_atts:
            text = att.parsed_content or _ocr_image_text(att)
            if text:
                parts.append(f"[图片: {att.file_name}]\n{text}")

    merged = "\n\n".join(parts)
    if msg.content:
        merged = f"{merged}\n\n{msg.content}" if merged else msg.content
    return merged


def _ocr_image_text(attachment) -> str:
    """Lazily OCR an image attachment for the vision-off downgrade path."""
    from pathlib import Path

    if not attachment.file_path or not Path(attachment.file_path).is_file():
        return ""
    try:
        from app.core.file_parser import FileParser

        return FileParser()._parse_image(attachment.file_path)
    except Exception:
        return ""
