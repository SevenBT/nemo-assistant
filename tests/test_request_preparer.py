"""Compression preserves protocol groups and never edits authoritative history."""
import copy
import json
from unittest.mock import Mock

import pytest

from app.agent.agent import Agent
from app.agent.agent_context import AgentContext
from app.agent.request_context import RequestCancelled, RequestContext, encode_for_model, validate_messages
from app.conversation.consolidator import Consolidator
from app.conversation.request_preparer import ConsolidatingRequestPreparer
from app.runtime.cancellation import CancellationToken
from test_agent_runtime import Model, Tools, call, TEXT


def request(messages, token=None, tools=None):
    return RequestContext(messages, tools, "session", "trace", 0, "normal", token or CancellationToken())


def tool_group(index, content="result"):
    return [
        {"role": "assistant", "content": None, "reasoning_content": "thought",
         "provider_state": {"signature": [index]}, "opaque_extension": {"keep": True},
         "tool_calls": [{"id": index, "type": "function", "extra_content": {"signature": index},
                         "function": {"name": "read", "arguments": json.dumps({"input": [index]})}}]},
        {"role": "tool", "tool_call_id": index, "content": content},
    ]


@pytest.fixture
def compression(monkeypatch):
    monkeypatch.setattr("app.conversation.context_manager.get_context_window_for_model", lambda _: 10000)
    gateway = Mock()
    gateway.chat_stream.side_effect = lambda *a, **k: iter([{"type": "text", "delta": "Earlier work completed; retain the latest request."}, {"type": "done"}])
    memory = Mock()
    consolidator = Consolidator(gateway, memory)
    return ConsolidatingRequestPreparer(consolidator), gateway, memory


def large_history():
    return [{"role": "system", "content": "fixed instructions"},
            {"role": "developer", "content": "fixed developer"}] + [
        {"role": role, "content": "old history " * 250}
        for _ in range(10) for role in ("user", "assistant")
    ] + [{"role": "user", "content": [
        {"type": "text", "text": "continue using this image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,private-image"}},
    ]}] + tool_group("latest")


def test_cached_summary_reused_across_requests_and_only_new_prefix_archived(compression):
    preparer, gateway, memory = compression
    messages = large_history()
    original = copy.deepcopy(messages)
    first = preparer.prepare(request(messages))
    validate_messages(first.messages)
    assert preparer._cost(first.messages) <= 1000
    assert first.messages[:2] == messages[:2]
    assert first.messages[-3:] == messages[-3:]
    assert messages == original
    first.messages[-1]["content"] = "consumer mutation"
    second = preparer.prepare(request(messages))
    assert second.messages[-1] == original[-1]
    grown = messages + tool_group("new")
    assert preparer.prepare(request(grown)).messages[-2:] == grown[-2:]
    assert gateway.chat_stream.call_count == memory.add.call_count == 1
    # A later expansion crosses the threshold even after the cached summary.
    for index in range(70):
        grown += tool_group(str(index), "feedback " * 100)
    third = preparer.prepare(request(grown))
    assert preparer._cost(third.messages) <= 1000
    validate_messages(third.messages)
    preparer.prepare(request(grown))
    assert gateway.chat_stream.call_count == memory.add.call_count == 2
    assert gateway.chat_stream.call_args.kwargs["cancel_token"] is not None


@pytest.mark.parametrize("response", ["error", "empty", "long"])
def test_summary_fallback_and_long_response_are_bounded(compression, response):
    preparer, gateway, memory = compression
    gateway.chat_stream.side_effect = None
    gateway.chat_stream.return_value = iter(
        [{"type": "error", "message": "offline"}] if response == "error" else
        [{"type": "done"}] if response == "empty" else
        [{"type": "text", "delta": "very long summary " * 10000}]
    )
    result = preparer.prepare(request(large_history()))
    assert preparer._cost(result.messages) <= 1000
    validate_messages(result.messages)
    memory.add.assert_called_once()


@pytest.mark.parametrize("mandatory", ["user", "system", "tools", "latest_group"])
def test_oversized_mandatory_context_fails_before_summary(compression, mandatory):
    preparer, gateway, memory = compression
    messages = large_history()
    tools = None
    if mandatory == "tools":
        tools = [{"description": "schema " * 2000}]
    elif mandatory == "latest_group":
        messages[-1]["content"] = "huge feedback " * 1000
    else:
        index = -3 if mandatory == "user" else 0
        messages[index]["content"] = "must preserve " * 1000
    with pytest.raises(ValueError, match="Mandatory context"):
        preparer.prepare(request(messages, tools=tools))
    gateway.chat_stream.assert_not_called()
    memory.add.assert_not_called()


