"""
Migration from old ConfigManager JSON format to new QConfig format.

Old format (flat nested):
    {"hotkeys": {...}, "api": {...}, "window": {...}, "litellm": {...}}

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
    if _is_old_format(data):
        # Convert old format to new
        data = _convert_old_to_new(data)
        if params_config_path.exists():
            _merge_params(params_config_path, data)
    elif params_config_path.exists():
        # Already new format, but still merge params_config
        _merge_params(params_config_path, data)

    # Collapse legacy OpenAI/Shangdao API config into a single LiteLLM entry.
    # Idempotent: a no-op once consolidation has already run.
    _consolidate_to_litellm(data)

    # Write (possibly) migrated config
    _atomic_write(app_config_path, data)

    # Backup old params file
    if params_config_path.exists():
        bak = params_config_path.with_suffix(".json.bak")
        if bak.exists():
            bak.unlink()
        params_config_path.rename(bak)


def _consolidate_to_litellm(data: dict) -> None:
    """Fold the removed OpenAI/Shangdao entrypoints into LiteLLM (in place).

    The app now has a single LiteLLM entrypoint. We translate any prior
    OpenAI-compatible endpoint (base_url + model + keyring key) into one
    LiteLLM model entry, drop the Shangdao section entirely, and force
    ApiType to "litellm". Runs on every startup but only acts when there is
    leftover legacy config, so it is safe to re-run.
    """
    api = data.get("API", {})
    # Legacy markers: temp keys from old-format conversion, or the plain
    # BaseUrl/Model keys an already-new-format user still has on disk.
    base_url = api.pop("_LegacyBaseUrl", None) or api.pop("BaseUrl", None)
    model_id = api.pop("_LegacyModel", None) or api.pop("Model", None)
    # The entrypoint the user was actually on before consolidation. Only when
    # it was NOT litellm does the migrated model become the active default.
    prev_api_type = api.pop("_LegacyApiType", None) or api.get("ApiType")
    had_shangdao = "Shangdao" in data
    needs_apitype_fix = api.get("ApiType") not in (None, "litellm")

    # Drop the removed sections/fields unconditionally.
    data.pop("Shangdao", None)
    if "LiteLLM" in data:
        data["LiteLLM"].pop("Enabled", None)

    if not (base_url or model_id or had_shangdao or needs_apitype_fix):
        # Nothing legacy left — already consolidated.
        if api:
            data["API"] = api
        return

    api["ApiType"] = "litellm"
    data["API"] = api

    # Build the LiteLLM section, prepending the migrated OpenAI endpoint.
    litellm = data.setdefault("LiteLLM", {})
    models = list(litellm.get("Models", []) or [])
    existing_ids = {m.get("id") for m in models}
    model_id = (model_id or "gpt-4o").strip() or "gpt-4o"

    if model_id not in existing_ids:
        models.insert(0, {
            "id": model_id,
            "name": model_id,
            "provider": "openai",
            "api_base": (base_url or "").strip(),
            "enabled": True,
        })
        litellm["Models"] = models

    # If the user was on the OpenAI/Shangdao entrypoint, the migrated model is
    # the one they were actually using → make it the active default. Otherwise
    # keep their existing LiteLLM default.
    if prev_api_type != "litellm" or not litellm.get("DefaultModel"):
        litellm["DefaultModel"] = model_id

    # Move the old OpenAI keyring key to the per-provider slot LiteLLM uses.
    try:
        old_key = keyring.get_password(_SERVICE_NAME, "api_key")
        if old_key and not keyring.get_password(_SERVICE_NAME, "litellm_openai_api_key"):
            keyring.set_password(_SERVICE_NAME, "litellm_openai_api_key", old_key)
    except Exception:
        pass


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
    new["Window"]["MinimizeTo"] = window.get("minimize_to", "taskbar")
    new["Window"]["Width"] = window.get("width", 440)
    new["Window"]["Height"] = window.get("height", 700)

    # API（仅保留通用参数；BaseUrl/Model/Key 由 _consolidate_to_litellm 转成
    # 一个 LiteLLM 模型条目）
    api = old.get("api", {})
    new.setdefault("API", {})
    new["API"]["MaxTokens"] = api.get("max_tokens", 4096)
    new["API"]["Temperature"] = api.get("temperature", 0.7)
    new["API"]["TopP"] = api.get("top_p", 1.0)
    new["API"]["SystemPrompt"] = api.get("system_prompt", "")
    # 临时携带旧 OpenAI 端点信息，供 _consolidate_to_litellm 消费后清除
    new["API"]["_LegacyBaseUrl"] = api.get("base_url", "https://api.openai.com/v1")
    new["API"]["_LegacyModel"] = api.get("model", "gpt-4o")
    new["API"]["_LegacyApiType"] = api.get("api_type", "openai")

    # Migrate plaintext API key to keyring if present
    if api.get("api_key"):
        keyring.set_password(_SERVICE_NAME, "api_key", api["api_key"])

    # LiteLLM
    ll = old.get("litellm", {})
    new.setdefault("LiteLLM", {})
    new["LiteLLM"]["Enabled"] = ll.get("enabled", False)
    new["LiteLLM"]["DefaultModel"] = ll.get("default_model", "gpt-4o")
    new["LiteLLM"]["Models"] = ll.get("models", [])

    # Hotkeys（默认值取自单一来源 DEFAULT_HOTKEYS）
    from app.core.config import DEFAULT_HOTKEYS
    hk = old.get("hotkeys", {})
    new.setdefault("Hotkeys", {})
    new["Hotkeys"]["Screenshot"] = hk.get("screenshot", DEFAULT_HOTKEYS["screenshot"])
    new["Hotkeys"]["NewNote"] = hk.get("new_note", DEFAULT_HOTKEYS["new_note"])
    new["Hotkeys"]["ToggleWindow"] = hk.get("toggle_window", DEFAULT_HOTKEYS["toggle_window"])
    new["Hotkeys"]["QuickAsk"] = hk.get("quick_ask", DEFAULT_HOTKEYS["quick_ask"])
    new["Hotkeys"]["Selection"] = hk.get("selection", DEFAULT_HOTKEYS["selection"])

    # Tools (tool_states from old format)
    new.setdefault("Tools", {})
    new["Tools"]["ToolStates"] = old.get("tool_states", {})
    # 老用户从旧格式迁移而来：视为已播种，跳过"高风险工具默认关"逻辑，
    # 避免升级后突然关掉他们一直在用的工具。
    new["Tools"]["DefaultsSeeded"] = True
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
