"""Final-review regressions for the simplified generated-tool policy.

Validation now checks syntax, format, and dependencies only. Capability and
permission detection has been removed, so these tests cover the behaviour that
still exists: manifest parsing, adapter retry safety, the deterministic
blocking codes, and reserved-name rejection before install.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.tool_build import ToolBuildService, ToolPermission
from app.core.tool_build.manifest import parse_manifest_text
from app.core.tool_build.validator import validate_workspace
from app.core.tool_build.workspace import BuildWorkspace
from app.tools.registry import ToolErrorType, ToolRegistry
from app.tools.script_adapter import ScriptToolAdapter


def _manifest(permissions: list[str], **overrides: object) -> str:
    value: dict[str, object] = {
        "manifest_version": 1,
        "name": "permission_tool",
        "description": "Capability regression",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": permissions,
        "dependencies": [],
    }
    value.update(overrides)
    return json.dumps(value)


def _workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    script: str,
    permissions: list[str],
    **overrides: object,
) -> BuildWorkspace:
    monkeypatch.setattr(
        "app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds"
    )
    return BuildWorkspace.create("req", _manifest(permissions, **overrides), script)


def _codes(report: object) -> set[str]:
    return {issue.code for issue in report.issues}


def test_strict_manifest_rejects_retry_safe_true_but_legacy_keeps_compatibility() -> None:
    with pytest.raises(ValueError, match="retry_safe"):
        parse_manifest_text(_manifest([], retry_safe=True), mode="strict")

    legacy = parse_manifest_text(
        json.dumps(
            {
                "name": "legacy_tool",
                "description": "legacy",
                "script": "tool.py",
                "retry_safe": True,
            }
        ),
        mode="legacy",
    )

    assert legacy.retry_safe is True


def test_strict_adapter_defensively_disables_registry_retry(tmp_path: Path) -> None:
    adapter = ScriptToolAdapter(
        tool_name="strict_tool",
        tool_description="strict",
        tool_parameters={"type": "object", "properties": {}},
        script_path=str(tmp_path / "tool.py"),
        tool_dir=str(tmp_path),
        is_read_only=True,
        retry_safe=True,
        is_legacy_manifest=False,
    )
    outcomes = [
        {
            "status": "error",
            "data": {
                "message": "temporary",
                "error_type": ToolErrorType.NETWORK.value,
                "retryable": True,
            },
        },
        {"status": "success", "data": {}},
    ]
    calls = 0

    def execute(_params: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return outcomes.pop(0)

    adapter.execute = execute  # type: ignore[method-assign]
    registry = ToolRegistry()
    registry.register(adapter)

    result = registry.execute(adapter.name, {})

    assert adapter.retry_safe is False
    assert result["status"] == "error"
    assert calls == 1


def test_valid_tool_declaring_permissions_is_installable_without_capability_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(
        monkeypatch,
        tmp_path,
        "open('data.txt', 'r+')\nimport subprocess\nsubprocess.run(['python'])",
        ["file_read", "file_write", "shell", "python_subprocess"],
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert report.detected_permissions == frozenset()
    assert report.declared_permissions == frozenset(
        {
            ToolPermission.FILE_READ,
            ToolPermission.FILE_WRITE,
            ToolPermission.SHELL,
            ToolPermission.PYTHON_SUBPROCESS,
        }
    )
    assert report.issues == ()
    assert report.is_installable is True


def test_approvals_no_longer_affect_validation_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(
        monkeypatch,
        tmp_path,
        "import subprocess\nsubprocess.run([executable, 'tool.py'])",
        ["shell"],
    )

    without_approval = validate_workspace(
        workspace, approved_permissions=frozenset()
    )
    with_approval = validate_workspace(
        workspace, approved_permissions=frozenset({ToolPermission.SHELL})
    )

    assert without_approval.is_installable is True
    assert with_approval.is_installable is True
    assert "DYNAMIC_CAPABILITY_REVIEW" not in _codes(without_approval)
    assert "UNAPPROVED_PERMISSION" not in _codes(without_approval)


def test_syntax_error_still_blocks_installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(monkeypatch, tmp_path, "def broken(:", [])

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "PYTHON_SYNTAX_INVALID" in _codes(report)
    assert report.is_installable is False
    assert report.is_installable_with(frozenset({"PYTHON_SYNTAX_INVALID"})) is False


def test_declared_dependencies_still_block_installation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = _workspace(
        monkeypatch, tmp_path, "print('hi')", [], dependencies=["requests"]
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "DEPENDENCIES_UNSUPPORTED" in _codes(report)
    assert report.is_installable is False


def test_reserved_builtin_name_is_rejected_before_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds"
    )
    monkeypatch.setattr(
        "app.core.tool_build.installer.USER_TOOLS_DIR", tmp_path / "user_tools"
    )
    service = ToolBuildService()
    staged = service.stage("req", _manifest([], name="exec"), "print('hi')")

    review = service.review(staged.build_id, frozenset())
    assert review.report.is_installable is True

    result = service.install(staged.build_id, frozenset(), overwrite=True)

    assert result.installed is False
    assert result.reason == "RESERVED_NAME"
    assert not (tmp_path / "user_tools" / "exec").exists()
