import json
import sys
from pathlib import Path
from typing import Any

import keyring

_SERVICE_NAME = "ai-agent-desktop"
_ACCOUNT_API_KEY = "api_key"
_ACCOUNT_SHANGDAO_KEY = "shangdao_api_key"
_ACCOUNT_LITELLM_KEY = "litellm_api_key"

# 商道模型元数据：URL 路径前缀、请求体中模型字段名及值
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

# LiteLLM 模型模板
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

# PyInstaller 打包后 __file__ 指向临时目录，需要用 exe 所在目录作为根目录
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

DEFAULT_APP_CONFIG: dict = {
    "hotkeys": {
        "screenshot":    "ctrl+alt+a",
        "new_note":      "ctrl+alt+n",
        "toggle_window": "ctrl+alt+space",
        "quick_ask":     "ctrl+alt+q",
    },
    "api": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o",
        "max_tokens": 4096,
        "temperature": 0.7,
        "system_prompt": "",  # 新增：默认为空，表示使用硬编码默认值
        "api_type": "openai",  # "openai" | "shangdao" | "litellm"
    },
    "shangdao": {
        "enabled": False,
        "base_url": "https://api.example.com",
        "model": "Qwen3_235B",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "litellm": {
        "enabled": False,
        "default_model": "gpt-4o",
        "models": [
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "provider": "openai",
                "enabled": True,
            },
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Claude 3.5 Sonnet",
                "provider": "anthropic",
                "enabled": True,
            },
            {
                "id": "gemini-2.0-flash-exp",
                "name": "Gemini 2.0 Flash",
                "provider": "google",
                "enabled": False,
            },
            {
                "id": "deepseek-chat",
                "name": "DeepSeek Chat",
                "provider": "deepseek",
                "enabled": False,
            },
        ],
    },
    "window": {
        "width": 440,
        "height": 700,
        "theme": "morning",
        "edge_snap": True,
        "edge_snap_width_threshold": 0.4,  # 边缘吸附宽度阈值（40% 屏幕宽度）
        "minimize_to": "tray",  # "tray" | "taskbar"
        "font_size": 15,  # 全局字体大小（px）
    },
}

DEFAULT_PARAMS_CONFIG: dict = {"tools": {}}


