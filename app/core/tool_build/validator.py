"""Deterministic, non-executing validation for staged generated tools."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .manifest import (
    MAX_MANIFEST_JSON_DEPTH,
    MAX_MANIFEST_JSON_NODES,
    parse_manifest_text,
)
from .models import (
    BuildStatus,
    IssueSeverity,
    ToolManifest,
    ToolPermission,
    ValidationIssue,
    ValidationReport,
)
from .workspace import BuildWorkspace, FileIdentity, SourceTraversalLimitExceeded

_MAX_SOURCE_FILE_BYTES = 1_048_576
_MAX_SOURCE_FILES = 16
_MAX_SOURCE_DIRECTORIES = 16
_MAX_SOURCE_DEPTH = 4
_MAX_SOURCE_TOTAL_BYTES = 2_097_152
_MAX_SOURCE_ENTRIES = 32
_MAX_ISSUES = 100
_MANIFEST_PATH = "manifest.json"
# Bound only guards the parser against pathological input; capability analysis
# is intentionally not performed (validation checks syntax/format/deps only).
_MAX_AST_NODES = 10_000


class _AnalysisLimit(RuntimeError):
    """Python source exceeds the bounded parse limit."""


@dataclass
class _Findings:
    """Bounded internal accumulation of validation findings."""

    issues: list[ValidationIssue] = field(default_factory=list)
    is_limited: bool = False

    def add(self, code: str, severity: IssueSeverity, message: str) -> None:
        if self.is_limited:
            return
        if len(self.issues) >= _MAX_ISSUES - 1:
            self.issues.append(
                ValidationIssue(
                    code="ISSUE_LIMIT_EXCEEDED",
                    severity=IssueSeverity.BLOCK,
                    message="Validation stopped after reaching the issue limit.",
                )
            )
            self.is_limited = True
            return
        self.issues.append(ValidationIssue(code=code, severity=severity, message=message))


def validate_workspace(
    workspace: BuildWorkspace, *, approved_permissions: frozenset[ToolPermission]
) -> ValidationReport:
    """Validate a staged workspace without executing its generated code.

    The workspace is not a sandbox. This function independently re-reads its
    checked source tree and deliberately ignores every file in ``reports``.
    """

    _validate_approved_permissions(approved_permissions)
    findings = _Findings()
    source = _read_workspace_source(workspace, findings)
    file_hashes = _hash_source(source)
    manifest = _load_strict_manifest(source, findings)

    if manifest is None:
        return _make_report(workspace, None, frozenset(), (), file_hashes, findings)

    script_path = _safe_script_path(manifest.script)
    if script_path is None:
        findings.add(
            "ENTRYPOINT_OUTSIDE_SOURCE",
            IssueSeverity.BLOCK,
            "The declared entrypoint is outside the source tree.",
        )
        return _make_report(
            workspace, manifest, frozenset(), manifest.dependencies, file_hashes, findings
        )

    _validate_source_layout(source, script_path, findings)
    script = source.get(script_path)
    if script is None:
        findings.add(
            "ENTRYPOINT_MISSING",
            IssueSeverity.BLOCK,
            "The declared entrypoint is missing from the source tree.",
        )
        return _make_report(
            workspace, manifest, frozenset(), manifest.dependencies, file_hashes, findings
        )

    if not script_path.endswith(".py"):
        findings.add(
            "ENTRYPOINT_TYPE_INVALID",
            IssueSeverity.BLOCK,
            "The declared entrypoint must be a Python source file.",
        )
        return _make_report(
            workspace, manifest, frozenset(), manifest.dependencies, file_hashes, findings
        )

    _inspect_python(script, findings)
    return _make_report(
        workspace, manifest, frozenset(), manifest.dependencies, file_hashes, findings
    )


def _validate_approved_permissions(approved_permissions: frozenset[ToolPermission]) -> None:
    if not isinstance(approved_permissions, frozenset):
        raise TypeError("approved_permissions must be a frozenset of ToolPermission values")
    if not all(isinstance(permission, ToolPermission) for permission in approved_permissions):
        raise TypeError("approved_permissions must contain ToolPermission values")


def _read_workspace_source(
    workspace: BuildWorkspace, findings: _Findings
) -> dict[str, str]:
    try:
        entries: list[tuple[Path, FileIdentity]] = []
        for path, identity, _ in workspace._source_files(
            max_entries=_MAX_SOURCE_ENTRIES,
            max_files=_MAX_SOURCE_FILES,
            max_directories=_MAX_SOURCE_DIRECTORIES,
            max_depth=_MAX_SOURCE_DEPTH,
        ):
            entries.append((path, identity))

        total_bytes = 0
        for path, identity in entries:
            metadata = path.stat(follow_symlinks=False)
            if metadata.st_dev != identity.device or metadata.st_ino != identity.inode:
                raise ValueError("source file identity changed before validation")
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("source file is not a safe regular file")
            if metadata.st_size > _MAX_SOURCE_FILE_BYTES:
                findings.add(
                    "SOURCE_FILE_TOO_LARGE",
                    IssueSeverity.BLOCK,
                    "A source file exceeds the validation size limit.",
                )
                return {}
            total_bytes += metadata.st_size
            if total_bytes > _MAX_SOURCE_TOTAL_BYTES:
                findings.add(
                    "SOURCE_TOTAL_SIZE_LIMIT",
                    IssueSeverity.BLOCK,
                    "The source tree exceeds the validation total-size limit.",
                )
                return {}

        return {
            path.relative_to(workspace.source_dir).as_posix(): _read_checked_utf8(
                path, identity
            )
            for path, identity in entries
        }
    except SourceTraversalLimitExceeded as exc:
        limit_codes = {
            "entry_count": "SOURCE_ENTRY_COUNT_LIMIT",
            "file_count": "SOURCE_FILE_COUNT_LIMIT",
            "directory_count": "SOURCE_DIRECTORY_COUNT_LIMIT",
            "depth": "SOURCE_DEPTH_LIMIT",
        }
        findings.add(
            limit_codes.get(exc.limit, "SOURCE_TRAVERSAL_LIMIT"),
            IssueSeverity.BLOCK,
            "The source tree exceeds a validation traversal limit.",
        )
        return {}
    except (MemoryError, OSError, UnicodeDecodeError, ValueError):
        findings.add(
            "SOURCE_TREE_INVALID",
            IssueSeverity.BLOCK,
            "The source tree could not be safely read.",
        )
        return {}


def _read_checked_utf8(path: Path, identity: FileIdentity) -> str:
    """Read a pre-sized source file while rechecking its opened identity."""

    with path.open("rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (
            metadata.st_dev != identity.device
            or metadata.st_ino != identity.inode
            or metadata.st_nlink != 1
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _MAX_SOURCE_FILE_BYTES
        ):
            raise ValueError("source file changed during validation")
        content = stream.read(_MAX_SOURCE_FILE_BYTES + 1)
    if len(content) > _MAX_SOURCE_FILE_BYTES:
        raise ValueError("source file exceeded validation limit during read")
    return content.decode("utf-8")


def _hash_source(source: dict[str, str]) -> dict[str, str]:
    return {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in source.items()
    }


def _load_strict_manifest(
    source: dict[str, str], findings: _Findings
) -> ToolManifest | None:
    text = source.get(_MANIFEST_PATH)
    if text is None:
        findings.add(
            "MANIFEST_MISSING", IssueSeverity.BLOCK, "The source manifest is missing."
        )
        return None
    try:
        raw_manifest = json.loads(text)
        _validate_json_depth(raw_manifest)
    except (json.JSONDecodeError, ValueError, OverflowError):
        findings.add(
            "MANIFEST_JSON_INVALID",
            IssueSeverity.BLOCK,
            "The source manifest is not valid JSON.",
        )
        return None
    except (MemoryError, RecursionError):
        findings.add(
            "MANIFEST_COMPLEXITY_LIMIT",
            IssueSeverity.BLOCK,
            "The source manifest exceeds the validation complexity limit.",
        )
        return None

    dependencies = _raw_dependencies(raw_manifest)
    if dependencies:
        findings.add(
            "DEPENDENCIES_UNSUPPORTED",
            IssueSeverity.BLOCK,
            "Dependencies are not supported during deterministic validation.",
        )
    try:
        return parse_manifest_text(text, mode="strict")
    except (MemoryError, RecursionError):
        findings.add(
            "MANIFEST_COMPLEXITY_LIMIT",
            IssueSeverity.BLOCK,
            "The source manifest exceeds the validation complexity limit.",
        )
        return None
    except ValueError:
        findings.add(
            "MANIFEST_INVALID",
            IssueSeverity.BLOCK,
            "The source manifest does not meet strict v1 requirements.",
        )
        return None


def _validate_json_depth(
    value: object, *, max_depth: int = MAX_MANIFEST_JSON_DEPTH
) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    steps = 0
    while pending:
        current, depth = pending.pop()
        steps += 1
        if steps > MAX_MANIFEST_JSON_NODES or depth > max_depth:
            raise RecursionError
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)


def _raw_dependencies(raw_manifest: object) -> tuple[str, ...]:
    if not isinstance(raw_manifest, dict):
        return ()
    dependencies = raw_manifest.get("dependencies")
    if not isinstance(dependencies, list):
        return ()
    return tuple(item for item in dependencies if isinstance(item, str))


def _validate_source_layout(
    source: dict[str, str], entrypoint: str, findings: _Findings
) -> None:
    allowed = {_MANIFEST_PATH, entrypoint}
    for path in source:
        if path not in allowed:
            findings.add(
                "SOURCE_FILE_UNSUPPORTED",
                IssueSeverity.BLOCK,
                "The source tree contains an unsupported file.",
            )


def _safe_script_path(script: str) -> str | None:
    normalized = script.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        return None
    return path.as_posix()


def _inspect_python(script: str, findings: _Findings) -> None:
    """Confirm the entrypoint parses as Python. No capability analysis is done."""

    if len(script.encode("utf-8")) > _MAX_SOURCE_FILE_BYTES:
        return
    try:
        tree = ast.parse(script)
        if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
            raise _AnalysisLimit
    except (MemoryError, RecursionError, _AnalysisLimit):
        findings.add(
            "AST_COMPLEXITY_LIMIT",
            IssueSeverity.BLOCK,
            "Python source exceeds the validation complexity limit.",
        )
        return
    except SyntaxError:
        findings.add(
            "PYTHON_SYNTAX_INVALID",
            IssueSeverity.BLOCK,
            "The entrypoint is not valid Python syntax.",
        )


def _make_report(
    workspace: BuildWorkspace,
    manifest: ToolManifest | None,
    detected: frozenset[ToolPermission],
    dependencies: Iterable[str],
    file_hashes: dict[str, str],
    findings: _Findings,
) -> ValidationReport:
    issues = tuple(findings.issues)
    status = (
        BuildStatus.INSTALL_REVIEW
        if ValidationReport.is_installable_for(issues)
        else BuildStatus.VALIDATION_FAILED
    )
    return ValidationReport(
        build_id=workspace.build_id,
        status=status,
        declared_permissions=manifest.permissions if manifest is not None else frozenset(),
        detected_permissions=detected,
        dependencies=tuple(dependencies),
        file_hashes=file_hashes,
        issues=issues,
    )
