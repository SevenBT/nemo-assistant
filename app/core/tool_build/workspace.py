"""Isolated, fail-closed workspace for one generated tool build."""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import ntpath
import os
import posixpath
import re
import secrets
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import TOOL_BUILDS_DIR

_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FIXED_DIRECTORIES = ("input", "source", "logs", "reports")
_RESERVED_SOURCE_NAMES = frozenset({"manifest.json"})
_REPARSE_POINT = 0x400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileIdentity:
    """Stable identity snapshot for a filesystem object."""

    device: int
    inode: int


class SourceTraversalLimitExceeded(ValueError):
    """Raised when a bounded source traversal reaches a configured limit."""

    def __init__(self, limit: str) -> None:
        super().__init__(f"source traversal {limit} limit exceeded")
        self.limit = limit


@dataclass
class _SourceTraversalBudget:
    max_entries: int | None
    max_files: int | None
    max_directories: int | None
    max_depth: int | None
    entry_count: int = 0
    file_count: int = 0
    directory_count: int = 1

    def add_entry(self) -> None:
        self.entry_count += 1
        if self.max_entries is not None and self.entry_count > self.max_entries:
            raise SourceTraversalLimitExceeded("entry_count")

    def add_file(self) -> None:
        self.file_count += 1
        if self.max_files is not None and self.file_count > self.max_files:
            raise SourceTraversalLimitExceeded("file_count")

    def add_directory(self, depth: int) -> None:
        if self.max_depth is not None and depth > self.max_depth:
            raise SourceTraversalLimitExceeded("depth")
        self.directory_count += 1
        if self.max_directories is not None and self.directory_count > self.max_directories:
            raise SourceTraversalLimitExceeded("directory_count")


