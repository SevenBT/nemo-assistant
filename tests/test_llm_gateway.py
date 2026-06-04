import json
from pathlib import Path

from app.core.llm_gateway import (
    GatewayLogger,
    LLMGateway,
    LocalRateLimiter,
    ProviderAdapter,
    RetryPolicy,
)


class ScriptedAdapter(ProviderAdapter):
    def __init__(self, attempts):
        self._attempts = list(attempts)
        self.calls = 0

    def stream(self, request):
        self.calls += 1
        for event in self._attempts.pop(0):
            yield event


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
