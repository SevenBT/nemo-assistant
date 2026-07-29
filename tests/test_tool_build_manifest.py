import json
from pathlib import Path

import pytest

from app.core.tool_build.manifest import (
    manifest_to_json,
    manifest_to_parameters,
    parse_manifest_text,
)
from app.core.tool_build.models import ToolManifest, ToolPermission


def valid_manifest(**overrides):
    value = {
        "manifest_version": 1,
        "name": "csv_summary",
        "description": "Summarize CSV data",
        "script": "tool.py",
        "version": "1.0.0",
        "parameters": {"path": {"type": "string", "required": True}},
        "output": {"type": "object"},
        "permissions": ["file_read"],
        "dependencies": [],
    }
    value.update(overrides)
    return value


def parse_strict(**overrides):
    return parse_manifest_text(json.dumps(valid_manifest(**overrides)), mode="strict")


def test_strict_manifest_requires_version_and_permission_list():
    manifest = parse_strict()

    assert manifest.name == "csv_summary"
    assert manifest.permissions == frozenset({ToolPermission.FILE_READ})
    assert manifest.is_legacy is False


@pytest.mark.parametrize("manifest_version", [None, 0, 2, "1", True])
def test_strict_manifest_rejects_missing_or_unsupported_version(manifest_version):
    value = valid_manifest()
    if manifest_version is None:
        value.pop("manifest_version")
    else:
        value["manifest_version"] = manifest_version

    with pytest.raises(ValueError, match="manifest_version"):
        parse_manifest_text(json.dumps(value), mode="strict")


@pytest.mark.parametrize(
    "name",
    ["", "1tool", "tool-name", "tool/name", "a" * 65, None],
)
def test_strict_manifest_rejects_invalid_tool_name(name):
    with pytest.raises(ValueError, match="name"):
        parse_strict(name=name)


@pytest.mark.parametrize(
    "name", ["CON", "prn", "Aux", "nul", "COM1", "com9", "LPT1", "lpt9"]
)
def test_strict_manifest_rejects_windows_dos_device_names(name):
    with pytest.raises(ValueError, match="reserved"):
        parse_strict(name=name)


def test_strict_manifest_rejects_unknown_permission():
    with pytest.raises(ValueError, match="unknown permission"):
        parse_strict(permissions=["magic"])


@pytest.mark.parametrize("permissions", [None, "file_read", {"permission": "file_read"}])
def test_strict_manifest_requires_permission_list(permissions):
    with pytest.raises(ValueError, match="permissions"):
        parse_strict(permissions=permissions)


@pytest.mark.parametrize("dependency", ["file:./x", "requests>=2.0"])
def test_strict_manifest_rejects_nonempty_dependencies(dependency):
    with pytest.raises(ValueError, match="dependency"):
        parse_strict(dependencies=[dependency])


@pytest.mark.parametrize("dependencies", [None, "requests", {}])
def test_strict_manifest_requires_dependency_list(dependencies):
    with pytest.raises(ValueError, match="dependencies"):
        parse_strict(dependencies=dependencies)


@pytest.mark.parametrize("script", ["/tmp/tool.py", "C:/tools/tool.py", r"C:\tools\tool.py", ""])
def test_strict_manifest_rejects_absolute_or_empty_script(script):
    with pytest.raises(ValueError, match="script"):
        parse_strict(script=script)


def test_strict_manifest_allows_relative_script_for_later_workspace_validation():
    manifest = parse_strict(script="subdir/tool.py")

    assert manifest.script == "subdir/tool.py"


@pytest.mark.parametrize("parameters", [None, [], "path"])
def test_strict_manifest_requires_parameters_object(parameters):
    with pytest.raises(ValueError, match="parameters"):
        parse_strict(parameters=parameters)


@pytest.mark.parametrize(
    "parameter",
    [
        {"type": "null"},
        {"type": None},
        {"type": []},
        {"type": {}},
        "string",
    ],
)
def test_strict_manifest_rejects_invalid_parameter_definition(parameter):
    with pytest.raises(ValueError, match="parameter"):
        parse_strict(parameters={"value": parameter})


