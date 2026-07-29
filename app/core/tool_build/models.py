"""Immutable domain DTOs for the tool build workflow."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

ImmutableValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | Mapping[str, "ImmutableValue"]
    | tuple["ImmutableValue", ...]
    | frozenset["ImmutableValue"]
)


def _freeze(value: object) -> ImmutableValue:
    """Create a recursive immutable snapshot of manifest data."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported manifest value type: {type(value).__name__}")


class ToolPermission(str, Enum):
    """Capabilities a generated tool may request."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    NETWORK = "network"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    SHELL = "shell"
    PYTHON_SUBPROCESS = "python_subprocess"
    PROCESS_SPAWN = "process_spawn"


class IssueSeverity(str, Enum):
    """Severity of a validation finding."""

    INFO = "info"
    WARNING = "warning"
    BLOCK = "block"


# Blocking findings that a user can never acknowledge away: the tool could not
# load or run even if installed (unsupported dependencies, invalid Python or
# manifest, broken entrypoint), the source could not be safely analysed at all
# (traversal/size/complexity limits), or the installer itself would fail on the
# artifact. Overriding these produces a tool that cannot work, so they stay a
# hard wall. Every other blocking code is risk-acknowledgeable by the user.
NON_OVERRIDABLE_ISSUE_CODES: frozenset[str] = frozenset(
    {
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
    }
)


class BuildStatus(str, Enum):
    """Lifecycle states for a tool build."""

    STAGED = "staged"
    VALIDATING = "validating"
    VALIDATION_FAILED = "validation_failed"
    INSTALL_REVIEW = "install_review"
    INSTALLED = "installed"
    INSTALL_FAILED = "install_failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class ToolManifest:
    """Declarative metadata for a generated tool."""

    manifest_version: int
    name: str
    description: str
    script: str
    parameters: Mapping[str, ImmutableValue]
    output: Mapping[str, ImmutableValue]
    version: str = ""
    author: str = ""
    permissions: frozenset[ToolPermission] = field(default_factory=frozenset)
    dependencies: tuple[str, ...] = ()
    retry_safe: bool = False
    is_legacy: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "output", _freeze(self.output))
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding produced by validation."""

    code: str
    severity: IssueSeverity
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Immutable result of validating a build."""

    build_id: str
    status: BuildStatus
    declared_permissions: frozenset[ToolPermission]
    detected_permissions: frozenset[ToolPermission]
    dependencies: tuple[str, ...]
    file_hashes: Mapping[str, str]
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "declared_permissions", frozenset(self.declared_permissions)
        )
        object.__setattr__(
            self, "detected_permissions", frozenset(self.detected_permissions)
        )
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "file_hashes", MappingProxyType(dict(self.file_hashes)))
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_installable(self) -> bool:
        """Return whether this report contains no blocking issue."""

        return self.is_installable_for(self.issues)

    @staticmethod
    def is_installable_for(issues: tuple[ValidationIssue, ...]) -> bool:
        """Return whether findings contain no blocking issue."""

        return not any(issue.severity is IssueSeverity.BLOCK for issue in issues)

    def is_installable_with(self, acknowledged_overrides: frozenset[str]) -> bool:
        """Return whether the user may install after acknowledging risk.

        Installation is permitted only when every blocking finding is both
        overridable (not in :data:`NON_OVERRIDABLE_ISSUE_CODES`) and explicitly
        acknowledged. A single non-overridable block fails closed regardless of
        acknowledgements. An empty set reproduces plain installability.
        """

        if not isinstance(acknowledged_overrides, frozenset) or not all(
            isinstance(code, str) for code in acknowledged_overrides
        ):
            raise TypeError("acknowledged_overrides must be a frozenset of str codes")
        blocking_codes = {
            issue.code
            for issue in self.issues
            if issue.severity is IssueSeverity.BLOCK
        }
        if blocking_codes & NON_OVERRIDABLE_ISSUE_CODES:
            return False
        return blocking_codes <= acknowledged_overrides


@dataclass(frozen=True)
class BuildReview:
    """Human review snapshot without environment or full execution logs."""

    build_id: str
    manifest: ToolManifest
    script_text: str
    report: ValidationReport


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an installation attempt."""

    installed: bool
    tool_name: str
    reason: str
    backup_path: str | None = None
