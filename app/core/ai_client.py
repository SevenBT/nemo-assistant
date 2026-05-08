import json
from typing import Iterator, Optional

import httpx
from openai import OpenAI

from app.core.config import ConfigManager

_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)


class AIClient:
    def __init__(self, config: ConfigManager):
        self._config = config

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._config.api_key or "sk-placeholder",
            base_url=self._config.api_base_url,
            timeout=_TIMEOUT,
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """
        Streaming chat. Yields:
          {"type": "text",      "delta": str}
          {"type": "tool_call", "id": str, "name": str, "arguments": dict}
          {"type": "done"}
          {"type": "error",     "message": str}

        Note: messages should already have attachment content merged
        via _merge_attachments_to_content() before calling this method.
        """
        kwargs: dict = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = self._client().chat.completions.create(**kwargs)
            tc_buf: dict[int, dict] = {}  # index -> {id, name, args_str}
            reasoning_buf = ""

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # Some models (e.g. DeepSeek-R1) emit reasoning_content alongside content
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc

                if delta.content:
                    yield {"type": "text", "delta": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tc_buf:
                            tc_buf[idx] = {"id": "", "name": "", "args_str": ""}
                        if tc.id:
                            tc_buf[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tc_buf[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tc_buf[idx]["args_str"] += tc.function.arguments

                if choice.finish_reason in ("stop", "tool_calls"):
                    break

            for tc_data in tc_buf.values():
                try:
                    args = json.loads(tc_data["args_str"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {
                    "type": "tool_call",
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "arguments": args,
                }

            yield {"type": "done", "reasoning_content": reasoning_buf or None}

        except Exception as e:
            yield {"type": "error", "message": str(e)}

    @staticmethod
    def merge_attachments_to_content(messages: list) -> list[dict]:
        """Merge attachment content into message content for API calls.

        For each message with attachments, prepend file content to the
        original content in the format:

            [文件: filename.txt]
            <parsed_content>

            <original_content>

        Args:
            messages: List of Message objects

        Returns:
            List of API-ready message dicts with merged content
        """
        api_messages = []
        for msg in messages:
            api_dict = msg.to_api_dict()

            # Only merge attachments for user messages
            if msg.role == "user" and msg.attachments:
                attachment_texts = []
                for att in msg.attachments:
                    attachment_texts.append(
                        f"[文件: {att.file_name}]\n{att.parsed_content}"
                    )

                merged_content = "\n\n".join(attachment_texts)
                if msg.content:
                    merged_content += f"\n\n{msg.content}"

                api_dict["content"] = merged_content

            api_messages.append(api_dict)

        return api_messages

