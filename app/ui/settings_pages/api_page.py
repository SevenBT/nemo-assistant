"""API 连接设置页 — OpenAI / 商道 / LiteLLM 三段折叠配置"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.litellm_model_edit_dialog import LiteLLMModelEditDialog
from app.ui.litellm_template_dialog import LiteLLMTemplateDialog
from app.core.config import (
    SHANGDAO_MODELS,
    cfg,
    get_api_key,
    get_litellm_provider_api_key,
    get_shangdao_api_key,
    set_api_key,
    set_litellm_provider_api_key,
    set_shangdao_api_key,
)


class ApiPage(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build()

    def _build(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── OpenAI section ──
        form = QFormLayout()
        self._base_url = QLineEdit()
        self._base_url.setText(cfg.get(cfg.apiBaseUrl))
        self._base_url.setPlaceholderText("https://api.openai.com/v1")
        self._base_url.editingFinished.connect(
            lambda: cfg.set(cfg.apiBaseUrl, self._base_url.text().strip())
        )
        form.addRow("API 地址:", self._base_url)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setText(get_api_key())
        self._api_key.setPlaceholderText("sk-…")
        self._api_key.editingFinished.connect(
            lambda: set_api_key(self._api_key.text().strip())
        )
        form.addRow("API Key:", self._api_key)

        self._model = QLineEdit()
        self._model.setText(cfg.get(cfg.model))
        self._model.setPlaceholderText("gpt-4o")
        self._model.editingFinished.connect(
            lambda: cfg.set(cfg.model, self._model.text().strip())
        )
        form.addRow("模型:", self._model)

        # 识图（多模态）能力：截图/图片附件是否把像素发给模型
        self._vision = QComboBox()
        self._VISION_OPTIONS = [
            ("auto", "自动（按模型名判断）"),
            ("on", "始终开启"),
            ("off", "始终关闭"),
        ]
        for value, label in self._VISION_OPTIONS:
            self._vision.addItem(label, value)
        current_vision = cfg.get(cfg.visionSupport)
        vision_idx = self._vision.findData(current_vision)
        self._vision.setCurrentIndex(vision_idx if vision_idx >= 0 else 0)
        self._vision.currentIndexChanged.connect(
            lambda i: cfg.set(cfg.visionSupport, self._vision.itemData(i))
        )
        self._vision.setToolTip(
            "识图功能是否把图片像素发给模型。\n"
            "自动：常见多模态模型名（gpt-4o/claude/gemini/vl 等）自动识别。\n"
            "若用自定义模型名且确认支持视觉，选「始终开启」。"
        )
        form.addRow("识图能力:", self._vision)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(256, 65536)
        self._max_tokens.setSingleStep(256)
        self._max_tokens.setValue(cfg.get(cfg.maxTokens))
        self._max_tokens.valueChanged.connect(
            lambda v: cfg.set(cfg.maxTokens, v)
        )
        form.addRow("最大 Token:", self._max_tokens)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(1)
        self._temperature.setValue(cfg.get(cfg.temperature))
        self._temperature.valueChanged.connect(
            lambda v: cfg.set(cfg.temperature, round(v, 1))
        )
        form.addRow("Temperature:", self._temperature)

        layout.addLayout(form)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # ── Shangdao section ──
        sd_header = QHBoxLayout()
        self._sd_enabled = QCheckBox("启用商道 API")
        self._sd_enabled.setChecked(cfg.get(cfg.shangdaoEnabled))
        self._sd_enabled.toggled.connect(self._on_sd_toggled)
        sd_header.addWidget(self._sd_enabled)
        sd_header.addStretch()
        self._sd_toggle_btn = QPushButton("▶ 展开配置")
        self._sd_toggle_btn.setFixedWidth(90)
        self._sd_toggle_btn.setFlat(True)
        self._sd_toggle_btn.clicked.connect(self._toggle_sd)
        sd_header.addWidget(self._sd_toggle_btn)
        layout.addLayout(sd_header)

        self._sd_detail = QWidget()
        sd_form = QFormLayout(self._sd_detail)
        sd_form.setContentsMargins(0, 0, 0, 0)

        self._sd_base_url = QLineEdit()
        self._sd_base_url.setText(cfg.get(cfg.shangdaoBaseUrl))
        self._sd_base_url.editingFinished.connect(
            lambda: cfg.set(cfg.shangdaoBaseUrl, self._sd_base_url.text().strip())
        )
        sd_form.addRow("API 地址:", self._sd_base_url)

        self._sd_api_key = QLineEdit()
        self._sd_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._sd_api_key.setText(get_shangdao_api_key())
        self._sd_api_key.editingFinished.connect(
            lambda: set_shangdao_api_key(self._sd_api_key.text().strip())
        )
        sd_form.addRow("API Key:", self._sd_api_key)

        self._sd_model = QComboBox()
        self._sd_model.setEditable(True)
        for name in SHANGDAO_MODELS:
            self._sd_model.addItem(name, name)
        current_sd_model = cfg.get(cfg.shangdaoModel)
        if self._sd_model.findText(current_sd_model) < 0:
            self._sd_model.addItem(current_sd_model, current_sd_model)
        self._sd_model.setCurrentText(current_sd_model)
        self._sd_model.lineEdit().setPlaceholderText("输入商道模型名")
        self._sd_model.currentTextChanged.connect(
            lambda v: cfg.set(cfg.shangdaoModel, v.strip())
        )
        sd_form.addRow("模型:", self._sd_model)

        self._sd_detail.setVisible(False)
        layout.addWidget(self._sd_detail)

        # ── Separator ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # ── LiteLLM section ──
        ll_header = QHBoxLayout()
        self._ll_enabled = QCheckBox("启用 LiteLLM")
        self._ll_enabled.setChecked(cfg.get(cfg.litellmEnabled))
        self._ll_enabled.toggled.connect(self._on_ll_toggled)
        ll_header.addWidget(self._ll_enabled)
        ll_header.addStretch()
        self._ll_toggle_btn = QPushButton("▶ 展开配置")
        self._ll_toggle_btn.setFixedWidth(90)
        self._ll_toggle_btn.setFlat(True)
        self._ll_toggle_btn.clicked.connect(self._toggle_ll)
        ll_header.addWidget(self._ll_toggle_btn)
        layout.addLayout(ll_header)

        self._ll_detail = QWidget()
        ll_form = QFormLayout(self._ll_detail)
        ll_form.setContentsMargins(0, 0, 0, 0)

        self._ll_default_model = QComboBox()
        self._ll_default_model.currentIndexChanged.connect(self._on_ll_default_changed)
        ll_form.addRow("默认模型:", self._ll_default_model)

        ll_model_actions = QWidget()
        ll_model_actions_layout = QHBoxLayout(ll_model_actions)
        ll_model_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._ll_add_template_btn = QPushButton("从模板添加")
        self._ll_add_template_btn.clicked.connect(self._add_ll_model_from_template)
        self._ll_add_custom_btn = QPushButton("添加自定义")
        self._ll_add_custom_btn.clicked.connect(self._add_custom_ll_model)
        self._ll_edit_btn = QPushButton("编辑当前")
        self._ll_edit_btn.clicked.connect(self._edit_current_ll_model)
        self._ll_delete_btn = QPushButton("删除当前")
        self._ll_delete_btn.clicked.connect(self._delete_current_ll_model)
        for btn in (
            self._ll_add_template_btn,
            self._ll_add_custom_btn,
            self._ll_edit_btn,
            self._ll_delete_btn,
        ):
            ll_model_actions_layout.addWidget(btn)
        ll_form.addRow("模型管理:", ll_model_actions)

        # Provider API keys
        self._ll_key_group = QGroupBox("API Key 配置")
        self._ll_key_layout = QFormLayout(self._ll_key_group)
        self._ll_key_layout.setContentsMargins(8, 8, 8, 8)
        self._ll_provider_keys: dict[str, QLineEdit] = {}
        ll_form.addRow(self._ll_key_group)
        self._refresh_ll_models()

        self._ll_detail.setVisible(False)
        layout.addWidget(self._ll_detail)

        layout.addStretch()
        self.setWidget(container)

    # ── Event handlers ──

    def _toggle_sd(self):
        visible = not self._sd_detail.isVisible()
        self._sd_detail.setVisible(visible)
        self._sd_toggle_btn.setText("▼ 收起配置" if visible else "▶ 展开配置")

    def _on_sd_toggled(self, enabled: bool):
        cfg.set(cfg.shangdaoEnabled, enabled)
        if enabled:
            cfg.set(cfg.apiType, "shangdao")
        elif not cfg.get(cfg.litellmEnabled):
            cfg.set(cfg.apiType, "openai")
        # Disable OpenAI fields when shangdao is active
        for w in (self._base_url, self._api_key, self._model, self._vision,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)
        self._ll_enabled.setEnabled(not enabled)

    def _toggle_ll(self):
        visible = not self._ll_detail.isVisible()
        self._ll_detail.setVisible(visible)
        self._ll_toggle_btn.setText("▼ 收起配置" if visible else "▶ 展开配置")

    def _on_ll_toggled(self, enabled: bool):
        cfg.set(cfg.litellmEnabled, enabled)
        if enabled:
            cfg.set(cfg.apiType, "litellm")
        elif not cfg.get(cfg.shangdaoEnabled):
            cfg.set(cfg.apiType, "openai")
        for w in (self._base_url, self._api_key, self._model, self._vision,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)
        self._sd_enabled.setEnabled(not enabled)

    def _refresh_ll_models(self, selected_model_id: str | None = None):
        models = list(cfg.get(cfg.litellmModels) or [])
        configured_model_ids = {m.get("id") for m in models if m.get("id")}
        current_model_id = (
            selected_model_id
            or self._ll_default_model.currentData()
            or cfg.get(cfg.litellmDefaultModel)
        )

        self._ll_default_model.blockSignals(True)
        self._ll_default_model.clear()
        for model in models:
            model_id = model.get("id", "")
            if not model_id:
                continue
            name = model.get("name") or model_id
            provider = model.get("provider", "")
            label = f"{name} ({provider})" if provider else name
            self._ll_default_model.addItem(label, model_id)

        if current_model_id and self._ll_default_model.findData(current_model_id) < 0:
            self._ll_default_model.addItem(current_model_id, current_model_id)

        idx = self._ll_default_model.findData(current_model_id)
        if idx >= 0:
            self._ll_default_model.setCurrentIndex(idx)
        self._ll_default_model.blockSignals(False)

        if self._ll_default_model.currentData():
            cfg.set(cfg.litellmDefaultModel, self._ll_default_model.currentData())

        can_modify_current = self._ll_default_model.currentData() in configured_model_ids
        self._ll_edit_btn.setEnabled(can_modify_current)
        self._ll_delete_btn.setEnabled(can_modify_current)
        self._refresh_ll_provider_keys(models)

    def _refresh_ll_provider_keys(self, models: list[dict]):
        cached_values = {
            provider: widget.text()
            for provider, widget in self._ll_provider_keys.items()
        }
        while self._ll_key_layout.count():
            item = self._ll_key_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._ll_provider_keys = {}
        providers = sorted({
            m.get("provider", "").strip()
            for m in models
            if m.get("provider", "").strip()
        })
        for provider in providers:
            key_input = QLineEdit()
            key_input.setEchoMode(QLineEdit.EchoMode.Password)
            key_input.setText(cached_values.get(provider, get_litellm_provider_api_key(provider)))
            key_input.setPlaceholderText(f"输入 {provider.capitalize()} API Key")
            key_input.editingFinished.connect(
                lambda p=provider, w=key_input: set_litellm_provider_api_key(p, w.text().strip())
            )
            self._ll_provider_keys[provider] = key_input
            self._ll_key_layout.addRow(f"{provider.capitalize()}:", key_input)
        self._ll_key_group.setVisible(bool(providers))

    def _add_ll_model_from_template(self):
        if LiteLLMTemplateDialog(self).exec():
            self._refresh_ll_models()

    def _add_custom_ll_model(self):
        if LiteLLMModelEditDialog(parent=self).exec():
            self._refresh_ll_models()

    def _edit_current_ll_model(self):
        model_id = self._ll_default_model.currentData()
        if not model_id:
            QMessageBox.warning(self, "未选择模型", "请先选择一个模型")
            return
        if LiteLLMModelEditDialog(model_id, self).exec():
            self._refresh_ll_models(cfg.get(cfg.litellmDefaultModel))

    def _delete_current_ll_model(self):
        model_id = self._ll_default_model.currentData()
        if not model_id:
            QMessageBox.warning(self, "未选择模型", "请先选择一个模型")
            return
        reply = QMessageBox.question(
            self,
            "删除模型",
            f"确定删除模型 {model_id} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        models = [
            m for m in list(cfg.get(cfg.litellmModels) or [])
            if m.get("id") != model_id
        ]
        cfg.set(cfg.litellmModels, models)
        next_default = models[0].get("id", "") if models else ""
        if cfg.get(cfg.litellmDefaultModel) == model_id:
            cfg.set(cfg.litellmDefaultModel, next_default)
        self._refresh_ll_models(next_default)

    def _on_ll_default_changed(self, index: int):
        model_id = self._ll_default_model.itemData(index)
        if model_id:
            cfg.set(cfg.litellmDefaultModel, model_id)
        configured_model_ids = {
            m.get("id") for m in list(cfg.get(cfg.litellmModels) or []) if m.get("id")
        }
        can_modify_current = model_id in configured_model_ids
        self._ll_edit_btn.setEnabled(can_modify_current)
        self._ll_delete_btn.setEnabled(can_modify_current)