@dataclass(frozen=True)
class BuildWorkspace:
    """Filesystem locations and creation-time identities for one build."""

    build_id: str
    root: Path
    input_dir: Path
    source_dir: Path
    logs_dir: Path
    reports_dir: Path
    requirement_path: Path
    tool_spec_path: Path
    manifest_path: Path
    script_path: Path
    _builds_identity: FileIdentity
    _root_identity: FileIdentity
    _input_identity: FileIdentity
    _source_identity: FileIdentity
    _logs_identity: FileIdentity
    _reports_identity: FileIdentity

    @classmethod
    def create(
        cls, requirement: str, manifest_text: str, script_text: str
    ) -> "BuildWorkspace":
        """Create a new build directory and atomically stage its input files."""

        if not all(isinstance(value, str) for value in (requirement, manifest_text, script_text)):
            raise TypeError("requirement, manifest_text, and script_text must be strings")

        builds_dir = TOOL_BUILDS_DIR
        builds_dir.mkdir(parents=True, exist_ok=True)
        builds_identity = _require_directory(builds_dir, label="tool builds directory")
        build_id = secrets.token_urlsafe(18)
        root = _new_build_root(builds_dir, builds_identity, build_id)
        root_identity = _require_directory(root, label="workspace root")
        directories = {name: root / name for name in _FIXED_DIRECTORIES}

        try:
            for directory in directories.values():
                _require_directory(builds_dir, builds_identity, "tool builds directory")
                _validate_parent(builds_dir, root, root_identity)
                directory.mkdir(exist_ok=False)
            identities = {
                name: _require_directory(directory, label=f"workspace {name} directory")
                for name, directory in directories.items()
            }
            source_dir = directories["source"]
            script_path = _source_script_path(manifest_text, source_dir)
            script_parent_ids = (
                (builds_dir, builds_identity),
                (root, root_identity),
                *_create_source_parents(source_dir, identities["source"], script_path),
            )

            requirement_path = directories["input"] / "requirement.txt"
            tool_spec_path = directories["input"] / "tool-spec.json"
            manifest_path = source_dir / "manifest.json"
            _atomic_write(
                requirement_path,
                requirement,
                ((builds_dir, builds_identity), (root, root_identity), (directories["input"], identities["input"])),
            )
            _atomic_write(
                tool_spec_path,
                manifest_text,
                ((builds_dir, builds_identity), (root, root_identity), (directories["input"], identities["input"])),
            )
            _atomic_write(
                manifest_path,
                manifest_text,
                ((builds_dir, builds_identity), (root, root_identity), (source_dir, identities["source"])),
            )
            _atomic_write(
                script_path,
                script_text,
                script_parent_ids,
            )
        except Exception:
            _safe_cleanup_created_root(builds_dir, builds_identity, root, root_identity)
            raise

        return cls(
            build_id=build_id,
            root=root,
            input_dir=directories["input"],
            source_dir=source_dir,
            logs_dir=directories["logs"],
            reports_dir=directories["reports"],
            requirement_path=requirement_path,
            tool_spec_path=tool_spec_path,
            manifest_path=manifest_path,
            script_path=script_path,
            _builds_identity=builds_identity,
            _root_identity=root_identity,
            _input_identity=identities["input"],
            _source_identity=identities["source"],
            _logs_identity=identities["logs"],
            _reports_identity=identities["reports"],
        )

    def file_hashes(self) -> dict[str, str]:
        """Return source-relative POSIX SHA-256 digests for safe regular files."""

        hashes: dict[str, str] = {}
        for path, identity, parents in self._source_files():
            content = _read_bytes_checked(path, identity, parents)
            hashes[path.relative_to(self.source_dir).as_posix()] = hashlib.sha256(content).hexdigest()
        return hashes

    def read_source(self) -> dict[str, str]:
        """Read all safe source files as UTF-8, using relative POSIX keys."""

        source: dict[str, str] = {}
        for path, identity, parents in self._source_files():
            content = _read_bytes_checked(path, identity, parents)
            try:
                source[path.relative_to(self.source_dir).as_posix()] = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"source file is not valid UTF-8: {path}") from exc
        return source

    def cleanup(self) -> bool:
        """Delete only the unchanged directory tree created by this instance."""

        if not self.root.exists() and not self.root.is_symlink():
            return False
        fixed_identities = dict(self._workspace_directories())
        _remove_tree(
            self.root,
            self._root_identity,
            ((TOOL_BUILDS_DIR, self._builds_identity),),
            fixed_identities,
        )
        return True

    def _workspace_directories(self) -> tuple[tuple[Path, FileIdentity], ...]:
        """Verify every fixed directory before operating on the workspace."""

        _require_directory(TOOL_BUILDS_DIR, self._builds_identity, "tool builds directory")
        _validate_parent(TOOL_BUILDS_DIR, self.root, self._root_identity)
        directories = (
            (self.input_dir, self._input_identity, "workspace input directory"),
            (self.source_dir, self._source_identity, "workspace source directory"),
            (self.logs_dir, self._logs_identity, "workspace logs directory"),
            (self.reports_dir, self._reports_identity, "workspace reports directory"),
        )
        for path, identity, label in directories:
            _validate_parent(self.root, path, identity, label)
        return tuple((path, identity) for path, identity, _ in directories)

    def _source_files(
        self,
        *,
        max_entries: int | None = None,
        max_files: int | None = None,
        max_directories: int | None = None,
        max_depth: int | None = None,
    ) -> Iterator[tuple[Path, FileIdentity, tuple[tuple[Path, FileIdentity], ...]]]:
        self._workspace_directories()
        source_parents = (
            (TOOL_BUILDS_DIR, self._builds_identity),
            (self.root, self._root_identity),
            (self.source_dir, self._source_identity),
        )
        budget = _SourceTraversalBudget(
            max_entries, max_files, max_directories, max_depth
        )
        yield from _walk_source(self.source_dir, self._source_identity, source_parents, budget, 0)


def _new_build_root(builds_dir: Path, builds_identity: FileIdentity, build_id: str) -> Path:
    if not _BUILD_ID_RE.fullmatch(build_id):
        raise ValueError("invalid generated build id")
    root = builds_dir / build_id
    _require_direct_child(builds_dir, root, "workspace root")
    _require_directory(builds_dir, builds_identity, "tool builds directory")
    root.mkdir(exist_ok=False)
    return root


