"""Focused ToolboxPanel UI details for reviewed and legacy script tools."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.tool_build import ToolPermission
from app.tools.script_adapter import ScriptToolAdapter
from app.tools.registry import ToolRegistry
from app.ui.toolbox_panel import _DetailPane, ToolboxPanel

pytestmark = pytest.mark.ui


def _script_tool(tmp_path: Path, *, legacy: bool) -> ScriptToolAdapter:
    return ScriptToolAdapter(
        tool_name="sample_tool",
        tool_description="Sample",
        tool_parameters={},
        script_path=str(tmp_path / "tool.py"),
        tool_dir=str(tmp_path),
        dependencies=["requests>=2"] if legacy else [],
        permissions=frozenset({ToolPermission.FILE_READ, ToolPermission.NETWORK}),
        is_legacy_manifest=legacy,
    )


@pytest.mark.parametrize("legacy", [True, False])
def test_script_tool_details_show_permissions_dependency_status_and_review_state(
    qtbot, tmp_path: Path, legacy: bool, monkeypatch
):
    pane = _DetailPane()
    qtbot.addWidget(pane)

    tool = _script_tool(tmp_path, legacy=legacy)
    if legacy:
        monkeypatch.setattr(
            ScriptToolAdapter,
            "missing_dependencies",
            property(lambda _tool: ("requests>=2",)),
        )
    pane.load(tool)

    permissions_text = pane._permissions_section.findChildren(type(pane._desc_lbl))[0].text()
    dependencies_text = pane._deps_section.findChildren(type(pane._desc_lbl))[0].text()
    assert "file_read" in permissions_text
    assert "network" in permissions_text
    if legacy:
        assert "legacy" in pane._meta_lbl.text().lower()
        assert "unreviewed" in pane._meta_lbl.text().lower()
        assert "requests" in dependencies_text
        assert "missing" in dependencies_text.lower()
        assert "automatically install" in dependencies_text.lower()
        assert "network" in dependencies_text.lower()
        assert "package build code" in dependencies_text.lower()
    else:
        metadata = pane._meta_lbl.text().lower()
        assert "strict manifest" in metadata
        assert "review status unknown" in metadata
        assert "reviewed tool" not in metadata
        assert "not automatically installed" in dependencies_text.lower()
        assert "legacy compatibility" not in dependencies_text.lower()


def test_detail_pane_uses_public_dependency_status_not_adapter_private_manager():
    import inspect
    import app.ui.toolbox_panel as module

    assert "._deps_mgr" not in inspect.getsource(module._DetailPane)


def test_generated_tool_saved_persists_enabled_state_and_refreshes_immutably(
    qtbot, tmp_path: Path, monkeypatch
):
    from app.core.config import cfg

    generated = _script_tool(tmp_path, legacy=False)
    generated.enabled = False
    other = _script_tool(tmp_path, legacy=True)
    other._name = "other_tool"
    registry = ToolRegistry()
    registry.register(generated)
    registry.register(other)
    panel = ToolboxPanel(registry)
    qtbot.addWidget(panel)
    original_states = {"sample_tool": False, "other_tool": False}
    state_store = {"value": original_states}
    saved_states: list[dict[str, bool]] = []
    reload_calls = 0

    monkeypatch.setattr(
        cfg,
        "get",
        lambda item: state_store["value"] if item is cfg.toolStates else {},
    )

    def save_states(item, value) -> None:
        if item is cfg.toolStates:
            saved_states.append(value)
            state_store["value"] = value

    def reload_tools() -> None:
        nonlocal reload_calls
        reload_calls += 1
        registry.apply_saved_states(state_store["value"])

    monkeypatch.setattr(cfg, "set", save_states)
    monkeypatch.setattr(panel, "_reload_user_tools", reload_tools)
    monkeypatch.setattr(panel, "_load_list", lambda: None)

    panel._on_generated_tool_saved("sample_tool")

    assert saved_states == [{"sample_tool": True, "other_tool": False}]
    assert saved_states[0] is not original_states
    assert original_states == {"sample_tool": False, "other_tool": False}
    assert reload_calls == 1
    assert generated.enabled is True
    assert other.enabled is False


def test_unknown_script_review_state_is_not_labeled_safe(qtbot, tmp_path: Path):
    pane = _DetailPane()
    qtbot.addWidget(pane)
    tool = _script_tool(tmp_path, legacy=False)
    tool._is_legacy_manifest = None

    pane.load(tool)

    assert "safe" not in pane._meta_lbl.text().lower()
    assert "unknown" in pane._meta_lbl.text().lower()
