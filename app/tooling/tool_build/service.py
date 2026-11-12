"""Safe orchestration of the staged strict tool-build lifecycle."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path

from . import installer as installer_module
from . import workspace as workspace_module
from .installer import install_verified_build
from .manifest import parse_manifest_text, validate_manifest_text_budget
from .models import (
    NON_OVERRIDABLE_ISSUE_CODES,
    BuildReview,
    BuildStatus,
    InstallResult,
    IssueSeverity,
    ToolPermission,
    ValidationReport,
)
from .validator import validate_workspace
from .workspace import BuildWorkspace, FileIdentity

_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FIXED_DIRECTORIES = ("input", "source", "logs", "reports")
_LOGGER = logging.getLogger(__name__)


class ToolBuildService:
    """Stage, review, and install strict generated tools without executing them."""

    def __init__(self) -> None:
        self._workspaces: dict[str, BuildWorkspace] = {}
        self._review_baselines: dict[
            tuple[str, frozenset[ToolPermission], frozenset[str]], ValidationReport
        ] = {}

    def stage(
        self, requirement: str, manifest_text: str, script_text: str
    ) -> BuildReview:
        """Strictly parse, stage, and validate input without touching user tools.

        A staged result is informative only. A caller must explicitly invoke
        ``review`` before installation so the displayed baseline has current
        approval semantics and an install-review report.
        """

        validate_manifest_text_budget(manifest_text)
        manifest = parse_manifest_text(manifest_text, mode="strict")
        workspace = BuildWorkspace.create(requirement, manifest_text, script_text)
        self._workspaces[workspace.build_id] = workspace
        report = validate_workspace(workspace, approved_permissions=frozenset())
        staged_report = replace(report, status=BuildStatus.STAGED)
        return BuildReview(workspace.build_id, manifest, script_text, staged_report)

    def review(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> BuildReview:
        """Return one bounded source snapshot and store it as a review baseline.

        A build whose only blocking findings are risk-acknowledgeable still
        exposes its real manifest and script so the user can inspect exactly
        what they are choosing to install. A build with any non-overridable
        block yields a bounded placeholder and is never installable.
        """

        _validate_build_id(build_id)
        if not _valid_approvals(approved_permissions) or not _valid_overrides(
            acknowledged_overrides
        ):
            raise ValueError("INVALID_INPUT")
        try:
            workspace = self.workspace_for(build_id)
            report = validate_workspace(workspace, approved_permissions=approved_permissions)
            if _has_non_overridable_block(report):
                review = self._invalid_review(workspace, report)
                self._store_baseline(build_id, approved_permissions, acknowledged_overrides, report)
                return review
            snapshot = installer_module._capture_source_snapshot(
                workspace, frozenset(report.file_hashes)
            )
            if snapshot.hashes != dict(report.file_hashes):
                raise _WorkspaceChangedError
            manifest = parse_manifest_text(snapshot.text("manifest.json"), mode="strict")
            script_text = snapshot.text(manifest.script.replace("\\", "/"))
        except _WorkspaceChangedError:
            raise ValueError("STALE_VALIDATION") from None
        except (KeyError, MemoryError, OSError, UnicodeDecodeError, ValueError) as exc:
            if "report" in locals() and not _has_non_overridable_block(report):
                _LOGGER.warning("tool build snapshot changed for build_id=%s", build_id, exc_info=True)
                raise ValueError("STALE_VALIDATION") from None
            _LOGGER.warning("tool build review failed for build_id=%s", build_id, exc_info=True)
            raise ValueError("VALIDATION_FAILED") from None

        review = BuildReview(workspace.build_id, manifest, script_text, report)
        self._store_baseline(build_id, approved_permissions, acknowledged_overrides, report)
        return review

    def _store_baseline(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        acknowledged_overrides: frozenset[str],
        report: ValidationReport,
    ) -> None:
        self._review_baselines[
            (build_id, approved_permissions, acknowledged_overrides)
        ] = report

    @staticmethod
    def _invalid_review(workspace: BuildWorkspace, report: ValidationReport) -> BuildReview:
        """Return a bounded, non-installable review without reading untrusted source."""

        manifest = parse_manifest_text(
            '{"manifest_version":1,"name":"invalid","description":"invalid",'
            '"script":"tool.py","parameters":{},"output":{},'
            '"permissions":[],"dependencies":[]}',
            mode="strict",
        )
        return BuildReview(workspace.build_id, manifest, "", report)

    def install(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        overwrite: bool,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> InstallResult:
        """Install only the exact baseline previously shown to the caller.

        ``acknowledged_overrides`` is part of the review identity: the user must
        have reviewed the build under the same acknowledgements, so a mismatch
        requires a fresh review rather than silently installing.
        """

        if not _is_valid_build_id(build_id):
            return InstallResult(False, "", "WORKSPACE_INVALID")
        if (
            not _valid_approvals(approved_permissions)
            or not isinstance(overwrite, bool)
            or not _valid_overrides(acknowledged_overrides)
        ):
            return InstallResult(False, "", "INVALID_INPUT")
        baseline = self._review_baselines.get(
            (build_id, approved_permissions, acknowledged_overrides)
        )
        if baseline is None:
            return InstallResult(False, "", "REVIEW_REQUIRED")
        try:
            workspace = self.workspace_for(build_id)
            fresh_report = validate_workspace(
                workspace, approved_permissions=approved_permissions
            )
            if not fresh_report.is_installable_with(acknowledged_overrides):
                return InstallResult(False, "", "VALIDATION_FAILED")
            snapshot = installer_module._capture_source_snapshot(
                workspace, frozenset(fresh_report.file_hashes)
            )
            if (
                snapshot.hashes != dict(fresh_report.file_hashes)
                or not installer_module._reports_match(baseline, fresh_report)
            ):
                return InstallResult(False, "", "STALE_VALIDATION")
            return install_verified_build(
                workspace,
                baseline,
                approved_permissions=approved_permissions,
                overwrite=overwrite,
                acknowledged_overrides=acknowledged_overrides,
            )
        except (MemoryError, OSError, UnicodeDecodeError, ValueError):
            _LOGGER.warning("tool build install failed for build_id=%s", build_id, exc_info=True)
            return InstallResult(False, "", "VALIDATION_FAILED")

    def workspace_for(self, build_id: str) -> BuildWorkspace:
        """Return one identity-checked workspace, recovering only a safe direct child."""

        _validate_build_id(build_id)
        workspace = self._workspaces.get(build_id)
        try:
            if workspace is not None:
                workspace._workspace_directories()
                return workspace
            recovered = _recover_workspace(build_id)
        except (MemoryError, OSError, ValueError):
            _LOGGER.warning("tool build workspace lookup failed for build_id=%s", build_id, exc_info=True)
            raise ValueError("WORKSPACE_INVALID") from None
        self._workspaces[build_id] = recovered
        return recovered


def _is_valid_build_id(build_id: object) -> bool:
    return (
        isinstance(build_id, str)
        and 1 <= len(build_id) <= 64
        and _BUILD_ID_RE.fullmatch(build_id) is not None
    )


def _validate_build_id(build_id: object) -> None:
    if not _is_valid_build_id(build_id):
        raise ValueError("WORKSPACE_INVALID")


def _valid_approvals(approved_permissions: object) -> bool:
    return isinstance(approved_permissions, frozenset) and all(
        isinstance(permission, ToolPermission) for permission in approved_permissions
    )


def _valid_overrides(acknowledged_overrides: object) -> bool:
    return isinstance(acknowledged_overrides, frozenset) and all(
        isinstance(code, str) for code in acknowledged_overrides
    )


def _has_non_overridable_block(report: ValidationReport) -> bool:
    """Return whether any blocking finding can never be acknowledged away."""

    return any(
        issue.severity is IssueSeverity.BLOCK
        and issue.code in NON_OVERRIDABLE_ISSUE_CODES
        for issue in report.issues
    )


class _WorkspaceChangedError(ValueError):
    """The validated and captured source snapshots differ."""


def _recover_workspace(build_id: str) -> BuildWorkspace:
    """Recover a workspace from its fixed layout after process restart.

    Every recovered endpoint is required to be a real direct child with a fresh
    identity snapshot. Source validation then checks every source descendant.
    """

    builds_dir = workspace_module.TOOL_BUILDS_DIR
    try:
        builds_dir.lstat()
        (builds_dir / build_id).lstat()
    except FileNotFoundError as exc:
        raise ValueError("unknown build identifier") from exc
    builds_identity = workspace_module._require_directory(
        builds_dir, label="tool builds directory"
    )
    root = builds_dir / build_id
    workspace_module._require_direct_child(builds_dir, root, "workspace root")
    root_identity = workspace_module._require_directory(root, label="workspace root")
    directories: dict[str, tuple[Path, FileIdentity]] = {}
    for name in _FIXED_DIRECTORIES:
        directory = root / name
        workspace_module._require_direct_child(root, directory, f"workspace {name} directory")
        directories[name] = (
            directory,
            workspace_module._require_directory(
                directory, label=f"workspace {name} directory"
            ),
        )

    input_dir, input_identity = directories["input"]
    source_dir, source_identity = directories["source"]
    logs_dir, logs_identity = directories["logs"]
    reports_dir, reports_identity = directories["reports"]
    requirement_path = input_dir / "requirement.txt"
    tool_spec_path = input_dir / "tool-spec.json"
    manifest_path = source_dir / "manifest.json"

    # Recovery intentionally does not inspect input or source files. The validator owns
    # bounded parsing and source traversal, so a damaged source remains a
    # structured validation result rather than a recovery-time path error.
    script_path = source_dir / "tool.py"

    return BuildWorkspace(
        build_id=build_id,
        root=root,
        input_dir=input_dir,
        source_dir=source_dir,
        logs_dir=logs_dir,
        reports_dir=reports_dir,
        requirement_path=requirement_path,
        tool_spec_path=tool_spec_path,
        manifest_path=manifest_path,
        script_path=script_path,
        _builds_identity=builds_identity,
        _root_identity=root_identity,
        _input_identity=input_identity,
        _source_identity=source_identity,
        _logs_identity=logs_identity,
        _reports_identity=reports_identity,
    )
