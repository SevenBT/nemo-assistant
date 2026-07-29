import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from app.core.tool_build import workspace as workspace_module
from app.core.tool_build.workspace import BuildWorkspace, SourceTraversalLimitExceeded


@pytest.fixture
def builds_dir(tmp_path, monkeypatch):
    path = tmp_path / "builds"
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", path)
    return path


def create_workspace(builds_dir, *, script="tool.py", script_text="print(1)"):
    manifest = json.dumps({"name": "x", "script": script}, ensure_ascii=False)
    return BuildWorkspace.create("make a formatter", manifest, script_text)


def test_workspace_writes_only_under_tool_builds(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir, script_text="print('你好')")

    assert workspace.source_dir.parent.parent == builds_dir
    assert workspace.manifest_path.read_text(encoding="utf-8") == '{"name": "x", "script": "tool.py"}'
    assert workspace.script_path.read_text(encoding="utf-8") == "print('你好')"
    assert workspace.requirement_path.read_text(encoding="utf-8") == "make a formatter"
    assert workspace.tool_spec_path.read_text(encoding="utf-8") == workspace.manifest_path.read_text(encoding="utf-8")
    assert {path.name for path in workspace.root.iterdir()} == {"input", "source", "logs", "reports"}
    assert not (tmp_path / "user_tools").exists()
    assert workspace.build_id
    assert workspace.root.parent == builds_dir


def test_workspace_rejects_non_string_inputs(builds_dir):
    with pytest.raises(TypeError, match="strings"):
        BuildWorkspace.create(None, "{}", "print(1)")
def test_build_ids_are_generated_and_distinct(builds_dir):
    first = create_workspace(builds_dir)
    second = create_workspace(builds_dir)

    assert first.build_id != second.build_id
    assert first.root != second.root


def test_script_path_cannot_escape_source_with_posix_or_windows_paths(builds_dir):
    for script in ("../outside.py", "a/../../outside.py", r"..\outside.py", r"C:\outside.py", "/outside.py"):
        with pytest.raises(ValueError):
            create_workspace(builds_dir, script=script)


def test_script_path_must_be_a_file_inside_source(builds_dir):
    with pytest.raises(ValueError):
        create_workspace(builds_dir, script=".")


def test_nested_script_uses_relative_posix_path(builds_dir):
    workspace = create_workspace(builds_dir, script=r"sub\tool.py")

    assert workspace.script_path == workspace.source_dir / "sub" / "tool.py"
    assert workspace.script_path.exists()


def test_file_hashes_use_relative_posix_sha256_and_change_after_edit(builds_dir):
    workspace = create_workspace(builds_dir, script_text="print(1)")
    extra = workspace.source_dir / "sub" / "unicode-文件.txt"
    extra.parent.mkdir()
    extra_content = "😀\n"
    extra.write_text(extra_content, encoding="utf-8")

    first = workspace.file_hashes()
    expected = hashlib.sha256("print(1)".encode("utf-8")).hexdigest()

    assert first["manifest.json"] == hashlib.sha256(
        workspace.manifest_path.read_bytes()
    ).hexdigest()
    assert first["tool.py"] == expected
    assert first["sub/unicode-文件.txt"] == hashlib.sha256(extra.read_bytes()).hexdigest()
    assert all(not Path(name).is_absolute() for name in first)
    assert all("\\" not in name for name in first)

    workspace.script_path.write_text("print(2)", encoding="utf-8")
    assert first["manifest.json"] != workspace.file_hashes()["tool.py"]


def test_file_hashes_reject_symlink_file_and_directory(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = workspace.source_dir / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="link|reparse"):
        workspace.file_hashes()

    link.unlink()
    linked_dir = workspace.source_dir / "linked-dir"
    linked_dir.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="link|reparse"):
        workspace.file_hashes()


