"""
Declarative configuration module based on qfluentwidgets QConfig.

Usage:
    from app.core.config import cfg, get_api_key, set_api_key

    value = cfg.get(cfg.contentFontSize)
    cfg.set(cfg.contentFontSize, 16)
    cfg.contentFontSize.valueChanged.connect(on_font_changed)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import keyring
from qfluentwidgets import (
    BoolValidator,
    ConfigItem,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    RangeConfigItem,
    RangeValidator,
    qconfig,
)

# ── Path constants ────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent.parent

CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
NOTES_DIR = DATA_DIR / "notes"
NOTES_IMAGES_DIR = NOTES_DIR / "images"
TRASH_DIR = NOTES_DIR / "trash"
TOOLS_DIR = BASE_DIR / "tools"
USER_TOOLS_DIR = DATA_DIR / "user_tools"
TOOL_RUNTIME_DIR = DATA_DIR / "tool_runtime"
TOOL_SITE_PACKAGES = TOOL_RUNTIME_DIR / "site-packages"

# ── Model metadata ────────────────────────────────────────────────────

SHANGDAO_MODELS: dict[str, dict] = {
    "Qwen3_235B": {
        "path_prefix": "CMHK-LMMP-PRD_Qwen3_235B_Ins/CMHK-LMMP-PRD",
        "body_model_field": "mode1",
        "body_model_value": "Qwen3_235B",
    },
    "Qwen2.5-72B": {
        "path_prefix": "CMHK-LMMP-PRD_Qwen2_5_72B/CMHK-LMMP-PRD",
        "body_model_field": "mode1",
        "body_model_value": "Qwen2.5-72B",
    },
    "DeepSeek-V3": {
        "path_prefix": "CMHK-LMMP-PRD_DeepSeek_R1/CMHK-LMMP-PRD",
        "body_model_field": "model",
        "body_model_value": "DeepSeek-V3-1-maas",
    },
}

MODEL_TEMPLATES: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        {"id": "o1", "name": "O1"},
        {"id": "o1-mini", "name": "O1 Mini"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
    ],
    "anthropic": [
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku"},
        {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
    ],
    "google": [
        {"id": "gemini-2.0-flash-exp", "name": "Gemini 2.0 Flash"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash"},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat"},
        {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner"},
    ],
}

# ── Theme list (for OptionsValidator) ─────────────────────────────────

THEME_OPTIONS = [
    "warm_night", "deep_ocean", "obsidian",
    "morning", "warm_sand", "mint", "rose", "lavender",
]

# ── Keyring constants ─────────────────────────────────────────────────

_SERVICE_NAME = "ai-agent-desktop"
_ACCOUNT_API_KEY = "api_key"
_ACCOUNT_SHANGDAO_KEY = "shangdao_api_key"
_ACCOUNT_SEARCH_KEY = "web_search_api_key"


# ── AppConfig declaration ─────────────────────────────────────────────


class AppConfig(QConfig):
    """Declarative app configuration. All items are class attributes."""

    # -- Appearance --
    theme = OptionsConfigItem(
        "Appearance", "Theme", "morning", OptionsValidator(THEME_OPTIONS)
    )
    contentFontSize = RangeConfigItem(
        "Appearance", "ContentFontSize", 15, RangeValidator(12, 24)
    )
    navigationFontSize = RangeConfigItem(
        "Appearance", "NavigationFontSize", 13, RangeValidator(10, 20)
    )

    # -- Editor --
    editorFontSize = RangeConfigItem(
        "Editor", "EditorFontSize", 15, RangeValidator(8, 36)
    )

    # -- Window --
    edgeSnap = ConfigItem("Window", "EdgeSnap", True, BoolValidator())
    edgeSnapThreshold = RangeConfigItem(
        "Window", "EdgeSnapThreshold", 40, RangeValidator(20, 80)
    )
    minimizeTo = OptionsConfigItem(
        "Window", "MinimizeTo", "tray", OptionsValidator(["tray", "taskbar"])
    )
    windowWidth = RangeConfigItem(
        "Window", "Width", 440, RangeValidator(300, 800)
    )
    windowHeight = RangeConfigItem(
        "Window", "Height", 700, RangeValidator(400, 1200)
    )

    # -- API --
    apiType = OptionsConfigItem(
        "API", "ApiType", "openai",
        OptionsValidator(["openai", "shangdao", "litellm"]),
    )
    apiBaseUrl = ConfigItem("API", "BaseUrl", "https://api.openai.com/v1")
    model = ConfigItem("API", "Model", "gpt-4o")
    maxTokens = RangeConfigItem(
        "API", "MaxTokens", 4096, RangeValidator(256, 65536)
    )
    temperature = ConfigItem("API", "Temperature", 0.7)
    systemPrompt = ConfigItem("API", "SystemPrompt", "")

    # -- Shangdao --
    shangdaoEnabled = ConfigItem("Shangdao", "Enabled", False, BoolValidator())
    shangdaoBaseUrl = ConfigItem(
        "Shangdao", "BaseUrl", "https://api.example.com"
    )
    shangdaoModel = OptionsConfigItem(
        "Shangdao", "Model", "Qwen3_235B",
        OptionsValidator(list(SHANGDAO_MODELS.keys())),
    )
    shangdaoMaxTokens = RangeConfigItem(
        "Shangdao", "MaxTokens", 2048, RangeValidator(256, 65536)
    )
    shangdaoTemperature = ConfigItem("Shangdao", "Temperature", 0.7)

    # -- LiteLLM --
    litellmEnabled = ConfigItem("LiteLLM", "Enabled", False, BoolValidator())
    litellmDefaultModel = ConfigItem("LiteLLM", "DefaultModel", "gpt-4o")
    litellmModels = ConfigItem("LiteLLM", "Models", [])

    # -- Tools --
    searchProvider = OptionsConfigItem(
        "Tools", "SearchProvider", "bocha",
        OptionsValidator(["ddg", "bing", "tavily", "brave", "bocha"]),
    )
    saveDir = ConfigItem("Tools", "SaveDir", "")
    toolStates = ConfigItem("Tools", "ToolStates", {})

    # -- Hotkeys --
    hotkeyScreenshot = ConfigItem("Hotkeys", "Screenshot", "ctrl+alt+a")
    hotkeyNewNote = ConfigItem("Hotkeys", "NewNote", "ctrl+alt+n")
    hotkeyToggleWindow = ConfigItem(
        "Hotkeys", "ToggleWindow", "ctrl+alt+space"
    )
    hotkeyQuickAsk = ConfigItem("Hotkeys", "QuickAsk", "ctrl+alt+q")

    # -- Layout (persisted, not shown in settings UI) --
    noteListWidth = ConfigItem("Layout", "NoteListWidth", 100)
    noteListVisible = ConfigItem(
        "Layout", "NoteListVisible", True, BoolValidator()
    )
    sessionPanelWidth = ConfigItem("Layout", "SessionPanelWidth", 140)
    settingsWidth = ConfigItem("Layout", "SettingsWidth", 720)
    settingsHeight = ConfigItem("Layout", "SettingsHeight", 540)
    settingsPage = ConfigItem("Layout", "SettingsPage", 0)

    def save(self):
        """Atomic write: write to temp file then os.replace."""
        cfg_file = Path(self.file) if not isinstance(self.file, Path) else self.file
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cfg_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.toDict(), f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(cfg_file))


# ── Keyring helpers ───────────────────────────────────────────────────


def get_api_key() -> str:
    return keyring.get_password(_SERVICE_NAME, _ACCOUNT_API_KEY) or ""


def set_api_key(key: str) -> None:
    keyring.set_password(_SERVICE_NAME, _ACCOUNT_API_KEY, key)


def get_shangdao_api_key() -> str:
    return keyring.get_password(_SERVICE_NAME, _ACCOUNT_SHANGDAO_KEY) or ""


def set_shangdao_api_key(key: str) -> None:
    keyring.set_password(_SERVICE_NAME, _ACCOUNT_SHANGDAO_KEY, key)


def get_search_api_key() -> str:
    return keyring.get_password(_SERVICE_NAME, _ACCOUNT_SEARCH_KEY) or ""


def set_search_api_key(key: str) -> None:
    keyring.set_password(_SERVICE_NAME, _ACCOUNT_SEARCH_KEY, key)


def get_litellm_provider_api_key(provider: str) -> str:
    return keyring.get_password(
        _SERVICE_NAME, f"litellm_{provider}_api_key"
    ) or ""


def set_litellm_provider_api_key(provider: str, key: str) -> None:
    keyring.set_password(_SERVICE_NAME, f"litellm_{provider}_api_key", key)


# ── Ensure directories exist ──────────────────────────────────────────

def _ensure_dirs() -> None:
    for d in [
        CONFIG_DIR, DATA_DIR, SESSIONS_DIR, NOTES_DIR, NOTES_IMAGES_DIR,
        TRASH_DIR, TOOLS_DIR, USER_TOOLS_DIR, TOOL_RUNTIME_DIR,
        TOOL_SITE_PACKAGES,
    ]:
        d.mkdir(parents=True, exist_ok=True)


_ensure_dirs()

# ── Singleton initialization ──────────────────────────────────────────

cfg = AppConfig()

# Run migration before loading (converts old format if needed)
from app.core.config_migrate import migrate_config  # noqa: E402
migrate_config(CONFIG_DIR)

qconfig.load(str(CONFIG_DIR / "app_config.json"), cfg)
