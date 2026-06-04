"""统一 LLM 网关。

集中处理模型路由、本地限流、重试策略、流式事件标准化和 JSONL 观测日志。
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Protocol

import httpx
from openai import OpenAI

from app.core.config import (
    DATA_DIR,
    SHANGDAO_MODELS,
    cfg,
    get_api_key,
    get_litellm_provider_api_key,
    get_shangdao_api_key,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)
_LOG_DIR = DATA_DIR.parent / "logs"
_DEFAULT_LOG_PATH = _LOG_DIR / "llm_gateway.jsonl"


@dataclass(frozen=True)
class LLMRequest:
    """网关内部的统一请求对象。

    上层只关心 messages/tools；网关在这里补齐 provider、model、key、
    base_url 等调用细节，再交给具体 adapter。
    """

    trace_id: str
    attempt_id: str
    api_type: str
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """Provider 适配器协议。

    每个供应商只负责把自己的响应翻译成统一事件，不处理全局限流、
    重试和日志，这些横切逻辑留在 LLMGateway。
    """

    def stream(self, request: LLMRequest) -> Iterator[dict]:
        """Yield normalized gateway events."""


def _get_error_payload(exc: Exception) -> Any:
    response = getattr(exc, "response", None)
    payload = (
        getattr(exc, "body", None)
        or getattr(exc, "doc", None)
        or getattr(response, "text", None)
    )
    if payload is None and response is not None:
        response_json = getattr(response, "json", None)
        if callable(response_json):
            try:
                payload = response_json()
            except Exception:
                return None
    return payload


def _error_type_code(payload: Any) -> tuple[str | None, str | None]:
    data: dict[str, Any] | None = None
    if isinstance(payload, dict):
        data = payload
    elif isinstance(payload, str) and payload.strip():
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    if not isinstance(data, dict):
        return None, None

    err = data.get("error")
    err_type = data.get("type")
    err_code = data.get("code")
    if isinstance(err, dict):
        err_type = err.get("type") or err_type
        err_code = err.get("code") or err_code
    return (
        str(err_type).strip().lower() if err_type else None,
        str(err_code).strip().lower() if err_code else None,
    )


def _retry_after_from_headers(headers: Any) -> float | None:
    if not headers:
        return None

    def header_value(name: str) -> Any:
        if hasattr(headers, "get"):
            value = headers.get(name) or headers.get(name.title())
            if value is not None:
                return value
        if isinstance(headers, dict):
            for key, value in headers.items():
                if isinstance(key, str) and key.lower() == name.lower():
                    return value
        return None

    try:
        retry_ms = header_value("retry-after-ms")
        if retry_ms is not None:
            value = float(retry_ms) / 1000.0
            if value > 0:
                return value
    except (TypeError, ValueError):
        pass

    retry_after = header_value("retry-after")
    if retry_after is None:
        return None
    text = str(retry_after).strip()
    if not text:
        return None
    try:
        return max(0.1, float(text))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(text)
    except Exception:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.1, (retry_at - datetime.now(retry_at.tzinfo)).total_seconds())


def _error_event(exc: Exception, prefix: str = "") -> dict:
    """把 SDK/httpx 异常转换为网关可判断的结构化 error 事件。"""
    response = getattr(exc, "response", None)
    status_code = getattr(exc, "status_code", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    payload = _get_error_payload(exc)
    err_type, err_code = _error_type_code(payload)
    headers = getattr(response, "headers", None)
    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        error_kind = "timeout"
    elif "connection" in name:
        error_kind = "connection"
    else:
        error_kind = None

    body = payload if isinstance(payload, str) else ""
    message = body.strip()[:500] if body.strip() else str(exc)
    if prefix:
        message = f"{prefix}: {message}"

    return {
        "type": "error",
        "message": message,
        "status_code": int(status_code) if status_code is not None else None,
        "error_kind": error_kind,
        "error_type": err_type,
        "error_code": err_code,
        "retry_after": _retry_after_from_headers(headers),
    }


def _parse_tool_calls(tc_buf: dict[int, dict[str, str]]) -> Iterator[dict]:
    """把流式 tool_call 分片组装成 AgentLoop 已经认识的事件格式。"""
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


class OpenAIAdapter:
    """OpenAI-compatible 适配器。

    适用于官方 OpenAI、DeepSeek、Ollama 等兼容 Chat Completions 的端点。
    """

    def stream(self, request: LLMRequest) -> Iterator[dict]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.tools:
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"

        try:
            client = OpenAI(
                api_key=request.api_key or "sk-placeholder",
                base_url=request.base_url,
                timeout=_TIMEOUT,
            )
            stream = client.chat.completions.create(**kwargs)
            tc_buf: dict[int, dict[str, str]] = {}
            reasoning_buf = ""

            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_buf += reasoning

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

            yield from _parse_tool_calls(tc_buf)
            yield {"type": "done", "reasoning_content": reasoning_buf or None}
        except Exception as exc:
            yield _error_event(exc)


class ShangdaoAdapter:
    """商道 SSE 网关适配器。"""

    def stream(self, request: LLMRequest) -> Iterator[dict]:
        model_meta = request.extra.get("model_meta")
        if not model_meta:
            yield {"type": "error", "message": f"未知的商道模型: {request.model}"}
            return
        if not request.api_key:
            yield {"type": "error", "message": "商道 API Key 未配置"}
            return

        url = (
            f"{request.base_url.rstrip('/')}/"
            f"{model_meta['path_prefix']}/v1/chat/completions"
        )
        body: dict[str, Any] = {
            model_meta["body_model_field"]: model_meta["body_model_value"],
            "messages": request.messages,
            "stream": True,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            body["tools"] = request.tools
            body["tool_choice"] = "auto"

        headers = {
            "x-api-key": f"Bearer {request.api_key}",
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
                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            reasoning_buf += reasoning
                        content = delta.get("content")
                        if content:
                            yield {"type": "text", "delta": content}
                        if choice.get("finish_reason") in ("stop", "tool_calls"):
                            break

                    yield {"type": "done", "reasoning_content": reasoning_buf or None}
        except Exception as exc:
            yield _error_event(exc, "商道 API 请求失败")


class LiteLLMAdapter:
    """LiteLLM Python 包适配器。"""

    def stream(self, request: LLMRequest) -> Iterator[dict]:
        try:
            import litellm
        except ImportError:
            yield {"type": "error", "message": "LiteLLM 未安装，请运行: pip install litellm"}
            return

        if not request.provider:
            yield {"type": "error", "message": f"模型 {request.model} 未找到"}
            return
        if not request.api_key:
            yield {"type": "error", "message": f"{request.provider} API Key 未配置"}
            return

        kwargs: dict[str, Any] = {
            "model": f"{request.provider}/{request.model}",
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True,
            "api_key": request.api_key,
        }
        if request.tools:
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"

        try:
            stream = litellm.completion(**kwargs)
            tc_buf: dict[int, dict[str, str]] = {}
            reasoning_buf = ""

            for chunk in stream:
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_buf += reasoning

                if hasattr(delta, "content") and delta.content:
                    yield {"type": "text", "delta": delta.content}

                if hasattr(delta, "tool_calls") and delta.tool_calls:
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

                if hasattr(choice, "finish_reason") and choice.finish_reason in ("stop", "tool_calls"):
                    break

            yield from _parse_tool_calls(tc_buf)
            yield {"type": "done", "reasoning_content": reasoning_buf or None}
        except Exception as exc:
            event = _error_event(exc, "LiteLLM 调用失败")
            yield event


class RetryPolicy:
    """模型调用重试策略。

    只重试瞬态错误：网络/超时、部分 5xx、429 等。鉴权、参数、
    余额不足这类错误不重试，避免制造无意义请求。
    """

    _RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
    _TRANSIENT_KINDS = frozenset({"timeout", "connection"})
    _NON_RETRYABLE_429_TOKENS = frozenset({
        "insufficient_quota",
        "quota_exceeded",
        "quota_exhausted",
        "billing_hard_limit_reached",
        "insufficient_balance",
        "payment_required",
    })
    _RETRYABLE_TEXT = (
        "429",
        "rate limit",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "overloaded",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "速率限制",
        "访问量过大",
    )

    def __init__(
        self,
        max_attempts: int = 3,
        delays: tuple[float, ...] = (1.0, 2.0),
        sleep: Callable[[float], None] = time.sleep,
        jitter: float = 0.0,
    ):
        self.max_attempts = max(1, max_attempts)
        self.delays = delays
        self.sleep = sleep
        self.jitter = max(0.0, jitter)

    def is_retryable(self, event: dict) -> bool:
        """根据结构化错误字段判断是否值得重试。"""
        status = event.get("status_code")
        if status is not None:
            status = int(status)
            if status == 429:
                err_type = (event.get("error_type") or "").lower()
                err_code = (event.get("error_code") or "").lower()
                if err_type in self._NON_RETRYABLE_429_TOKENS or err_code in self._NON_RETRYABLE_429_TOKENS:
                    return False
                return True
            if status in self._RETRYABLE_STATUS_CODES or status >= 500:
                return True
            return False

        kind = (event.get("error_kind") or "").lower()
        if kind in self._TRANSIENT_KINDS:
            return True
        text = (event.get("message") or "").lower()
        return any(marker in text for marker in self._RETRYABLE_TEXT)

    def wait(self, attempt: int, event: dict) -> float:
        """按 Retry-After 或退避表等待，并返回实际等待秒数。"""
        retry_after = event.get("retry_after")
        if retry_after:
            delay = float(retry_after)
        else:
            delay = self.delays[min(attempt - 1, len(self.delays) - 1)] if self.delays else 0.0
            if self.jitter:
                delay += random.uniform(0.0, self.jitter)
        self.sleep(delay)
        return delay


class LocalRateLimiter:
    """进程内简单限流器。

    当前只做桌面应用本地治理：全局并发 + 每个 provider/model 的 RPM。
    不依赖外部 Redis/数据库。
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        rpm: int = 60,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._semaphore = threading.Semaphore(max(1, max_concurrent))
        self._rpm = max(1, rpm)
        self._sleep = sleep
        self._lock = threading.Lock()
        self._timestamps: dict[str, deque[float]] = defaultdict(deque)

    @contextmanager
    def acquire(self, key: str):
        self._semaphore.acquire()
        try:
            self._wait_for_slot(key)
            yield
        finally:
            self._semaphore.release()

    def _wait_for_slot(self, key: str) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                bucket = self._timestamps[key]
                while bucket and now - bucket[0] >= 60:
                    bucket.popleft()
                if len(bucket) < self._rpm:
                    bucket.append(now)
                    return
                wait_s = max(0.01, 60 - (now - bucket[0]))
            self._sleep(wait_s)


