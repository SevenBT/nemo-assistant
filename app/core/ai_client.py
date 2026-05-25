"""
AI 对话客户端。

封装 OpenAI、商道、LiteLLM 三种 API 的流式调用，
统一输出 text/tool_call/done/error 事件流。

设计思路：
    AIClient 是 AgentLoop 与 LLM 之间的适配层。
    无论底层用哪家 API，对外都暴露统一的 chat_stream() 接口，
    返回标准化的事件字典流（Iterator[dict]）。
    AgentLoop 不需要关心具体用的是哪个 LLM 提供商。

支持的后端：
    - OpenAI：通过官方 SDK，兼容所有 OpenAI 格式的 API（如 DeepSeek、本地 Ollama 等）
    - 商道：自定义网关，走 HTTP SSE 协议
    - LiteLLM：统一多家 LLM 的开源库，支持 100+ 模型提供商
"""
import json
from typing import Iterator, Optional

import httpx
from openai import OpenAI

from app.core.config import (
    SHANGDAO_MODELS,       # 商道模型元数据字典（路径前缀、模型字段名等）
    cfg,                   # 全局配置单例（QFluentWidgets ConfigItem）
    get_api_key,           # 获取 OpenAI API Key
    get_litellm_provider_api_key,  # 获取 LiteLLM 各 provider 的 API Key
    get_shangdao_api_key,  # 获取商道网关 API Key
)

# HTTP 超时配置：连接 15s，读取 120s（流式响应可能很慢），写入 15s，连接池 15s
_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)


