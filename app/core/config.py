"""
声明式配置模块，基于 qfluentwidgets QConfig。

用法:
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
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
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


def get_shangdao_model_meta(model: str) -> dict | None:
    """Return request metadata for built-in or user-defined Shangdao models."""
    model = (model or "").strip()
    if not model:
        return None
    if model in SHANGDAO_MODELS:
        return SHANGDAO_MODELS[model]
    return {
        "path_prefix": f"CMHK-LMMP-PRD_{model}/CMHK-LMMP-PRD",
        "body_model_field": "model",
        "body_model_value": model,
    }


# Substrings that mark an OpenAI-compatible model name as vision-capable.
# Used only for the "auto" heuristic; users can override via visionSupport.
_VISION_MODEL_MARKERS = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision",
    "o1", "o3", "o4",
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    "gemini",
    "vl", "vision", "llava", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "pixtral", "internvl", "minicpm-v", "glm-4v", "step-1v",
)


def model_supports_vision(model: str) -> bool:
    """Heuristic: does this OpenAI-compatible model name imply image input?"""
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(marker in name for marker in _VISION_MODEL_MARKERS)


def current_vision_enabled() -> bool:
    """Whether the active OpenAI-type model can receive image pixels.

    Resolves the user override (visionSupport = on/off) or falls back to a
    name-based heuristic ("auto"). Only meaningful for api_type == 'openai';
    shangdao/litellm callers should make their own determination.
    """
    setting = (cfg.get(cfg.visionSupport) or "auto").strip().lower()
    if setting == "on":
        return True
    if setting == "off":
        return False
    return model_supports_vision(cfg.get(cfg.model))


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
    # Dark
    "warm_night", "obsidian", "morandi_dusk",
    "tokyo_night", "mocha", "rose_pine", "nord", "everforest",
    # Light
    "almond", "misty", "sage", "morandi_clay",
    "morandi_haze", "morandi_olive", "morandi_lilac",
    "latte", "rose_pine_dawn",
]

# ── Keyring constants ─────────────────────────────────────────────────

_SERVICE_NAME = "ai-agent-desktop"
_ACCOUNT_API_KEY = "api_key"
_ACCOUNT_SHANGDAO_KEY = "shangdao_api_key"
_ACCOUNT_SEARCH_KEY = "web_search_api_key"


# ── AppConfig declaration ─────────────────────────────────────────────


class AppConfig(QConfig):
    """应用配置类，所有配置项为类属性，支持信号通知变更。"""

    # -- Appearance --
    theme = OptionsConfigItem(
        "Appearance", "Theme", "almond", OptionsValidator(THEME_OPTIONS)
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
    # 当前 OpenAI 兼容模型是否支持多模态识图（发送图片像素）。
    # "auto" = 按模型名启发式推断；"on"/"off" = 用户手动覆盖。
    visionSupport = OptionsConfigItem(
        "API", "VisionSupport", "auto",
        OptionsValidator(["auto", "on", "off"]),
    )

    # -- Shangdao --
    shangdaoEnabled = ConfigItem("Shangdao", "Enabled", False, BoolValidator())
    shangdaoBaseUrl = ConfigItem(
        "Shangdao", "BaseUrl", "https://api.example.com"
    )
    shangdaoModel = ConfigItem("Shangdao", "Model", "Qwen3_235B")
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
    toolWorkspace = ConfigItem("Tools", "Workspace", "")
    saveDir = ConfigItem("Tools", "SaveDir", "")
    toolStates = ConfigItem("Tools", "ToolStates", {})

    # -- Hotkeys --
    hotkeyScreenshot = ConfigItem("Hotkeys", "Screenshot", "ctrl+alt+a")
    hotkeyNewNote = ConfigItem("Hotkeys", "NewNote", "ctrl+alt+n")
    hotkeyToggleWindow = ConfigItem(
        "Hotkeys", "ToggleWindow", "ctrl+alt+space"
    )
    hotkeyQuickAsk = ConfigItem("Hotkeys", "QuickAsk", "ctrl+alt+q")
    hotkeySelection = ConfigItem("Hotkeys", "Selection", "ctrl+alt+e")

    # -- Selection (划词即行动) --
    selectionFloatEnabled = ConfigItem(
        "Selection", "FloatEnabled", True, BoolValidator()
    )
    # 各划词动作的显隐开关（控制浮标上是否出现对应按钮）。
    selectionExplainEnabled = ConfigItem(
        "Selection", "ExplainEnabled", True, BoolValidator()
    )
    selectionNoteEnabled = ConfigItem(
        "Selection", "NoteEnabled", True, BoolValidator()
    )
    # 「连续解释」显隐开关（一组管「连续解释」与「＋新开连续」两个浮标按钮）。
    selectionContinueExplainEnabled = ConfigItem(
        "Selection", "ContinueExplainEnabled", True, BoolValidator()
    )
    # 「改写回填」显隐开关（一组管 润色 / 翻译 / 订正 三个浮标按钮）。
    selectionRewriteEnabled = ConfigItem(
        "Selection", "RewriteEnabled", True, BoolValidator()
    )
    # 「解释」动作的自定义提示词；空串表示用内置默认。
    # 含 {text} 占位，运行时填入选中文字；若不含 {text} 则自动在末尾附上选中文字。
    selectionExplainPrompt = ConfigItem("Selection", "ExplainPrompt", "")
    # 三个改写动作的自定义提示词；空串表示用内置默认。占位规则同上。
    selectionPolishPrompt = ConfigItem("Selection", "PolishPrompt", "")
    selectionTranslatePrompt = ConfigItem("Selection", "TranslatePrompt", "")
    selectionFixGrammarPrompt = ConfigItem("Selection", "FixGrammarPrompt", "")
    # 改写回填前是否校验选区未变（多一次 Ctrl+C 换取「不粘到错误位置」的安全）。
    selectionRewriteVerify = ConfigItem(
        "Selection", "RewriteVerify", True, BoolValidator()
    )
    # 当前激活的「阅读会话」id（连续解释的接续目标）；空串表示无激活会话。
    # 至多一个会话激活；连续解释往它累积上下文，新开/切换会改写它。
    activeReadingSessionId = ConfigItem("Selection", "ActiveReadingSessionId", "")

    # -- Layout (persisted, not shown in settings UI) --
    noteListWidth = ConfigItem("Layout", "NoteListWidth", 360)
    noteListVisible = ConfigItem(
        "Layout", "NoteListVisible", True, BoolValidator()
    )
    sessionPanelWidth = ConfigItem("Layout", "SessionPanelWidth", 140)
    settingsWidth = ConfigItem("Layout", "SettingsWidth", 720)
    settingsHeight = ConfigItem("Layout", "SettingsHeight", 540)
    settingsPage = ConfigItem("Layout", "SettingsPage", 0)

    def save(self):
        """原子写入：先写临时文件再 os.replace，防止写入中断导致配置损坏。"""
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
        TRASH_DIR, USER_TOOLS_DIR, TOOL_RUNTIME_DIR,
        TOOL_SITE_PACKAGES, SCREENSHOTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


_ensure_dirs()

# ── Singleton initialization ──────────────────────────────────────────

cfg = AppConfig()

# 加载前先执行迁移（如需要则转换旧格式）
from app.core.config_migrate import migrate_config  # noqa: E402
migrate_config(CONFIG_DIR)

qconfig.load(str(CONFIG_DIR / "app_config.json"), cfg)
