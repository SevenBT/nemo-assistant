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
    ShangdaoAdapter,
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
    api_type = "openai"
    model = "test-model"
    shangdao_model = "Qwen3_235B"
    litellm_default_model = "deepseek-chat"


class FakeShangdaoResponse:
    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines


class FakeShangdaoClient:
    response = None
    captured_request = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, json, headers):
        self.__class__.captured_request = {
            "method": method,
            "url": url,
            "json": json,
            "headers": headers,
        }
        return self.__class__.response


def _sse(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False)


def _shangdao_request(tools=None):
    return LLMRequest(
        trace_id="trace",
        attempt_id="attempt",
        api_type="shangdao",
        model="Qwen3_235B",
        messages=[{"role": "user", "content": "算一下 1+1"}],
        tools=tools,
        max_tokens=2048,
        temperature=0.7,
        api_key="sk-test",
        base_url="https://example.test",
        extra={
            "model_meta": {
                "path_prefix": "CMHK-LMMP-PRD_Qwen3_235B_Ins/CMHK-LMMP-PRD",
                "body_model_field": "mode1",
                "body_model_value": "Qwen3_235B",
            }
        },
    )


def test_gateway_retries_retryable_error_before_streaming():
    adapter = ScriptedAdapter([
        [{"type": "error", "message": "rate limit", "status_code": 429}],
        [{"type": "text", "delta": "ok"}, {"type": "done"}],
    ])
    sleeps = []
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"openai": adapter},
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
        adapters={"openai": adapter},
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
        adapters={"openai": adapter},
        limiter=limiter,
        logger=GatewayLogger.disabled(),
    )

    list(gateway.chat_stream([{"role": "user", "content": "hi"}]))

    assert limiter.keys == ["openai:test-model"]


def test_gateway_logger_writes_sanitized_jsonl(tmp_path: Path):
    log_path = tmp_path / "llm_gateway.jsonl"
    adapter = ScriptedAdapter([[{"type": "text", "delta": "ok"}, {"type": "done"}]])
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"openai": adapter},
        logger=GatewayLogger(log_path),
    )

    list(gateway.chat_stream([{"role": "user", "content": "secret prompt"}]))

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["api_type"] == "openai"
    assert record["model"] == "test-model"
    assert record["status"] == "ok"
    assert record["input_message_count"] == 1
    assert "secret prompt" not in lines[0]


def test_gateway_stops_stream_and_retry_after_cancellation():
    adapter = CancellingAdapter()
    token = CancellationToken()
    gateway = LLMGateway(
        config_proxy=StaticConfig(),
        adapters={"openai": adapter},
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

    event = _error_event(exc, "商道 API 请求失败")

    assert event["type"] == "error"
    assert event["status_code"] == 504
    assert "商道 API 请求失败" in event["message"]
    assert "gateway timeout" in event["message"]


def test_shangdao_adapter_parses_streamed_tool_calls(monkeypatch):
    import app.core.llm_gateway as llm_gateway

    FakeShangdaoClient.response = FakeShangdaoResponse([
        _sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": "{\"expression\": ",
                        },
                    }]
                }
            }]
        }),
        _sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": "\"1+1\"}"},
                    }]
                },
                "finish_reason": "tool_calls",
            }]
        }),
    ])
    monkeypatch.setattr(llm_gateway.httpx, "Client", FakeShangdaoClient)

    events = list(ShangdaoAdapter().stream(_shangdao_request(tools=[{
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "calculate",
            "parameters": {"type": "object"},
        },
    }])))

    assert events == [
        {
            "type": "tool_call",
            "id": "call_1",
            "name": "calculator",
            "arguments": {"expression": "1+1"},
        },
        {"type": "done", "reasoning_content": None},
    ]
    assert FakeShangdaoClient.captured_request["json"]["tool_choice"] == "auto"


def test_shangdao_adapter_sends_tool_history_as_plain_messages(monkeypatch):
    import app.core.llm_gateway as llm_gateway

    FakeShangdaoClient.response = FakeShangdaoResponse([
        _sse({
            "choices": [{
                "delta": {"content": "结果是 2"},
                "finish_reason": "stop",
            }]
        }),
    ])
    monkeypatch.setattr(llm_gateway.httpx, "Client", FakeShangdaoClient)
    request = _shangdao_request()
    request = LLMRequest(
        **{
            **request.__dict__,
            "messages": [
                {"role": "user", "content": "算 1+1"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": "{\"expression\": \"1+1\"}",
                        },
                    }],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "{\"status\":\"success\",\"data\":{\"result\":2}}",
                },
            ],
        }
    )

    events = list(ShangdaoAdapter().stream(request))

    sent_messages = FakeShangdaoClient.captured_request["json"]["messages"]
    assert events == [
        {"type": "text", "delta": "结果是 2"},
        {"type": "done", "reasoning_content": None},
    ]
    assert sent_messages == [
        {"role": "user", "content": "算 1+1"},
        {
            "role": "assistant",
            "content": (
                "已请求调用工具:\n"
                "- calculator({\"expression\": \"1+1\"})"
            ),
        },
        {
            "role": "user",
            "content": (
                "工具 calculator 返回结果:\n"
                "{\"status\":\"success\",\"data\":{\"result\":2}}"
            ),
        },
    ]
    assert "tool_calls" not in sent_messages[1]
    assert "tool_call_id" not in sent_messages[2]


def test_shangdao_adapter_parses_legacy_function_call(monkeypatch):
    import app.core.llm_gateway as llm_gateway

    FakeShangdaoClient.response = FakeShangdaoResponse([
        _sse({
            "choices": [{
                "delta": {
                    "function_call": {
                        "name": "calculator",
                        "arguments": "{\"expression\": \"2+3\"}",
                    }
                },
                "finish_reason": "tool_calls",
            }]
        }),
    ])
    monkeypatch.setattr(llm_gateway.httpx, "Client", FakeShangdaoClient)

    events = list(ShangdaoAdapter().stream(_shangdao_request()))

    assert events[0]["type"] == "tool_call"
    assert events[0]["id"].startswith("call_")
    assert events[0]["name"] == "calculator"
    assert events[0]["arguments"] == {"expression": "2+3"}
    assert events[1] == {"type": "done", "reasoning_content": None}
