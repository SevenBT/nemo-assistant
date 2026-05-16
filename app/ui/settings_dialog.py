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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import MessageBox as FluentMessageBox

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
        api_layout = QVBoxLayout(api_w)

        # 使用 QScrollArea 包裹整个 API 配置区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")

        scroll_content = QWidget()
        api_form = QFormLayout(scroll_content)

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

        # ── LiteLLM API 分组（可折叠）─────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        api_form.addRow(sep2)

        # 折叠标题行：启用开关 + 展开/收起按钮
        ll_header = QWidget()
        ll_header_layout = QHBoxLayout(ll_header)
        ll_header_layout.setContentsMargins(0, 0, 0, 0)

        self._ll_enabled = QCheckBox("启用 LiteLLM")
        self._ll_enabled.toggled.connect(self._on_ll_toggled)
        ll_header_layout.addWidget(self._ll_enabled)
        ll_header_layout.addStretch()

        self._ll_toggle_btn = QPushButton("▶ 展开配置")
        self._ll_toggle_btn.setFixedWidth(90)
        self._ll_toggle_btn.setFlat(True)
        self._ll_toggle_btn.clicked.connect(self._on_ll_expand)
        ll_header_layout.addWidget(self._ll_toggle_btn)

        api_form.addRow(ll_header)

        # 折叠内容容器
        self._ll_detail = QWidget()
        ll_detail_form = QFormLayout(self._ll_detail)
        ll_detail_form.setContentsMargins(0, 0, 0, 0)

        self._ll_default_model = QComboBox()
        ll_detail_form.addRow("默认模型:", self._ll_default_model)

        # API Key 配置
        ll_key_group = QGroupBox("API Key 配置")
        ll_key_layout = QFormLayout(ll_key_group)
        ll_key_layout.setContentsMargins(8, 8, 8, 8)

        # 动态生成每个 provider 的输入框
        self._ll_provider_keys: dict[str, QLineEdit] = {}
        for provider in self._config.litellm_providers:
            key_input = QLineEdit()
            key_input.setEchoMode(QLineEdit.EchoMode.Password)
            key_input.setPlaceholderText(f"输入 {provider.capitalize()} API Key")
            self._ll_provider_keys[provider] = key_input
            ll_key_layout.addRow(f"{provider.capitalize()}:", key_input)

        ll_key_group.setLayout(ll_key_layout)
        ll_detail_form.addRow(ll_key_group)

        # 多模型调用配置
        ll_multi_group = QGroupBox("多模型调用")
        ll_multi_layout = QVBoxLayout(ll_multi_group)
        ll_multi_layout.setContentsMargins(8, 8, 8, 8)
        self._ll_model_rows: dict[str, tuple[QCheckBox, QWidget]] = {}  # model_id -> (checkbox, row_widget)
        self._ll_multi_container = ll_multi_layout  # 保存引用以便动态添加

        # 底部添加按钮
        add_layout = QHBoxLayout()

        template_btn = QPushButton("从模板添加")
        template_btn.clicked.connect(self._add_from_template)
        add_layout.addWidget(template_btn)

        custom_btn = QPushButton("自定义添加")
        custom_btn.clicked.connect(self._add_custom_model)
        add_layout.addWidget(custom_btn)

        add_layout.addStretch()
        ll_multi_layout.addLayout(add_layout)

        ll_detail_form.addRow(ll_multi_group)

        self._ll_detail.setVisible(False)  # 默认折叠
        api_form.addRow(self._ll_detail)

        scroll.setWidget(scroll_content)
        api_layout.addWidget(scroll)

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

        self._edge_snap = QCheckBox("顶栏吸附")
        win_form.addRow("", self._edge_snap)

        self._edge_snap_threshold = QDoubleSpinBox()
        self._edge_snap_threshold.setRange(0.2, 0.8)  # 20% - 80%
        self._edge_snap_threshold.setSingleStep(0.05)
        self._edge_snap_threshold.setDecimals(2)
        self._edge_snap_threshold.setSuffix(" (屏幕宽度比例)")
        win_form.addRow("吸附宽度阈值:", self._edge_snap_threshold)

        self._minimize_to = QComboBox()
        self._minimize_to.addItem("系统托盘", "tray")
        self._minimize_to.addItem("任务栏", "taskbar")
        win_form.addRow("最小化到:", self._minimize_to)

        self._theme_combo = QComboBox()
        for key, t in THEMES.items():
            self._theme_combo.addItem(t["name"], key)
        win_form.addRow("主题:", self._theme_combo)

        self._font_size = QSpinBox()
        self._font_size.setRange(12, 24)
        self._font_size.setSingleStep(1)
        self._font_size.setSuffix(" px")
        win_form.addRow("字体大小:", self._font_size)

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
    def _on_ll_expand(self):
        """展开/收起 LiteLLM 配置"""
        visible = not self._ll_detail.isVisible()
        self._ll_detail.setVisible(visible)
        self._ll_toggle_btn.setText("▼ 收起配置" if visible else "▶ 展开配置")

    def _on_ll_toggled(self, enabled: bool):
        """启用/禁用 LiteLLM 时同步其他 API 字段的启用状态"""
        # LiteLLM 启用时，禁用 OpenAI 和商道配置
        for w in (self._base_url, self._api_key, self._model,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)
        self._sd_enabled.setEnabled(not enabled)

    def _on_sd_expand(self):
        visible = not self._sd_detail.isVisible()
        self._sd_detail.setVisible(visible)
        self._sd_toggle_btn.setText("▼ 收起配置" if visible else "▶ 展开配置")

    def _on_sd_toggled(self, enabled: bool):
        """启用/禁用商道时同步普通 API 字段的启用状态。"""
        for w in (self._base_url, self._api_key, self._model,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)
        self._ll_enabled.setEnabled(not enabled)

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

        self._edge_snap.setChecked(win.get("edge_snap", True))
        self._edge_snap_threshold.setValue(win.get("edge_snap_width_threshold", 0.4))
        minimize_to = win.get("minimize_to", "tray")
        midx = self._minimize_to.findData(minimize_to)
        if midx >= 0:
            self._minimize_to.setCurrentIndex(midx)
        theme = win.get("theme", "morning")
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._font_size.setValue(win.get("font_size", 15))

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

        # LiteLLM 配置
        ll = self._config.litellm_config
        self._ll_enabled.setChecked(ll.get("enabled", False))

        # 填充默认模型下拉框
        self._ll_default_model.clear()
        for model in ll.get("models", []):
            self._ll_default_model.addItem(
                f"{model['name']} ({model['provider']})",
                model["id"]
            )
        # 设置当前默认模型
        default_model = ll.get("default_model", "gpt-4o")
        didx = self._ll_default_model.findData(default_model)
        if didx >= 0:
            self._ll_default_model.setCurrentIndex(didx)

        # 加载每个 provider 的 API Key
        for provider, key_input in self._ll_provider_keys.items():
            api_key = self._config.get_litellm_provider_api_key(provider)
            key_input.setText(api_key)

        # 动态生成多模型调用的 QCheckBox 列表
        self._ll_model_rows.clear()
        # 清空之前的控件（保留底部的添加按钮布局）
        # 从后往前删除，保留最后一个（添加按钮布局）
        while self._ll_multi_container.count() > 1:
            item = self._ll_multi_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for model in ll.get("models", []):
            row_widget = self._create_model_row(model)
            # 插入到添加按钮布局之前
            self._ll_multi_container.insertWidget(self._ll_multi_container.count() - 1, row_widget)

        self._on_ll_toggled(ll.get("enabled", False))

    def _save(self):
        # 检测最小化模式是否变更（需要重启生效）
        old_minimize_to = self._config.window_config.get("minimize_to", "tray")
        new_minimize_to = self._minimize_to.currentData()
        minimize_changed = old_minimize_to != new_minimize_to

        # 判断启用的 API 类型
        if self._ll_enabled.isChecked():
            api_type = "litellm"
        elif self._sd_enabled.isChecked():
            api_type = "shangdao"
        else:
            api_type = "openai"

        self._config.update_api_config(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
            system_prompt=self._system_prompt_edit.toPlainText().strip(),
            api_type=api_type,
        )
        self._config.update_window_config(
            theme=self._theme_combo.currentData(),
            edge_snap=self._edge_snap.isChecked(),
            edge_snap_width_threshold=self._edge_snap_threshold.value(),
            minimize_to=self._minimize_to.currentData(),
            font_size=self._font_size.value(),
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
            enabled=self._sd_enabled.isChecked(),
            base_url=self._sd_base_url.text().strip(),
            model=self._sd_model.currentData(),
            max_tokens=self._sd_max_tokens.value(),
            temperature=self._sd_temperature.value(),
        )

        # LiteLLM 配置
        ll_enabled = self._ll_enabled.isChecked()
        ll_default_model = self._ll_default_model.currentData()

        # 保存每个 provider 的 API Key
        for provider, key_input in self._ll_provider_keys.items():
            api_key = key_input.text().strip()
            if api_key:
                self._config.set_litellm_provider_api_key(provider, api_key)

        # 更新模型的 enabled 状态
        updated_models = []
        for model in self._config.litellm_models:
            model_id = model["id"]
            if model_id in self._ll_model_rows:
                checkbox, _ = self._ll_model_rows[model_id]
                model["enabled"] = checkbox.isChecked()
            updated_models.append(model)

        self._config.update_litellm_config(
            enabled=ll_enabled,
            default_model=ll_default_model,
        )
        self._config.set_litellm_models(updated_models)

        self._hotkey_widget.save()

        if minimize_changed:
            FluentMessageBox("提示", "最小化模式已更改，重启应用后生效。", self).exec()

        self.accept()

    # ------------------------------------------------------------------ litellm model management
    def _create_model_row(self, model: dict) -> QWidget:
        """创建一行模型配置（复选框 + 编辑 + 删除按钮）"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        # 复选框
        checkbox = QCheckBox(f"{model['name']} ({model['provider']})")
        checkbox.setChecked(model.get("enabled", False))
        row_layout.addWidget(checkbox)

        row_layout.addStretch()

        # 编辑按钮
        edit_btn = QPushButton("编辑")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(lambda: self._edit_model(model["id"]))
        row_layout.addWidget(edit_btn)

        # 删除按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedWidth(50)
        delete_btn.clicked.connect(lambda: self._delete_model(model["id"]))
        row_layout.addWidget(delete_btn)

        # 保存引用
        self._ll_model_rows[model["id"]] = (checkbox, row_widget)

        return row_widget

    def _add_from_template(self):
        """从模板添加模型"""
        from app.ui.litellm_template_dialog import LiteLLMTemplateDialog

        dialog = LiteLLMTemplateDialog(self._config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load()  # 重新加载配置

    def _add_custom_model(self):
        """添加自定义模型"""
        from app.ui.litellm_model_edit_dialog import LiteLLMModelEditDialog

        dialog = LiteLLMModelEditDialog(self._config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _edit_model(self, model_id: str):
        """编辑模型"""
        from app.ui.litellm_model_edit_dialog import LiteLLMModelEditDialog

        dialog = LiteLLMModelEditDialog(self._config, model_id=model_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load()

    def _delete_model(self, model_id: str):
        """删除模型"""
        w = FluentMessageBox("确认删除", f"确定要删除模型 {model_id} 吗？", self)
        if w.exec():
            try:
                self._config.remove_litellm_model(model_id)
                self._load()
            except ValueError as e:
                FluentMessageBox("删除失败", str(e), self).exec()
