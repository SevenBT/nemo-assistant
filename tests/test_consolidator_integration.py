from types import SimpleNamespace
from unittest.mock import Mock

from app.core.consolidator import Consolidator, _messages_to_text
from app.models.message import Message, MessageRole


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
