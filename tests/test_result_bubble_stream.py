from app.llm.llm_gateway import CancellationToken
from app.i18n import t
from app.ui.result_bubble import _run_prompt_stream
import time


class FakeGateway:
    def __init__(self, events):
        self.events = events
        self.request = None

    def chat_stream(self, messages, *, tools, cancel_token, trace_id, stream_timeout):
        self.request = (messages, tools, cancel_token, trace_id, stream_timeout)
        yield from self.events


def test_prompt_stream_sends_only_one_user_message_without_tools():
    gateway = FakeGateway(
        [{"type": "text", "delta": "解释"}, {"type": "done"}]
    )
    token = CancellationToken()
    chunks = []
    completed = []
    errors = []

    _run_prompt_stream(
        gateway,
        "请简要解释：\n\n文本",
        token,
            lambda text, _emitted_at: chunks.append(text),
        lambda *_args: completed.append(True),
        errors.append,
        request_id="selection-test",
        action_key="explain",
        request_started=time.perf_counter(),
        prompt_prepare_ms=0.25,
    )

    assert gateway.request == (
        [{"role": "user", "content": "请简要解释：\n\n文本"}],
        None,
        token,
        "selection-test",
        30,
    )
    assert chunks == ["解释"]
    assert completed == [True]
    assert errors == []


def test_prompt_stream_forwards_gateway_errors_without_completion():
    gateway = FakeGateway([{"type": "error", "message": "request failed"}])
    token = CancellationToken()
    completed = []
    errors = []

    _run_prompt_stream(
        gateway,
        "prompt",
        token,
            lambda _chunk, _emitted_at: None,
        lambda *_args: completed.append(True),
        errors.append,
        request_id="selection-error",
        action_key="explain",
        request_started=time.perf_counter(),
        prompt_prepare_ms=0.0,
    )

    assert completed == []
    assert errors == ["request failed"]


def test_prompt_stream_reports_timeout_if_gateway_ends_without_done():
    gateway = FakeGateway([{"type": "text", "delta": "partial"}])
    token = CancellationToken()
    chunks = []
    completed = []
    errors = []

    _run_prompt_stream(
        gateway,
        "prompt",
        token,
        lambda text, _emitted_at: chunks.append(text),
        lambda *_args: completed.append(True),
        errors.append,
        request_id="selection-timeout",
        action_key="explain",
        request_started=time.perf_counter(),
        prompt_prepare_ms=0.0,
    )

    assert chunks == ["partial"]
    assert completed == []
    assert errors == [t("resultbubble.timeout")]
