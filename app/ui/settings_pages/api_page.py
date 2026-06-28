"""API 连接设置页 — 单一 LiteLLM 入口

用户自定义模型条目（id/name/provider/api_base），按 provider 保存 API Key，
切换默认模型即切换供应商。
"""

from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.litellm_model_edit_dialog import LiteLLMModelEditDialog
from app.ui.litellm_template_dialog import LiteLLMTemplateDialog
from app.core.config import (
    cfg,
    get_litellm_provider_api_key,
    set_litellm_provider_api_key,
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

        # ── 模型管理 ──
        ll_form = QFormLayout()

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

        layout.addLayout(ll_form)

        # ── Provider API Keys ──
        self._ll_key_group = QGroupBox("API Key 配置")
        self._ll_key_layout = QFormLayout(self._ll_key_group)
        self._ll_key_layout.setContentsMargins(8, 8, 8, 8)
        self._ll_provider_keys: dict[str, QLineEdit] = {}
        layout.addWidget(self._ll_key_group)
        self._refresh_ll_models()

        # ── 通用参数 ──
        param_group = QGroupBox("通用参数")
        param_form = QFormLayout(param_group)
        param_form.setContentsMargins(8, 8, 8, 8)

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
        param_form.addRow("识图能力:", self._vision)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(256, 65536)
        self._max_tokens.setSingleStep(256)
        self._max_tokens.setValue(cfg.get(cfg.maxTokens))
        self._max_tokens.valueChanged.connect(
            lambda v: cfg.set(cfg.maxTokens, v)
        )
        param_form.addRow("最大 Token:", self._max_tokens)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(1)
        self._temperature.setValue(cfg.get(cfg.temperature))
        self._temperature.valueChanged.connect(
            lambda v: cfg.set(cfg.temperature, round(v, 1))
        )
        param_form.addRow("Temperature:", self._temperature)

        self._top_p = QDoubleSpinBox()
        self._top_p.setRange(0.0, 1.0)
        self._top_p.setSingleStep(0.05)
        self._top_p.setDecimals(2)
        self._top_p.setValue(cfg.get(cfg.topP))
        self._top_p.valueChanged.connect(
            lambda v: cfg.set(cfg.topP, round(v, 2))
        )
        self._top_p.setToolTip(
            "核采样（nucleus sampling）。\n"
            "1.0 表示不裁剪候选词；调低会让输出更聚焦。\n"
            "通常与 Temperature 二选一调整，不建议同时大幅改动。"
        )
        param_form.addRow("Top P:", self._top_p)

        layout.addWidget(param_group)

        # ── 系统提示词 ──
        prompt_group = QGroupBox("系统提示词")
        prompt_layout = QVBoxLayout(prompt_group)
        prompt_layout.setContentsMargins(8, 8, 8, 8)
        prompt_hint = QLabel(
            "全局系统提示词，作用于所有会话。单个会话若设置了自己的提示词，"
            "则优先使用会话的。留空表示不附加全局提示词。"
        )
        prompt_hint.setWordWrap(True)
        prompt_layout.addWidget(prompt_hint)
        self._system_prompt = QPlainTextEdit()
        self._system_prompt.setFixedHeight(120)
        self._system_prompt.setPlaceholderText("例如：你是一个简洁、专业的中文助手……")
        self._system_prompt.setPlainText(cfg.get(cfg.systemPrompt) or "")
        self._system_prompt.focusOutEvent = self._wrap_prompt_focus_out(
            self._system_prompt.focusOutEvent
        )
        prompt_layout.addWidget(self._system_prompt)
        layout.addWidget(prompt_group)

        layout.addStretch()
        self.setWidget(container)

    def _wrap_prompt_focus_out(self, original):
        """系统提示词编辑框失焦时写回 cfg，避免每次按键都落盘。"""

        def handler(event):
            cfg.set(cfg.systemPrompt, self._system_prompt.toPlainText().strip())
            original(event)

        return handler

    def save(self):
        """供设置窗口在确定/关闭时统一调用，兜底未失焦的系统提示词编辑框。"""
        cfg.set(cfg.systemPrompt, self._system_prompt.toPlainText().strip())

    # ── Event handlers ──

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