def test_file_hashes_reject_hard_link(builds_dir):
    workspace = create_workspace(builds_dir)
    hard_link = workspace.source_dir / "hard-link.py"
    try:
        os.link(workspace.script_path, hard_link)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(ValueError, match="hard link"):
        workspace.file_hashes()


def test_file_hashes_reject_non_regular_file_when_supported(builds_dir):
    workspace = create_workspace(builds_dir)
    fifo = workspace.source_dir / "pipe"
    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes unavailable")
    try:
        os.mkfifo(fifo)
    except OSError as exc:
        pytest.skip(f"named pipes unavailable: {exc}")

    with pytest.raises(ValueError, match="regular"):
        workspace.file_hashes()


def test_read_source_returns_source_files_with_posix_names(builds_dir):
    workspace = create_workspace(builds_dir, script_text="print('source')")
    helper = workspace.source_dir / "lib" / "helper.py"
    helper.parent.mkdir()
    helper.write_text("return 1", encoding="utf-8")

    assert workspace.read_source() == {
        "manifest.json": workspace.manifest_path.read_text(encoding="utf-8"),
        "tool.py": "print('source')",
        "lib/helper.py": "return 1",
    }


@pytest.mark.parametrize(
    ("setup", "limits", "expected_limit"),
    [
        (
            lambda workspace: (workspace.source_dir / "extra.py").write_text("pass", encoding="utf-8"),
            {"max_files": 2},
            "file_count",
        ),
        (
            lambda workspace: (workspace.source_dir / "nested").mkdir(),
            {"max_directories": 1},
            "directory_count",
        ),
        (
            lambda workspace: (workspace.source_dir / "nested").mkdir(),
            {"max_depth": 0},
            "depth",
        ),
    ],
    ids=["files", "directories", "depth"],
)
def test_source_file_iteration_enforces_limits_during_enumeration(
    builds_dir, setup, limits, expected_limit
):
    workspace = create_workspace(builds_dir)
    setup(workspace)

    with pytest.raises(SourceTraversalLimitExceeded) as exc_info:
        tuple(workspace._source_files(**limits))

    assert exc_info.value.limit == expected_limit


def test_source_iteration_stops_requesting_entries_at_total_entry_limit(
    builds_dir, monkeypatch
):
    workspace = create_workspace(builds_dir)
    requested = 0
    real_scandir = os.scandir

    class ObservableScandir:
        def __enter__(self):
            self._entries = iter(real_scandir(workspace.source_dir))
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            self._entries.close()

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal requested
            requested += 1
            if requested > 3:
                pytest.fail("source traversal requested an entry after the N+1 boundary")
            if requested <= 2:
                return next(self._entries)
            raise AssertionError("entry limit must fail before requesting another DirEntry")

    monkeypatch.setattr(workspace_module.os, "scandir", lambda _path: ObservableScandir())

    with pytest.raises(SourceTraversalLimitExceeded) as exc_info:
        tuple(workspace._source_files(max_entries=1))

    assert exc_info.value.limit == "entry_count"
    assert requested == 2


def test_source_iteration_counts_entries_before_path_inspection(builds_dir, monkeypatch):
    workspace = create_workspace(builds_dir)
    real_scandir = os.scandir
    inspected = 0

    class ObservableScandir:
        def __enter__(self):
            self._entries = iter(real_scandir(workspace.source_dir))
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            self._entries.close()

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._entries)

    original_inspect = workspace_module._inspect_path

    def observe_inspect(path, *, label):
        nonlocal inspected
        if label == "source path":
            inspected += 1
        return original_inspect(path, label=label)

    monkeypatch.setattr(workspace_module.os, "scandir", lambda _path: ObservableScandir())
    monkeypatch.setattr(workspace_module, "_inspect_path", observe_inspect)

    with pytest.raises(SourceTraversalLimitExceeded) as exc_info:
        tuple(workspace._source_files(max_entries=0))

    assert exc_info.value.limit == "entry_count"
    assert inspected == 0


