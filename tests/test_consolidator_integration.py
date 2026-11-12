from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.agent_hooks import BeforeTurnContext, ConsolidatorHook
from app.core.consolidator import Consolidator, _messages_to_text
from app.models.message import Message, MessageRole, ToolCall


def test_small_conversation_is_returned_without_consolidation():
    llm_gateway = Mock()
    memory_manager = Mock()
    consolidator = Consolidator(llm_gateway, memory_manager, model="gpt-4-turbo")
    messages = [
        Message(role=MessageRole.USER, content="你好"),
        Message(role=MessageRole.ASSISTANT, content="你好，有什么可以帮你？"),
    ]

    result = consolidator.maybe_consolidate(messages, session_id="test-session")

    assert result is messages
    llm_gateway.chat_stream.assert_not_called()
    memory_manager.add.assert_not_called()


def test_summary_text_hides_image_payloads():
    data_url = "data:image/png;base64,private-payload"
    message = SimpleNamespace(
        role="user",
        content=[
            {"type": "text", "text": "描述这张图片"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    )

    summary_text = _messages_to_text([message])

    assert "描述这张图片" in summary_text
    assert "[image]" in summary_text
    assert data_url not in summary_text


@pytest.mark.parametrize("response", ["long_summary", "error", "empty"])
def test_compressed_messages_and_summary_fit_total_budget(monkeypatch, response):
    monkeypatch.setattr("app.core.context_manager.get_context_window_for_model", lambda _: 1000)
    gateway = Mock()
    if response == "long_summary":
        gateway.chat_stream.return_value = [{"type": "text", "delta": "摘要内容。" * 1000}]
    elif response == "error":
        gateway.chat_stream.return_value = [{"type": "error", "message": "unavailable"}]
    else:
        gateway.chat_stream.return_value = [{"type": "done"}]
    memory = Mock()
    consolidator = Consolidator(gateway, memory)
    messages = [Message(content="history " * 80) for _ in range(10)] + [
        Message(role=MessageRole.ASSISTANT, content="latest answer"),
        Message(role=MessageRole.USER, content="please continue"),
    ]
    original_contents = [m.content for m in messages]

    result = consolidator.maybe_consolidate(messages, "session")

    assert len(result) == 3  # 摘要 + 最近两条；下一条旧消息会超过预算。
    assert result[0].role == MessageRole.SYSTEM
    assert result[0].content.startswith("[以下是之前对话的摘要]")
    assert result[1:] == messages[-2:]
    assert consolidator._ctx_mgr.count_messages_tokens(result) <= 100
    assert [m.content for m in messages] == original_contents
    memory.add.assert_called_once()


def test_large_tool_arguments_are_compressed_within_budget(monkeypatch):
    monkeypatch.setattr("app.core.context_manager.get_context_window_for_model", lambda _: 1000)
    gateway = Mock()
    gateway.chat_stream.return_value = [{"type": "text", "delta": "工具已完成"}]
    consolidator = Consolidator(gateway, Mock())
    messages = [
        Message(role=MessageRole.ASSISTANT, tool_calls=[
            ToolCall(id="call", name="search", arguments={"query": "history " * 1000}),
        ]),
        Message(content="continue"),
    ]

    result = consolidator.maybe_consolidate(messages, "session")

    assert result[-1] is messages[-1]
    assert consolidator._ctx_mgr.count_messages_tokens(result) <= 100


def test_hook_applies_compression_even_when_message_count_is_unchanged(monkeypatch):
    monkeypatch.setattr("app.core.context_manager.get_context_window_for_model", lambda _: 1000)
    gateway = Mock()
    gateway.chat_stream.return_value = [{"type": "text", "delta": "用户希望继续未完成任务"}]
    consolidator = Consolidator(gateway, Mock())
    hook = ConsolidatorHook(consolidator)
    original = [{"role": "user", "content": "large request " * 1000}]

    result = hook.before_turn(BeforeTurnContext(
        trace_id="test", session_id="session", turn_count=0, messages=original,
    ))

    assert result is not None
    assert len(result) == len(original) == 1
    assert "用户希望继续未完成任务" in result[0]["content"]
    assert consolidator._ctx_mgr.count_tokens(result[0]["content"]) <= 100
    assert original[0]["content"] == "large request " * 1000


def test_consolidator_rejects_target_above_ten_percent():
    with pytest.raises(ValueError, match="target_ratio"):
        Consolidator(Mock(), Mock(), consolidation_ratio=0.5)
