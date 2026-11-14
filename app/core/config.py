"""
声明式配置模块，基于 qfluentwidgets QConfig。

用法:
    from app.core.config import cfg, get_litellm_provider_api_key

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

from app.core.runtime_paths import (BASE_DIR, BUNDLE_DIR, CONFIG_DIR, DATA_DIR, SESSIONS_DIR,
    NOTES_DIR, NOTES_IMAGES_DIR, TRASH_DIR, SCREENSHOTS_DIR, TOOLS_DIR, ASSETS_DIR,
    USER_TOOLS_DIR, TOOL_RUNTIME_DIR, TOOL_SITE_PACKAGES, TOOL_BUILDS_DIR)

# ── Model metadata ────────────────────────────────────────────────────

from app.core.model_capabilities import model_supports_vision


def current_vision_enabled() -> bool:
    """Whether the active model can receive image pixels.

    Resolves the user override (visionSupport = on/off) or falls back to a
    name-based heuristic ("auto") on the current LiteLLM default model.
    """
    setting = (cfg.get(cfg.visionSupport) or "auto").strip().lower()
    if setting == "on":
        return True
    if setting == "off":
        return False
    return model_supports_vision(cfg.get(cfg.litellmDefaultModel))


# 模型模板：从模板快速添加模型时的候选清单。
# provider 键选择共用 HTTP 传输层的厂商配置：
#   openai / anthropic / gemini / deepseek / meta_llama / dashscope(Qwen) / zai(GLM)
# api_base 留空即走该 provider 默认端点，用户只需在设置页填对应 API Key。
MODEL_TEMPLATES: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol"},
        {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra"},
        {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna"},
        {"id": "gpt-5.5", "name": "GPT-5.5"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
        {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
        {"id": "claude-fable-5", "name": "Claude Fable 5"},
        {"id": "claude-haiku-5", "name": "Claude Haiku 5"},
    ],
    "gemini": [
        {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash"},
        {"id": "gemini-3.5-pro", "name": "Gemini 3.5 Pro"},
        {"id": "gemini-3.1-pro", "name": "Gemini 3.1 Pro"},
    ],
    "meta_llama": [
        {"id": "Llama-4-Maverick", "name": "Llama 4 Maverick"},
        {"id": "Llama-4-Scout", "name": "Llama 4 Scout"},
        {"id": "Llama-3.3-70B-Instruct", "name": "Llama 3.3"},
    ],
    "deepseek": [
        {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
        {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash"},
    ],
    "dashscope": [
        {"id": "qwen3-max", "name": "Qwen3 Max"},
        {"id": "qwen3.6-plus", "name": "Qwen3.6 Plus"},
    ],
    "zai": [
        {"id": "glm-5.1", "name": "GLM-5.1"},
    ],
}

# 全新用户的默认模型集（litellmModels 的初始值来源，单一来源）。
# 从各 provider 模板汇总；第一条设为默认启用，其余仅入列供选择/编辑。
# 用户只需在设置页为想用的 provider 填 API Key 即可开箱使用。
DEFAULT_LITELLM_MODEL = "deepseek-v4-flash"

DEFAULT_LITELLM_MODELS: list[dict] = [
    {
        "id": m["id"],
        "name": m["name"],
        "provider": provider,
        "api_base": "",
        "enabled": m["id"] == DEFAULT_LITELLM_MODEL,
    }
    for provider, models in MODEL_TEMPLATES.items()
    for m in models
]

# ── Theme list (for OptionsValidator) ─────────────────────────────────

THEME_OPTIONS = [
    # Dark
    "warm_night", "obsidian",
    "mocha", "rose_pine", "nord", "everforest", "everforest_bright",
    "solarized", "gruvbox",
    # Light
    "almond", "misty", "sage", "morandi_clay",
    "morandi_haze", "morandi_olive", "morandi_lilac",
    "latte", "rose_pine_dawn",
    "solarized_light", "gruvbox_light",
    "cloud_white", "ivory_paper", "snow_white", "pure_white",
    "warm_linen", "warm_almond",
]

# ── Keyring constants ─────────────────────────────────────────────────

_SERVICE_NAME = "ai-agent-desktop"
_ACCOUNT_SEARCH_KEY = "web_search_api_key"

# ── Hotkey defaults (single source of truth) ──────────────────────────
# config 项默认值、迁移、HotkeyManager、设置页都从这里取默认组合键，
# 避免默认值散落多处产生分歧。键为 action id，值为 keyboard 组合串。
from app.core.hotkey_actions import DEFAULT_HOTKEYS


# ── AppConfig declaration ─────────────────────────────────────────────


class AppConfig(QConfig):
    """应用配置类，所有配置项为类属性，支持信号通知变更。"""

    # -- Appearance --
    # 界面语言：默认英文（en），可切中文（zh）。切换后需重启生效。
    language = OptionsConfigItem(
        "Appearance", "Language", "en", OptionsValidator(["en", "zh"])
    )
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
        "Window", "MinimizeTo", "taskbar", OptionsValidator(["tray", "taskbar"])
    )
    windowWidth = RangeConfigItem(
        "Window", "Width", 440, RangeValidator(300, 800)
    )
    windowHeight = RangeConfigItem(
        "Window", "Height", 700, RangeValidator(400, 1200)
    )

    # -- API --
    # Deprecated storage discriminator, retained only for old config compatibility.
    # Runtime dispatch uses each model's api_protocol, never this value.
    apiType = OptionsConfigItem(
        "API", "ApiType", "litellm",
        OptionsValidator(["litellm"]),
    )
    maxTokens = RangeConfigItem(
        "API", "MaxTokens", 4096, RangeValidator(256, 65536)
    )
    temperature = RangeConfigItem(
        "API", "Temperature", 0.7, RangeValidator(0.0, 2.0)
    )
    topP = RangeConfigItem(
        "API", "TopP", 1.0, RangeValidator(0.0, 1.0)
    )
    systemPrompt = ConfigItem("API", "SystemPrompt", "")
    # 当前模型是否支持多模态识图（发送图片像素）。
    # "auto" = 按模型名启发式推断；"on"/"off" = 用户手动覆盖。
    visionSupport = OptionsConfigItem(
        "API", "VisionSupport", "auto",
        OptionsValidator(["auto", "on", "off"]),
    )

    # Legacy storage names remain stable to preserve existing config and keyring entries.
    litellmDefaultModel = ConfigItem("LiteLLM", "DefaultModel", DEFAULT_LITELLM_MODEL)
    litellmModels = ConfigItem("LiteLLM", "Models", DEFAULT_LITELLM_MODELS)

    # -- Tools --
    searchProvider = OptionsConfigItem(
        "Tools", "SearchProvider", "bocha",
        OptionsValidator(["ddg", "bing", "tavily", "brave", "bocha"]),
    )
    toolWorkspace = ConfigItem("Tools", "Workspace", "")
    saveDir = ConfigItem("Tools", "SaveDir", "")
    toolStates = ConfigItem("Tools", "ToolStates", {})
    # 是否已对全新用户播种过高风险工具的默认关闭状态（只播种一次，之后尊重用户选择）。
    toolDefaultsSeeded = ConfigItem("Tools", "DefaultsSeeded", False, BoolValidator())

    # -- Hotkeys --
    hotkeyScreenshot = ConfigItem(
        "Hotkeys", "Screenshot", DEFAULT_HOTKEYS["screenshot"]
    )
    hotkeyNewNote = ConfigItem(
        "Hotkeys", "NewNote", DEFAULT_HOTKEYS["new_note"]
    )
    hotkeyToggleWindow = ConfigItem(
        "Hotkeys", "ToggleWindow", DEFAULT_HOTKEYS["toggle_window"]
    )
    hotkeyQuickAsk = ConfigItem(
        "Hotkeys", "QuickAsk", DEFAULT_HOTKEYS["quick_ask"]
    )
    hotkeySelection = ConfigItem(
        "Hotkeys", "Selection", DEFAULT_HOTKEYS["selection"]
    )
    hotkeyBindings = ConfigItem("Hotkeys", "Bindings", {})

    # -- Selection (划词即行动) --
    selectionFloatEnabled = ConfigItem(
        "Selection", "FloatEnabled", True, BoolValidator()
    )
    # Ordered built-in/custom buttons, visibility and toolbar placement.
    selectionActions = ConfigItem("Selection", "Actions", {})
    # 旧版显隐开关仅用于首次迁移；新版逐按钮状态由 selectionActions 保存。
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
    # 润色仍为内置；翻译和订正提示词在首次迁移时转入 selectionActions。
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
        TOOL_SITE_PACKAGES, TOOL_BUILDS_DIR, SCREENSHOTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


_ensure_dirs()

# ── Singleton initialization ──────────────────────────────────────────

cfg = AppConfig()

# 加载前先执行迁移（如需要则转换旧格式）
from app.core.config_migrate import migrate_config  # noqa: E402
migrate_config(CONFIG_DIR)

qconfig.load(str(CONFIG_DIR / "app_config.json"), cfg)
