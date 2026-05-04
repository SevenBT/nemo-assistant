import json
import sys
from pathlib import Path
from typing import Any

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
    "api": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o",
        "max_tokens": 4096,
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
    },
}

DEFAULT_PARAMS_CONFIG: dict = {"tools": {}}


class ConfigManager:
    def __init__(self):
        self._ensure_dirs()
        self._app = self._load(CONFIG_DIR / "app_config.json", DEFAULT_APP_CONFIG)
        self._params = self._load(CONFIG_DIR / "params_config.json", DEFAULT_PARAMS_CONFIG)

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
        return self._app["api"]["api_key"]

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
    def window_config(self) -> dict:
        return self._app["window"]

    @property
    def theme(self) -> str:
        return self._app["window"].get("theme", "classic")

    @property
    def app_config(self) -> dict:
        return self._app

    @property
    def params_config(self) -> dict:
        return self._params

    # ------------------------------------------------------------------ write
    def update_api_config(self, **kwargs):
        self._app["api"].update(kwargs)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def update_window_config(self, **kwargs):
        self._app["window"].update(kwargs)
        self._write(CONFIG_DIR / "app_config.json", self._app)

    def get_tool_params(self, tool_name: str) -> dict:
        return self._params["tools"].get(tool_name, {})

    def set_tool_param(self, tool_name: str, param: str, value: Any):
        self._params["tools"].setdefault(tool_name, {})[param] = value
        self._write(CONFIG_DIR / "params_config.json", self._params)

    def update_tools_config(self, updates: dict):
        """Batch-update tool params. updates = {tool_name: {param: value, ...}, ...}"""
        for tool_name, params in updates.items():
            self._params["tools"].setdefault(tool_name, {}).update(params)
        self._write(CONFIG_DIR / "params_config.json", self._params)
