"""Loader collision regressions for user script tools."""
from __future__ import annotations

import json
from pathlib import Path

from app.tools.base import BuiltinTool
from app.tools.loader import discover_builtin_tools, load_builtin_tools, load_user_script_tools
from app.tools.registry import ToolRegistry


class _Builtin(BuiltinTool):
    @property
    def name(self):
        return "builtin"

    @property
    def description(self):
        return "builtin"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, params):
        return {"status": "success", "data": {}}


class _BrokenBuiltin(_Builtin):
    @classmethod
    def create(cls, ctx):
        raise RuntimeError("broken")


def _write_tool(root: Path, directory: str, name: str) -> None:
    tool_dir = root / directory
    tool_dir.mkdir()
    (tool_dir / "tool.py").write_text("print('{}')", encoding="utf-8")
    (tool_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": "legacy tool",
                "script": "tool.py",
                "parameters": {},
            }
        ),
        encoding="utf-8",
    )


def test_discover_builtin_tools_sorts_and_deduplicates(monkeypatch):
    import app.tools.loader as loader

    class _Package:
        __path__ = []
        __name__ = "app.tools"

    class ZTool(_Builtin):
        pass

    class ATool(_Builtin):
        pass

    class _Module:
        first = ZTool
        duplicate = ZTool
        second = ATool

    monkeypatch.setitem(__import__("sys").modules, "app.tools", _Package())
    monkeypatch.setattr(loader.pkgutil, "iter_modules", lambda _path: [(None, "fake", False)])
    monkeypatch.setattr(loader.importlib, "import_module", lambda *_args: _Module)

    assert [tool.__name__ for tool in discover_builtin_tools()] == ["ATool", "ZTool"]


def test_load_builtin_tools_registers_successes_and_skips_failures(monkeypatch):
    import app.tools.loader as loader

    monkeypatch.setattr(loader, "discover_builtin_tools", lambda: [_Builtin, _BrokenBuiltin])
    registry = ToolRegistry()

    assert load_builtin_tools(object(), registry) == ["builtin"]
    assert registry.get("builtin") is not None


def test_user_tool_does_not_silently_overwrite_existing_registry_name(tmp_path, caplog):
    _write_tool(tmp_path, "duplicate", "read_file")
    registry = ToolRegistry()
    existing = object()
    registry._tools["read_file"] = existing

    registered = load_user_script_tools(tmp_path, registry)

    assert registered == []
    assert registry.get("read_file") is existing
    assert "conflicts with an existing tool" in caplog.text


def test_loader_returns_empty_for_missing_directory(tmp_path):
    assert load_user_script_tools(tmp_path / "missing", ToolRegistry()) == []


def test_loader_skips_malformed_legacy_manifests(tmp_path, caplog):
    for index, manifest in enumerate((
        {"description": "missing name"},
        {"name": "missing description"},
        {"name": "null script", "description": "bad", "script": None},
        {"name": "empty script", "description": "bad", "script": ""},
    )):
        tool_dir = tmp_path / f"invalid-{index}"
        tool_dir.mkdir()
        (tool_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert load_user_script_tools(tmp_path, ToolRegistry()) == []
    assert "Skip user tool" in caplog.text


def test_loader_keeps_legacy_missing_script_default(tmp_path):
    tool_dir = tmp_path / "legacy-default"
    tool_dir.mkdir()
    (tool_dir / "tool.py").write_text("print('{}')", encoding="utf-8")
    (tool_dir / "manifest.json").write_text(
        json.dumps({"name": "legacy_default", "description": "compatible"}),
        encoding="utf-8",
    )

    registry = ToolRegistry()

    assert load_user_script_tools(tmp_path, registry) == ["legacy_default"]
    assert registry.get("legacy_default")._script_path.endswith("tool.py")


def test_second_user_tool_with_same_manifest_name_is_skipped(tmp_path, caplog):
    _write_tool(tmp_path, "first", "same_name")
    _write_tool(tmp_path, "second", "same_name")
    registry = ToolRegistry()

    registered = load_user_script_tools(tmp_path, registry)

    assert registered == ["same_name"]
    assert "conflicts with an existing tool" in caplog.text
