import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.tool_build.models import ToolPermission
from app.core.tool_build.validator import validate_workspace
from app.core.tool_build.workspace import BuildWorkspace


def _manifest(name="safe_tool", permissions=None):
    return json.dumps(
        {
            "manifest_version": 1,
            "name": name,
            "description": "safe",
            "script": "tool.py",
            "parameters": {},
            "output": {"type": "object"},
            "permissions": permissions or [],
            "dependencies": [],
        }
    )


@pytest.fixture
def install_environment(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    monkeypatch.setattr("app.core.tool_build.installer.USER_TOOLS_DIR", tmp_path / "user_tools")
    return tmp_path / "user_tools"


def _workspace(name="safe_tool", script="print('new')", permissions=None):
    return BuildWorkspace.create("request", _manifest(name, permissions), script)


def _review(workspace, approved_permissions=frozenset()):
    return validate_workspace(workspace, approved_permissions=approved_permissions)


def _install(
    workspace,
    report,
    *,
    approved_permissions=frozenset(),
    overwrite=False,
    acknowledged_overrides=frozenset(),
):
    from app.core.tool_build.installer import install_verified_build

    return install_verified_build(
        workspace,
        report,
        approved_permissions=approved_permissions,
        overwrite=overwrite,
        acknowledged_overrides=acknowledged_overrides,
    )


def test_non_overridable_block_cannot_be_acknowledged(install_environment):
    workspace = _workspace("broken_tool", script="def broken(:")
    report = _review(workspace)

    result = _install(
        workspace,
        report,
        acknowledged_overrides=frozenset({"PYTHON_SYNTAX_INVALID"}),
    )

    assert result.installed is False
    assert result.reason == "STALE_VALIDATION"
    assert not (install_environment / "broken_tool").exists()


@pytest.mark.parametrize("invalid", [None, {"SOME_CODE"}, ["x"], frozenset({1})])
def test_install_rejects_invalid_override_input(install_environment, invalid):
    workspace = _workspace()

    result = _install(workspace, _review(workspace), acknowledged_overrides=invalid)

    assert result.installed is False
    assert result.reason == "INVALID_INPUT"


def test_install_copies_verified_snapshot(install_environment):
    workspace = _workspace()

    result = _install(workspace, _review(workspace))

    assert result.installed is True
    assert result.tool_name == "safe_tool"
    assert result.reason == ""
    assert (install_environment / "safe_tool" / "tool.py").read_text(encoding="utf-8") == "print('new')"
    assert not (install_environment / ".staging" / workspace.build_id).exists()


def test_explicit_current_permission_approval_allows_matching_tool(install_environment):
    approved = frozenset({ToolPermission.FILE_READ})
    workspace = _workspace(
        "reader", "open('source.txt')", permissions=["file_read"]
    )
    report = _review(workspace, approved)

    result = _install(workspace, report, approved_permissions=approved)

    assert result.installed is True


def test_forged_permission_report_does_not_authorize(install_environment):
    approved = frozenset({ToolPermission.FILE_READ})
    workspace = _workspace(
        "reader", "open('source.txt')", permissions=["file_read"]
    )
    report = _review(workspace, approved)
    forged = replace(
        report,
        declared_permissions=frozenset(),
        detected_permissions=frozenset(),
        issues=(),
    )

    result = _install(workspace, forged, approved_permissions=frozenset())

    assert result.installed is False
    assert result.reason == "STALE_VALIDATION"
    assert not (install_environment / "reader").exists()


@pytest.mark.parametrize("invalid", [set(), [], frozenset({"file_read"})])
def test_install_requires_frozen_typed_permission_approval(install_environment, invalid):
    workspace = _workspace()

    result = _install(workspace, _review(workspace), approved_permissions=invalid)

    assert result.installed is False
    assert result.reason == "INVALID_INPUT"


def test_reports_match_rejects_issue_message_difference():
    from app.core.tool_build import installer
    from app.core.tool_build.models import BuildStatus, IssueSeverity, ValidationIssue, ValidationReport

    review = ValidationReport(
        build_id="build",
        status=BuildStatus.INSTALL_REVIEW,
        declared_permissions=frozenset(),
        detected_permissions=frozenset(),
        dependencies=(),
        file_hashes={"tool.py": "a" * 64},
        issues=(ValidationIssue("WARNING", IssueSeverity.WARNING, "first message"),),
    )
    fresh = ValidationReport(
        build_id="build",
        status=BuildStatus.INSTALL_REVIEW,
        declared_permissions=frozenset(),
        detected_permissions=frozenset(),
        dependencies=(),
        file_hashes={"tool.py": "a" * 64},
        issues=(ValidationIssue("WARNING", IssueSeverity.WARNING, "changed message"),),
    )

    assert installer._reports_match(review, fresh) is False


def test_uninstallable_fresh_report_does_not_capture_source_snapshot(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace(script="def broken(:")
    report = _review(workspace)
    monkeypatch.setattr(
        installer,
        "_capture_source_snapshot",
        lambda *_args: pytest.fail("uninstallable reports must reject before snapshot"),
    )

    result = _install(workspace, report)

    assert result.reason == "STALE_VALIDATION"


def test_snapshot_uses_validator_file_limits(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    report = _review(workspace)
    (workspace.source_dir / "extra.py").write_text("pass", encoding="utf-8")
    monkeypatch.setattr(installer, "_MAX_SOURCE_FILES", 1)

    result = _install(workspace, report)

    assert result.reason == "STALE_VALIDATION"


def test_manifest_switch_during_revalidation_is_stale(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace("alpha")
    report = _review(workspace)
    original = workspace.manifest_path.read_text(encoding="utf-8")
    real_validate = installer.validate_workspace

    def validate_b_then_restore(*args, **kwargs):
        workspace.manifest_path.write_text(_manifest("beta"), encoding="utf-8")
        fresh = real_validate(*args, **kwargs)
        workspace.manifest_path.write_text(original, encoding="utf-8")
        return fresh

    monkeypatch.setattr(installer, "validate_workspace", validate_b_then_restore)

    result = _install(workspace, report)

    assert result.installed is False
    assert result.reason == "STALE_VALIDATION"
    assert not (install_environment / "alpha").exists()


def test_dangling_symlink_target_endpoint_fails_closed(install_environment, tmp_path):
    workspace = _workspace()
    report = _review(workspace)
    install_environment.mkdir()
    target = install_environment / "safe_tool"
    try:
        target.symlink_to(tmp_path / "missing-target")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert _install(workspace, report).reason == "INSTALL_FAILED"


def test_dangling_symlink_stage_endpoint_fails_closed(install_environment, tmp_path):
    workspace = _workspace()
    report = _review(workspace)
    staging = install_environment / ".staging"
    staging.mkdir(parents=True)
    try:
        (staging / workspace.build_id).symlink_to(tmp_path / "missing-stage")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert _install(workspace, report).reason == "INSTALL_FAILED"


def test_same_name_requires_explicit_overwrite(install_environment):
    existing = install_environment / "safe_tool"
    existing.mkdir(parents=True)
    (existing / "tool.py").write_text("print('old')", encoding="utf-8")
    workspace = _workspace()

    result = _install(workspace, _review(workspace))

    assert result.reason == "NAME_CONFLICT"
    assert (existing / "tool.py").read_text(encoding="utf-8") == "print('old')"


def test_overwrite_replaces_existing_user_tool_and_keeps_backup(install_environment):
    existing = install_environment / "safe_tool"
    existing.mkdir(parents=True)
    (existing / "tool.py").write_text("print('old')", encoding="utf-8")
    workspace = _workspace()

    result = _install(workspace, _review(workspace), overwrite=True)

    assert result.installed is True
    assert (existing / "tool.py").read_text(encoding="utf-8") == "print('new')"
    assert (install_environment / result.backup_path / "tool.py").read_text(encoding="utf-8") == "print('old')"


def test_rejects_actual_builtin_and_reserved_names(install_environment):
    for name in ("exec", "note", "notes", "_staging"):
        workspace = _workspace(name)

        result = _install(workspace, _review(workspace), overwrite=True)

        assert result.reason == "RESERVED_NAME"
        assert not (install_environment / name).exists()


def test_windows_move_uses_thread_local_last_error_binding(monkeypatch, tmp_path):
    from app.core.tool_build import installer

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    calls: list[tuple[str, bool]] = []

    class MoveFile:
        argtypes = None
        restype = None

        def __call__(self, *_args):
            return 0

    class Kernel32:
        MoveFileExW = MoveFile()

    def win_dll(name: str, *, use_last_error: bool):
        calls.append((name, use_last_error))
        return Kernel32()

    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(installer.ctypes, "WinDLL", win_dll, raising=False)
    monkeypatch.setattr(installer.ctypes, "set_last_error", lambda _value: None)
    monkeypatch.setattr(installer.ctypes, "get_last_error", lambda: installer._ERROR_FILE_EXISTS)

    with pytest.raises(FileExistsError):
        installer._move_no_replace(source, destination)

    assert calls == [("kernel32", True)]


def test_staging_extra_file_is_rejected_before_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_copy = installer._copy_snapshot_to_stage

    def add_extra(*args):
        result = real_copy(*args)
        (args[1] / "extra.py").write_text("pass", encoding="utf-8")
        return result

    monkeypatch.setattr(installer, "_copy_snapshot_to_stage", add_extra)

    result = _install(workspace, _review(workspace))

    assert result.reason == "INSTALL_FAILED"
    assert not (install_environment / "safe_tool").exists()


def test_staging_replaced_directory_is_rejected_before_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_copy = installer._copy_snapshot_to_stage

    def replace_stage(*args):
        result = real_copy(*args)
        stage = args[1]
        stage.rename(stage.with_name("stage-original"))
        stage.mkdir()
        return result

    monkeypatch.setattr(installer, "_copy_snapshot_to_stage", replace_stage)

    assert _install(workspace, _review(workspace)).reason == "INSTALL_FAILED"


def test_staging_modified_file_is_rejected_before_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_copy = installer._copy_snapshot_to_stage

    def modify(*args):
        result = real_copy(*args)
        (args[1] / "tool.py").write_text("print('changed')", encoding="utf-8")
        return result

    monkeypatch.setattr(installer, "_copy_snapshot_to_stage", modify)

    result = _install(workspace, _review(workspace))

    assert result.reason == "INSTALL_FAILED"


def test_first_install_detects_target_created_during_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_verify = installer._verify_staging

    created = False

    def create_target(*args):
        nonlocal created
        result = real_verify(*args)
        if not created:
            created = True
            target = install_environment / "safe_tool"
            target.mkdir()
            (target / "marker").write_text("other", encoding="utf-8")
        return result

    monkeypatch.setattr(installer, "_verify_staging", create_target)

    result = _install(workspace, _review(workspace))

    assert result.reason == "NAME_CONFLICT"
    assert (install_environment / "safe_tool" / "marker").exists()


def test_final_target_race_uses_atomic_no_clobber(install_environment, monkeypatch):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_move = installer._move_no_replace

    def create_then_move(source, target):
        target.mkdir()
        return real_move(source, target)

    monkeypatch.setattr(installer, "_move_no_replace", create_then_move)

    result = _install(workspace, _review(workspace))

    assert result.reason == "NAME_CONFLICT"
    assert (install_environment / "safe_tool").exists()


def test_overwrite_detects_target_replacement_before_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    target = install_environment / "safe_tool"
    target.mkdir(parents=True)
    (target / "old").write_text("old", encoding="utf-8")
    workspace = _workspace()
    real_verify = installer._verify_staging

    def replace_target(*args):
        result = real_verify(*args)
        target.rename(install_environment / "original")
        target.mkdir()
        (target / "marker").write_text("replacement", encoding="utf-8")
        return result

    monkeypatch.setattr(installer, "_verify_staging", replace_target)

    result = _install(workspace, _review(workspace), overwrite=True)

    assert result.reason == "INSTALL_FAILED"
    assert (target / "marker").exists()


def test_overwrite_detects_backup_root_replacement_before_commit(install_environment, monkeypatch):
    from app.core.tool_build import installer

    target = install_environment / "safe_tool"
    target.mkdir(parents=True)
    (target / "old").write_text("old", encoding="utf-8")
    workspace = _workspace()
    real_verify = installer._verify_staging
    replaced = False

    def replace_backups(*args):
        nonlocal replaced
        result = real_verify(*args)
        if not replaced:
            replaced = True
            backups = install_environment / ".backups"
            backups.rename(install_environment / "backups-original")
            backups.mkdir()
        return result

    monkeypatch.setattr(installer, "_verify_staging", replace_backups)

    result = _install(workspace, _review(workspace), overwrite=True)

    assert result.reason == "INSTALL_FAILED"
    assert (target / "old").exists()


def test_cleanup_preserves_nested_stage_when_ancestor_is_replaced(install_environment, monkeypatch, caplog):
    from app.core.tool_build import installer

    user_tools = install_environment
    staging = user_tools / ".staging"
    backups = user_tools / ".backups"
    stage = staging / "build"
    nested = stage / "nested"
    child = nested / "child"
    child.mkdir(parents=True)
    backups.mkdir()
    marker = child / "marker.txt"
    marker.write_text("original", encoding="utf-8")
    roots = installer._InstallRoots(
        installer._require_directory(user_tools, "user tools"),
        installer._require_directory(staging, "staging"),
        installer._require_directory(backups, "backups"),
    )
    stage_identity = installer._require_directory(stage, "stage")
    nested_identity = installer._require_directory(nested, "nested")
    child_identity = installer._require_directory(child, "child")
    marker_identity = installer._require_regular_file(marker, None, "marker")
    staged = installer._StageSnapshot(
        stage_identity,
        ((stage, stage_identity), (nested, nested_identity), (child, child_identity)),
        (installer._StagedFile("nested/child/marker.txt", marker_identity, "digest"),),
    )
    real_require_file = installer._require_regular_file
    replaced = False

    def move_child_beneath_replacement(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            nested.rename(stage / "nested-original")
            nested.mkdir()
            (stage / "nested-original" / "child").rename(nested / "child")
        return real_require_file(*args, **kwargs)

    monkeypatch.setattr(installer, "_require_regular_file", move_child_beneath_replacement)

    with caplog.at_level("WARNING"):
        installer._cleanup_stage(stage, staged, roots)

    assert (nested / "child" / "marker.txt").read_text(encoding="utf-8") == "original"
    assert "preserving" in caplog.text


def test_cleanup_preserves_stage_when_staging_root_is_replaced(install_environment, monkeypatch, caplog):
    from app.core.tool_build import installer

    workspace = _workspace()
    real_copy = installer._copy_snapshot_to_stage

    def replace_staging_root(*args):
        result = real_copy(*args)
        staging = install_environment / ".staging"
        staging.rename(install_environment / "staging-original")
        staging.mkdir()
        return result

    monkeypatch.setattr(installer, "_copy_snapshot_to_stage", replace_staging_root)

    with caplog.at_level("WARNING"):
        result = _install(workspace, _review(workspace))

    assert result.reason == "INSTALL_FAILED"
    assert (install_environment / "staging-original" / workspace.build_id).exists()
    assert "preserving" in caplog.text


def test_overwrite_rollback_when_final_replace_fails(install_environment, monkeypatch):
    from app.core.tool_build import installer

    target = install_environment / "safe_tool"
    target.mkdir(parents=True)
    (target / "old").write_text("old", encoding="utf-8")
    workspace = _workspace()
    real_move = installer._move_no_replace

    def fail_final(source, destination):
        if Path(source).parent.name == ".staging":
            raise OSError("final replacement failed")
        return real_move(source, destination)

    monkeypatch.setattr(installer, "_move_no_replace", fail_final)
    result = _install(workspace, _review(workspace), overwrite=True)

    assert result.reason == "INSTALL_FAILED"
    assert (target / "old").exists()


def test_symlink_source_is_rejected(install_environment, tmp_path):
    workspace = _workspace()
    report = _review(workspace)
    workspace.script_path.unlink()
    try:
        workspace.script_path.symlink_to(tmp_path / "outside.py")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert _install(workspace, report).reason == "STALE_VALIDATION"


def test_hardlink_source_is_rejected(install_environment):
    workspace = _workspace()
    report = _review(workspace)
    try:
        os.link(workspace.script_path, workspace.source_dir / "copy.py")
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    assert _install(workspace, report).reason == "STALE_VALIDATION"


def test_junction_or_reparse_source_is_rejected_when_supported(install_environment, tmp_path):
    if os.name != "nt":
        pytest.skip("junctions require Windows")
    workspace = _workspace()
    original = workspace.source_dir.with_name("source-original")
    workspace.source_dir.rename(original)
    target = tmp_path / "target"
    target.mkdir()
    if os.system(f'cmd /d /c mklink /J "{workspace.source_dir}" "{target}" >nul 2>&1') != 0:
        pytest.skip("junctions unavailable")

    assert _install(workspace, _review(workspace)).reason == "STALE_VALIDATION"


def test_install_has_no_pip_or_registry_side_effect(install_environment, monkeypatch):
    workspace = _workspace()
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: pytest.fail("no pip"))
    monkeypatch.setattr(
        "app.tools.registry.ToolRegistry.register", lambda *_a, **_k: pytest.fail("no registry")
    )

    assert _install(workspace, _review(workspace)).installed is True
