"""Manifest parsing and conversion helpers for generated tools."""

from __future__ import annotations

import json
import ntpath
import posixpath
import re
from collections.abc import Mapping
from typing import Literal

from .models import ToolManifest, ToolPermission

_TOOL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_WINDOWS_DOS_DEVICE_RE = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
_SUPPORTED_PARAMETER_TYPES = frozenset(
    {"string", "number", "integer", "boolean", "array", "object"}
)
_SUPPORTED_PARAMETER_SOURCES = frozenset({"ai", "config"})
_SCHEMA_PASSTHROUGH_FIELDS = frozenset(
    {
        "type",
        "description",
        "enum",
        "items",
        "properties",
        "additionalProperties",
        "default",
    }
)
MAX_MANIFEST_BYTES = 262_144
MAX_MANIFEST_JSON_DEPTH = 64
MAX_MANIFEST_JSON_NODES = 10_000


def parse_manifest_text(
    text: str, *, mode: Literal["strict", "legacy"]
) -> ToolManifest:
    """Parse manifest JSON into an immutable ToolManifest."""

    if mode == "strict":
        return _parse_strict_manifest(_load_manifest_object(text))
    if mode == "legacy":
        return _parse_legacy_manifest(_load_manifest_object(text))
    raise ValueError(f"unsupported manifest parse mode: {mode}")


def manifest_to_parameters(manifest: ToolManifest) -> dict[str, object]:
    """Convert manifest parameters to an OpenAI-compatible object schema."""

    properties: dict[str, object] = {}
    required: list[str] = []

    for name, raw_parameter in manifest.parameters.items():
        if not isinstance(raw_parameter, Mapping):
            if manifest.is_legacy:
                parameter: Mapping[str, object] = {}
            else:
                raise ValueError(f"parameter {name} must be an object")
        else:
            parameter = raw_parameter

        source = parameter.get("source")
        if source == "config":
            continue
        if source == "manual" and not manifest.is_legacy:
            raise ValueError("manual parameter source is not supported for v1 manifests")

        schema = _parameter_to_schema(parameter, default_type="string")
        properties[str(name)] = schema

        is_required = parameter.get("required", True if manifest.is_legacy else False)
        if is_required is True:
            required.append(str(name))

    return {"type": "object", "properties": properties, "required": required}