class ConfigManager:
    def __init__(self):
        self._ensure_dirs()
        self._app = self._load(CONFIG_DIR / "app_config.json", DEFAULT_APP_CONFIG)
        self._params = self._load(CONFIG_DIR / "params_config.json", DEFAULT_PARAMS_CONFIG)
        self._migrate_key_to_keyring()

    def _migrate_key_to_keyring(self):
        """One-time migration: move plaintext API key from JSON into the system keyring."""
        json_key = self._app["api"].get("api_key", "")
        if json_key:
            keyring.set_password(_SERVICE_NAME, _ACCOUNT_API_KEY, json_key)
            self._app["api"]["api_key"] = ""
            self._write(CONFIG_DIR / "app_config.json", self._app)
    # ------------------------------------------------------------------ dirs
    def _ensure_dirs(self):
        for d in [CONFIG_DIR, DATA_DIR, SESSIONS_DIR, NOTES_DIR, NOTES_IMAGES_DIR, TRASH_DIR, TOOLS_DIR, USER_TOOLS_DIR, TOOL_RUNTIME_DIR, TOOL_SITE_PACKAGES]:
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ io
    def _load(self, path: Path, default: dict) -> dict:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge(default, data)
            except Exception:
                pass
        self._write(path, default)
        return dict(default)

    @staticmethod
    def _merge(base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._merge(result[k], v)
            else:
                result[k] = v
        return result

    @staticmethod
    def _write(path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------ api props
    @property
    def api_base_url(self) -> str:
        return self._app["api"]["base_url"]

    @property
    def api_key(self) -> str:
        return keyring.get_password(_SERVICE_NAME, _ACCOUNT_API_KEY) or ""

    @property
    def model(self) -> str:
        return self._app["api"]["model"]

    @property
    def max_tokens(self) -> int:
        return self._app["api"]["max_tokens"]

    @property
    def temperature(self) -> float:
        return self._app["api"]["temperature"]

    @property
    def system_prompt(self) -> str:
        """返回用户自定义的 System Prompt，如果为空则返回空字符串（由调用方处理默认值）"""
        return self._app["api"].get("system_prompt", "")

    @property
    def window_config(self) -> dict:
        return self._app["window"]

    @property
    def theme(self) -> str:
        return self._app["window"].get("theme", "morning")

    @property
    def edge_snap_width_threshold(self) -> float:
        """边缘吸附宽度阈值（相对于屏幕宽度的比例）"""
        return self._app["window"].get("edge_snap_width_threshold", 0.4)

    @property
    def minimize_to(self) -> str:
        """最小化目标：'tray' 或 'taskbar'"""
        return self._app["window"].get("minimize_to", "tray")

    @property
    def font_size(self) -> int:
        """全局字体大小（px）"""
        return self._app["window"].get("font_size", 15)

    @property
    def api_type(self) -> str:
        """当前使用的 API 类型：'openai' 或 'shangdao'"""
        return self._app["api"].get("api_type", "openai")

    # ------------------------------------------------------------------ shangdao props
    @property
    def shangdao_config(self) -> dict:
        return self._app.get("shangdao", {})

    @property
    def shangdao_enabled(self) -> bool:
        return self._app.get("shangdao", {}).get("enabled", False)

    @property
    def shangdao_base_url(self) -> str:
        return self._app.get("shangdao", {}).get("base_url", "https://api.example.com")

    @property
    def shangdao_model(self) -> str:
        return self._app.get("shangdao", {}).get("model", "Qwen3_235B")

    def get_shangdao_api_key(self) -> str:
        return keyring.get_password(_SERVICE_NAME, _ACCOUNT_SHANGDAO_KEY) or ""

    def set_shangdao_api_key(self, key: str):
        keyring.set_password(_SERVICE_NAME, _ACCOUNT_SHANGDAO_KEY, key)

    # ------------------------------------------------------------------ litellm props
    @property
    def litellm_config(self) -> dict:
        """返回完整的 LiteLLM 配置"""
        return self._app.get("litellm", {})

    @property
    def litellm_enabled(self) -> bool:
        """LiteLLM 是否启用"""
        return self._app.get("litellm", {}).get("enabled", False)

    def get_litellm_provider_api_key(self, provider: str) -> str:
        """获取指定 provider 的 API Key"""
        return keyring.get_password(_SERVICE_NAME, f"litellm_{provider}_api_key") or ""

    def set_litellm_provider_api_key(self, provider: str, key: str):
        """设置指定 provider 的 API Key"""
        keyring.set_password(_SERVICE_NAME, f"litellm_{provider}_api_key", key)

    @property
    def litellm_providers(self) -> list[str]:
        """返回所有 provider 列表（去重）"""
        return list(set(m["provider"] for m in self.litellm_models))

    @property
    def litellm_default_model(self) -> str:
        """正常聊天使用的默认模型"""
        return self._app.get("litellm", {}).get("default_model", "gpt-4o")

    @property
    def litellm_models(self) -> list[dict]:
        """返回所有可用模型列表"""
        return self._app.get("litellm", {}).get("models", [])

    @property
    def litellm_enabled_models(self) -> list[dict]:
        """返回启用的模型列表（用于多模型调用）"""
        return [m for m in self.litellm_models if m.get("enabled", False)]

    def get_litellm_model_by_id(self, model_id: str) -> dict | None:
        """根据 model_id 查找模型配置"""
        for model in self.litellm_models:
            if model.get("id") == model_id:
                return model
        return None

    def update_litellm_config(self, **kwargs):
        """更新 LiteLLM 配置（不包括 API Key）"""
        self._app.setdefault("litellm", {}).update(kwargs)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_litellm_model_enabled(self, model_id: str, enabled: bool):
        """更新指定模型的启用状态"""
        for model in self._app.get("litellm", {}).get("models", []):
            if model.get("id") == model_id:
                model["enabled"] = enabled
                self._write(CONFIG_DIR / "app_config.json", self._app)
                return
        raise ValueError(f"Model {model_id} not found in litellm.models")

    def set_litellm_models(self, models: list[dict]):
        """批量设置 LiteLLM 模型列表"""
        self._app.setdefault("litellm", {})["models"] = models
        self._write(CONFIG_DIR / "app_config.json", self._app)
    @property
    def app_config(self) -> dict:
        return self._app

    @property
    def params_config(self) -> dict:
        return self._params

    # ------------------------------------------------------------------ write
    def update_api_config(self, **kwargs):
        if "api_key" in kwargs:
            keyring.set_password(_SERVICE_NAME, _ACCOUNT_API_KEY, kwargs.pop("api_key"))
        self._app["api"].update(kwargs)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_shangdao_config(self, api_key: str | None = None, **kwargs):
        """更新商道配置。api_key 存入 keyring。"""
        self._app.setdefault("shangdao", {}).update(kwargs)
        if api_key is not None:
            self.set_shangdao_api_key(api_key)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_window_config(self, **kwargs):
        self._app["window"].update(kwargs)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def get_tool_params(self, tool_name: str) -> dict:
        return self._params["tools"].get(tool_name, {})

    def set_tool_param(self, tool_name: str, param: str, value: Any):
        self._params["tools"].setdefault(tool_name, {})[param] = value
        self._write(CONFIG_DIR / "params_config.json", self._params)

    @property
    def hotkeys(self) -> dict:
        return self._app.get("hotkeys", DEFAULT_APP_CONFIG["hotkeys"])

    def update_hotkeys(self, updates: dict):
        self._app.setdefault("hotkeys", {}).update(updates)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    # ------------------------------------------------------------------ tool states
    def get_tool_enabled(self, tool_name: str) -> bool:
        return self._app.get("tool_states", {}).get(tool_name, True)

    def set_tool_enabled(self, tool_name: str, enabled: bool):
        self._app.setdefault("tool_states", {})[tool_name] = enabled
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_tools_config(self, updates: dict):
        """Batch-update tool params. updates = {tool_name: {param: value, ...}, ...}"""
        for tool_name, params in updates.items():
            self._params["tools"].setdefault(tool_name, {}).update(params)
        self._write(CONFIG_DIR / "params_config.json", self._params)

    # ------------------------------------------------------------------ litellm model management
    def add_litellm_model(self, model_id: str, name: str, provider: str, enabled: bool = False):
        """添加模型（去重）"""
        models = self._app.setdefault("litellm", {}).setdefault("models", [])

        # 检查是否已存在
        if any(m["id"] == model_id for m in models):
            raise ValueError(f"模型 {model_id} 已存在")

        models.append({
            "id": model_id,
            "name": name,
            "provider": provider,
            "enabled": enabled,
        })
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def remove_litellm_model(self, model_id: str):
        """删除模型"""
        models = self._app.get("litellm", {}).get("models", [])
        original_len = len(models)

        self._app["litellm"]["models"] = [m for m in models if m["id"] != model_id]

        if len(self._app["litellm"]["models"]) == original_len:
            raise ValueError(f"模型 {model_id} 不存在")

        # 如果删除的是默认模型，重置为第一个模型
        if self.litellm_default_model == model_id:
            remaining = self._app["litellm"]["models"]
            if remaining:
                self._app["litellm"]["default_model"] = remaining[0]["id"]

        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_litellm_model(self, model_id: str, **kwargs):
        """更新模型信息（name, enabled）"""
        models = self._app.get("litellm", {}).get("models", [])

        for model in models:
            if model["id"] == model_id:
                # 只允许更新 name 和 enabled
                if "name" in kwargs:
                    model["name"] = kwargs["name"]
                if "enabled" in kwargs:
                    model["enabled"] = kwargs["enabled"]
                self._write(CONFIG_DIR / "app_config.json", self._app)
                return

        raise ValueError(f"模型 {model_id} 不存在")

    @staticmethod
    def get_model_templates() -> dict[str, list[dict]]:
        """获取模型模板（硬编码）"""
        return MODEL_TEMPLATES
