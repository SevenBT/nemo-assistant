from dataclasses import FrozenInstanceError

import pytest

import app.core.tool_build as tool_build
from app.core.tool_build.models import (
    BuildReview,
    BuildStatus,
    InstallResult,
    IssueSeverity,
    ToolManifest,
    ToolPermission,
    ValidationIssue,
    ValidationReport,
)


EXPECTED_PUBLIC_TYPES = {
    "BuildReview",
    "BuildStatus",
    "InstallResult",
    "IssueSeverity",
    "ToolBuildService",
    "ToolManifest",
    "ToolPermission",
    "ValidationIssue",
    "ValidationReport",
}

EXPECTED_PUBLIC_CONSTANTS = {
    "NON_OVERRIDABLE_ISSUE_CODES",
}


def make_manifest(**overrides):
    values = {
        "manifest_version": 1,
        "name": "csv_summary",
        "description": "Summarize CSV data",
        "script": "tool.py",
        "version": "1.0.0",
        "author": "Nemo",
        "parameters": {"path": {"type": "string", "required": True}},
        "output": {"type": "object"},
        "permissions": frozenset({ToolPermission.FILE_READ}),
        "dependencies": (),
        "retry_safe": True,
        "is_legacy": False,
    }
    values.update(overrides)
    return ToolManifest(**values)


def make_report(**overrides):
    values = {
        "build_id": "b1",
        "status": BuildStatus.VALIDATING,
        "declared_permissions": frozenset(),
        "detected_permissions": frozenset(),
        "dependencies": (),
        "file_hashes": {},
        "issues": (),
    }
    values.update(overrides)
    return ValidationReport(**values)


def test_permission_values_are_exact_and_stable():
    assert [(permission.name, permission.value) for permission in ToolPermission] == [
        ("FILE_READ", "file_read"),
        ("FILE_WRITE", "file_write"),
        ("NETWORK", "network"),
        ("CLIPBOARD_READ", "clipboard_read"),
        ("CLIPBOARD_WRITE", "clipboard_write"),
        ("SHELL", "shell"),
        ("PYTHON_SUBPROCESS", "python_subprocess"),
        ("PROCESS_SPAWN", "process_spawn"),
    ]


def test_public_model_enums_expose_expected_values():
    assert [status.value for status in BuildStatus] == [
        "staged",
        "validating",
        "validation_failed",
        "install_review",
        "installed",
        "install_failed",
        "cancelled",
        "abandoned",
    ]
    assert IssueSeverity.WARNING.value == "warning"
    assert IssueSeverity.BLOCK.value == "block"


def test_tool_manifest_exposes_all_downstream_fields():
    manifest = make_manifest()

    assert manifest.manifest_version == 1
    assert manifest.name == "csv_summary"
    assert manifest.description == "Summarize CSV data"
    assert manifest.script == "tool.py"
    assert manifest.version == "1.0.0"
    assert manifest.author == "Nemo"
    assert manifest.parameters["path"]["type"] == "string"
    assert manifest.output["type"] == "object"
    assert manifest.permissions == frozenset({ToolPermission.FILE_READ})
    assert manifest.dependencies == ()
    assert manifest.retry_safe is True
    assert manifest.is_legacy is False


def test_manifest_takes_recursive_immutable_snapshot_of_mutable_input():
    parameters = {
        "path": {
            "type": "array",
            "items": [{"type": "string"}],
        }
    }
    output = {"type": "object", "required": ["count"]}
    permissions = [ToolPermission.FILE_READ]
    dependencies = ["example==1.0"]

    manifest = make_manifest(
        parameters=parameters,
        output=output,
        permissions=permissions,
        dependencies=dependencies,
    )
    parameters["path"]["type"] = "integer"
    parameters["path"]["items"][0]["type"] = "number"
    output["required"].append("extra")
    permissions.append(ToolPermission.NETWORK)
    dependencies.append("other==1.0")

    assert manifest.parameters["path"]["type"] == "array"
    assert manifest.parameters["path"]["items"][0]["type"] == "string"
    assert manifest.output["required"] == ("count",)
    assert manifest.permissions == frozenset({ToolPermission.FILE_READ})
    assert manifest.dependencies == ("example==1.0",)
    with pytest.raises(TypeError):
        manifest.parameters["path"]["type"] = "boolean"
    with pytest.raises(TypeError):
        manifest.parameters["path"]["items"][0]["type"] = "boolean"


