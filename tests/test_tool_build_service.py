"""Regression tests for the strict staged tool-build service."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.tool_build import InstallResult, ToolBuildService, ToolPermission


VALID_MANIFEST = json.dumps(
    {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "A safe generated tool",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
)

DEFAULT_TEMPLATE_MANIFEST = json.dumps(
    {
        "manifest_version": 1,
        "name": "stdin_template_tool",
        "description": "A strict tool using the default stdin template",
        "script": "tool.py",
        "version": "1.0.0",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
)

DEFAULT_TEMPLATE_SCRIPT = '''import json
import sys


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    print(json.dumps({"status": "success", "data": payload}))


if __name__ == "__main__":
    main()
'''


def manifest_with_permissions(permissions: list[str]) -> str:
    value = json.loads(VALID_MANIFEST)
    value["permissions"] = permissions
    value["name"] = "permission_tool"
    return json.dumps(value)


@pytest.fixture
def build_environment(monkeypatch, tmp_path):
    builds = tmp_path / "builds"
    user_tools = tmp_path / "user_tools"
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", builds)
    monkeypatch.setattr("app.core.tool_build.installer.USER_TOOLS_DIR", user_tools)
    return builds, user_tools


@pytest.fixture
def service(build_environment):
    return ToolBuildService()


def test_stage_never_writes_user_tools(service, build_environment):
    builds, user_tools = build_environment

    review = service.stage("make a safe tool", VALID_MANIFEST, "print('{}')")

    assert review.report.status.value == "staged"
    assert not user_tools.exists()
    assert (builds / review.build_id / "source" / "manifest.json").exists()


def test_default_prompt_template_reaches_installable_review_without_execution(service, monkeypatch):
    monkeypatch.setattr(
        "subprocess.run", lambda *_args, **_kwargs: pytest.fail("must not execute generated code")
    )

    staged = service.stage(
        "make a stdin tool", DEFAULT_TEMPLATE_MANIFEST, DEFAULT_TEMPLATE_SCRIPT
    )
    review = service.review(staged.build_id, frozenset())

    assert review.report.is_installable is True
    assert review.report.detected_permissions == frozenset()
    assert review.report.status.value == "install_review"


def test_stage_rejects_legacy_manifest_without_side_effects(service, build_environment):
    builds, _ = build_environment
    legacy = json.dumps({"name": "old", "description": "old", "script": "tool.py"})

    with pytest.raises(ValueError, match="manifest_version"):
        service.stage("req", legacy, "print(1)")

    assert not builds.exists()


def test_install_revalidates_after_script_edit(service):
    review = service.stage("req", VALID_MANIFEST, "print('{}')")
    service.review(review.build_id, frozenset())
    script = service.workspace_for(review.build_id).script_path
    script.write_text("print('edited but still valid')", encoding="utf-8")

    result = service.install(review.build_id, frozenset(), overwrite=False)

    assert result.installed is False
    assert result.reason == "STALE_VALIDATION"


def test_install_passes_only_current_explicit_permissions(service, monkeypatch):
    staged = service.stage(
        "req", manifest_with_permissions(["file_read"]), "open('document.txt')"
    )
    approved = frozenset({ToolPermission.FILE_READ})
    review = service.review(staged.build_id, approved)
    captured = {}

    def fake_install(
        workspace, report, *, approved_permissions, overwrite, acknowledged_overrides
    ):
        captured.update(
            workspace=workspace,
            report=report,
            approved_permissions=approved_permissions,
            overwrite=overwrite,
            acknowledged_overrides=acknowledged_overrides,
        )
        return InstallResult(True, "permission_tool", "")

    monkeypatch.setattr("app.core.tool_build.service.install_verified_build", fake_install)

    result = service.install(review.build_id, approved, overwrite=True)

    assert result.installed is True
    assert captured["approved_permissions"] == approved
    assert captured["overwrite"] is True
    assert captured["acknowledged_overrides"] == frozenset()


def test_install_requires_presented_review_after_restart(build_environment):
    first = ToolBuildService()
    staged = first.stage("req", VALID_MANIFEST, "print('{}')")

    result = ToolBuildService().install(staged.build_id, frozenset(), overwrite=False)

    assert result.installed is False
    assert result.reason == "REVIEW_REQUIRED"


def test_install_requires_matching_approval_review(service):
    staged = service.stage("req", VALID_MANIFEST, "print('{}')")
    service.review(staged.build_id, frozenset())

    result = service.install(
        staged.build_id, frozenset({ToolPermission.FILE_READ}), overwrite=False
    )

    assert result.installed is False
    assert result.reason == "REVIEW_REQUIRED"


def test_install_rejects_safe_source_change_after_review(service, monkeypatch):
    staged = service.stage("req", VALID_MANIFEST, "print('A')")
    review = service.review(staged.build_id, frozenset())
    service.workspace_for(staged.build_id).script_path.write_text("print('B')", encoding="utf-8")
    monkeypatch.setattr(
        "app.core.tool_build.service.install_verified_build",
        lambda *_args, **_kwargs: pytest.fail("changed source must not reach installer"),
    )

    result = service.install(staged.build_id, frozenset(), overwrite=False)

    assert result.installed is False
    assert result.reason == "STALE_VALIDATION"
    assert review.script_text == "print('A')"


def test_review_snapshot_matches_report_hashes(service):
    staged = service.stage("req", VALID_MANIFEST, "print('consistent')")

    review = service.review(staged.build_id, frozenset())

    assert review.report.file_hashes["manifest.json"]
    assert review.report.file_hashes["tool.py"]
    assert review.script_text == "print('consistent')"


def test_review_handles_deleted_entrypoint_without_path_error(service):
    staged = service.stage("req", VALID_MANIFEST, "print('x')")
    service.workspace_for(staged.build_id).script_path.unlink()

    review = service.review(staged.build_id, frozenset())

    assert review.report.status.value == "validation_failed"
    assert review.script_text == ""


def test_review_rejects_snapshot_change_between_validation_and_read(service, monkeypatch):
    staged = service.stage("req", VALID_MANIFEST, "print('A')")
    real_validate = __import__("app.core.tool_build.service", fromlist=["validate_workspace"]).validate_workspace

    def change_after_validate(workspace, *, approved_permissions):
        report = real_validate(workspace, approved_permissions=approved_permissions)
        workspace.script_path.write_text("print('B')", encoding="utf-8")
        return report

    monkeypatch.setattr("app.core.tool_build.service.validate_workspace", change_after_validate)

    with pytest.raises(ValueError, match="STALE_VALIDATION"):
        service.review(staged.build_id, frozenset())


@pytest.mark.parametrize("build_id", ["", "../outside", "safe/tool", "a\\b", "."])
def test_workspace_lookup_rejects_unsafe_build_ids_without_filesystem_access(service, build_id, monkeypatch):
    monkeypatch.setattr(
        "app.core.tool_build.service._recover_workspace",
        lambda _build_id: pytest.fail("invalid identifiers must not access the filesystem"),
    )

    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        service.workspace_for(build_id)



@pytest.mark.parametrize("build_id", ["", "../outside", "x" * 65])
def test_all_public_service_entrypoints_reject_invalid_build_id_first(
    service, build_id, monkeypatch
):
    monkeypatch.setattr(
        "app.core.tool_build.service._recover_workspace",
        lambda _build_id: pytest.fail("invalid identifiers must not access the filesystem"),
    )
    service._review_baselines[(build_id, frozenset())] = object()

    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        service.workspace_for(build_id)
    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        service.review(build_id, frozenset())

    result = service.install(build_id, frozenset(), overwrite=False)

    assert result.reason == "WORKSPACE_INVALID"


def test_review_extreme_json_integer_is_structured_non_installable(service):
    staged = service.stage("req", VALID_MANIFEST, "print('{}')")
    service.workspace_for(staged.build_id).manifest_path.write_text(
        '{"manifest_version":' + "9" * 5_000 + '}', encoding="utf-8"
    )

    review = service.review(staged.build_id, frozenset())

    assert review.report.is_installable is False
    assert any(issue.code == "MANIFEST_JSON_INVALID" for issue in review.report.issues)

    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        service.workspace_for("unknown_build")


def test_restart_recovers_safe_workspace(build_environment):
    first = ToolBuildService()
    review = first.stage("req", VALID_MANIFEST, "print('{}')")

    recovered = ToolBuildService().review(review.build_id, frozenset())

    assert recovered.build_id == review.build_id
    assert recovered.manifest.name == "safe_tool"



def test_restart_review_reports_invalid_manifest_structurally(build_environment):
    first = ToolBuildService()
    staged = first.stage("req", VALID_MANIFEST, "print('{}')")
    first.workspace_for(staged.build_id).manifest_path.write_text("{invalid", encoding="utf-8")

    review = ToolBuildService().review(staged.build_id, frozenset())

    assert review.report.status.value == "validation_failed"
    assert any(issue.code == "MANIFEST_JSON_INVALID" for issue in review.report.issues)


def test_restart_review_reports_missing_entrypoint_structurally(build_environment):
    first = ToolBuildService()
    staged = first.stage("req", VALID_MANIFEST, "print('{}')")
    first.workspace_for(staged.build_id).script_path.unlink()

    review = ToolBuildService().review(staged.build_id, frozenset())

    assert review.report.status.value == "validation_failed"
    assert any(issue.code == "ENTRYPOINT_MISSING" for issue in review.report.issues)


def test_restart_review_bounds_oversized_manifest(build_environment, monkeypatch):
    first = ToolBuildService()
    staged = first.stage("req", VALID_MANIFEST, "print('{}')")
    first.workspace_for(staged.build_id).manifest_path.write_text("x" * 1_048_577, encoding="utf-8")
    review = ToolBuildService().review(staged.build_id, frozenset())

    assert review.report.status.value == "validation_failed"
    assert any(issue.code == "SOURCE_FILE_TOO_LARGE" for issue in review.report.issues)


def test_restart_rejects_workspace_symlink_root(build_environment, tmp_path):
    first = ToolBuildService()
    review = first.stage("req", VALID_MANIFEST, "print('{}')")
    root = first.workspace_for(review.build_id).root
    original = root.with_name("original-build")
    root.rename(original)
    try:
        root.symlink_to(tmp_path / "outside", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="WORKSPACE_INVALID"):
        ToolBuildService().workspace_for(review.build_id)


def test_service_never_runs_pip_or_generated_code(service, monkeypatch):
    monkeypatch.setattr(
        "subprocess.run", lambda *_args, **_kwargs: pytest.fail("service must not run subprocesses")
    )

    review = service.stage("req", VALID_MANIFEST, "print('not executed')")
    service.review(review.build_id, frozenset())

    assert review.report.status.value == "staged"


def test_stage_rejects_oversized_manifest_before_json_parse_or_workspace_write(
    service, build_environment, monkeypatch
):
    builds, user_tools = build_environment
    oversized = "SENSITIVE_INPUT" + "x" * 1_100_000
    monkeypatch.setattr(
        "app.core.tool_build.manifest.json.loads",
        lambda _text: pytest.fail("oversized manifest must not reach json.loads"),
    )

    with pytest.raises(ValueError, match="MANIFEST_SIZE_LIMIT"):
        service.stage("req", oversized, "print('{}')")

    assert not builds.exists()
    assert not user_tools.exists()


def test_stage_rejects_deep_manifest_with_stable_redacted_reason(
    service, build_environment
):
    builds, user_tools = build_environment
    deep = '{"manifest_version":1,"name":"safe","description":"safe","script":"tool.py",' \
        '"parameters":' + "[" * 200 + "0" + "]" * 200 + \
        ',"output":{},"permissions":[],"dependencies":[],"secret":"DO_NOT_LEAK"}'

    with pytest.raises(ValueError, match="MANIFEST_COMPLEXITY_LIMIT") as caught:
        service.stage("req", deep, "print('{}')")

    assert "DO_NOT_LEAK" not in str(caught.value)
    assert not builds.exists()
    assert not user_tools.exists()


_DYNAMIC_SCRIPT = "import importlib\n\n\ndef run(name):\n    return importlib.import_module(name)\n"


def test_review_keeps_placeholder_for_non_overridable_block(service):
    """A hard block yields the bounded placeholder without reading source."""

    staged = service.stage("req", VALID_MANIFEST, "def broken(:")

    review = service.review(staged.build_id, frozenset())

    assert review.report.is_installable is False
    assert review.manifest.name == "invalid"
    assert review.script_text == ""


def test_install_with_acknowledged_override_installs_dynamic_tool(service, build_environment):
    _, user_tools = build_environment
    staged = service.stage("dynamic", VALID_MANIFEST, _DYNAMIC_SCRIPT)
    overrides = frozenset({"DYNAMIC_CAPABILITY_REVIEW"})
    service.review(staged.build_id, frozenset(), acknowledged_overrides=overrides)

    result = service.install(
        staged.build_id,
        frozenset(),
        overwrite=False,
        acknowledged_overrides=overrides,
    )

    assert result.installed is True
    assert (user_tools / "safe_tool" / "tool.py").exists()


def test_install_override_requires_matching_review_baseline(service):
    """Overrides are part of the review identity: a mismatch needs re-review."""

    staged = service.stage("dynamic", VALID_MANIFEST, _DYNAMIC_SCRIPT)
    service.review(staged.build_id, frozenset())  # reviewed without overrides

    result = service.install(
        staged.build_id,
        frozenset(),
        overwrite=False,
        acknowledged_overrides=frozenset({"DYNAMIC_CAPABILITY_REVIEW"}),
    )

    assert result.installed is False
    assert result.reason == "REVIEW_REQUIRED"


@pytest.mark.parametrize("invalid", [None, {"X"}, ["X"], frozenset({1})])
def test_install_rejects_invalid_override_type(service, invalid):
    staged = service.stage("req", VALID_MANIFEST, "print('{}')")
    service.review(staged.build_id, frozenset())

    result = service.install(
        staged.build_id, frozenset(), overwrite=False, acknowledged_overrides=invalid
    )

    assert result.installed is False
    assert result.reason == "INVALID_INPUT"