class GatewayLogger:
    """脱敏 JSONL 调用日志。

    只记录模型、耗时、重试、错误类型等排障字段，不记录 prompt 和 API Key。
    """

    def __init__(self, path: Path | str | None = _DEFAULT_LOG_PATH, enabled: bool = True):
        self._path = Path(path) if path else None
        self._enabled = enabled and self._path is not None
        self._lock = threading.Lock()

    @classmethod
    def disabled(cls) -> "GatewayLogger":
        return cls(path=None, enabled=False)

    def write(self, record: dict[str, Any]) -> None:
        if not self._enabled or self._path is None:
            return
        safe = {k: v for k, v in record.items() if v is not None}
        safe["created_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(safe, ensure_ascii=False)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:
            logger.exception("Failed to write LLM gateway log")


class LLMGateway:
    """统一网关入口。

    上层调用 chat_stream()，网关负责：
    1. 从配置解析当前 provider/model；
    2. 进入本地限流；
    3. 调用对应 adapter；
    4. 必要时重试；
    5. 写脱敏日志。
    """

    def __init__(
        self,
        config_proxy: Any = None,
        adapters: dict[str, ProviderAdapter] | None = None,
        retry_policy: RetryPolicy | None = None,
        limiter: LocalRateLimiter | None = None,
        logger: GatewayLogger | None = None,
    ):
        self._proxy = config_proxy
        self._adapters = adapters or {
            "openai": OpenAIAdapter(),
            "shangdao": ShangdaoAdapter(),
            "litellm": LiteLLMAdapter(),
        }
        self._retry_policy = retry_policy or RetryPolicy()
        self._limiter = limiter or LocalRateLimiter()
        self._logger = logger if logger is not None else GatewayLogger()

    def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> Iterator[dict]:
        """对外暴露的流式接口，返回 AgentLoop 已兼容的事件字典。"""
        request = self._build_request(messages, tools)
        adapter = self._adapters.get(request.api_type)
        if adapter is None:
            yield {"type": "error", "message": f"未知 API 类型: {request.api_type}"}
            return

        rate_key = f"{request.api_type}:{request.model}"
        with self._limiter.acquire(rate_key):
            yield from self._stream_with_retry(adapter, request)

    def _stream_with_retry(self, adapter: ProviderAdapter, request: LLMRequest) -> Iterator[dict]:
        """执行一次或多次 provider 调用。

        关键规则：只在“还没有向 UI/上层输出任何 text/tool_call”时重试。
        一旦已经流出内容，失败就直接上报，避免出现重复文本或错乱工具调用。
        """
        retry_count = 0
        final_status = "error"
        final_error: dict | None = None
        t0 = time.perf_counter()
        ttft_ms: float | None = None

        for attempt in range(1, self._retry_policy.max_attempts + 1):
            streamed = False
            attempt_request = LLMRequest(
                **{**request.__dict__, "attempt_id": uuid.uuid4().hex}
            )
            for event in adapter.stream(attempt_request):
                event_type = event.get("type")
                if event_type == "text" and ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                if event_type in {"text", "tool_call"}:
                    streamed = True
                    yield event
                    continue
                if event_type == "error":
                    final_error = event
                    can_retry = (
                        not streamed
                        and attempt < self._retry_policy.max_attempts
                        and self._retry_policy.is_retryable(event)
                    )
                    if can_retry:
                        retry_count += 1
                        self._retry_policy.wait(attempt, event)
                        break
                    yield event
                    self._write_log(request, t0, ttft_ms, retry_count, "error", event)
                    return
                if event_type == "done":
                    final_status = "ok"
                    yield event
                    self._write_log(request, t0, ttft_ms, retry_count, final_status, None)
                    return
                yield event
            else:
                self._write_log(request, t0, ttft_ms, retry_count, final_status, final_error)
                return

        if final_error is not None:
            yield final_error
        self._write_log(request, t0, ttft_ms, retry_count, "error", final_error)

    def _write_log(
        self,
        request: LLMRequest,
        started_at: float,
        ttft_ms: float | None,
        retry_count: int,
        status: str,
        error: dict | None,
    ) -> None:
        """写一条脱敏 attempt 汇总日志。"""
        self._logger.write({
            "trace_id": request.trace_id,
            "api_type": request.api_type,
            "provider": request.provider or request.api_type,
            "model": request.model,
            "stream": True,
            "input_message_count": len(request.messages),
            "has_tools": bool(request.tools),
            "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "retry_count": retry_count,
            "status": status,
            "error_type": error.get("error_type") if error else None,
            "error_kind": error.get("error_kind") if error else None,
            "error_status_code": error.get("status_code") if error else None,
            "error_message": error.get("message") if error else None,
        })

    def _build_request(self, messages: list[dict], tools: Optional[list[dict]]) -> LLMRequest:
        """把全局配置或 config_proxy 解析为 provider-neutral 请求。"""
        api_type = self._value("api_type", cfg.apiType)
        trace_id = uuid.uuid4().hex

        if api_type == "shangdao":
            model = self._value("shangdao_model", cfg.shangdaoModel)
            model_meta = SHANGDAO_MODELS.get(model)
            return LLMRequest(
                trace_id=trace_id,
                attempt_id=uuid.uuid4().hex,
                api_type=api_type,
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=cfg.get(cfg.shangdaoMaxTokens),
                temperature=cfg.get(cfg.shangdaoTemperature),
                api_key=get_shangdao_api_key(),
                base_url=cfg.get(cfg.shangdaoBaseUrl),
                extra={"model_meta": model_meta},
            )

        if api_type == "litellm":
            model = self._value("litellm_default_model", cfg.litellmDefaultModel)
            model_config = self._litellm_model_config(model)
            provider = model_config.get("provider", "") if model_config else ""
            return LLMRequest(
                trace_id=trace_id,
                attempt_id=uuid.uuid4().hex,
                api_type=api_type,
                model=model,
                provider=provider,
                messages=messages,
                tools=tools,
                max_tokens=cfg.get(cfg.maxTokens),
                temperature=cfg.get(cfg.temperature),
                api_key=get_litellm_provider_api_key(provider) if provider else "",
            )

        return LLMRequest(
            trace_id=trace_id,
            attempt_id=uuid.uuid4().hex,
            api_type="openai",
            model=self._value("model", cfg.model),
            messages=messages,
            tools=tools,
            max_tokens=cfg.get(cfg.maxTokens),
            temperature=cfg.get(cfg.temperature),
            api_key=get_api_key(),
            base_url=cfg.get(cfg.apiBaseUrl),
        )

    def _value(self, proxy_attr: str, config_item: Any) -> Any:
        """优先读取调用方覆盖配置，否则读取全局 cfg。"""
        if self._proxy is not None and hasattr(self._proxy, proxy_attr):
            return getattr(self._proxy, proxy_attr)
        return cfg.get(config_item)

    def _litellm_model_config(self, model_id: str) -> dict | None:
        """查找 LiteLLM 模型配置，支持 tool_generator 的临时模型覆盖。"""
        if self._proxy is not None and hasattr(self._proxy, "get_litellm_model_by_id"):
            model = self._proxy.get_litellm_model_by_id(model_id)
            if model:
                return model
        return next(
            (m for m in cfg.get(cfg.litellmModels) if m.get("id") == model_id),
            None,
        )