def test_read_source_rejects_symlink_and_binary_files(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    outside = tmp_path / "secret"
    outside.write_text("secret", encoding="utf-8")
    link = workspace.source_dir / "secret"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="link|reparse"):
        workspace.read_source()


def test_cleanup_removes_only_current_build_and_returns_true(builds_dir):
    workspace = create_workspace(builds_dir)
    sibling = create_workspace(builds_dir)

    assert workspace.cleanup() is True
    assert not workspace.root.exists()
    assert sibling.root.exists()
    assert workspace.cleanup() is False


def test_cleanup_rejects_relocated_workspace(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    relocated = tmp_path / "relocated"
    workspace.root.rename(relocated)

    assert workspace.cleanup() is False
    assert relocated.exists()


def test_atomic_writes_leave_no_temporary_file_after_creation(builds_dir):
    workspace = create_workspace(builds_dir)

    assert not any(path.name.startswith(".") and path.name.endswith(".tmp") for path in workspace.root.rglob("*"))


def test_manifest_script_is_not_written_through_existing_symlink(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    workspace.script_path.unlink()
    outside = tmp_path / "outside.py"
    outside.write_text("keep", encoding="utf-8")
    try:
        workspace.script_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="link|reparse"):
        workspace.read_source()
    assert outside.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("script", ["manifest.json", "./manifest.json", "MANIFEST.JSON"])
def test_manifest_script_cannot_overwrite_reserved_manifest(builds_dir, script):
    with pytest.raises(ValueError, match="manifest"):
        create_workspace(builds_dir, script=script)


@pytest.mark.parametrize("script", [r"C:tool.py", "tool.py:payload", r"\\\\server\\share\\tool.py"])
def test_script_path_rejects_windows_drive_relative_ads_and_unc_paths(builds_dir, script):
    with pytest.raises(ValueError, match="relative|script"):
        create_workspace(builds_dir, script=script)


def test_file_hashes_rejects_replaced_source_directory(builds_dir):
    workspace = create_workspace(builds_dir)
    original = workspace.root / "source-original"
    workspace.source_dir.rename(original)
    workspace.source_dir.mkdir()
    (workspace.source_dir / "tool.py").write_text("replacement", encoding="utf-8")

    with pytest.raises(ValueError, match="identity|source|workspace"):
        workspace.file_hashes()


def test_read_source_rejects_replaced_root_directory(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    workspace.root.rename(tmp_path / "original-build")
    workspace.root.mkdir()
    (workspace.root / "source").mkdir()
    (workspace.root / "source" / "tool.py").write_text("replacement", encoding="utf-8")

    with pytest.raises(ValueError, match="identity|root|workspace"):
        workspace.read_source()


def test_cleanup_rejects_same_path_replacement_and_preserves_it(builds_dir, tmp_path):
    workspace = create_workspace(builds_dir)
    workspace.root.rename(tmp_path / "original-build")
    workspace.root.mkdir()
    replacement_marker = workspace.root / "replacement.txt"
    replacement_marker.write_text("do not remove", encoding="utf-8")

    with pytest.raises(ValueError, match="identity|root|workspace"):
        workspace.cleanup()
    assert replacement_marker.read_text(encoding="utf-8") == "do not remove"


def test_cleanup_rejects_replaced_source_directory_and_preserves_it(builds_dir):
    workspace = create_workspace(builds_dir)
    original = workspace.root / "source-original"
    workspace.source_dir.rename(original)
    workspace.source_dir.mkdir()
    replacement_marker = workspace.source_dir / "replacement.txt"
    replacement_marker.write_text("do not remove", encoding="utf-8")

    with pytest.raises(ValueError, match="identity|source|workspace"):
        workspace.cleanup()
    assert replacement_marker.read_text(encoding="utf-8") == "do not remove"


def test_read_source_rejects_binary_file_without_link_permissions(builds_dir):
    workspace = create_workspace(builds_dir)
    binary = workspace.source_dir / "binary.bin"
    binary.write_bytes(bytes((0xFF, 0xFE, 0x00)))

    with pytest.raises(ValueError, match="UTF-8"):
        workspace.read_source()


def test_windows_reparse_check_fails_closed_when_attribute_lookup_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.tool_build.workspace.TOOL_BUILDS_DIR", tmp_path / "builds")
    monkeypatch.setattr("app.core.tool_build.workspace.os.name", "nt")
    monkeypatch.setattr(
        "app.core.tool_build.workspace._get_windows_file_attributes",
        lambda _path: (_ for _ in ()).throw(OSError("attribute lookup failed")),
    )

    with pytest.raises(ValueError, match="reparse"):
        BuildWorkspace.create("req", '{"script":"tool.py"}', "print(1)")

def test_file_hashes_rejects_source_junction_when_supported(builds_dir, tmp_path):
    if os.name != "nt":
        pytest.skip("junctions are only available on Windows")

    workspace = create_workspace(builds_dir)
    original = workspace.root / "source-original"
    workspace.source_dir.rename(original)
    target = tmp_path / "junction-target"
    target.mkdir()
    result = os.system(f'cmd /d /c mklink /J "{workspace.source_dir}" "{target}" >nul 2>&1')
    if result != 0:
        pytest.skip("junction creation is unavailable in this Windows environment")

    with pytest.raises(ValueError, match="reparse|identity|source"):
        workspace.file_hashes()


def _write_parent_chain(parent):
    return ((parent, workspace_module._require_directory(parent, label="test directory")),)


def test_atomic_write_cleans_verified_temporary_file_after_replace_failure(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "target.txt"
    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(workspace_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        workspace_module._atomic_write(target, "content", _write_parent_chain(parent))

    assert not any(path.name.endswith(".tmp") for path in parent.iterdir())


def test_atomic_write_preserves_replaced_temporary_file_after_replace_failure(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "target.txt"
    replacement = parent / ".replacement.tmp"

    def replace_temporary_then_fail(source, _target):
        Path(source).unlink()
        replacement.write_text("do not remove", encoding="utf-8")
        replacement.rename(source)
        raise OSError("replace failed")

    monkeypatch.setattr(workspace_module.os, "replace", replace_temporary_then_fail)

    with pytest.raises(OSError, match="replace failed"):
        workspace_module._atomic_write(target, "content", _write_parent_chain(parent))

    assert (parent / next(path.name for path in parent.iterdir() if path.name.endswith(".tmp"))).read_text(encoding="utf-8") == "do not remove"


def test_atomic_write_preserves_temporary_when_parent_replaced_after_replace_failure(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "target.txt"
    original_parent = tmp_path / "original-parent"

    def replace_parent_then_fail(_source, _target):
        parent.rename(original_parent)
        parent.mkdir()
        (parent / Path(_source).name).write_text("do not remove", encoding="utf-8")
        raise OSError("replace failed")

    monkeypatch.setattr(workspace_module.os, "replace", replace_parent_then_fail)

    with pytest.raises(OSError, match="replace failed"):
        workspace_module._atomic_write(target, "content", _write_parent_chain(parent))

    temporary = next(path for path in parent.iterdir() if path.name.endswith(".tmp"))
    assert temporary.read_text(encoding="utf-8") == "do not remove"


def test_safe_cleanup_records_diagnostic_when_conservative_cleanup_fails(tmp_path, caplog):
    builds_dir = tmp_path / "builds"
    builds_dir.mkdir()
    builds_identity = workspace_module._require_directory(builds_dir, label="test builds")
    root = builds_dir / "build"
    root.mkdir()
    root_identity = workspace_module._require_directory(root, label="test root")
    root.rmdir()
    root.write_text("replacement", encoding="utf-8")

    with caplog.at_level("WARNING"):
        workspace_module._safe_cleanup_created_root(
            builds_dir, builds_identity, root, root_identity
        )

    assert "preserving workspace" in caplog.text
