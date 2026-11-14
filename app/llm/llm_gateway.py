"""Unified LLM gateway.

Centralizes model routing, local rate limiting, retry policy, streaming
event normalization, and JSONL observability logging.

统一 LLM 网关。
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from app.config.runtime_paths import DATA_DIR
from app.llm.cancellation import CancellationToken, _close_resource
from app.llm.runtime_config import GatewayConfig, provider_api_type
from app.llm.billing import billing_url_for, normalize_provider_cost

logger = logging.getLogger(__name__)

_LOG_DIR = DATA_DIR.parent / "logs"
_DEFAULT_LOG_PATH = _LOG_DIR / "llm_gateway.jsonl"
_WAIT_SLICE_SECONDS = 0.05
_MAX_RETRY_AFTER_SECONDS = 30.0
def _is_cancelled(cancel_token: "CancellationToken | None") -> bool:
    return bool(cancel_token and cancel_token.is_cancelled())


from app.llm.providers.contracts import LLMRequest, ProviderAdapter
from app.llm.providers.errors import (
    _error_event, _coerce_int, _normalize_usage, sanitize_error_event,
)


def _bounded_wait(
    delay: float,
    *,
    cancel_token: CancellationToken | None,
    deadline: float | None,
    sleep: Callable[[float], None],
) -> bool:
    """Wait in bounded slices; return False on cancellation/deadline."""

    remaining = max(0.0, delay)
    while remaining > 0:
        if _is_cancelled(cancel_token):
            return False
        deadline_remaining = (
            max(0.0, deadline - time.monotonic()) if deadline is not None else remaining
        )
        if deadline is not None and deadline_remaining <= 0:
            return False
        interval = min(remaining, deadline_remaining, _WAIT_SLICE_SECONDS)
        sleep(interval)
        remaining -= interval
    return not _is_cancelled(cancel_token)


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
        # Local configuration/protocol failures and refused ports cannot heal by retrying.
        if (event.get("error_kind") or "").lower() in ('connection_refused', 'protocol', 'configuration'):
            return False
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

    def wait(
        self,
        attempt: int,
        event: dict,
        *,
        cancel_token: CancellationToken | None = None,
        deadline: float | None = None,
    ) -> float:
        """Wait for bounded Retry-After/backoff, interruptible by cancellation."""

        retry_after = event.get("retry_after")
        if retry_after:
            delay = min(float(retry_after), _MAX_RETRY_AFTER_SECONDS)
        else:
            delay = self.delays[min(attempt - 1, len(self.delays) - 1)] if self.delays else 0.0
            if self.jitter:
                delay += random.uniform(0.0, self.jitter)
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.monotonic()))
        if cancel_token is None and deadline is None:
            self.sleep(delay)
            return delay
        _bounded_wait(
            delay,
            cancel_token=cancel_token,
            deadline=deadline,
            sleep=self.sleep,
        )
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
    def acquire(
        self,
        key: str,
        *,
        cancel_token: CancellationToken | None = None,
        deadline: float | None = None,
    ):
        acquired = False
        while not acquired:
            if _is_cancelled(cancel_token) or (
                deadline is not None and time.monotonic() >= deadline
            ):
                yield False
                return
            timeout = _WAIT_SLICE_SECONDS
            if deadline is not None:
                timeout = min(timeout, max(0.0, deadline - time.monotonic()))
            acquired = self._semaphore.acquire(timeout=timeout)
        try:
            if not self._wait_for_slot(
                key, cancel_token=cancel_token, deadline=deadline
            ):
                yield False
                return
            yield True
        finally:
            self._semaphore.release()

    def _wait_for_slot(
        self,
        key: str,
        *,
        cancel_token: CancellationToken | None = None,
        deadline: float | None = None,
    ) -> bool:
        while True:
            if _is_cancelled(cancel_token) or (
                deadline is not None and time.monotonic() >= deadline
            ):
                return False
            with self._lock:
                now = time.monotonic()
                bucket = self._timestamps[key]
                while bucket and now - bucket[0] >= 60:
                    bucket.popleft()
                if len(bucket) < self._rpm:
                    bucket.append(now)
                    return True
                wait_s = max(0.01, 60 - (now - bucket[0]))
            if not _bounded_wait(
                wait_s,
                cancel_token=cancel_token,
                deadline=deadline,
                sleep=self._sleep,
            ):
                return False


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
        trace_sink: Any = None,
        config: GatewayConfig | None = None,
    ):
        self._config = config
        self._proxy = config_proxy
        if adapters is None:
            from app.llm.providers.adapter import HTTPProviderAdapter
            adapter = HTTPProviderAdapter()
            from app.llm.providers.adapter import CODECS
            adapters = {key: adapter for key in CODECS}
        self._adapters = adapters
        self._retry_policy = retry_policy or RetryPolicy()
        self._limiter = limiter or LocalRateLimiter()
        self._logger = logger if logger is not None else GatewayLogger()
        # 可选 TraceStore：AgentLoop 链路传入后，LLM 汇总额外按 trace_id 落库。
        # 其它调用方（consolidator/dream/...）不传则只走 JSONL，行为不变。
        self._trace_sink = trace_sink

    def close(self) -> None:
        """Release persistent HTTP pools after active calls have been cancelled."""
        for adapter in {id(a): a for a in self._adapters.values()}.values():
            _close_resource(adapter)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        cancel_token: CancellationToken | None = None,
        trace_id: str | None = None,
        seq: int = 0,
        stream_timeout: float | None = None,
    ) -> Iterator[dict]:
        """对外暴露的流式接口，返回 AgentLoop 已兼容的事件字典。

        trace_id 由 AgentLoop 在 turn 开始时生成并贯穿；缺省时网关自生成一个，
        保证非 AgentLoop 调用方（consolidator/dream/tool_generator/result_bubble）
        无需改动也能正常工作。seq 标记同一 turn 内第几次 LLM 往返。
        """
        try:
            request = self._build_request(messages, tools, trace_id, stream_timeout)
        except ValueError as exc:
            yield _error_event(exc, '模型配置无效')
            return
        adapter = self._adapters.get(request.api_type)
        if adapter is None:
            yield {"type": "error", "message": f"未知 API 类型: {request.api_type}"}
            return

        rate_key = f"{request.api_type}:{request.model}"
        deadline = (
            time.monotonic() + stream_timeout
            if stream_timeout is not None and stream_timeout > 0
            else None
        )
        with self._limiter.acquire(
            rate_key, cancel_token=cancel_token, deadline=deadline
        ) as acquired:
            if not acquired:
                return
            yield from self._stream_with_retry(
                adapter, request, cancel_token, seq, deadline=deadline
            )

    def _stream_with_retry(
        self,
        adapter: ProviderAdapter,
        request: LLMRequest,
        cancel_token: CancellationToken | None = None,
        seq: int = 0,
        *,
        deadline: float | None = None,
    ) -> Iterator[dict]:
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
            if _is_cancelled(cancel_token) or (
                deadline is not None and time.monotonic() >= deadline
            ):
                return
            t0, ttft_ms = time.perf_counter(), None
            streamed = False
            attempt_request = LLMRequest(
                **{**request.__dict__, "attempt_id": uuid.uuid4().hex,
                   "stream_timeout": max(0.001, deadline - time.monotonic())
                   if deadline is not None else request.stream_timeout}
            )
            request = attempt_request
            stream_iter = adapter.stream(attempt_request, cancel_token=cancel_token)
            retry_next_attempt = False
            try:
                for event in stream_iter:
                    if _is_cancelled(cancel_token):
                        _close_resource(stream_iter)
                        self._write_log(
                            request, t0, ttft_ms, retry_count, "cancelled", None, seq
                        )
                        return
                    event_type = event.get("type")
                    if event_type == "progress":
                        streamed = True
                        continue
                    if event_type == "text" and ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t0) * 1000
                    if event_type in {"text", "tool_call"}:
                        streamed = True
                        yield event
                        continue
                    if event_type == "error":
                        error_usage = event.get("usage")
                        error_cost = event.get("provider_cost")
                        event = sanitize_error_event(event)
                        final_error = event
                        can_retry = (
                            not streamed
                            and attempt < self._retry_policy.max_attempts
                            and self._retry_policy.is_retryable(event)
                            and not _is_cancelled(cancel_token)
                        )
                        if can_retry:
                            self._write_log(request, t0, ttft_ms, retry_count, "error", event, seq, error_usage, provider_cost=error_cost)
                            retry_count += 1
                            self._retry_policy.wait(
                                attempt,
                                event,
                                cancel_token=cancel_token,
                                deadline=deadline,
                            )
                            if _is_cancelled(cancel_token) or (
                                deadline is not None and time.monotonic() >= deadline
                            ):
                                return
                            retry_next_attempt = True
                            break
                        # 同 done：先写日志再 yield，否则消费者 break 后丢日志。
                        self._write_log(request, t0, ttft_ms, retry_count, "error", event, seq, error_usage, provider_cost=error_cost)
                        yield event
                        return
                    if event_type == "done":
                        final_status = "ok"
                        # 必须在 yield 之前写日志：消费者（AgentLoop）收到 done
                        # 即 break，生成器会永久挂起在 yield 处，yield 之后的代码
                        # 再也执行不到 —— 放后面会导致 llm_calls/token 永不落库。
                        self._write_log(
                            request, t0, ttft_ms, retry_count, final_status,
                            None, seq, event.get("usage"),
                            provider_cost=event.get("provider_cost"),
                        )
                        yield event
                        return
                    yield event
            except Exception as exc:
                error = _error_event(exc)
                self._write_log(request, t0, ttft_ms, retry_count, "error", error, seq)
                raise
            finally:
                _close_resource(stream_iter)
            if retry_next_attempt:
                continue
            status = "cancelled" if _is_cancelled(cancel_token) else final_status
            self._write_log(request, t0, ttft_ms, retry_count, status, final_error, seq)
            return

        if _is_cancelled(cancel_token):
            self._write_log(request, t0, ttft_ms, retry_count, "cancelled", None, seq)
            return
        if final_error is not None:
            yield final_error
        self._write_log(request, t0, ttft_ms, retry_count, "error", final_error, seq)

    def _write_log(
        self,
        request: LLMRequest,
        started_at: float,
        ttft_ms: float | None,
        retry_count: int,
        status: str,
        error: dict | None,
        seq: int = 0,
        usage: dict | None = None,
        provider_cost: dict | None = None,
    ) -> None:
        """写一条脱敏 attempt 汇总日志，并按 trace_id 同步到 TraceStore。"""
        safe_error = sanitize_error_event(error) if error else None
        record = {
            "trace_id": request.trace_id,
            "attempt_id": request.attempt_id,
            "api_type": request.api_type,
            "profile_revision": 1,
            "provider": request.provider or request.api_type,
            "model": request.model,
            "stream": True,
            "input_message_count": len(request.messages),
            "has_tools": bool(request.tools),
            "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
            "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "retry_count": retry_count,
            "status": status,
            "error_type": safe_error.get("error_type") if safe_error else None,
            "error_kind": safe_error.get("error_kind") if safe_error else None,
            "error_status_code": safe_error.get("status_code") if safe_error else None,
            "error_message": safe_error.get("message") if safe_error else None,
            "billing_url": billing_url_for(request.provider, request.base_url),
        }
        cost = normalize_provider_cost(provider_cost)
        if cost is not None:
            record["provider_cost"] = cost
        # 保留服务商明确返回的 token 用量，包括失败或截断的调用。
        if usage:
            usage = {k: _coerce_int(usage.get(k)) for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens")}
            record["usage"] = usage
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                if usage.get(key) is not None:
                    record[key] = usage[key]
        self._logger.write(record)
        if self._trace_sink is not None:
            try:
                self._trace_sink.record_llm_call(request.trace_id, seq, record)
            except Exception:
                logger.debug("[LLMGateway] trace sink record_llm_call failed", exc_info=True)

    def _build_request(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        trace_id: str | None = None,
        stream_timeout: float | None = None,
    ) -> LLMRequest:
        """把全局配置或 config_proxy 解析为 provider-neutral 请求。"""
        trace_id = trace_id or uuid.uuid4().hex

        config = self._config
        if config is None:
            from app.desktop.desktop_runtime import gateway_config
            config = gateway_config(self._proxy)
        return LLMRequest(
            trace_id=trace_id, attempt_id=uuid.uuid4().hex,
            api_type=provider_api_type(config.provider, config.api_protocol),
            api_protocol=config.api_protocol,
            model=config.model, provider=config.provider, base_url=config.base_url,
            api_key=config.api_key, messages=messages, tools=tools,
            max_tokens=config.max_tokens, temperature=config.temperature,
            top_p=config.top_p, stream_timeout=stream_timeout,
        )