def test_validation_report_is_installable_only_without_blocking_issue():
    warning = ValidationIssue("WARN", IssueSeverity.WARNING, "warning")
    blocking = ValidationIssue("BLOCK", IssueSeverity.BLOCK, "blocked")

    assert make_report(issues=[warning]).is_installable is True
    assert make_report(issues=[warning, blocking]).is_installable is False
    assert ValidationReport.is_installable_for((warning,)) is True
    assert ValidationReport.is_installable_for((blocking,)) is False


def test_non_overridable_issue_codes_cover_unrunnable_and_unsafe_findings():
    from app.core.tool_build.models import NON_OVERRIDABLE_ISSUE_CODES

    assert isinstance(NON_OVERRIDABLE_ISSUE_CODES, frozenset)
    # Findings whose tool could never load or run, plus installer-fatal states.
    for code in (
        "DEPENDENCIES_UNSUPPORTED",
        "PYTHON_SYNTAX_INVALID",
        "MANIFEST_MISSING",
        "MANIFEST_JSON_INVALID",
        "MANIFEST_INVALID",
        "MANIFEST_COMPLEXITY_LIMIT",
        "ENTRYPOINT_MISSING",
        "ENTRYPOINT_OUTSIDE_SOURCE",
        "ENTRYPOINT_TYPE_INVALID",
        "SOURCE_FILE_TOO_LARGE",
        "SOURCE_TOTAL_SIZE_LIMIT",
        "SOURCE_ENTRY_COUNT_LIMIT",
        "SOURCE_FILE_COUNT_LIMIT",
        "SOURCE_DIRECTORY_COUNT_LIMIT",
        "SOURCE_DEPTH_LIMIT",
        "SOURCE_TRAVERSAL_LIMIT",
        "SOURCE_TREE_INVALID",
        "SOURCE_FILE_UNSUPPORTED",
        "AST_COMPLEXITY_LIMIT",
        "ISSUE_LIMIT_EXCEEDED",
    ):
        assert code in NON_OVERRIDABLE_ISSUE_CODES
    # Risk-acknowledgeable findings must stay overridable.
    for code in (
        "UNDECLARED_PERMISSION",
        "UNAPPROVED_PERMISSION",
        "DYNAMIC_CAPABILITY_REVIEW",
        "SENSITIVE_ENVIRONMENT",
    ):
        assert code not in NON_OVERRIDABLE_ISSUE_CODES


def test_is_installable_with_requires_every_block_acknowledged():
    dynamic = ValidationIssue(
        "DYNAMIC_CAPABILITY_REVIEW", IssueSeverity.BLOCK, "dynamic"
    )
    sensitive = ValidationIssue(
        "SENSITIVE_ENVIRONMENT", IssueSeverity.BLOCK, "sensitive"
    )
    report = make_report(issues=[dynamic, sensitive])

    # Every blocking code must be acknowledged.
    assert report.is_installable_with(frozenset()) is False
    assert report.is_installable_with(frozenset({"DYNAMIC_CAPABILITY_REVIEW"})) is False
    assert (
        report.is_installable_with(
            frozenset({"DYNAMIC_CAPABILITY_REVIEW", "SENSITIVE_ENVIRONMENT"})
        )
        is True
    )


def test_is_installable_with_rejects_any_non_overridable_block():
    dynamic = ValidationIssue(
        "DYNAMIC_CAPABILITY_REVIEW", IssueSeverity.BLOCK, "dynamic"
    )
    dependency = ValidationIssue(
        "DEPENDENCIES_UNSUPPORTED", IssueSeverity.BLOCK, "deps"
    )
    report = make_report(issues=[dynamic, dependency])

    # A non-overridable block can never be acknowledged away.
    assert (
        report.is_installable_with(
            frozenset({"DYNAMIC_CAPABILITY_REVIEW", "DEPENDENCIES_UNSUPPORTED"})
        )
        is False
    )


