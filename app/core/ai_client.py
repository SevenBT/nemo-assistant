import json
from typing import Iterator, Optional

import httpx
from openai import OpenAI

from app.core.config import ConfigManager, SHANGDAO_MODELS

_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)


class AIClient:
    def __init__(self, config: ConfigManager):
        self._config = config

    def _openai_client(self) -> OpenAI:
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
        via merge_attachments_to_content() before calling this method.
        """
        api_type = self._config.api_type
        if api_type == "shangdao":
            yield from self._chat_stream_shangdao(messages, tools)
        elif api_type == "litellm":
            yield from self._chat_stream_litellm(messages, tools)
        else:
            yield from self._chat_stream_openai(messages, tools)

    def _chat_stream_openai(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
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
            stream = self._openai_client().chat.completions.create(**kwargs)
            tc_buf: dict[int, dict] = {}  # index -> {id, name, args_str}
            reasoning_buf = ""

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

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

    def _chat_stream_shangdao(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        model_name = self._config.shangdao_model
        model_meta = SHANGDAO_MODELS.get(model_name)
        if not model_meta:
            yield {"type": "error", "message": f"未知的商道模型: {model_name}"}
            return

        api_key = self._config.get_shangdao_api_key()
        if not api_key:
            yield {"type": "error", "message": "商道 API Key 未配置"}
            return

        base_url = self._config.shangdao_base_url.rstrip("/")
        path_prefix = model_meta["path_prefix"]
        url = f"{base_url}/{path_prefix}/v1/chat/completions"

        sd_config = self._config.shangdao_config
        body: dict = {
            model_meta["body_model_field"]: model_meta["body_model_value"],
            "messages": messages,
            "stream": True,
            "max_tokens": sd_config.get("max_tokens", 2048),
            "temperature": sd_config.get("temperature", 0.7),
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "x-api-key": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                with client.stream("POST", url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    reasoning_buf = ""
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("message") or choice.get("delta", {})

                        rc = delta.get("reasoning_content")
                        if rc:
                            reasoning_buf += rc

                        content = delta.get("content")
                        if content:
                            yield {"type": "text", "delta": content}

                        finish = choice.get("finish_reason")
                        if finish == "stop":
                            break

                    yield {"type": "done", "reasoning_content": reasoning_buf or None}

        except httpx.HTTPStatusError as e:
            yield {"type": "error", "message": f"商道 API 请求失败 ({e.response.status_code}): {e.response.text}"}
        except Exception as e:
            yield {"type": "error", "message": str(e)}

    def _chat_stream_litellm(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """使用 LiteLLM 库直接调用（不需要服务）"""
        try:
            import litellm
        except ImportError:
            yield {"type": "error", "message": "LiteLLM 未安装，请运行: pip install litellm"}
            return
        
        # 获取默认模型和 provider
        model_id = self._config.litellm_default_model
        model_config = self._config.get_litellm_model_by_id(model_id)
        
        if not model_config:
            yield {"type": "error", "message": f"模型 {model_id} 未找到"}
            return
        
        provider = model_config["provider"]
        api_key = self._config.get_litellm_provider_api_key(provider)
        
        if not api_key:
            yield {"type": "error", "message": f"{provider} API Key 未配置"}
            return
        
        # 构造 LiteLLM 模型名：provider/model
        litellm_model = f"{provider}/{model_id}"
        
        kwargs: dict = {
            "model": litellm_model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "stream": True,
            "api_key": api_key,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            stream = litellm.completion(**kwargs)
            tc_buf: dict[int, dict] = {}
            reasoning_buf = ""
            
            for chunk in stream:
                if not hasattr(chunk, 'choices') or not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc
                
                if hasattr(delta, 'content') and delta.content:
                    yield {"type": "text", "delta": delta.content}
                
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
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
                
                if hasattr(choice, 'finish_reason') and choice.finish_reason in ("stop", "tool_calls"):
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
            yield {"type": "error", "message": f"LiteLLM 调用失败: {str(e)}"}

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
