import json

import pytest

from app.core.tool_build.models import ToolPermission
from app.core.tool_build.validator import validate_workspace
from app.core.tool_build.workspace import BuildWorkspace


def make_workspace(monkeypatch, tmp_path, manifest=None, script="print('ok')"):
    monkeypatch.setattr(
        "app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds"
    )
    manifest = manifest or {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
    return BuildWorkspace.create("req", json.dumps(manifest), script)


def issue_codes(report):
    return {issue.code for issue in report.issues}


def test_extreme_json_integer_returns_structured_invalid_manifest(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    workspace.manifest_path.write_text(
        '{"manifest_version":' + "9" * 5_000 + '}', encoding="utf-8"
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert report.is_installable is False
    assert "MANIFEST_JSON_INVALID" in issue_codes(report)


def test_missing_entrypoint_is_blocked(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    workspace.script_path.unlink()

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "ENTRYPOINT_MISSING" in issue_codes(report)
    assert report.is_installable is False


def test_dependency_is_blocked_without_running_pip(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 1,
        "name": "x",
        "description": "x",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": ["requests==2.32.0"],
    }
    workspace = make_workspace(monkeypatch, tmp_path, manifest=manifest)

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "DEPENDENCIES_UNSUPPORTED" in issue_codes(report)
    assert report.is_installable is False


def test_manifest_must_be_strict_v1(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 0,
        "name": "safe_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
    workspace = make_workspace(monkeypatch, tmp_path, manifest=manifest)

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "MANIFEST_INVALID" in issue_codes(report)
    assert report.is_installable is False


def test_declared_permissions_are_metadata_only_and_do_not_block(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 1,
        "name": "network_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": ["file_read", "network"],
        "dependencies": [],
    }
    workspace = make_workspace(
        monkeypatch,
        tmp_path,
        manifest=manifest,
        script="import requests\nrequests.get('x')",
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert report.declared_permissions == frozenset(
        {ToolPermission.FILE_READ, ToolPermission.NETWORK}
    )
    assert report.detected_permissions == frozenset()
    assert report.is_installable is True
    assert not report.issues


def test_report_contains_only_relative_hashes(monkeypatch, tmp_path):
    workspace = make_workspace(
        monkeypatch,
        tmp_path,
        script="import os\nos.environ['SUPER_SECRET_TOKEN']",
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert set(report.file_hashes) == {"manifest.json", "tool.py"}
    assert all(len(digest) == 64 for digest in report.file_hashes.values())


@pytest.mark.parametrize(
    ("script", "expected_codes"),
    [
        ("def broken(:\n", {"PYTHON_SYNTAX_INVALID"}),
        ("x = (" * 10_001, {"AST_COMPLEXITY_LIMIT", "PYTHON_SYNTAX_INVALID"}),
    ],
    ids=["syntax", "complexity"],
)
def test_invalid_or_overly_complex_python_is_blocked(
    monkeypatch, tmp_path, script, expected_codes
):
    workspace = make_workspace(monkeypatch, tmp_path, script=script)

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert report.is_installable is False
    assert issue_codes(report) & expected_codes


def test_validator_requires_frozenset_permissions(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)

    with pytest.raises(TypeError, match="frozenset"):
        validate_workspace(workspace, approved_permissions=set())


def test_entrypoint_outside_source_is_blocked(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    manifest["script"] = "../outside.py"
    workspace.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "ENTRYPOINT_OUTSIDE_SOURCE" in issue_codes(report)
    assert report.is_installable is False


def test_unexpected_source_file_is_blocked(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    (workspace.source_dir / "helper.py").write_text("print('helper')", encoding="utf-8")

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "SOURCE_FILE_UNSUPPORTED" in issue_codes(report)
    assert report.is_installable is False


@pytest.mark.parametrize(
    ("manifest_text", "expected_code"),
    [
        (None, "MANIFEST_MISSING"),
        ("{broken", "MANIFEST_JSON_INVALID"),
    ],
)
def test_missing_or_invalid_manifest_is_blocked(
    monkeypatch, tmp_path, manifest_text, expected_code
):
    workspace = make_workspace(monkeypatch, tmp_path)
    if manifest_text is None:
        workspace.manifest_path.unlink()
    else:
        workspace.manifest_path.write_text(manifest_text, encoding="utf-8")

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert expected_code in issue_codes(report)
    assert report.is_installable is False


def test_non_python_entrypoint_is_blocked(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "safe",
        "script": "tool.txt",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
    workspace = make_workspace(monkeypatch, tmp_path, manifest=manifest)

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "ENTRYPOINT_TYPE_INVALID" in issue_codes(report)
    assert report.is_installable is False


def test_oversized_source_is_blocked_before_content_read(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr("app.core.tool_build.validator._MAX_SOURCE_FILE_BYTES", 1)
    monkeypatch.setattr(
        BuildWorkspace,
        "read_source",
        lambda _workspace: pytest.fail("validator must not read an oversized source file"),
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "SOURCE_FILE_TOO_LARGE" in issue_codes(report)
    assert report.is_installable is False


def test_excessive_source_file_count_is_blocked_before_content_read(monkeypatch, tmp_path):
    workspace = make_workspace(monkeypatch, tmp_path)
    (workspace.source_dir / "extra.py").write_text("pass", encoding="utf-8")
    monkeypatch.setattr("app.core.tool_build.validator._MAX_SOURCE_FILES", 2)
    monkeypatch.setattr(
        BuildWorkspace,
        "read_source",
        lambda _workspace: pytest.fail("validator must not read excessive source files"),
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert "SOURCE_FILE_COUNT_LIMIT" in issue_codes(report)
    assert report.is_installable is False


def test_valid_tool_with_declared_permissions_is_installable(monkeypatch, tmp_path):
    manifest = {
        "manifest_version": 1,
        "name": "capable_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": ["file_read", "network", "shell"],
        "dependencies": [],
    }
    workspace = make_workspace(
        monkeypatch, tmp_path, manifest=manifest, script="print('ok')"
    )

    report = validate_workspace(workspace, approved_permissions=frozenset())

    assert report.is_installable is True
    assert not report.issues
    assert report.detected_permissions == frozenset()
    assert report.declared_permissions == frozenset(
        {ToolPermission.FILE_READ, ToolPermission.NETWORK, ToolPermission.SHELL}
    )


def test_simplified_flow_installs_capable_tool_but_still_blocks_broken_syntax(
    monkeypatch, tmp_path
):
    """核心简化:声明危险权限 + 真实调用,不再需要审批/风险确认,一次校验即可装;
    但语法错误(工具跑不起来)仍然拦截。"""

    capable_manifest = {
        "manifest_version": 1,
        "name": "shell_net_tool",
        "description": "runs a shell command and a network call",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": ["shell", "network"],
        "dependencies": [],
    }
    capable_script = (
        "import json, subprocess, urllib.request\n"
        "subprocess.run(['echo', 'hi'])\n"
        "urllib.request.urlopen('http://example.com')\n"
        "print(json.dumps({'status': 'success', 'data': {}}))\n"
    )
    capable = make_workspace(
        monkeypatch, tmp_path, manifest=capable_manifest, script=capable_script
    )

    report = validate_workspace(capable, approved_permissions=frozenset())

    assert report.is_installable is True
    assert not report.issues
    assert report.detected_permissions == frozenset()
    assert "shell" in {p.value for p in report.declared_permissions}

    broken = make_workspace(monkeypatch, tmp_path, script="def main(:\n    pass\n")
    broken_report = validate_workspace(broken, approved_permissions=frozenset())

    assert broken_report.is_installable is False
    assert "PYTHON_SYNTAX_INVALID" in issue_codes(broken_report)