def test_is_installable_with_matches_plain_install_when_no_block():
    warning = ValidationIssue("WARN", IssueSeverity.WARNING, "warning")
    report = make_report(issues=[warning])

    # No blocking issue: installable regardless of acknowledgements.
    assert report.is_installable_with(frozenset()) is True
    assert report.is_installable is True


def test_is_installable_with_rejects_invalid_override_input():
    report = make_report(issues=[])

    for bad in (None, {"DYNAMIC_CAPABILITY_REVIEW"}, ["DYNAMIC_CAPABILITY_REVIEW"], frozenset({1})):
        with pytest.raises(TypeError):
            report.is_installable_with(bad)


def test_validation_report_snapshots_mutable_collections():
    permissions = [ToolPermission.FILE_READ]
    dependencies = ["pytest"]
    file_hashes = {"tool.py": "hash"}
    issues = [ValidationIssue("WARN", IssueSeverity.WARNING, "warning")]

    report = make_report(
        declared_permissions=permissions,
        dependencies=dependencies,
        file_hashes=file_hashes,
        issues=issues,
    )
    permissions.append(ToolPermission.NETWORK)
    dependencies.append("other")
    file_hashes["tool.py"] = "changed"
    issues.clear()

    assert report.declared_permissions == frozenset({ToolPermission.FILE_READ})
    assert report.dependencies == ("pytest",)
    assert report.file_hashes == {"tool.py": "hash"}
    assert len(report.issues) == 1
    with pytest.raises(TypeError):
        report.file_hashes["other.py"] = "hash"


def test_build_review_exposes_report_without_sensitive_state():
    manifest = make_manifest()
    report = make_report()
    review = BuildReview(
        build_id="b1",
        manifest=manifest,
        script_text="print('{}')",
        report=report,
    )

    assert review.build_id == "b1"
    assert review.manifest is manifest
    assert review.script_text == "print('{}')"
    assert review.report is report
    assert not hasattr(review, "environment")
    assert not hasattr(review, "logs")


def test_install_result_exposes_installer_contract():
    result = InstallResult(
        installed=False,
        tool_name="csv_summary",
        reason="NAME_CONFLICT",
        backup_path=None,
    )

    assert result.installed is False
    assert result.tool_name == "csv_summary"
    assert result.reason == "NAME_CONFLICT"
    assert result.backup_path is None


@pytest.mark.parametrize(
    ("value", "attribute", "replacement"),
    [
        (make_manifest(), "name", "changed"),
        (
            ValidationIssue("WARN", IssueSeverity.WARNING, "warning"),
            "message",
            "changed",
        ),
        (make_report(), "status", BuildStatus.INSTALL_REVIEW),
        (
            BuildReview("b1", make_manifest(), "print('{}')", make_report()),
            "script_text",
            "changed",
        ),
        (
            InstallResult(True, "csv_summary", "", None),
            "installed",
            False,
        ),
    ],
)
def test_all_dtos_are_frozen(value, attribute, replacement):
    with pytest.raises(FrozenInstanceError):
        setattr(value, attribute, replacement)


def test_tool_build_package_exports_all_public_types():
    assert set(tool_build.__all__) == EXPECTED_PUBLIC_TYPES | EXPECTED_PUBLIC_CONSTANTS
    model_types = EXPECTED_PUBLIC_TYPES - {"ToolBuildService"}
    assert {name: getattr(tool_build, name) for name in model_types} == {
        name: getattr(tool_build.models, name) for name in model_types
    }
    assert tool_build.ToolBuildService.__name__ == "ToolBuildService"
    assert {
        name: getattr(tool_build, name) for name in EXPECTED_PUBLIC_CONSTANTS
    } == {
        name: getattr(tool_build.models, name) for name in EXPECTED_PUBLIC_CONSTANTS
    }
