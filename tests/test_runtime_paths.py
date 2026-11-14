"""Module relocation must preserve writable data and bundled resource roots."""

from pathlib import Path
import runpy
import sys

import pytest

from app.config import runtime_paths


def test_source_paths_still_use_project_root(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    paths = runpy.run_path(str(Path(runtime_paths.__file__)))
    root = Path(__file__).resolve().parents[1]

    assert paths["BASE_DIR"] == paths["BUNDLE_DIR"] == root
    assert paths["CONFIG_DIR"] == root / "config"
    assert paths["SESSIONS_DIR"] == root / "data" / "sessions"
    assert paths["USER_TOOLS_DIR"] == root / "data" / "user_tools"
    assert paths["ASSETS_DIR"] == root / "assets"


@pytest.mark.parametrize("has_bundle_dir", [False, True])
def test_frozen_paths_separate_writable_data_from_resources_without_io(
    tmp_path, monkeypatch, has_bundle_dir
):
    executable_dir = tmp_path / "installed"
    bundle_dir = tmp_path / "unpacked" if has_bundle_dir else executable_dir
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable_dir / "Nemo Assistant.exe"))
    if has_bundle_dir:
        monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    else:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    paths = runpy.run_path(str(Path(runtime_paths.__file__)))

    assert paths["BASE_DIR"] == executable_dir
    assert paths["BUNDLE_DIR"] == bundle_dir
    assert paths["CONFIG_DIR"] == executable_dir / "config"
    assert paths["SESSIONS_DIR"] == executable_dir / "data" / "sessions"
    assert paths["TOOL_BUILDS_DIR"] == executable_dir / "data" / "tool_builds"
    assert paths["ASSETS_DIR"] == bundle_dir / "assets"
    assert paths["TOOLS_DIR"] == bundle_dir / "tools"
    assert list(tmp_path.iterdir()) == []
