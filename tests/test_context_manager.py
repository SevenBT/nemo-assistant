import pytest

from app.conversation.context_manager import (
    ContextManager,
    count_tokens,
    get_context_window_for_model,
)
from app.models.message import Message


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4-turbo", 128_000),
        ("gpt-4o", 128_000),
        ("claude-4-opus", 200_000),
        ("deepseek-v4", 128_000),
        ("unknown-model", 128_000),
    ],
)
def test_context_window_for_model(model, expected):
    assert get_context_window_for_model(model) == expected


def test_count_tokens_handles_empty_and_nonempty_text():
    assert count_tokens("") == 0
    assert count_tokens("你好 world") > 0


def test_token_count_treats_special_token_spellings_as_literal_text():
    manager = ContextManager()
    text = "<|endoftext|>" * 50

    assert manager.count_tokens(text) == len(manager._encoding.encode(text, disallowed_special=()))


def test_context_manager_reserves_completion_capacity():
    manager = ContextManager(model="gpt-4-turbo", reserve_ratio=0.25)

    assert manager._max_context == 128_000
    assert manager._usable_context == 96_000


@pytest.mark.parametrize("reserve_ratio", [0, 0.2, 0.7])
def test_consolidation_budget_uses_total_context(reserve_ratio):
    manager = ContextManager(model="gpt-4-turbo", reserve_ratio=reserve_ratio)

    assert manager.consolidation_budget() == 12_800
    assert manager.consolidation_budget(0.05) == 6_400


@pytest.mark.parametrize("ratio", [0, -0.1, 0.1001, 0.5, float("nan")])
def test_consolidation_budget_rejects_ratios_outside_limit(ratio):
    with pytest.raises(ValueError, match="target_ratio"):
        ContextManager().consolidation_budget(ratio)


def test_keep_count_stays_within_budget_including_separators(monkeypatch):
    monkeypatch.setattr("app.conversation.context_manager.get_context_window_for_model", lambda _: 100)
    manager = ContextManager()
    messages = [Message(content="hello") for _ in range(12)]

    keep = manager.calculate_keep_count(messages, reserved_tokens=4)

    assert keep == 3  # 3 个正文 token + 2 个消息分隔符；不强制凑够 4 条。
    assert manager.count_messages_tokens(messages[-keep:]) <= 6
    assert manager.count_messages_tokens(messages[-keep - 1:]) > 6


def test_keep_count_does_not_keep_an_oversized_last_message(monkeypatch):
    monkeypatch.setattr("app.conversation.context_manager.get_context_window_for_model", lambda _: 100)
    manager = ContextManager()

    assert manager.calculate_keep_count([Message(content="hello " * 20)]) == 0
    assert manager.calculate_keep_count([]) == 0
    assert manager.calculate_keep_count([Message(content="hello")]) == 1


def test_keep_count_drops_orphaned_tool_results(monkeypatch):
    monkeypatch.setattr("app.conversation.context_manager.get_context_window_for_model", lambda _: 100)
    manager = ContextManager()
    messages = [
        Message(role="assistant", content="large call " * 20),
        Message(role="tool", content="result", tool_call_id="call"),
        Message(role="user", content="continue"),
    ]

    assert manager.calculate_keep_count(messages) == 1


def test_truncate_text_respects_token_budget_and_unicode():
    manager = ContextManager()
    text = "你好，世界。" * 100

    truncated = manager.truncate_text(text, 11)

    assert text.startswith(truncated)
    assert "\ufffd" not in truncated
    assert manager.count_tokens(truncated) <= 11
    assert manager.truncate_text(text, 0) == ""
