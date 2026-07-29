"""Fail-closed atomic installation for statically verified tool builds.

Static validation is not a sandbox. This module does not execute generated code,
install dependencies, access the network, or mutate a live tool registry.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.config import USER_TOOLS_DIR

from .manifest import parse_manifest_text
from .models import InstallResult, ToolPermission, ValidationReport
from .validator import validate_workspace
from .workspace import (
    BuildWorkspace,
    FileIdentity,
    SourceTraversalLimitExceeded,
    _has_reparse_attribute,
)

_LOGGER = logging.getLogger(__name__)
_STAGING_DIRECTORY = ".staging"
_BACKUPS_DIRECTORY = ".backups"
_MAX_SOURCE_FILE_BYTES = 1_048_576
_MAX_SOURCE_FILES = 16
_MAX_SOURCE_DIRECTORIES = 16
_MAX_SOURCE_DEPTH = 4
_MAX_SOURCE_TOTAL_BYTES = 2_097_152
_MAX_SOURCE_ENTRIES = 32
_MOVEFILE_WRITE_THROUGH = 0x8
_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_EXISTS = 80
_RESERVED_TOOL_NAMES = frozenset(
    {_STAGING_DIRECTORY, _BACKUPS_DIRECTORY, "_staging", "_backups"}
)
# This stable snapshot prevents replacing current shipped names without loading
# tools. Task 6 can use the live registry/service set to address future drift.
_BUILTIN_TOOL_NAMES = frozenset(
    {
        "clipboard", "exec", "fetch_url", "find_files", "grep", "list_dir",
        "memory", "multi_model_consult", "note", "notes", "read_file", "reminder",
        "run_python", "save_file", "scheduled_task", "web_search",
    }
)


@dataclass(frozen=True)
class _SourceFile:
    relative: str
    content: bytes
    digest: str


@dataclass(frozen=True)
class _SourceSnapshot:
    files: tuple[_SourceFile, ...]

    @property
    def hashes(self) -> dict[str, str]:
        return {file.relative: file.digest for file in self.files}

    def text(self, relative: str) -> str:
        for file in self.files:
            if file.relative == relative:
                return file.content.decode("utf-8")
        raise KeyError(relative)


@dataclass(frozen=True)
class _StagedFile:
    relative: str
    identity: FileIdentity
    digest: str


@dataclass(frozen=True)
class _StageSnapshot:
    root_identity: FileIdentity
    directories: tuple[tuple[Path, FileIdentity], ...]
    files: tuple[_StagedFile, ...]


@dataclass(frozen=True)
class _InstallRoots:
    user_identity: FileIdentity
    staging_identity: FileIdentity
    backups_identity: FileIdentity


def install_verified_build(
    workspace: BuildWorkspace,
    report: ValidationReport,
    *,
    approved_permissions: frozenset[ToolPermission],
    overwrite: bool,
    acknowledged_overrides: frozenset[str] = frozenset(),
) -> InstallResult:
    """Atomically install an unchanged workspace using current explicit approval.

    The caller report is only a review baseline. Permission approval is accepted
    exclusively through ``approved_permissions`` and is independently checked.
    ``acknowledged_overrides`` carries the user's explicit, risk-acknowledged
    consent to install despite specific overridable blocking findings; it never
    relaxes the artifact-identity, snapshot, or atomic-commit checks and can
    never clear a non-overridable block.
    """

    if not isinstance(workspace, BuildWorkspace) or not isinstance(report, ValidationReport):
        return InstallResult(False, "", "INVALID_INPUT")
    if not _valid_approvals(approved_permissions) or not isinstance(overwrite, bool):
        return InstallResult(False, "", "INVALID_INPUT")
    if not _valid_overrides(acknowledged_overrides):
        return InstallResult(False, "", "INVALID_INPUT")

    fresh_report = validate_workspace(workspace, approved_permissions=approved_permissions)
    if not fresh_report.is_installable_with(acknowledged_overrides):
        return InstallResult(False, "", "STALE_VALIDATION")
    try:
        snapshot = _capture_source_snapshot(workspace, frozenset(fresh_report.file_hashes))
        manifest = parse_manifest_text(snapshot.text("manifest.json"), mode="strict")
    except (KeyError, MemoryError, OSError, UnicodeDecodeError, ValueError):
        return InstallResult(False, "", "STALE_VALIDATION")

    if (
        not _reports_match(report, fresh_report)
        or not fresh_report.is_installable_with(acknowledged_overrides)
        or snapshot.hashes != dict(fresh_report.file_hashes)
    ):
        return InstallResult(False, manifest.name, "STALE_VALIDATION")
    if _is_reserved_name(manifest.name):
        return InstallResult(False, manifest.name, "RESERVED_NAME")

    try:
        result = _install_snapshot(workspace, snapshot, fresh_report, manifest.name, overwrite)
    except (MemoryError, OSError, ValueError) as exc:
        _LOGGER.warning("tool build installation failed for %s: %s", manifest.name, exc)
        return InstallResult(False, manifest.name, "INSTALL_FAILED")
    if result.installed and acknowledged_overrides:
        _LOGGER.info(
            "tool build %s installed with risk-acknowledged overrides: %s",
            manifest.name,
            ", ".join(sorted(acknowledged_overrides)),
        )
    return result


def _valid_approvals(approved_permissions: object) -> bool:
    return isinstance(approved_permissions, frozenset) and all(
        isinstance(permission, ToolPermission) for permission in approved_permissions
    )


def _valid_overrides(acknowledged_overrides: object) -> bool:
    return isinstance(acknowledged_overrides, frozenset) and all(
        isinstance(code, str) for code in acknowledged_overrides
    )


def _reports_match(review: ValidationReport, fresh: ValidationReport) -> bool:
    """Compare every immutable review field; the old report grants no authority."""

    return (
        review.build_id == fresh.build_id
        and review.status == fresh.status
        and review.declared_permissions == fresh.declared_permissions
        and review.detected_permissions == fresh.detected_permissions
        and review.dependencies == fresh.dependencies
        and dict(review.file_hashes) == dict(fresh.file_hashes)
        and review.issues == fresh.issues
    )


def _capture_source_snapshot(
    workspace: BuildWorkspace, expected_paths: frozenset[str]
) -> _SourceSnapshot:
    """Capture only the bounded, validator-approved source path set once."""

    files: list[_SourceFile] = []
    total_bytes = 0
    try:
        entries = tuple(
            workspace._source_files(
                max_entries=_MAX_SOURCE_ENTRIES,
                max_files=_MAX_SOURCE_FILES,
                max_directories=_MAX_SOURCE_DIRECTORIES,
                max_depth=_MAX_SOURCE_DEPTH,
            )
        )
        for path, identity, _parents in entries:
            relative = path.relative_to(workspace.source_dir).as_posix()
            if relative not in expected_paths:
                raise ValueError("source path is absent from validation report")
            metadata = path.stat(follow_symlinks=False)
            if metadata.st_size > _MAX_SOURCE_FILE_BYTES:
                raise ValueError("source file exceeds snapshot limit")
            total_bytes += metadata.st_size
            if total_bytes > _MAX_SOURCE_TOTAL_BYTES:
                raise ValueError("source total exceeds snapshot limit")
            content = _read_source_file(path, identity)
            files.append(_SourceFile(relative, content, hashlib.sha256(content).hexdigest()))
    except (MemoryError, RecursionError, OSError, SourceTraversalLimitExceeded) as exc:
        raise ValueError("cannot safely capture bounded source snapshot") from exc
    snapshot = _SourceSnapshot(tuple(sorted(files, key=lambda file: file.relative)))
    if frozenset(snapshot.hashes) != expected_paths:
        raise ValueError("source path set differs from validation report")
    return snapshot


def _read_source_file(path: Path, expected: FileIdentity) -> bytes:
    _require_regular_file(path, expected, "source file")
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _identity(opened) != expected or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ValueError("source file changed during snapshot")
            content = stream.read(_MAX_SOURCE_FILE_BYTES + 1)
            if len(content) > _MAX_SOURCE_FILE_BYTES:
                raise ValueError("source file exceeded snapshot limit")
        _require_regular_file(path, expected, "source file")
        return content
    except OSError as exc:
        raise ValueError("cannot safely snapshot source file") from exc


def _install_snapshot(
    workspace: BuildWorkspace,
    source: _SourceSnapshot,
    report: ValidationReport,
    tool_name: str,
    overwrite: bool,
) -> InstallResult:
    roots = _prepare_install_roots()
    target = _direct_child(USER_TOOLS_DIR, tool_name, "tool directory")
    initial_target = _initial_target_identity(target)
    if initial_target is not None and not overwrite:
        return InstallResult(False, tool_name, "NAME_CONFLICT")

    staging_root = USER_TOOLS_DIR / _STAGING_DIRECTORY
    backups_root = USER_TOOLS_DIR / _BACKUPS_DIRECTORY
    stage = _direct_child(staging_root, workspace.build_id, "staging directory")
    backup = _direct_child(backups_root, workspace.build_id, "backup directory")
    if _path_exists(stage) or _path_exists(backup):
        raise ValueError("build identifier already has installation state")

    stage.mkdir()
    stage_identity = _require_directory(stage, "staging directory")
    staged: _StageSnapshot | None = None
    try:
        staged = _copy_snapshot_to_stage(source, stage, stage_identity)
        _verify_staging(stage, staged, report, tool_name)
        if initial_target is None:
            result = _commit_new(tool_name, target, stage, staged, roots, report)
        else:
            result = _commit_overwrite(
                tool_name, target, backup, stage, staged, roots, initial_target, report
            )
        if not result.installed:
            _cleanup_stage(stage, staged, roots)
        return result
    except (MemoryError, OSError, ValueError):
        if staged is not None:
            _cleanup_stage(stage, staged, roots)
        else:
            _cleanup_unfinished_stage(stage, stage_identity, roots)
        raise


def _prepare_install_roots() -> _InstallRoots:
    if not _path_exists(USER_TOOLS_DIR):
        USER_TOOLS_DIR.mkdir(parents=True, exist_ok=False)
    user_identity = _require_directory(USER_TOOLS_DIR, "user tools directory")
    staging = _create_or_verify_child(USER_TOOLS_DIR, user_identity, _STAGING_DIRECTORY)
    backups = _create_or_verify_child(USER_TOOLS_DIR, user_identity, _BACKUPS_DIRECTORY)
    return _InstallRoots(
        user_identity,
        _require_directory(staging, "staging root"),
        _require_directory(backups, "backups root"),
    )


def _create_or_verify_child(parent: Path, parent_identity: FileIdentity, name: str) -> Path:
    _require_directory(parent, "user tools directory", parent_identity)
    child = _direct_child(parent, name, "installer directory")
    if _path_exists(child):
        _require_directory(child, "installer directory")
    else:
        child.mkdir()
        _require_directory(child, "installer directory")
    return child


def _initial_target_identity(target: Path) -> FileIdentity | None:
    if not _path_exists(target):
        return None
    return _require_directory(target, "existing tool directory")


def _copy_snapshot_to_stage(
    source: _SourceSnapshot, stage: Path, stage_identity: FileIdentity
) -> _StageSnapshot:
    """Write the immutable source bytes and preserve all staged identities."""

    directories: dict[Path, FileIdentity] = {stage: stage_identity}
    staged_files: list[_StagedFile] = []
    for file in source.files:
        destination = _stage_destination(stage, file.relative)
        _create_stage_parents(stage, stage_identity, destination.parent, directories)
        if _path_exists(destination):
            raise ValueError("staged file already exists")
        try:
            with destination.open("xb") as stream:
                stream.write(file.content)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ValueError("cannot create staged file") from exc
        identity = _require_regular_file(destination, None, "staged file")
        staged_files.append(_StagedFile(file.relative, identity, file.digest))
    return _StageSnapshot(
        stage_identity,
        tuple(sorted(directories.items(), key=lambda item: str(item[0]))),
        tuple(sorted(staged_files, key=lambda file: file.relative)),
    )


def _stage_destination(stage: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid source-relative path")
    return _contained_path(stage, stage.joinpath(*path.parts), "staged file")


def _create_stage_parents(
    stage: Path,
    stage_identity: FileIdentity,
    parent: Path,
    directories: dict[Path, FileIdentity],
) -> None:
    current = stage
    _require_directory(current, "staging directory", stage_identity)
    for component in parent.relative_to(stage).parts:
        _require_directory(current, "staging directory", directories[current])
        child = _direct_child(current, component, "staging directory")
        if _path_exists(child):
            identity = _require_directory(child, "staging directory")
        else:
            child.mkdir()
            identity = _require_directory(child, "staging directory")
        directories[child] = identity
        current = child


def _verify_staging(
    stage: Path,
    staged: _StageSnapshot,
    report: ValidationReport,
    tool_name: str,
) -> None:
    """Require the exact copied tree before committing it to the live root."""

    _require_directory(stage, "staging directory", staged.root_identity)
    expected_directories = dict(staged.directories)
    expected_files = {file.relative: file for file in staged.files}
    seen_files: set[str] = set()
    seen_directories: set[Path] = set()

    def walk(directory: Path, identity: FileIdentity) -> None:
        _require_directory(directory, "staging directory", identity)
        seen_directories.add(directory)
        try:
            children = tuple(directory.iterdir())
        except OSError as exc:
            raise ValueError("cannot enumerate staging directory") from exc
        for child in children:
            _require_directory(directory, "staging directory", identity)
            child_identity, mode = _inspect_path(child, "staging path")
            if stat.S_ISDIR(mode):
                expected = expected_directories.get(child)
                if expected is None or expected != child_identity:
                    raise ValueError("unexpected or replaced staging directory")
                walk(child, expected)
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("staging path is not a regular file")
            relative = child.relative_to(stage).as_posix()
            expected_file = expected_files.get(relative)
            if expected_file is None or expected_file.identity != child_identity:
                raise ValueError("unexpected or replaced staged file")
            content = _read_source_file(child, child_identity)
            if hashlib.sha256(content).hexdigest() != expected_file.digest:
                raise ValueError("staged file digest changed")
            seen_files.add(relative)

    walk(stage, staged.root_identity)
    if seen_directories != set(expected_directories) or seen_files != set(expected_files):
        raise ValueError("staging tree differs from copied snapshot")
    if {file.relative: file.digest for file in staged.files} != dict(report.file_hashes):
        raise ValueError("staged files differ from validated report")
    manifest = parse_manifest_text(
        _read_source_file(stage / "manifest.json", expected_files["manifest.json"].identity).decode("utf-8"),
        mode="strict",
    )
    if manifest.name != tool_name:
        raise ValueError("staged manifest name changed")


def _commit_new(
    tool_name: str,
    target: Path,
    stage: Path,
    staged: _StageSnapshot,
    roots: _InstallRoots,
    report: ValidationReport,
) -> InstallResult:
    _verify_commit_roots(roots)
    _verify_staging(stage, staged, report, tool_name)
    if _endpoint_identity(target, "target endpoint") is not None:
        _require_directory(target, "concurrent tool directory")
        return InstallResult(False, tool_name, "NAME_CONFLICT")
    _verify_commit_roots(roots)
    if _endpoint_identity(target, "target endpoint") is not None:
        _require_directory(target, "concurrent tool directory")
        return InstallResult(False, tool_name, "NAME_CONFLICT")
    try:
        _move_no_replace(stage, target)
    except FileExistsError:
        _require_directory(target, "concurrent tool directory")
        return InstallResult(False, tool_name, "NAME_CONFLICT")
    _require_directory(target, "installed tool directory", staged.root_identity)
    return InstallResult(True, tool_name, "")


def _commit_overwrite(
    tool_name: str,
    target: Path,
    backup: Path,
    stage: Path,
    staged: _StageSnapshot,
    roots: _InstallRoots,
    target_identity: FileIdentity,
    report: ValidationReport,
) -> InstallResult:
    _verify_commit_roots(roots)
    _verify_staging(stage, staged, report, tool_name)
    _verify_commit_roots(roots)
    if _endpoint_identity(backup, "backup endpoint") is not None:
        raise ValueError("backup path unexpectedly exists")
    _require_directory(target, "existing tool directory", target_identity)
    _move_no_replace(target, backup)
    try:
        _verify_commit_roots(roots)
        _require_directory(backup, "backup directory", target_identity)
        _verify_staging(stage, staged, report, tool_name)
        _verify_commit_roots(roots)
        _require_directory(backup, "backup directory", target_identity)
        if _endpoint_identity(target, "target endpoint") is not None:
            raise ValueError("target unexpectedly exists after backup move")
        _move_no_replace(stage, target)
        _require_directory(target, "installed tool directory", staged.root_identity)
    except (MemoryError, OSError, ValueError):
        _rollback_backup(target, backup, roots, target_identity)
        raise
    return InstallResult(True, tool_name, "", f"{_BACKUPS_DIRECTORY}/{backup.name}")


def _verify_commit_roots(roots: _InstallRoots) -> None:
    _require_directory(USER_TOOLS_DIR, "user tools directory", roots.user_identity)
    _require_directory(USER_TOOLS_DIR / _STAGING_DIRECTORY, "staging root", roots.staging_identity)
    _require_directory(USER_TOOLS_DIR / _BACKUPS_DIRECTORY, "backups root", roots.backups_identity)


def _rollback_backup(
    target: Path, backup: Path, roots: _InstallRoots, original: FileIdentity
) -> None:
    """Restore only an identity-verified backup over a still-absent target."""

    try:
        _verify_commit_roots(roots)
        if _endpoint_identity(target, "rollback target") is not None:
            raise ValueError("cannot restore over an unknown target")
        _require_directory(backup, "backup directory", original)
        _move_no_replace(backup, target)
        _require_directory(target, "restored tool directory", original)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("preserving installation state after unsafe rollback: %s", exc)


def _cleanup_stage(stage: Path, staged: _StageSnapshot, roots: _InstallRoots) -> None:
    try:
        directories = dict(staged.directories)
        _remove_stage_tree(
            stage,
            stage,
            directories,
            {file.relative: file.identity for file in staged.files},
            roots,
        )
    except (OSError, ValueError) as exc:
        _LOGGER.warning("preserving unverified staging state: %s", exc)


def _cleanup_unfinished_stage(
    stage: Path, identity: FileIdentity, roots: _InstallRoots
) -> None:
    try:
        _remove_stage_tree(stage, stage, {stage: identity}, {}, roots)
    except (OSError, ValueError) as exc:
        _LOGGER.warning("preserving unfinished unverified staging state: %s", exc)


def _verify_cleanup_chain(
    stage: Path,
    directory: Path,
    directories: dict[Path, FileIdentity],
    roots: _InstallRoots,
) -> None:
    """Verify every retained ancestor identity from stage to ``directory``."""

    _verify_commit_roots(roots)
    current = stage
    _require_directory(current, "staging directory", directories[current])
    for component in directory.relative_to(stage).parts:
        current = _direct_child(current, component, "staging directory")
        expected = directories.get(current)
        if expected is None:
            raise ValueError("staging ancestor is absent from identity map")
        _require_directory(current, "staging directory", expected)


def _remove_stage_tree(
    directory: Path,
    stage: Path,
    directories: dict[Path, FileIdentity],
    files: dict[str, FileIdentity],
    roots: _InstallRoots,
) -> None:
    _verify_cleanup_chain(stage, directory, directories, roots)
    try:
        children = tuple(directory.iterdir())
    except OSError as exc:
        raise ValueError("cannot enumerate staging directory") from exc
    for child in children:
        _verify_cleanup_chain(stage, directory, directories, roots)
        child_identity, mode = _inspect_path(child, "staging path")
        if stat.S_ISDIR(mode):
            expected = directories.get(child)
            if expected != child_identity:
                raise ValueError("staging directory identity changed")
            _remove_stage_tree(child, stage, directories, files, roots)
        elif stat.S_ISREG(mode):
            relative = child.relative_to(stage).as_posix()
            expected = files.get(relative)
            if expected != child_identity:
                raise ValueError("staging file identity changed")
            _verify_cleanup_chain(stage, directory, directories, roots)
            _require_regular_file(child, expected, "staging file")
            _verify_cleanup_chain(stage, directory, directories, roots)
            child.unlink()
        else:
            raise ValueError("staging path is not a regular file")
    _verify_cleanup_chain(stage, directory, directories, roots)
    directory.rmdir()


def _move_no_replace(source: Path, destination: Path) -> None:
    """Move an endpoint only if destination is atomically absent on Windows."""

    if os.name != "nt":
        raise OSError("atomic no-replace move is unavailable on this platform")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.MoveFileExW.restype = ctypes.c_int
    ctypes.set_last_error(0)
    if kernel32.MoveFileExW(str(source), str(destination), _MOVEFILE_WRITE_THROUGH):
        return
    error = ctypes.get_last_error()
    if error in {_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
        raise FileExistsError(error, "destination already exists", str(destination))
    if _endpoint_identity(destination, "move destination") is not None:
        raise FileExistsError(error, "destination already exists", str(destination))
    raise OSError(error, "MoveFileExW failed", str(source), str(destination))


def _is_reserved_name(tool_name: str) -> bool:
    return tool_name.casefold() in {
        name.casefold() for name in _RESERVED_TOOL_NAMES | _BUILTIN_TOOL_NAMES
    }


def _direct_child(parent: Path, name: str, label: str) -> Path:
    if not name or Path(name).name != name:
        raise ValueError(f"invalid {label}")
    return _contained_path(parent, parent / name, label)


def _contained_path(parent: Path, child: Path, label: str) -> Path:
    try:
        child.relative_to(parent)
    except ValueError as exc:
        raise ValueError(f"{label} is outside its expected directory") from exc
    return child


def _path_exists(path: Path) -> bool:
    """Return endpoint existence from lstat; ambiguity and links fail closed."""

    return _endpoint_identity(path, "filesystem endpoint") is not None


def _endpoint_identity(path: Path, label: str) -> FileIdentity | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError(f"cannot determine {label} existence") from exc
    if stat.S_ISLNK(metadata.st_mode) or _has_reparse_attribute(path):
        raise ValueError(f"{label} is a link or reparse point")
    return _identity(metadata)


def _require_directory(path: Path, label: str, expected: FileIdentity | None = None) -> FileIdentity:
    identity, mode = _inspect_path(path, label)
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a real directory")
    if expected is not None and identity != expected:
        raise ValueError(f"{label} identity changed")
    return identity


def _require_regular_file(path: Path, expected: FileIdentity | None, label: str) -> FileIdentity:
    identity, mode = _inspect_path(path, label)
    try:
        nlink = path.stat(follow_symlinks=False).st_nlink
    except OSError as exc:
        raise ValueError(f"cannot inspect {label}") from exc
    if not stat.S_ISREG(mode) or nlink != 1:
        raise ValueError(f"{label} must be a single-link regular file")
    if expected is not None and identity != expected:
        raise ValueError(f"{label} identity changed")
    return identity


def _inspect_path(path: Path, label: str) -> tuple[FileIdentity, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or _has_reparse_attribute(path):
        raise ValueError(f"{label} is a link or reparse point")
    return _identity(metadata), metadata.st_mode


def _identity(metadata: os.stat_result) -> FileIdentity:
    return FileIdentity(device=metadata.st_dev, inode=metadata.st_ino)