def manifest_to_json(manifest: ToolManifest) -> str:
    """Serialize a strict v1 manifest as JSON parseable by strict mode."""

    if manifest.is_legacy or manifest.manifest_version != 1:
        raise ValueError("only strict v1 manifests can be serialized")

    value = {
        "manifest_version": manifest.manifest_version,
        "name": manifest.name,
        "description": manifest.description,
        "script": manifest.script,
        "version": manifest.version,
        "author": manifest.author,
        "parameters": _thaw(manifest.parameters),
        "output": _thaw(manifest.output),
        "permissions": sorted(permission.value for permission in manifest.permissions),
        "dependencies": list(manifest.dependencies),
        "retry_safe": manifest.retry_safe,
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_manifest_object(text: str) -> dict[str, object]:
    validate_manifest_text_budget(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("manifest JSON is invalid") from exc
    except (OverflowError, RecursionError, MemoryError) as exc:
        raise ValueError("MANIFEST_COMPLEXITY_LIMIT") from exc

    try:
        _validate_manifest_structure(value)
    except (MemoryError, RecursionError, OverflowError) as exc:
        raise ValueError("MANIFEST_COMPLEXITY_LIMIT") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value


def validate_manifest_text_budget(text: str) -> None:
    """Reject untrusted manifest text before the first JSON parse."""

    if not isinstance(text, str):
        raise TypeError("manifest text must be a string")
    try:
        size = len(text.encode("utf-8"))
    except (MemoryError, OverflowError) as exc:
        raise ValueError("MANIFEST_SIZE_LIMIT") from exc
    if size > MAX_MANIFEST_BYTES:
        raise ValueError("MANIFEST_SIZE_LIMIT")
    _validate_json_lexical_depth(text)


def _validate_json_lexical_depth(text: str) -> None:
    depth = 0
    is_string = False
    is_escaped = False
    for character in text:
        if is_string:
            if is_escaped:
                is_escaped = False
            elif character == "\\":
                is_escaped = True
            elif character == '"':
                is_string = False
            continue
        if character == '"':
            is_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_MANIFEST_JSON_DEPTH:
                raise ValueError("MANIFEST_COMPLEXITY_LIMIT")
        elif character in "]}":
            depth = max(0, depth - 1)


def _validate_manifest_structure(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_MANIFEST_JSON_NODES or depth > MAX_MANIFEST_JSON_DEPTH:
            raise ValueError("MANIFEST_COMPLEXITY_LIMIT")
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)


def _parse_strict_manifest(value: dict[str, object]) -> ToolManifest:
    manifest_version = value.get("manifest_version")
    if type(manifest_version) is not int or manifest_version != 1:
        raise ValueError("manifest_version must be integer 1")

    name = _required_string(value, "name")
    if not _TOOL_NAME_RE.fullmatch(name):
        raise ValueError("name must match ^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    if _WINDOWS_DOS_DEVICE_RE.fullmatch(name):
        raise ValueError("name is reserved by Windows")

    script = _required_string(value, "script")
    if not _is_relative_script_path(script):
        raise ValueError("script must be a non-empty relative path")

    parameters = _required_mapping(value, "parameters")
    _validate_strict_parameters(parameters)

    output = _required_mapping(value, "output")
    permissions = _parse_permissions(value.get("permissions"))
    dependencies = _parse_strict_dependencies(value.get("dependencies"))
    if value.get("retry_safe") is True:
        raise ValueError("retry_safe must be false or omitted in manifest v1")

    return ToolManifest(
        manifest_version=1,
        name=name,
        description=_required_string(value, "description"),
        script=script,
        version=_optional_string(value, "version"),
        author=_optional_string(value, "author"),
        parameters=parameters,
        output=output,
        permissions=permissions,
        dependencies=dependencies,
        retry_safe=False,
        is_legacy=False,
    )


def _parse_legacy_manifest(value: dict[str, object]) -> ToolManifest:
    parameters = value.get("parameters", {})
    if not isinstance(parameters, Mapping):
        parameters = {}

    output = value.get("output", {})
    if not isinstance(output, Mapping):
        output = {}

    dependencies = value.get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []

    return ToolManifest(
        manifest_version=0,
        name=str(value.get("name", "")),
        description=str(value.get("description", "")),
        script=str(value.get("script", "")),
        version=str(value.get("version", "")),
        author=str(value.get("author", "")),
        parameters=parameters,
        output=output,
        permissions=frozenset(),
        dependencies=tuple(str(dependency) for dependency in dependencies),
        retry_safe=value.get("retry_safe") is True,
        is_legacy=True,
    )


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key, "")
    if item is None:
        return ""
    if not isinstance(item, str):
        raise ValueError(f"{key} must be a string")
    return item


def _required_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise ValueError(f"{key} must be an object")
    return item


def _is_relative_script_path(script: str) -> bool:
    if not script.strip():
        return False
    return not posixpath.isabs(script) and not ntpath.isabs(script)


def _parse_permissions(raw_permissions: object) -> frozenset[ToolPermission]:
    if not isinstance(raw_permissions, list):
        raise ValueError("permissions must be a list")

    permissions: set[ToolPermission] = set()
    for raw_permission in raw_permissions:
        if not isinstance(raw_permission, str):
            raise ValueError("permissions must contain strings")
        try:
            permissions.add(ToolPermission(raw_permission))
        except ValueError as exc:
            raise ValueError(f"unknown permission: {raw_permission}") from exc
    return frozenset(permissions)


def _parse_strict_dependencies(raw_dependencies: object) -> tuple[str, ...]:
    if not isinstance(raw_dependencies, list):
        raise ValueError("dependencies must be a list")
    if raw_dependencies:
        raise ValueError("dependency list must be empty in manifest v1")
    return ()


def _validate_strict_parameters(parameters: Mapping[str, object]) -> None:
    for name, parameter in parameters.items():
        if not isinstance(name, str) or not isinstance(parameter, Mapping):
            raise ValueError("parameter definitions must be objects")

        parameter_type = parameter.get("type")
        if (
            not isinstance(parameter_type, str)
            or parameter_type not in _SUPPORTED_PARAMETER_TYPES
        ):
            raise ValueError(f"parameter {name} has unsupported type")

        source = parameter.get("source")
        if source is None:
            continue
        if not isinstance(source, str) or source not in _SUPPORTED_PARAMETER_SOURCES:
            raise ValueError(f"parameter {name} has unsupported source")


def _parameter_to_schema(
    parameter: Mapping[str, object], *, default_type: str
) -> dict[str, object]:
    parameter_type = parameter.get("type", default_type)
    if not isinstance(parameter_type, str):
        raise ValueError("parameter type must be a string")

    schema: dict[str, object] = {"type": parameter_type}
    for key in _SCHEMA_PASSTHROUGH_FIELDS:
        if key in {"type", "default"}:
            continue
        if key in parameter:
            schema[key] = _thaw(parameter[key])
    return schema


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_thaw(item) for item in value)
    if isinstance(value, ToolPermission):
        return value.value
    return value
