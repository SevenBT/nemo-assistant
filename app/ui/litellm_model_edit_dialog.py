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


class LiteLLMModelEditDialog(QDialog):
    """添加自定义模型或编辑现有模型的对话框"""

    def __init__(self, model_id: str | None = None, parent=None):
        super().__init__(parent)
        self._model_id = model_id  # None 表示添加，否则表示编辑
        self._is_edit_mode = model_id is not None

        self.setWindowTitle("编辑模型" if self._is_edit_mode else "添加自定义模型")
        self.setMinimumWidth(400)
        self._build()
        if self._is_edit_mode:
            self._load_model()

    def _build(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Model ID
        self._model_id_input = QLineEdit()
        self._model_id_input.setPlaceholderText("例如: gpt-4o, claude-3-opus")
        form.addRow("Model ID:", self._model_id_input)

        # 显示名称
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("例如: GPT-4o, Claude 3 Opus")
        form.addRow("显示名称:", self._name_input)

        # Provider（可编辑下拉框）
        self._provider_combo = QComboBox()
        self._provider_combo.setEditable(True)
        self._provider_combo.setPlaceholderText("选择或输入 provider")
        # 添加常见的 provider
        for provider in ["openai", "anthropic", "google", "deepseek", "azure", "cohere"]:
            self._provider_combo.addItem(provider.capitalize(), provider)
        form.addRow("Provider:", self._provider_combo)

        # 启用状态
        self._enabled_checkbox = QCheckBox("启用此模型用于多模型调用")
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
            QMessageBox.critical(self, "错误", f"模型 {self._model_id} 不存在")
            self.reject()
            return

        self._model_id_input.setText(model["id"])
        self._model_id_input.setEnabled(False)  # 编辑模式下不可修改 ID

        self._name_input.setText(model["name"])

        provider = model["provider"]
        idx = self._provider_combo.findData(provider)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        else:
            # 如果是自定义 provider，直接设置文本
            self._provider_combo.setCurrentText(provider.capitalize())
        self._provider_combo.setEnabled(False)  # 编辑模式下不可修改 provider

        self._enabled_checkbox.setChecked(model.get("enabled", False))

    def _save(self):
        """保存模型"""
        model_id = self._model_id_input.text().strip()
        name = self._name_input.text().strip()
        provider = self._provider_combo.currentData() or self._provider_combo.currentText().strip().lower()
        enabled = self._enabled_checkbox.isChecked()

        # 验证输入
        if not model_id:
            QMessageBox.warning(self, "输入错误", "Model ID 不能为空")
            return
        if not name:
            QMessageBox.warning(self, "输入错误", "显示名称不能为空")
            return
        if not provider:
            QMessageBox.warning(self, "输入错误", "Provider 不能为空")
            return

        try:
            models = list(cfg.get(cfg.litellmModels))
            if self._is_edit_mode:
                # 编辑模式：只更新 name 和 enabled
                for m in models:
                    if m["id"] == model_id:
                        m["name"] = name
                        m["enabled"] = enabled
                        break
                cfg.set(cfg.litellmModels, models)
                QMessageBox.information(self, "成功", "模型更新成功")
            else:
                # 添加模式：检查重复
                if any(m["id"] == model_id for m in models):
                    raise ValueError(f"模型 {model_id} 已存在")
                models.append({
                    "id": model_id,
                    "name": name,
                    "provider": provider,
                    "enabled": enabled,
                })
                cfg.set(cfg.litellmModels, models)
                QMessageBox.information(self, "成功", "模型添加成功")

            self.accept()

        except ValueError as e:
            QMessageBox.critical(self, "错误", str(e))
