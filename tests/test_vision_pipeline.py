"""Regression coverage for screenshot pixels through intake, hooks and routing."""

import copy
import json
import httpx
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QColor, QImage

from app.agent.agent_hooks import BeforeTurnContext, ConsolidatorHook
from app.conversation.consolidator import Consolidator, _messages_to_text
from app.conversation.context_manager import count_messages_tokens, message_to_token_text
from app.conversation.conversation_prompt_builder import merge_attachments_to_content
from app.llm.llm_gateway import LLMRequest
from app.llm.providers.adapter import HTTPProviderAdapter
from app.i18n import t
from app.models.attachment import Attachment
from app.models.message import Message, MessageRole
from app.ui import attachment_intake


def _request(messages, provider="deepseek", base_url=""):
    return LLMRequest(
        trace_id="vision-test", attempt_id="vision-test", api_type="openai_chat",
        model="test-model", messages=messages, provider=provider,
        api_key="test-key", base_url=base_url,
    )


def _capture_completion(monkeypatch):
    calls = []

    def handle(request):
        calls.append(dict(json.loads(request.content), url=str(request.url), headers=request.headers))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')

    def stream(request):
        with_client = HTTPProviderAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        try:
            return list(with_client.stream(request))
        finally:
            with_client.close()
    monkeypatch.setattr(HTTPProviderAdapter, 'capture', staticmethod(stream), raising=False)
    return calls


def _image_content():
    return [
        {"type": "text", "text": "这是什么"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,pixels"}},
    ]


@pytest.mark.parametrize("base_url", ["", "https://example.test/v1"])
def test_deepseek_images_use_transport_that_preserves_pixels(monkeypatch, base_url):
    calls = _capture_completion(monkeypatch)
    messages = [{"role": "user", "content": _image_content()}]
    original = copy.deepcopy(messages)

    HTTPProviderAdapter.capture(_request(messages, base_url=base_url))

    assert calls[0]["model"] == "test-model"
    assert calls[0]["url"] == (base_url or "https://api.deepseek.com/beta") + "/chat/completions"
    assert calls[0]["headers"]["authorization"] == "Bearer test-key"
    assert calls[0]["thinking"] == {"type": "disabled"}
    assert calls[0]["messages"] == original
    assert messages == original


@pytest.mark.parametrize("provider", ["deepseek", "openai", "anthropic"])
def test_text_requests_keep_existing_provider_routing(monkeypatch, provider):
    calls = _capture_completion(monkeypatch)
    messages = [{"role": "user", "content": "hello"}]

    HTTPProviderAdapter.capture(_request(messages, provider=provider))

    assert calls[0]["model"] == "test-model"
    assert calls[0]["url"].startswith("https://")
    if provider == "deepseek":
        assert calls[0]["thinking"] == {"type": "disabled"}
    else:
        assert "thinking" not in calls[0]


def test_other_vision_provider_keeps_existing_routing(monkeypatch):
    calls = _capture_completion(monkeypatch)
    messages = [{"role": "user", "content": _image_content()}]

    HTTPProviderAdapter.capture(_request(messages, provider="anthropic"))

    assert calls[0]["model"] == "test-model"
    assert calls[0]["messages"][0]["content"][1]["source"]["data"] == "pixels"


def test_two_clipboard_images_survive_hooks_and_gateway(tmp_path, monkeypatch):
    monkeypatch.setattr(attachment_intake, "SCREENSHOTS_DIR", tmp_path)
    calls = _capture_completion(monkeypatch)
    image = QImage(16, 16, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    mime = QMimeData()
    mime.setImageData(image)
    first = attachment_intake.attachments_from_mime(mime)
    second = attachment_intake.attachments_from_mime(mime)
    assert first[0].file_path != second[0].file_path
    messages = merge_attachments_to_content([
        Message(role=MessageRole.USER, content="这是什么", attachments=first),
        Message(role=MessageRole.ASSISTANT, content="上一条回答"),
        Message(role=MessageRole.USER, content="再看一次", attachments=second),
    ], vision_enabled=True)
    original = copy.deepcopy(messages)
    hook = ConsolidatorHook(Consolidator(Mock(), Mock()))

    assert hook.before_turn(BeforeTurnContext(
        trace_id="vision-test", session_id="session-test", turn_count=0,
        messages=messages,
    )) is None
    HTTPProviderAdapter.capture(_request(messages))

    assert messages == original
    assert calls[0]["model"] == "test-model"
    for index in (0, 2):
        part = calls[0]["messages"][index]["content"][-1]
        assert part["type"] == "image_url"
        assert part["image_url"]["url"].startswith("data:image/png;base64,")


def test_multimodal_counting_and_summary_exclude_image_bytes():
    content = _image_content()
    content[1]["image_url"]["url"] += "secret-pixels" * 10000
    msg = Message(role=MessageRole.USER, content=content)

    assert message_to_token_text(msg) == "这是什么\n[image]"
    assert 0 < count_messages_tokens([msg]) < 100
    summary_input = _messages_to_text([msg])
    assert "这是什么" in summary_input
    assert "[image]" in summary_input
    assert "secret-pixels" not in summary_input
    assert "data:image" not in summary_input


def test_disabled_vision_explains_setting_instead_of_missing_upload():
    att = Attachment("unreadable.png", "shot.png", "image", 0)
    msg = Message(role=MessageRole.USER, content="看看", attachments=[att])

    content = merge_attachments_to_content([msg], vision_enabled=False)[0]["content"]

    assert t("prompt.imageVisionDisabled") in content
    assert "shot.png" in content
    assert "看看" in content


def test_unreadable_image_retains_ocr_and_explains_missing_pixels():
    att = Attachment("unreadable.png", "shot.png", "image", 0, parsed_content="saved OCR")
    msg = Message(role=MessageRole.USER, content="看看", attachments=[att])

    content = merge_attachments_to_content([msg], vision_enabled=True)[0]["content"]

    assert t("prompt.imageUnavailable") in content
    assert "saved OCR" in content
    assert "看看" in content
