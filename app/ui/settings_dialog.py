from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.ui.style import THEMES

_SEARCH_PROVIDERS = [
    ("ddg", "DuckDuckGo（免费，无需 Key）"),
    ("bing", "Bing Search"),
    ("tavily", "Tavily"),
    ("brave", "Brave Search"),
]

_KEY_HINTS = {
    "ddg": "DuckDuckGo 无需 API Key",
    "bing": "Azure Bing Search API Key（portal.azure.com）",
    "tavily": "Tavily API Key（tavily.com）",
    "brave": "Brave Search API Key（api.search.brave.com）",
}


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # ── API tab ───────────────────────────────────────────────────
        api_w = QWidget()
        api_form = QFormLayout(api_w)

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("https://api.openai.com/v1")
        api_form.addRow("API 地址:", self._base_url)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-…")
        api_form.addRow("API Key:", self._api_key)

        self._model = QLineEdit()
        self._model.setPlaceholderText("gpt-4o")
        api_form.addRow("模型:", self._model)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(256, 65536)
        self._max_tokens.setSingleStep(256)
        api_form.addRow("最大 Token:", self._max_tokens)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(1)
        api_form.addRow("Temperature:", self._temperature)

        tabs.addTab(api_w, "API")

        # ── Window tab ────────────────────────────────────────────────
        win_w = QWidget()
        win_form = QFormLayout(win_w)

        self._opacity = QDoubleSpinBox()
        self._opacity.setRange(0.3, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setDecimals(2)
        win_form.addRow("透明度:", self._opacity)

        self._always_on_top = QCheckBox("始终置顶")
        win_form.addRow("", self._always_on_top)

        self._edge_snap = QCheckBox("顶栏吸附")
        win_form.addRow("", self._edge_snap)

        self._theme_combo = QComboBox()
        for key, t in THEMES.items():
            self._theme_combo.addItem(t["name"], key)
        win_form.addRow("主题:", self._theme_combo)

        tabs.addTab(win_w, "窗口")

        # ── Tools tab ─────────────────────────────────────────────────
        tools_w = QWidget()
        tools_form = QFormLayout(tools_w)

        # Search provider
        self._search_provider = QComboBox()
        for data, label in _SEARCH_PROVIDERS:
            self._search_provider.addItem(label, data)
        self._search_provider.currentIndexChanged.connect(self._on_provider_changed)
        tools_form.addRow("搜索引擎:", self._search_provider)

        # Search API key
        self._search_key = QLineEdit()
        self._search_key.setEchoMode(QLineEdit.EchoMode.Password)
        tools_form.addRow("搜索 API Key:", self._search_key)

        # File save directory
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        self._save_dir = QLineEdit()
        self._save_dir.setPlaceholderText(str(Path.home() / "Downloads"))
        browse_btn = QPushButton("浏览…")
        browse_btn.setFixedWidth(60)
        browse_btn.clicked.connect(self._browse_save_dir)
        save_layout.addWidget(self._save_dir)
        save_layout.addWidget(browse_btn)
        tools_form.addRow("文件保存目录:", save_row)

        tabs.addTab(tools_w, "工具")

        layout.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------ helpers
    def _on_provider_changed(self, _index: int):
        provider = self._search_provider.currentData()
        is_free = provider == "ddg"
        self._search_key.setEnabled(not is_free)
        self._search_key.setPlaceholderText(_KEY_HINTS.get(provider, "API Key"))

    def _browse_save_dir(self):
        current = self._save_dir.text().strip() or str(Path.home() / "Downloads")
        path = QFileDialog.getExistingDirectory(self, "选择文件保存目录", current)
        if path:
            self._save_dir.setText(path)

    # ------------------------------------------------------------------ load / save
    def _load(self):
        api = self._config.app_config["api"]
        win = self._config.window_config
        self._base_url.setText(api.get("base_url", ""))
        self._api_key.setText(self._config.api_key)
        self._model.setText(api.get("model", ""))
        self._max_tokens.setValue(api.get("max_tokens", 4096))
        self._temperature.setValue(api.get("temperature", 0.7))
        self._opacity.setValue(win.get("opacity", 0.97))
        self._always_on_top.setChecked(win.get("always_on_top", True))
        self._edge_snap.setChecked(win.get("edge_snap", True))
        theme = win.get("theme", "classic")
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        # Tools tab
        ws = self._config.get_tool_params("web_search")
        provider = ws.get("provider", "ddg")
        pidx = self._search_provider.findData(provider)
        if pidx >= 0:
            self._search_provider.setCurrentIndex(pidx)
        self._search_key.setText(ws.get("api_key", ""))
        self._on_provider_changed(self._search_provider.currentIndex())  # sync enable state

        sf = self._config.get_tool_params("save_file")
        self._save_dir.setText(sf.get("save_dir", ""))

    def _save(self):
        self._config.update_api_config(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
        )
        self._config.update_window_config(
            opacity=self._opacity.value(),
            always_on_top=self._always_on_top.isChecked(),
            theme=self._theme_combo.currentData(),
            edge_snap=self._edge_snap.isChecked(),
        )
        self._config.update_tools_config(
            {
                "web_search": {
                    "provider": self._search_provider.currentData(),
                    "api_key": self._search_key.text().strip(),
                },
                "save_file": {
                    "save_dir": self._save_dir.text().strip(),
                },
            }
        )
        self.accept()