def test_cancel_during_summary_never_archives_or_calls_main_model(compression):
    preparer, gateway, memory = compression
    token, model = CancellationToken(), Model()
    closed = []
    def summary(*args, **kwargs):
        assert kwargs["cancel_token"] is token
        try:
            yield {"type": "text", "delta": "partial"}
            token.cancel()
            yield {"type": "done"}
        finally:
            closed.append(True)
    gateway.chat_stream.side_effect = summary
    result = Agent(AgentContext(llm_gateway=model, registry=Tools(), cancel_token=token,
                               request_preparer=preparer), large_history()).run_sync()
    assert result["status"] == "cancelled" and model.requests == [] and closed == [True]
    memory.add.assert_not_called()


def test_cancellation_checked_before_archive_and_invalid_fallback_fails(compression, monkeypatch):
    preparer, gateway, memory = compression
    token = CancellationToken()
    def cancelled(*args, **kwargs):
        token.cancel()
        return "completed but cancelled"
    monkeypatch.setattr(preparer._consolidator, "summarize", cancelled)
    with pytest.raises(RequestCancelled):
        preparer.prepare(request(large_history(), token))
    memory.add.assert_not_called()
    monkeypatch.setattr(preparer._consolidator, "summarize", lambda *a, **k: "")
    with pytest.raises(ValueError, match="empty"):
        preparer.prepare(request(large_history()))
    memory.add.assert_not_called()


def test_compression_after_tool_feedback_preserves_input_prefix_and_final_metadata(compression):
    preparer, gateway, memory = compression
    # First request fits, but the completed tool result triggers compression.
    messages = [{"role": "system", "content": "fixed"}, {"role": "user", "content": "old"},
                {"role": "assistant", "content": ""}, {"role": "user", "content": "current"}]
    base = preparer._cost(messages, Tools().definitions())
    messages[2]["content"] = "word " * (5600-base-200)
    assert preparer._cost(messages, Tools().definitions()) < 5600
    class LargeFeedback(Tools):
        def execute(self, *args):
            return {"status": "success", "data": "feedback " * 500}
    model = Model([call(), {"type": "done", "provider_state": {"signature": "tools"}}],
                  [{"type": "text", "delta": "final"},
                   {"type": "done", "provider_state": {"signature": "answer"}, "reasoning_content": "reason"}])
    result = Agent(AgentContext(llm_gateway=model, registry=LargeFeedback(), request_preparer=preparer), messages).run_sync()
    assert result["ok"], result
    assert len(model.requests) == 2 and gateway.chat_stream.call_count == memory.add.call_count == 1
    assert result["messages"][:len(messages)] == messages
    assert len(model.requests[1][0]) < len(result["messages"])
    assert result["messages"][-1] == {"role": "assistant", "content": "final", "provider_state": {"signature": "answer"}, "reasoning_content": "reason"}
    assert sum(m["content"] == "final" for m in result["messages"]) == 1
    validate_messages(result["messages"])


@pytest.mark.parametrize("messages", [
    [{"role": "tool", "tool_call_id": "orphan", "content": "x"}],
    tool_group("pending")[:1],
    tool_group("call")[:1] + [{"role": "user", "content": "interrupted"}],
    [{"role": "unknown", "content": "x"}],
    [{"role": "assistant", "tool_calls": ["invalid"]}],
    [{"role": "assistant", "tool_calls": [{"id": "a", "function": []}]}],
    [{"role": "tool", "tool_call_id": ["unhashable"]}],
])
def test_malformed_tool_groups_rejected_before_compression(compression, messages):
    preparer, gateway, memory = compression
    with pytest.raises(ValueError):
        preparer.prepare(request(messages))
    gateway.chat_stream.assert_not_called()
    memory.add.assert_not_called()


def test_encoder_preserves_all_opaque_extensions_without_aliases():
    messages = tool_group("call")
    encoded = encode_for_model(messages)
    assert encoded == messages
    encoded[0]["provider_state"]["signature"].clear()
    assert messages[0]["provider_state"]["signature"] == ["call"]


def test_desktop_factory_creates_fresh_preparer_per_run(compression, monkeypatch, tmp_path):
    from app.desktop import agent_factory
    from types import SimpleNamespace
    preparer, _, _ = compression
    monkeypatch.setattr(agent_factory, "AgentThread", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(agent_factory, "SESSIONS_DIR", tmp_path)
    args = dict(llm_gateway=object(), registry=object(), api_messages=[], session_id="s", consolidator=preparer._consolidator)
    first, second = agent_factory.create_agent_worker(**args), agent_factory.create_agent_worker(**args)
    assert first.context.request_preparer is not second.context.request_preparer
    assert first.context.hooks == second.context.hooks == []
