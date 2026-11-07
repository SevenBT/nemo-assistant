import pytest

from app.core.context_manager import (
    ContextManager,
    count_tokens,
    get_context_window_for_model,
)


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


def test_context_manager_reserves_completion_capacity():
    manager = ContextManager(model="gpt-4-turbo", reserve_ratio=0.25)

    assert manager._max_context == 128_000
    assert manager._usable_context == 96_000
