"""
Migration from old ConfigManager JSON format to new QConfig format.

Old format (flat nested):
    {"hotkeys": {...}, "api": {...}, "window": {...}, "shangdao": {...}, "litellm": {...}}

New format (QConfig group.name):
    {"Appearance": {"Theme": "morning"}, "Window": {"EdgeSnap": true}, ...}
"""

import json
import os
from pathlib import Path

import keyring

_SERVICE_NAME = "ai-agent-desktop"


def migrate_config(config_dir: Path) -> None:
    """Migrate old config format to new QConfig format if needed."""
    app_config_path = config_dir / "app_config.json"
    params_config_path = config_dir / "params_config.json"

    if not app_config_path.exists():
        # No existing config, nothing to migrate
        # Also handle params_config if it exists standalone
        if params_config_path.exists():
            _migrate_params_only(params_config_path, app_config_path)
        return

    try:
        with open(app_config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    # Detect old format: has top-level "api" or "hotkeys" or "window" key
    if not _is_old_format(data):
        # Already new format, but still check params_config
        if params_config_path.exists():
            _merge_params_into_new(params_config_path, app_config_path, data)
        return

    # Convert old format to new
    new_data = _convert_old_to_new(data)

    # Merge params_config.json
    if params_config_path.exists():
        _merge_params(params_config_path, new_data)

    # Write new format
    _atomic_write(app_config_path, new_data)

    # Backup old params file
    if params_config_path.exists():
        bak = params_config_path.with_suffix(".json.bak")
        if bak.exists():
            bak.unlink()
        params_config_path.rename(bak)


def _is_old_format(data: dict) -> bool:
    """Old format has lowercase top-level keys like 'api', 'window', 'hotkeys'."""
    return any(k in data for k in ("api", "hotkeys", "window"))


def _convert_old_to_new(old: dict) -> dict:
    """Transform old ConfigManager format to QConfig group.name format."""
    new: dict = {}

    # Appearance
    window = old.get("window", {})
    new.setdefault("Appearance", {})
    new["Appearance"]["Theme"] = window.get("theme", "almond")
    fs = window.get("font_size", 15)
    new["Appearance"]["ContentFontSize"] = fs
    new["Appearance"]["NavigationFontSize"] = max(fs - 2, 10)

    # Editor
    new.setdefault("Editor", {})
    new["Editor"]["EditorFontSize"] = window.get("note_editor_font_size", 15)

    # Window
    new.setdefault("Window", {})
    new["Window"]["EdgeSnap"] = window.get("edge_snap", True)
    threshold = window.get("edge_snap_width_threshold", 0.4)
    new["Window"]["EdgeSnapThreshold"] = int(threshold * 100)
    new["Window"]["MinimizeTo"] = window.get("minimize_to", "tray")
    new["Window"]["Width"] = window.get("width", 440)
    new["Window"]["Height"] = window.get("height", 700)

    # API
    api = old.get("api", {})
    new.setdefault("API", {})
    new["API"]["ApiType"] = api.get("api_type", "openai")
    new["API"]["BaseUrl"] = api.get("base_url", "https://api.openai.com/v1")
    new["API"]["Model"] = api.get("model", "gpt-4o")
    new["API"]["MaxTokens"] = api.get("max_tokens", 4096)
    new["API"]["Temperature"] = api.get("temperature", 0.7)
    new["API"]["SystemPrompt"] = api.get("system_prompt", "")

    # Migrate plaintext API key to keyring if present
    if api.get("api_key"):
        keyring.set_password(_SERVICE_NAME, "api_key", api["api_key"])

    # Shangdao
    sd = old.get("shangdao", {})
    new.setdefault("Shangdao", {})
    new["Shangdao"]["Enabled"] = sd.get("enabled", False)
    new["Shangdao"]["BaseUrl"] = sd.get("base_url", "https://api.example.com")
    new["Shangdao"]["Model"] = sd.get("model", "Qwen3_235B")
    new["Shangdao"]["MaxTokens"] = sd.get("max_tokens", 2048)
    new["Shangdao"]["Temperature"] = sd.get("temperature", 0.7)

    # LiteLLM
    ll = old.get("litellm", {})
    new.setdefault("LiteLLM", {})
    new["LiteLLM"]["Enabled"] = ll.get("enabled", False)
    new["LiteLLM"]["DefaultModel"] = ll.get("default_model", "gpt-4o")
    new["LiteLLM"]["Models"] = ll.get("models", [])

    # Hotkeys
    hk = old.get("hotkeys", {})
    new.setdefault("Hotkeys", {})
    new["Hotkeys"]["Screenshot"] = hk.get("screenshot", "ctrl+alt+a")
    new["Hotkeys"]["NewNote"] = hk.get("new_note", "ctrl+alt+n")
    new["Hotkeys"]["ToggleWindow"] = hk.get("toggle_window", "ctrl+alt+space")
    new["Hotkeys"]["QuickAsk"] = hk.get("quick_ask", "ctrl+alt+q")

    # Tools (tool_states from old format)
    new.setdefault("Tools", {})
    new["Tools"]["ToolStates"] = old.get("tool_states", {})
    new["Tools"]["SearchProvider"] = "bocha"
    new["Tools"]["SaveDir"] = ""

    # Layout
    new.setdefault("Layout", {})
    new["Layout"]["NoteListWidth"] = window.get("note_list_width", 250)
    new["Layout"]["NoteListVisible"] = window.get("note_list_visible", True)
    new["Layout"]["SessionPanelWidth"] = window.get("session_panel_width", 200)

    return new


def _merge_params(params_path: Path, new_data: dict) -> None:
    """Merge params_config.json tool params into new config data."""
    try:
        with open(params_path, encoding="utf-8") as f:
            params = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    tools = params.get("tools", {})
    web_search = tools.get("web_search", {})
    save_file = tools.get("save_file", {})

    new_data.setdefault("Tools", {})

    if web_search.get("provider"):
        new_data["Tools"]["SearchProvider"] = web_search["provider"]

    # Migrate search API key to keyring
    if web_search.get("api_key"):
        keyring.set_password(_SERVICE_NAME, "web_search_api_key", web_search["api_key"])

    if save_file.get("save_dir"):
        new_data["Tools"]["SaveDir"] = save_file["save_dir"]


def _merge_params_into_new(params_path: Path, app_config_path: Path, data: dict) -> None:
    """Merge params_config into already-new-format config."""
    _merge_params(params_path, data)
    _atomic_write(app_config_path, data)
    bak = params_path.with_suffix(".json.bak")
    if bak.exists():
        bak.unlink()
    params_path.rename(bak)


def _migrate_params_only(params_path: Path, app_config_path: Path) -> None:
    """Handle case where only params_config.json exists (no app_config)."""
    new_data: dict = {}
    _merge_params(params_path, new_data)
    if new_data:
        _atomic_write(app_config_path, new_data)
    bak = params_path.with_suffix(".json.bak")
    if bak.exists():
        bak.unlink()
    params_path.rename(bak)


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically using temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(path))
