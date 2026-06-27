import json
from pathlib import Path

import httpx

from app.core.llm_gateway import (
    CancellationToken,
    GatewayLogger,
    LLMGateway,
    LLMRequest,
    LocalRateLimiter,
    ProviderAdapter,
    RetryPolicy,
    _error_event,
)


class ScriptedAdapter(ProviderAdapter):
    def __init__(self, attempts):
        self._attempts = list(attempts)
        self.calls = 0

    def stream(self, request, cancel_token=None):
        self.calls += 1
        for event in self._attempts.pop(0):
            yield event


class CloseableResource:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class CancellingAdapter(ProviderAdapter):
    def __init__(self):
        self.calls = 0
        self.resource = CloseableResource()

    def stream(self, request, cancel_token=None):
        self.calls += 1
        if cancel_token:
            cancel_token.add_resource(self.resource)
        try:
            yield {"type": "text", "delta": "partial"}
            if cancel_token:
                cancel_token.cancel()
            yield {"type": "error", "message": "should not retry", "error_kind": "connection"}
        finally:
            if cancel_token:
                cancel_token.remove_resource(self.resource)


class SpyLimiter(LocalRateLimiter):
    def __init__(self):
        super().__init__(max_concurrent=99, rpm=9999, sleep=lambda _: None)
        self.keys = []

    def acquire(self, key):
        self.keys.append(key)
        return super().acquire(key)


class StaticConfig:
    litellm_default_model = "test-model"


def test_gateway_retries_retryable_error_before_streaming():
    adapter = ScriptedAdapter([
        [{"type": "error", "message": "rate limit", "status_code": 429}],
        [{"type": "text", "delta": "ok"}, {"type": "done"}],
    ])
    sleeps = []
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=2, sleep=sleeps.append),
        logger=GatewayLogger.disabled(),
    )

    events = list(gateway.chat_stream([{"role": "user", "content": "hi"}]))

    assert adapter.calls == 2
    assert sleeps == [1.0]
    assert events == [{"type": "text", "delta": "ok"}, {"type": "done"}]


def test_gateway_does_not_retry_after_text_was_streamed():
    adapter = ScriptedAdapter([
        [
            {"type": "text", "delta": "partial"},
            {"type": "error", "message": "connection reset", "error_kind": "connection"},
        ],
        [{"type": "text", "delta": "duplicate"}, {"type": "done"}],
    ])
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=2, sleep=lambda _: None),
        logger=GatewayLogger.disabled(),
    )

    events = list(gateway.chat_stream([{"role": "user", "content": "hi"}]))

    assert adapter.calls == 1
    assert events[-1]["type"] == "error"
    assert events[0] == {"type": "text", "delta": "partial"}


def test_gateway_uses_limiter_with_api_type_and_model_key():
    adapter = ScriptedAdapter([[{"type": "done"}]])
    limiter = SpyLimiter()
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        limiter=limiter,
        logger=GatewayLogger.disabled(),
    )

    list(gateway.chat_stream([{"role": "user", "content": "hi"}]))

    assert limiter.keys == ["litellm:test-model"]


def test_gateway_logger_writes_sanitized_jsonl(tmp_path: Path):
    log_path = tmp_path / "llm_gateway.jsonl"
    adapter = ScriptedAdapter([[{"type": "text", "delta": "ok"}, {"type": "done"}]])
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        logger=GatewayLogger(log_path),
    )

    list(gateway.chat_stream([{"role": "user", "content": "secret prompt"}]))

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["api_type"] == "litellm"
    assert record["model"] == "test-model"
    assert record["status"] == "ok"
    assert record["input_message_count"] == 1
    assert "secret prompt" not in lines[0]


def test_gateway_stops_stream_and_retry_after_cancellation():
    adapter = CancellingAdapter()
    token = CancellationToken()
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=2, sleep=lambda _: None),
        logger=GatewayLogger.disabled(),
    )

    events = list(gateway.chat_stream(
        [{"role": "user", "content": "hi"}],
        cancel_token=token,
    ))

    assert events == [{"type": "text", "delta": "partial"}]
    assert adapter.calls == 1
    assert adapter.resource.closed is True


def test_error_event_handles_unread_streaming_httpx_response():
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(
        504,
        request=request,
        stream=httpx.ByteStream(b"gateway timeout"),
    )
    exc = httpx.HTTPStatusError(
        "Server error '504 Gateway Timeout'",
        request=request,
        response=response,
    )

    event = _error_event(exc, "LiteLLM 调用失败")

    assert event["type"] == "error"
    assert event["status_code"] == 504
    assert "LiteLLM 调用失败" in event["message"]
    assert "gateway timeout" in event["message"]