class AIClient:
    """
    AI 对话客户端，支持 OpenAI / 商道 / LiteLLM 三种后端。

    职责：
        - 根据配置中的 apiType 自动选择后端
        - 将各后端的流式响应统一为标准事件字典格式
        - 处理工具调用（tool_calls）的流式拼接
        - 封装错误处理，保证不抛异常（通过 error 事件通知调用方）

    使用方式：
        client = AIClient()
        for event in client.chat_stream(messages, tools):
            match event["type"]:
                case "text":      # 处理文本片段
                case "tool_call": # 处理工具调用
                case "done":      # 流结束
                case "error":     # 出错
    """

    def __init__(self, config_proxy=None):
        """
        初始化客户端。

        Args:
            config_proxy: 可选的配置代理对象，用于覆盖全局配置读取。
                         主要用于测试或多配置场景（如同时开多个对话窗口用不同模型）。
                         为 None 时使用全局 cfg 单例。
        """
        self._proxy = config_proxy

    def _openai_client(self) -> OpenAI:
        """
        创建 OpenAI SDK 客户端实例。

        注意：每次调用都创建新实例（无连接池复用），
        因为 base_url 和 api_key 可能随配置变化。
        """
        return OpenAI(
            api_key=get_api_key() or "sk-placeholder",  # 占位符防止 SDK 报错
            base_url=cfg.get(cfg.apiBaseUrl),
            timeout=_TIMEOUT,
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """
        流式对话的统一入口，根据 apiType 配置分发到对应后端。

        这是 AIClient 的核心方法，AgentLoop._state_stream() 直接调用它。
        无论底层用哪个 API，返回的事件格式完全一致。

        Args:
            messages: OpenAI 格式的消息列表（role/content/tool_calls 等）
            tools: 工具定义列表（JSON Schema 格式），None 表示不启用工具调用

        Yields:
            {"type": "text",      "delta": str}              — 文本片段（逐 token）
            {"type": "tool_call", "id", "name", "arguments"} — 完整的工具调用（流结束后一次性 yield）
            {"type": "done",      "reasoning_content": str|None} — 流结束标记
            {"type": "error",     "message": str}            — 错误（不抛异常，通过事件通知）

        注意：调用前需先通过 merge_attachments_to_content() 合并附件到消息内容中。
        """
        api_type = self._proxy.api_type if self._proxy else cfg.get(cfg.apiType)
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
        """
        通过 OpenAI SDK 进行流式调用。

        兼容所有 OpenAI 格式的 API（官方 OpenAI、Azure、DeepSeek、本地 Ollama 等），
        只要 base_url 指向正确的端点即可。

        流式处理逻辑：
            1. 逐 chunk 接收 SSE 事件
            2. 文本内容实时 yield（低延迟）
            3. 工具调用分片到达，先缓存到 tc_buf，流结束后一次性 yield 完整调用
            4. reasoning_content（思维链）累积后随 done 事件返回

        工具调用的流式拼接：
            OpenAI 的 tool_calls 是分片传输的——第一个 chunk 带 id 和 name，
            后续 chunk 只带 arguments 的片段。需要按 index 缓存并拼接 args_str，
            流结束后 JSON 解析得到完整参数字典。
        """
        kwargs: dict = {
            "model": self._proxy.model if self._proxy else cfg.get(cfg.model),
            "messages": messages,
            "max_tokens": cfg.get(cfg.maxTokens),
            "temperature": cfg.get(cfg.temperature),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"  # 让模型自行决定是否调用工具

        try:
            stream = self._openai_client().chat.completions.create(**kwargs)
            tc_buf: dict[int, dict] = {}  # 工具调用缓冲区：index → {id, name, args_str}
            reasoning_buf = ""             # 思维链内容累积

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # 累积思维链内容（部分模型如 DeepSeek-R1 支持）
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc

                # 文本内容：实时 yield，AgentLoop 会通过信号推送给 UI
                if delta.content:
                    yield {"type": "text", "delta": delta.content}

                # 工具调用片段：按 index 缓存，逐步拼接 arguments
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

                # finish_reason 标记流结束
                if choice.finish_reason in ("stop", "tool_calls"):
                    break

            # 流结束后，将缓冲区中的工具调用解析为完整事件逐个 yield
            for tc_data in tc_buf.values():
                try:
                    args = json.loads(tc_data["args_str"] or "{}")
                except json.JSONDecodeError:
                    args = {}  # 参数解析失败时降级为空字典，避免整个流程中断
                yield {
                    "type": "tool_call",
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "arguments": args,
                }

            yield {"type": "done", "reasoning_content": reasoning_buf or None}

        except Exception as e:
            # 所有异常统一转为 error 事件，不向上抛出
            yield {"type": "error", "message": str(e)}

    def _chat_stream_shangdao(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """
        通过商道网关 HTTP SSE 进行流式调用。

        商道是自定义的 AI 网关服务，不使用 OpenAI SDK，而是直接发 HTTP 请求。
        响应格式为 Server-Sent Events（SSE），每行以 "data:" 开头。

        与 OpenAI 后端的区别：
            - 认证方式不同：使用 x-api-key 请求头
            - URL 路径由模型元数据决定（不同模型走不同的路径前缀）
            - body 中的模型字段名可能不是 "model"（由 body_model_field 配置）
            - 不使用 SDK，手动解析 SSE 流
            - 当前不支持工具调用的流式拼接（商道网关暂未支持 tool_calls 流式）
        """
        # 从配置中获取模型名，再查模型元数据（路径前缀、body 字段名等）
        model_name = self._proxy.shangdao_model if self._proxy else cfg.get(cfg.shangdaoModel)
        model_meta = SHANGDAO_MODELS.get(model_name)
        if not model_meta:
            yield {"type": "error", "message": f"未知的商道模型: {model_name}"}
            return

        api_key = get_shangdao_api_key()
        if not api_key:
            yield {"type": "error", "message": "商道 API Key 未配置"}
            return

        # 拼接完整 URL：base_url + 模型路径前缀 + /v1/chat/completions
        base_url = cfg.get(cfg.shangdaoBaseUrl).rstrip("/")
        path_prefix = model_meta["path_prefix"]
        url = f"{base_url}/{path_prefix}/v1/chat/completions"

        # 构建请求体（注意：模型字段名和值由元数据决定，不一定是 "model"）
        body: dict = {
            model_meta["body_model_field"]: model_meta["body_model_value"],
            "messages": messages,
            "stream": True,
            "max_tokens": cfg.get(cfg.shangdaoMaxTokens),
            "temperature": cfg.get(cfg.shangdaoTemperature),
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # 商道网关使用自定义请求头进行认证
        headers = {
            "x-api-key": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                # 使用 httpx 的流式请求，逐行读取 SSE 事件
                with client.stream("POST", url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    reasoning_buf = ""
                    for line in resp.iter_lines():
                        # SSE 格式：空行分隔事件，每行以 "data:" 开头
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":  # SSE 流结束标记
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        # 商道返回的字段可能是 "message" 或 "delta"
                        delta = choice.get("message") or choice.get("delta", {})

                        # 思维链内容
                        rc = delta.get("reasoning_content")
                        if rc:
                            reasoning_buf += rc

                        # 文本内容
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
        """
        使用 LiteLLM 库直接调用（不需要独立服务）。

        LiteLLM 是一个统一多家 LLM 提供商的开源库，支持 100+ 模型。
        它的接口与 OpenAI SDK 兼容，所以处理逻辑和 _chat_stream_openai 基本相同。

        与 OpenAI 后端的区别：
            - 模型名格式为 "provider/model_id"（如 "anthropic/claude-3-opus"）
            - API Key 按 provider 分别配置
            - 需要额外安装 litellm 包（延迟 import，未安装时给出友好提示）
            - 使用 hasattr 做防御性检查（不同 provider 返回的对象属性可能不同）
        """
        try:
            import litellm
        except ImportError:
            yield {"type": "error", "message": "LiteLLM 未安装，请运行: pip install litellm"}
            return

        # 获取默认模型 ID 和对应的模型配置（包含 provider 信息）
        model_id = self._proxy.litellm_default_model if self._proxy else cfg.get(cfg.litellmDefaultModel)
        if self._proxy:
            model_config = self._proxy.get_litellm_model_by_id(model_id)
        else:
            models = cfg.get(cfg.litellmModels)
            model_config = next((m for m in models if m.get("id") == model_id), None)

        if not model_config:
            yield {"type": "error", "message": f"模型 {model_id} 未找到"}
            return

        # 根据 provider 获取对应的 API Key（如 anthropic、google、deepseek 各有各的 key）
        provider = model_config["provider"]
        api_key = get_litellm_provider_api_key(provider)

        if not api_key:
            yield {"type": "error", "message": f"{provider} API Key 未配置"}
            return

        # LiteLLM 模型名格式：provider/model_id（如 "anthropic/claude-3-opus"）
        litellm_model = f"{provider}/{model_id}"

        kwargs: dict = {
            "model": litellm_model,
            "messages": messages,
            "max_tokens": cfg.get(cfg.maxTokens),
            "temperature": cfg.get(cfg.temperature),
            "stream": True,
            "api_key": api_key,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = litellm.completion(**kwargs)
            tc_buf: dict[int, dict] = {}   # 工具调用缓冲区（同 OpenAI 后端）
            reasoning_buf = ""

            for chunk in stream:
                if not hasattr(chunk, 'choices') or not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # 思维链（部分 provider 支持）
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_buf += rc

                # 文本内容（使用 hasattr 防御：不同 provider 的 delta 对象可能缺少属性）
                if hasattr(delta, 'content') and delta.content:
                    yield {"type": "text", "delta": delta.content}

                # 工具调用片段拼接（逻辑同 OpenAI 后端）
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

            # 流结束后输出完整的工具调用
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
        """
        将消息中的附件内容合并到 content 字段，供 API 调用使用。

        LLM API 不认识自定义的 attachments 字段，所以在发送前需要把附件内容
        拼接到 content 文本中。只处理用户消息（assistant 消息不会有附件）。

        拼接格式：
            [文件: example.py]
            <文件解析后的文本内容>

            [文件: data.csv]
            <文件解析后的文本内容>

            <用户原始输入的文本>

        Args:
            messages: 内部消息对象列表（带 .attachments 属性和 .to_api_dict() 方法）

        Returns:
            OpenAI 格式的消息字典列表，附件内容已合并到 content 字段中
        """
        api_messages = []
        for msg in messages:
            api_dict = msg.to_api_dict()

            # 仅对用户消息合并附件（assistant/system/tool 消息不处理）
            if msg.role == "user" and msg.attachments:
                attachment_texts = []
                for att in msg.attachments:
                    attachment_texts.append(
                        f"[文件: {att.file_name}]\n{att.parsed_content}"
                    )

                # 附件在前，用户文本在后（让 AI 先看到文件内容再看用户指令）
                merged_content = "\n\n".join(attachment_texts)
                if msg.content:
                    merged_content += f"\n\n{msg.content}"

                api_dict["content"] = merged_content

            api_messages.append(api_dict)

        return api_messages
