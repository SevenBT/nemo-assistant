import json

import pytest

from app.core.llm_gateway import CancellationToken
from app.core.tool_generator import (
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

    monkeypatch.setattr("app.core.tool_generator.LLMGateway", FakeGateway)

    assert list(stream_generate("make a tool", cancel_token=token)) == [{"type": "done"}]
    assert captured["cancel_token"] is token
    assert "stream_timeout" not in captured


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