def _source_script_path(manifest_text: str, source_dir: Path) -> Path:
    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise ValueError("manifest JSON is invalid") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("script"), str):
        raise ValueError("manifest script must be a string")

    script = manifest["script"]
    if not script.strip() or ":" in script:
        raise ValueError("manifest script must be a relative non-ADS path")
    drive, _ = ntpath.splitdrive(script)
    if drive or posixpath.isabs(script) or ntpath.isabs(script):
        raise ValueError("manifest script must be a relative path")

    parts = tuple(part for part in re.split(r"[/\\]", script) if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise ValueError("manifest script cannot contain parent traversal")
    candidate = source_dir.joinpath(*parts)
    _require_contained_path(source_dir, candidate, "manifest script")
    normalized = candidate.relative_to(source_dir).as_posix().casefold()
    if normalized in _RESERVED_SOURCE_NAMES:
        raise ValueError("manifest script conflicts with reserved manifest.json")
    return candidate


def _create_source_parents(
    source_dir: Path, source_identity: FileIdentity, script_path: Path
) -> tuple[tuple[Path, FileIdentity], ...]:
    _require_directory(source_dir, source_identity, "workspace source directory")
    parent = script_path.parent
    relative_parents = parent.relative_to(source_dir).parts
    current = source_dir
    identities: list[tuple[Path, FileIdentity]] = [(source_dir, source_identity)]
    for name in relative_parents:
        _require_directory(current, identities[-1][1], "source parent directory")
        next_path = current / name
        _require_contained_path(source_dir, next_path, "manifest script")
        next_path.mkdir(exist_ok=True)
        next_identity = _require_directory(next_path, label="source parent directory")
        identities.append((next_path, next_identity))
        current = next_path
    return tuple(identities)


def _walk_source(
    directory: Path,
    identity: FileIdentity,
    parents: tuple[tuple[Path, FileIdentity], ...],
    budget: _SourceTraversalBudget,
    depth: int,
) -> Iterator[tuple[Path, FileIdentity, tuple[tuple[Path, FileIdentity], ...]]]:
    _validate_directories(parents)
    _require_directory(directory, identity, "source directory")
    try:
        with os.scandir(directory) as children:
            for entry in children:
                budget.add_entry()
                _validate_directories(parents)
                child = Path(entry.path)
                child_identity, mode = _inspect_path(child, label="source path")
                if stat.S_ISDIR(mode):
                    budget.add_directory(depth + 1)
                    child_parents = (*parents, (child, child_identity))
                    yield from _walk_source(
                        child, child_identity, child_parents, budget, depth + 1
                    )
                elif stat.S_ISREG(mode):
                    budget.add_file()
                    _require_single_link(child, label="source file")
                    yield child, child_identity, parents
                else:
                    raise ValueError(f"source path is not a regular file: {child}")
    except OSError as exc:
        raise ValueError(f"cannot enumerate source directory: {directory}") from exc


def _read_bytes_checked(
    path: Path,
    identity: FileIdentity,
    parents: tuple[tuple[Path, FileIdentity], ...],
) -> bytes:
    _validate_directories(parents)
    _require_regular_file(path, identity, "source file")
    try:
        with path.open("rb") as stream:
            opened_metadata = os.fstat(stream.fileno())
            opened = _identity_from_stat(opened_metadata)
            if opened != identity:
                raise ValueError(f"source file identity changed before read: {path}")
            if opened_metadata.st_nlink != 1:
                raise ValueError(f"source file is a hard link: {path}")
            content = stream.read()
        _validate_directories(parents)
        _require_regular_file(path, identity, "source file")
        return content
    except OSError as exc:
        raise ValueError(f"cannot read source file: {path}") from exc


def _atomic_write(
    path: Path,
    text: str,
    parent_chain: tuple[tuple[Path, FileIdentity], ...],
) -> None:
    _validate_directories(parent_chain)
    parent = path.parent
    parent_identity = parent_chain[-1][1]
    _require_directory(parent, parent_identity, "write parent directory")
    _require_contained_path(parent, path, "write path")
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite existing path: {path}")

    temporary: Path | None = None
    temporary_identity: FileIdentity | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_identity, temporary_mode = _inspect_path(
            temporary, label="atomic write temporary file"
        )
        if not stat.S_ISREG(temporary_mode):
            raise ValueError(f"atomic write temporary file must be regular: {temporary}")
        _require_single_link(temporary, label="atomic write temporary file")
        _validate_directories(parent_chain)
        _require_directory(parent, parent_identity, "write parent directory")
        os.replace(temporary, path)
    except OSError:
        if temporary is not None and temporary_identity is not None:
            _cleanup_verified_temporary(temporary, temporary_identity, parent_chain)
        raise


def _cleanup_verified_temporary(
    temporary: Path,
    identity: FileIdentity,
    parent_chain: tuple[tuple[Path, FileIdentity], ...],
) -> None:
    """Remove a failed atomic-write temporary file only if identity is unchanged."""

    try:
        _validate_directories(parent_chain)
        _require_regular_file(temporary, identity, "atomic write temporary file")
        _validate_directories(parent_chain)
        _require_regular_file(temporary, identity, "atomic write temporary file")
        temporary.unlink()
    except (OSError, ValueError) as exc:
        _LOGGER.warning(
            "preserving unverified atomic-write temporary file %s: %s", temporary, exc
        )

def _remove_tree(
    directory: Path,
    identity: FileIdentity,
    parents: tuple[tuple[Path, FileIdentity], ...],
    expected_directories: Mapping[Path, FileIdentity],
) -> None:
    _validate_directories(parents)
    _require_directory(directory, identity, "workspace directory")
    try:
        children = tuple(directory.iterdir())
    except OSError as exc:
        raise ValueError(f"cannot enumerate workspace directory: {directory}") from exc

    for child in children:
        _validate_directories(parents)
        child_identity, mode = _inspect_path(child, label="workspace path")
        expected_identity = expected_directories.get(child)
        if expected_identity is not None and child_identity != expected_identity:
            raise ValueError(f"workspace directory identity changed: {child}")
        _validate_directories((*parents, (directory, identity)))
        if stat.S_ISDIR(mode):
            _remove_tree(
                child,
                child_identity,
                (*parents, (directory, identity)),
                expected_directories,
            )
        elif stat.S_ISREG(mode):
            _require_single_link(child, label="workspace file")
            _validate_directories(parents)
            _require_regular_file(child, child_identity, "workspace file")
            child.unlink()
        else:
            raise ValueError(f"workspace path is not a regular file: {child}")

    _validate_directories(parents)
    _require_directory(directory, identity, "workspace directory")
    directory.rmdir()


def _safe_cleanup_created_root(
    builds_dir: Path,
    builds_identity: FileIdentity,
    root: Path,
    root_identity: FileIdentity,
) -> None:
    """Best-effort cleanup that refuses any changed or untrusted directory."""

    try:
        if root.exists() and _require_directory(builds_dir, builds_identity, "tool builds directory"):
            _remove_tree(root, root_identity, ((builds_dir, builds_identity),), {})
    except (OSError, ValueError) as exc:
        _LOGGER.warning("preserving workspace after failed creation cleanup %s: %s", root, exc)


def _validate_directories(paths: tuple[tuple[Path, FileIdentity], ...]) -> None:
    for path, identity in paths:
        _require_directory(path, identity, "workspace directory")


def _validate_parent(
    parent: Path,
    child: Path,
    child_identity: FileIdentity,
    label: str = "workspace directory",
) -> None:
    _require_direct_child(parent, child, label)
    _require_directory(child, child_identity, label)


def _require_direct_child(parent: Path, child: Path, label: str) -> None:
    if child.parent != parent:
        raise ValueError(f"{label} is not a direct child of its expected parent")
    _require_contained_path(parent, child, label)


def _require_contained_path(parent: Path, child: Path, label: str) -> None:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} is outside its expected directory") from exc