@pytest.mark.parametrize("source", ["manual", "secret", "", 1, [], {}])
def test_strict_manifest_rejects_unsupported_parameter_source(source):
    with pytest.raises(ValueError, match="source"):
        parse_strict(parameters={"value": {"type": "string", "source": source}})


@pytest.mark.parametrize(
    "parameter_type",
    ["string", "number", "integer", "boolean", "array", "object"],
)
def test_strict_manifest_accepts_supported_parameter_types(parameter_type):
    manifest = parse_strict(parameters={"value": {"type": parameter_type}})

    assert manifest.parameters["value"]["type"] == parameter_type


@pytest.mark.parametrize("output", [None, [], "object"])
def test_strict_manifest_requires_output_object(output):
    with pytest.raises(ValueError, match="output"):
        parse_strict(output=output)


def test_strict_manifest_requires_output_field():
    value = valid_manifest()
    value.pop("output")

    with pytest.raises(ValueError, match="output"):
        parse_manifest_text(json.dumps(value), mode="strict")


def test_legacy_manifest_parses_without_new_fields_and_is_marked():
    manifest = parse_manifest_text(
        json.dumps(
            {
                "name": "old",
                "description": "old",
                "script": "tool.py",
                "parameters": {"query": {"description": "Search term"}},
                "dependencies": ["requests>=2.0"],
                "retry_safe": True,
            }
        ),
        mode="legacy",
    )

    assert manifest.is_legacy is True
    assert manifest.manifest_version == 0
    assert manifest.permissions == frozenset()
    assert manifest.output == {}
    assert manifest.dependencies == ("requests>=2.0",)
    assert manifest.retry_safe is True
    assert manifest.parameters["query"]["description"] == "Search term"


def test_manifest_to_parameters_filters_config_and_preserves_schema_fields():
    manifest = parse_strict(
        parameters={
            "query": {
                "type": "string",
                "description": "Search term",
                "enum": ["one", "two"],
                "required": True,
            },
            "limit": {"type": "integer", "required": False},
            "api_key": {"type": "string", "source": "config"},
        }
    )

    parameters = manifest_to_parameters(manifest)

    assert parameters == {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term",
                "enum": ["one", "two"],
            },
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }


def test_manifest_to_parameters_defaults_legacy_type_and_required():
    manifest = parse_manifest_text(
        json.dumps(
            {
                "name": "old",
                "description": "old",
                "script": "tool.py",
                "parameters": {"query": {}},
            }
        ),
        mode="legacy",
    )

    assert manifest_to_parameters(manifest) == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


def test_manifest_to_parameters_rejects_manual_source_for_v1():
    manifest = ToolManifest(
        manifest_version=1,
        name="manual_source",
        description="Manual source regression",
        script="tool.py",
        parameters={"query": {"type": "string", "source": "manual"}},
        output={"type": "object"},
        permissions=frozenset(),
        dependencies=(),
    )

    with pytest.raises(ValueError, match="manual"):
        manifest_to_parameters(manifest)


def test_manifest_to_json_emits_parseable_v1_manifest():
    original = parse_strict(
        author="Nemo",
        retry_safe=False,
        permissions=["file_read", "network"],
    )

    encoded = manifest_to_json(original)
    value = json.loads(encoded)
    reparsed = parse_manifest_text(encoded, mode="strict")

    assert value["permissions"] == ["file_read", "network"]
    assert "is_legacy" not in value
    assert reparsed == original


@pytest.mark.parametrize("text", ["", "[]", "null", "{bad json"])
def test_parser_rejects_non_object_or_invalid_json(text):
    with pytest.raises(ValueError, match="manifest"):
        parse_manifest_text(text, mode="strict")


def test_parser_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        parse_manifest_text(json.dumps(valid_manifest()), mode="unsupported")


def test_parsing_has_no_filesystem_or_dependency_install_side_effects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    parse_strict()

    assert list(Path(tmp_path).iterdir()) == []
