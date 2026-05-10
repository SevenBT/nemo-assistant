import json
import sys
from pathlib import Path
from typing import Any

import keyring

_SERVICE_NAME = "ai-agent-desktop"
_ACCOUNT_API_KEY = "api_key"
_ACCOUNT_SHANGDAO_KEY = "shangdao_api_key"

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
        "api_type": "openai",  # "openai" | "shangdao"
    },
    "shangdao": {
        "enabled": False,
        "base_url": "https://api.example.com",
        "model": "Qwen3_235B",
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "window": {
        "width": 440,
        "height": 700,
        "x": 100,
        "y": 80,
        "opacity": 0.97,
        "always_on_top": True,
        "theme": "classic",
        "edge_snap": True,
        "edge_snap_width_threshold": 0.4,  # 边缘吸附宽度阈值（40% 屏幕宽度）
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
        for d in [CONFIG_DIR, DATA_DIR, SESSIONS_DIR, NOTES_DIR, NOTES_IMAGES_DIR, TRASH_DIR, TOOLS_DIR]:
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
        return self._app["window"].get("theme", "classic")

    @property
    def edge_snap_width_threshold(self) -> float:
        """边缘吸附宽度阈值（相对于屏幕宽度的比例）"""
        return self._app["window"].get("edge_snap_width_threshold", 0.4)

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

    def update_tools_config(self, updates: dict):
        """Batch-update tool params. updates = {tool_name: {param: value, ...}, ...}"""
        for tool_name, params in updates.items():
            self._params["tools"].setdefault(tool_name, {}).update(params)
        self._write(CONFIG_DIR / "params_config.json", self._params)
