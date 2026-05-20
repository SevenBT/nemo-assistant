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
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
        for name in SHANGDAO_MODELS:
            self._sd_model.addItem(name, name)
        self._sd_model.setCurrentText(cfg.get(cfg.shangdaoModel))
        self._sd_model.currentTextChanged.connect(
            lambda v: cfg.set(cfg.shangdaoModel, v)
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
        models = cfg.get(cfg.litellmModels)
        for m in models:
            self._ll_default_model.addItem(m.get("name", m["id"]), m["id"])
        current_default = cfg.get(cfg.litellmDefaultModel)
        idx = self._ll_default_model.findData(current_default)
        if idx >= 0:
            self._ll_default_model.setCurrentIndex(idx)
        self._ll_default_model.currentIndexChanged.connect(self._on_ll_default_changed)
        ll_form.addRow("默认模型:", self._ll_default_model)

        # Provider API keys
        ll_key_group = QGroupBox("API Key 配置")
        ll_key_layout = QFormLayout(ll_key_group)
        ll_key_layout.setContentsMargins(8, 8, 8, 8)
        self._ll_provider_keys: dict[str, QLineEdit] = {}
        providers = list(set(m.get("provider", "") for m in models if m.get("provider")))
        for provider in sorted(providers):
            key_input = QLineEdit()
            key_input.setEchoMode(QLineEdit.EchoMode.Password)
            key_input.setText(get_litellm_provider_api_key(provider))
            key_input.setPlaceholderText(f"输入 {provider.capitalize()} API Key")
            key_input.editingFinished.connect(
                lambda p=provider, w=key_input: set_litellm_provider_api_key(p, w.text().strip())
            )
            self._ll_provider_keys[provider] = key_input
            ll_key_layout.addRow(f"{provider.capitalize()}:", key_input)
        ll_form.addRow(ll_key_group)

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
        for w in (self._base_url, self._api_key, self._model,
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
        for w in (self._base_url, self._api_key, self._model,
                  self._max_tokens, self._temperature):
            w.setEnabled(not enabled)
        self._sd_enabled.setEnabled(not enabled)

    def _on_ll_default_changed(self, index: int):
        model_id = self._ll_default_model.itemData(index)
        if model_id:
            cfg.set(cfg.litellmDefaultModel, model_id)