def _require_directory(
    path: Path,
    expected: FileIdentity | None = None,
    label: str = "directory",
) -> FileIdentity:
    identity, mode = _inspect_path(path, label=label)
    if not stat.S_ISDIR(mode):
        raise ValueError(f"{label} must be a real directory: {path}")
    if expected is not None and identity != expected:
        raise ValueError(f"{label} identity changed: {path}")
    return identity


def _require_regular_file(path: Path, expected: FileIdentity, label: str) -> None:
    identity, mode = _inspect_path(path, label=label)
    if not stat.S_ISREG(mode):
        raise ValueError(f"{label} must be a regular file: {path}")
    if identity != expected:
        raise ValueError(f"{label} identity changed: {path}")
    _require_single_link(path, label=label)


def _require_single_link(path: Path, label: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"cannot inspect {label}: {path}") from exc
    if metadata.st_nlink != 1:
        raise ValueError(f"{label} is a hard link: {path}")


def _inspect_path(path: Path, *, label: str) -> tuple[FileIdentity, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect {label}: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or _has_reparse_attribute(path):
        raise ValueError(f"{label} is a link or reparse point: {path}")
    return _identity_from_stat(metadata), metadata.st_mode


def _identity_from_stat(metadata: os.stat_result) -> FileIdentity:
    return FileIdentity(device=metadata.st_dev, inode=metadata.st_ino)


def _has_reparse_attribute(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        attributes = _get_windows_file_attributes(path)
    except (AttributeError, OSError) as exc:
        raise ValueError(f"cannot verify Windows reparse attributes: {path}") from exc
    if attributes == _INVALID_FILE_ATTRIBUTES:
        raise ValueError(f"cannot verify Windows reparse attributes: {path}")
    return bool(attributes & _REPARSE_POINT)


def _get_windows_file_attributes(path: Path) -> int:
    kernel32 = ctypes.windll.kernel32
    kernel32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetFileAttributesW.restype = ctypes.c_uint32
    return int(kernel32.GetFileAttributesW(str(path)))
