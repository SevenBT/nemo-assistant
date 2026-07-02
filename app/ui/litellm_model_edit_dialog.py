from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.core.config import cfg
from app.i18n import t


class LiteLLMModelEditDialog(QDialog):
    """添加自定义模型或编辑现有模型的对话框"""

    def __init__(self, model_id: str | None = None, parent=None):
        super().__init__(parent)
        self._model_id = model_id  # None 表示添加，否则表示编辑
        self._is_edit_mode = model_id is not None

        self.setWindowTitle(t("litellm.model.title_edit") if self._is_edit_mode else t("litellm.model.title_add"))
        self.setMinimumWidth(400)
        self._build()
        if self._is_edit_mode:
            self._load_model()

    def _build(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Model ID
        self._model_id_input = QLineEdit()
        self._model_id_input.setPlaceholderText(t("litellm.model.model_id_ph"))
        form.addRow("Model ID:", self._model_id_input)

        # 显示名称
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText(t("litellm.model.display_name_ph"))
        form.addRow(t("litellm.model.display_name"), self._name_input)

        # Provider（可编辑下拉框）
        self._provider_combo = QComboBox()
        self._provider_combo.setEditable(True)
        self._provider_combo.setPlaceholderText(t("litellm.model.provider_ph"))
        # 添加常见的 provider（值即 LiteLLM 路由前缀）
        for provider in [
            "openai", "anthropic", "gemini", "deepseek",
            "meta_llama", "dashscope", "zai", "azure", "cohere",
        ]:
            self._provider_combo.addItem(provider.capitalize(), provider)
        form.addRow("Provider:", self._provider_combo)

        # API 地址（可选）：自定义端点 / 中转 / 兼容服务，留空走该 provider 默认
        self._api_base_input = QLineEdit()
        self._api_base_input.setPlaceholderText(t("litellm.model.api_base_ph"))
        form.addRow(t("litellm.model.api_base"), self._api_base_input)

        # 启用状态
        self._enabled_checkbox = QCheckBox(t("litellm.model.enable"))
        form.addRow("", self._enabled_checkbox)

        layout.addLayout(form)

        # 按钮
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_model(self):
        """加载现有模型数据（编辑模式）"""
        models = cfg.get(cfg.litellmModels)
        model = next((m for m in models if m["id"] == self._model_id), None)
        if not model:
            QMessageBox.critical(self, t("litellm.model.err_title"), t("litellm.model.err_not_exist", model_id=self._model_id))
            self.reject()
            return

        self._model_id_input.setText(model["id"])

        self._name_input.setText(model["name"])

        provider = model["provider"]
        idx = self._provider_combo.findData(provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        else:
            # 如果是自定义 provider，直接设置文本
            self._provider_combo.setCurrentText(provider.capitalize())
        self._api_base_input.setText(model.get("api_base", ""))
        self._enabled_checkbox.setChecked(model.get("enabled", False))

    def _save(self):
        """保存模型"""
        model_id = self._model_id_input.text().strip()
        name = self._name_input.text().strip()
        provider = self._provider_combo.currentText().strip().lower()
        api_base = self._api_base_input.text().strip()
        enabled = self._enabled_checkbox.isChecked()

        # 验证输入
        if not model_id:
            QMessageBox.warning(self, t("litellm.model.input_err_title"), t("litellm.model.err_no_id"))
            return
        if not name:
            QMessageBox.warning(self, t("litellm.model.input_err_title"), t("litellm.model.err_no_name"))
            return
        if not provider:
            QMessageBox.warning(self, t("litellm.model.input_err_title"), t("litellm.model.err_no_provider"))
            return

        try:
            models = list(cfg.get(cfg.litellmModels))
            if self._is_edit_mode:
                old_model_id = self._model_id or ""
                if model_id != old_model_id and any(m["id"] == model_id for m in models):
                    raise ValueError(t("litellm.model.err_exists", model_id=model_id))

                for m in models:
                    if m["id"] == old_model_id:
                        m["id"] = model_id
                        m["name"] = name
                        m["provider"] = provider
                        m["api_base"] = api_base
                        m["enabled"] = enabled
                        break
                cfg.set(cfg.litellmModels, models)
                if cfg.get(cfg.litellmDefaultModel) == old_model_id:
                    cfg.set(cfg.litellmDefaultModel, model_id)
                QMessageBox.information(self, t("litellm.model.success_title"), t("litellm.model.update_ok"))
            else:
                # 添加模式：检查重复
                if any(m["id"] == model_id for m in models):
                    raise ValueError(t("litellm.model.err_exists", model_id=model_id))
                models.append({
                    "id": model_id,
                    "name": name,
                    "provider": provider,
                    "api_base": api_base,
                    "enabled": enabled,
                })
                cfg.set(cfg.litellmModels, models)
                QMessageBox.information(self, t("litellm.model.success_title"), t("litellm.model.add_ok"))

            self.accept()

        except ValueError as e:
            QMessageBox.critical(self, t("litellm.model.err_title"), str(e))
