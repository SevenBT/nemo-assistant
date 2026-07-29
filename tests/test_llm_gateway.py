import json
import threading
import time
from pathlib import Path

import httpx
import pytest

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

    def acquire(self, key, **kwargs):
        self.keys.append(key)
        return super().acquire(key, **kwargs)


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


def test_connection_refused_wrapped_as_500_is_not_retried():
    # LiteLLM 把 ConnectionRefusedError 包成 InternalServerError(500)，
    # 网关不应把它当 5xx 瞬态错误重试。
    err = {
        "type": "error",
        "message": "LiteLLM 调用失败: litellm.InternalServerError: DeepseekException - [WinError 10061] 由于目标计算机积极拒绝，无法连接。",
        "status_code": 500,
        "error_kind": "connection_refused",
    }
    adapter = ScriptedAdapter([[err], [{"type": "done"}]])
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=3, sleep=lambda _: None),
        logger=GatewayLogger.disabled(),
    )

    events = list(gateway.chat_stream([{"role": "user", "content": "hi"}]))

    assert adapter.calls == 1
    assert events[-1]["type"] == "error"


def test_error_event_classifies_winerror_10061_as_connection_refused():
    exc = Exception(
        "litellm.InternalServerError: InternalServerError: DeepseekException - "
        "[WinError 10061] 由于目标计算机积极拒绝，无法连接。"
    )

    event = _error_event(exc, "LiteLLM 调用失败")

    assert event["error_kind"] == "connection_refused"
    assert RetryPolicy().is_retryable(event) is False


def test_error_event_strips_litellm_boilerplate_from_message():
    exc = Exception(
        "litellm.InternalServerError: DeepseekException - [WinError 10061] "
        "由于目标计算机积极拒绝，无法连接。\n"
        "Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new\n"
        "LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.\n"
        "Provider List: https://docs.litellm.ai/docs/providers"
    )

    event = _error_event(exc, "LiteLLM 调用失败")

    assert "由于目标计算机积极拒绝" in event["message"]
    assert "Give Feedback" not in event["message"]
    assert "Provider List" not in event["message"]
    assert "docs.litellm.ai" not in event["message"]
    # 样板行剥掉后仍能识别为连接被拒绝。
    assert event["error_kind"] == "connection_refused"


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


class BlockingLimiter(LocalRateLimiter):
    def __init__(self):
        super().__init__(max_concurrent=1, rpm=9999)
        self.hold = self._semaphore.acquire()

    def release_hold(self):
        self._semaphore.release()


class CancelDuringWait:
    def __init__(self, token: CancellationToken):
        self.token = token
        self.calls = 0

    def __call__(self, _seconds: float) -> None:
        self.calls += 1
        self.token.cancel()


@pytest.mark.parametrize("wait_kind", ["semaphore", "rpm", "retry_after"])
def test_generation_cancellation_interrupts_all_local_waits_promptly(wait_kind):
    adapter = ScriptedAdapter([[{"type": "error", "message": "busy", "status_code": 429, "retry_after": 3600}]])
    token = CancellationToken()
    limiter = LocalRateLimiter(max_concurrent=1, rpm=9999)
    retry = RetryPolicy(max_attempts=2)

    if wait_kind == "semaphore":
        limiter = BlockingLimiter()
    elif wait_kind == "rpm":
        cancel_sleep = CancelDuringWait(token)
        limiter = LocalRateLimiter(max_concurrent=1, rpm=1, sleep=cancel_sleep)
        limiter._timestamps["litellm:test-model"].append(time.monotonic())
    else:
        retry = RetryPolicy(max_attempts=2, sleep=CancelDuringWait(token))

    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=retry,
        limiter=limiter,
        logger=GatewayLogger.disabled(),
    )
    events = []
    worker = threading.Thread(
        target=lambda: events.extend(
            gateway.chat_stream(
                [{"role": "user", "content": "hi"}],
                cancel_token=token,
                stream_timeout=0.2,
            )
        )
    )
    worker.start()
    if wait_kind == "semaphore":
        time.sleep(0.03)
        token.cancel()
    worker.join(0.5)
    if isinstance(limiter, BlockingLimiter):
        limiter.release_hold()

    assert worker.is_alive() is False
    assert events == []


def test_retry_after_is_capped_by_generation_deadline():
    sleeps = []
    adapter = ScriptedAdapter([
        [{"type": "error", "message": "busy", "status_code": 429, "retry_after": 3600}],
        [{"type": "done"}],
    ])
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=2, sleep=sleeps.append),
        logger=GatewayLogger.disabled(),
    )

    list(gateway.chat_stream(
        [{"role": "user", "content": "hi"}],
        cancel_token=CancellationToken(),
        stream_timeout=0.25,
    ))

    assert sleeps
    assert sum(sleeps) <= 0.25


def test_error_event_redacts_credentials_paths_and_nested_provider_payload(tmp_path):
    secret_path = str(tmp_path / "private" / "request.json")
    exc = Exception(
        "Authorization: Bearer bearer-secret api_key=key-secret password=pw-secret "
        "https://provider.test/v1?token=query-secret&safe=ok "
        f"path={secret_path} "
        "payload={'nested': {'apiKey': 'nested-secret'}, 'status': 'overloaded'}"
    )
    exc.body = {
        "error": {
            "type": "rate_limit",
            "code": "429",
            "message": "overloaded",
            "token": "body-secret",
            "nested": [{"password": "nested-password"}],
        }
    }

    event = _error_event(exc, "Provider request failed")
    serialized = json.dumps(event, ensure_ascii=False)

    for secret in (
        "bearer-secret", "key-secret", "pw-secret", "query-secret",
        "nested-secret", "body-secret", "nested-password", secret_path,
    ):
        assert secret not in serialized
    assert "rate_limit" in serialized
    assert event["status_code"] is None
    assert "Provider request failed" in event["message"]


def test_gateway_persistence_receives_only_sanitized_error_summary(tmp_path):
    class TraceSink:
        def __init__(self):
            self.records = []

        def record_llm_call(self, _trace_id, _seq, record):
            self.records.append(record)

    secret = "Bearer persist-secret api_key=persist-key C:/Users/private/request.json"
    adapter = ScriptedAdapter([[{"type": "error", "message": secret, "status_code": 401}]])
    sink = TraceSink()
    log_path = tmp_path / "gateway.jsonl"
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"litellm": adapter},
        retry_policy=RetryPolicy(max_attempts=1),
        logger=GatewayLogger(log_path),
        trace_sink=sink,
    )

    events = list(gateway.chat_stream([{"role": "user", "content": "hi"}]))
    persisted = log_path.read_text(encoding="utf-8") + json.dumps(sink.records)

    assert "persist-secret" not in json.dumps(events)
    assert "persist-key" not in persisted
    assert "C:/Users/private" not in persisted
    assert sink.records[0]["error_status_code"] == 401

