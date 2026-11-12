import json

import pytest

from app.llm.llm_gateway import CancellationToken
from app.tooling.tool_generator import (
    _SYSTEM_PROMPT,
    parse_result,
    stream_generate,
)


def test_system_prompt_requests_strict_manifest_v1_without_dependencies():
    assert '"manifest_version": 1' in _SYSTEM_PROMPT
    assert '"output"' in _SYSTEM_PROMPT
    assert '"permissions"' in _SYSTEM_PROMPT
    assert "file_read" in _SYSTEM_PROMPT
    assert "process_spawn" in _SYSTEM_PROMPT
    assert '"dependencies": []' in _SYSTEM_PROMPT
    assert "系统会自动安装" not in _SYSTEM_PROMPT


def test_stream_generate_forwards_cancellation_without_gateway_extension(monkeypatch):
    captured = {}
    token = CancellationToken()

    class FakeGateway:
        def __init__(self, *args, **kwargs):
            captured["config_proxy"] = kwargs.get("config_proxy")

        def chat_stream(self, messages, *, cancel_token):
            captured["messages"] = messages
            captured["cancel_token"] = cancel_token
            return iter(({"type": "done"},))

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr("app.tooling.tool_generator.LLMGateway", FakeGateway)

    assert list(stream_generate("make a tool", cancel_token=token)) == [{"type": "done"}]
    assert captured["cancel_token"] is token
    assert "stream_timeout" not in captured
    assert captured["closed"]


def test_parse_result_extracts_valid_code_blocks():
    manifest = {"name": "legacy", "description": "Legacy response"}
    response = (
        f"```json\n{json.dumps(manifest)}\n```\n"
        "```python\nprint('{}')\n```"
    )

    manifest_text, script_text, error = parse_result(response)

    assert json.loads(manifest_text) == manifest
    assert script_text == "print('{}')"
    assert error == ""


def test_model_override_preserves_custom_endpoint_and_protocol(monkeypatch):
    from types import SimpleNamespace
    from app.tooling.tool_generator import ModelOverride, _ConfigProxy
    entry = {'id': 'custom', 'provider': 'openai', 'api_base': 'https://proxy.test/v1',
             'api_protocol': 'responses', 'enabled': True, 'future_field': 'keep'}
    fake_cfg = SimpleNamespace(litellmModels=object(), get=lambda _: [entry])
    monkeypatch.setattr('app.tooling.tool_generator.cfg', fake_cfg)
    resolved = _ConfigProxy(ModelOverride('litellm', 'custom', 'Custom', 'openai')).get_litellm_model_by_id('custom')
    assert resolved == entry
    assert resolved is not entry


def test_parse_result_does_not_apply_strict_manifest_validation():
    response = (
        '```json\n{"name": "legacy", "description": "old"}\n```\n'
        "```python\npass\n```"
    )

    _, _, error = parse_result(response)

    assert error == ""


def test_parse_result_rejects_invalid_json_without_writing_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = "```json\n{bad\n```\n```python\npass\n```"

    _, _, error = parse_result(response)

    assert "manifest.json 格式错误" in error
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("manifest_text", ["null", "1", "[]"])
def test_parse_result_rejects_non_object_manifest_json(manifest_text):
    response = f"```json\n{manifest_text}\n```\n```python\npass\n```"

    _, _, error = parse_result(response)

    assert "manifest.json 必须是对象" in error
