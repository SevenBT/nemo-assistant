from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager, SHANGDAO_MODELS
from app.core.constants import DEFAULT_USER_PROMPT
from app.ui.hotkey_settings_widget import HotkeySettingsWidget
from app.ui.style import THEMES

_SEARCH_PROVIDERS = [
    ("ddg", "DuckDuckGo（免费，无需 Key）"),
    ("bing", "Bing Search"),
    ("tavily", "Tavily"),
    ("brave", "Brave Search"),
    ("bocha", "博查 AI 搜索"),
]

_KEY_HINTS = {
    "ddg": "DuckDuckGo 无需 API Key",
    "bing": "Azure Bing Search API Key（portal.azure.com）",
    "tavily": "Tavily API Key（tavily.com）",
    "brave": "Brave Search API Key（api.search.brave.com）",
    "bocha": "博查 API Key（bocha.ai）",
}


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, hotkey_mgr=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._hotkey_mgr = hotkey_mgr
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

        # ── 商道 API 分组（可折叠）────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        api_form.addRow(sep)

        # 折叠标题行：启用开关 + 展开/收起按钮
        sd_header = QWidget()
        sd_header_layout = QHBoxLayout(sd_header)
        sd_header_layout.setContentsMargins(0, 0, 0, 0)

        self._sd_enabled = QCheckBox("启用商道 API")
        self._sd_enabled.toggled.connect(self._on_sd_toggled)
        sd_header_layout.addWidget(self._sd_enabled)
        sd_header_layout.addStretch()

        self._sd_toggle_btn = QPushButton("▶ 展开配置")
        self._sd_toggle_btn.setFixedWidth(90)
        self._sd_toggle_btn.setFlat(True)
        self._sd_toggle_btn.clicked.connect(self._on_sd_expand)
        sd_header_layout.addWidget(self._sd_toggle_btn)

        api_form.addRow(sd_header)

        # 折叠内容容器
        self._sd_detail = QWidget()
        sd_detail_form = QFormLayout(self._sd_detail)
        sd_detail_form.setContentsMargins(0, 0, 0, 0)

        self._sd_base_url = QLineEdit()
        self._sd_base_url.setPlaceholderText("https://api.example.com")
        sd_detail_form.addRow("API 地址:", self._sd_base_url)

        self._sd_api_key = QLineEdit()
        self._sd_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._sd_api_key.setPlaceholderText("API Key")
        sd_detail_form.addRow("API Key:", self._sd_api_key)

        self._sd_model = QComboBox()
        for name in SHANGDAO_MODELS:
            self._sd_model.addItem(name, name)
        sd_detail_form.addRow("模型:", self._sd_model)

        self._sd_max_tokens = QSpinBox()
        self._sd_max_tokens.setRange(256, 65536)
        self._sd_max_tokens.setSingleStep(256)
        sd_detail_form.addRow("最大 Token:", self._sd_max_tokens)

        self._sd_temperature = QDoubleSpinBox()
        self._sd_temperature.setRange(0.0, 2.0)
        self._sd_temperature.setSingleStep(0.1)
        self._sd_temperature.setDecimals(1)
        sd_detail_form.addRow("Temperature:", self._sd_temperature)

        self._sd_detail.setVisible(False)  # 默认折叠
        api_form.addRow(self._sd_detail)

        tabs.addTab(api_w, "API")

        # ── Model tab ─────────────────────────────────────────────────
        model_w = QWidget()
        model_layout = QVBoxLayout(model_w)

        # System Prompt 标签
        prompt_label = QLabel("System Prompt:")
        model_layout.addWidget(prompt_label)

        # 多行编辑器
        self._system_prompt_edit = QPlainTextEdit()
        self._system_prompt_edit.setMinimumHeight(200)
        self._system_prompt_edit.setPlaceholderText("自定义 AI 行为风格和回复方式…")
        model_layout.addWidget(self._system_prompt_edit)

        # 恢复默认按钮
        reset_btn = QPushButton("恢复默认")
        reset_btn.setFixedWidth(100)
        reset_btn.clicked.connect(self._reset_system_prompt)
        model_layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # 管理预设角色按钮
        preset_btn = QPushButton("管理预设角色")
        preset_btn.setFixedWidth(120)
        preset_btn.clicked.connect(self._manage_presets)
        model_layout.addWidget(preset_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        model_layout.addStretch()  # 底部留白

        tabs.addTab(model_w, "模型")

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

        self._edge_snap_threshold = QDoubleSpinBox()
        self._edge_snap_threshold.setRange(0.2, 0.8)  # 20% - 80%
        self._edge_snap_threshold.setSingleStep(0.05)
        self._edge_snap_threshold.setDecimals(2)
        self._edge_snap_threshold.setSuffix(" (屏幕宽度比例)")
        win_form.addRow("吸附宽度阈值:", self._edge_snap_threshold)

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

        # ── Hotkeys tab ───────────────────────────────────────────────
        self._hotkey_widget = HotkeySettingsWidget(self._config, self._hotkey_mgr)
        tabs.addTab(self._hotkey_widget, "快捷键")

        layout.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------ helpers
    def _on_sd_expand(self):
        visible = not self._sd_detail.isVisible()
        self._sd_detail.setVisible(visible)
        self._sd_toggle_btn.setText("▼ 收起配置" if visible else "▶ 展开配置")

    def _on_sd_toggled(self, enabled: bool):
        """启用/禁用商道时同步普通 API 字段的启用状态。"""
        for w in (self._base_url, self._api_key, self._model,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)

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

    def _reset_system_prompt(self):
        """恢复默认 System Prompt"""
        self._system_prompt_edit.setPlainText(DEFAULT_USER_PROMPT)

    def _manage_presets(self):
        """打开预设角色管理对话框"""
        from app.core.preset_manager import PresetManager
        from app.ui.preset_manager_dialog import PresetManagerDialog

        preset_mgr = PresetManager()
        dialog = PresetManagerDialog(preset_mgr, self)
        dialog.exec()


    # ------------------------------------------------------------------ load / save
    def _load(self):
        api = self._config.app_config["api"]
        win = self._config.window_config
        self._base_url.setText(api.get("base_url", ""))
        self._api_key.setText(self._config.api_key)
        self._model.setText(api.get("model", ""))
        self._max_tokens.setValue(api.get("max_tokens", 4096))
        self._temperature.setValue(api.get("temperature", 0.7))

        # 加载 System Prompt
        self._system_prompt_edit.setPlainText(self._config.system_prompt)

        self._opacity.setValue(win.get("opacity", 0.97))
        self._always_on_top.setChecked(win.get("always_on_top", True))
        self._edge_snap.setChecked(win.get("edge_snap", True))
        self._edge_snap_threshold.setValue(win.get("edge_snap_width_threshold", 0.4))
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

        # 商道配置
        sd = self._config.shangdao_config
        self._sd_enabled.setChecked(sd.get("enabled", False))
        self._sd_base_url.setText(sd.get("base_url", "https://api.example.com"))
        sd_model = sd.get("model", "Qwen3_235B")
        midx = self._sd_model.findData(sd_model)
        if midx >= 0:
            self._sd_model.setCurrentIndex(midx)
        self._sd_api_key.setText(self._config.get_shangdao_api_key())
        self._sd_max_tokens.setValue(sd.get("max_tokens", 2048))
        self._sd_temperature.setValue(sd.get("temperature", 0.7))
        self._on_sd_toggled(sd.get("enabled", False))

    def _save(self):
        enabled = self._sd_enabled.isChecked()
        self._config.update_api_config(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
            system_prompt=self._system_prompt_edit.toPlainText().strip(),
            api_type="shangdao" if enabled else "openai",
        )
        self._config.update_window_config(
            opacity=self._opacity.value(),
            always_on_top=self._always_on_top.isChecked(),
            theme=self._theme_combo.currentData(),
            edge_snap=self._edge_snap.isChecked(),
            edge_snap_width_threshold=self._edge_snap_threshold.value(),
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
        # 商道配置
        self._config.update_shangdao_config(
            api_key=self._sd_api_key.text().strip(),
            enabled=enabled,
            base_url=self._sd_base_url.text().strip(),
            model=self._sd_model.currentData(),
            max_tokens=self._sd_max_tokens.value(),
            temperature=self._sd_temperature.value(),
        )
        self._hotkey_widget.save()
        self.accept()
