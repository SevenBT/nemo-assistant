from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QMessageBox,
    QVBoxLayout,
)

from app.core.config import ConfigManager


class LiteLLMTemplateDialog(QDialog):
    """从模板快速添加模型的对话框"""

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("从模板添加模型")
        self.setMinimumWidth(400)
        self.setMinimumHeight(350)
        self._build()
        self._load_templates()

    def _build(self):
        layout = QVBoxLayout(self)

        # Provider 选择
        layout.addWidget(QLabel("选择厂商:"))
        self._provider_combo = QComboBox()
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self._provider_combo)

        # 模型列表（多选）
        layout.addWidget(QLabel("选择要添加的模型（可多选）:"))
        self._model_list = QListWidget()
        self._model_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self._model_list)

        # 按钮
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._add_models)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_templates(self):
        """加载模板数据"""
        templates = self._config.get_model_templates()
        for provider in templates.keys():
            self._provider_combo.addItem(provider.capitalize(), provider)

        # 触发第一次加载
        if self._provider_combo.count() > 0:
            self._on_provider_changed(0)

    def _on_provider_changed(self, _index: int):
        """切换 provider 时更新模型列表"""
        self._model_list.clear()

        provider = self._provider_combo.currentData()
        if not provider:
            return

        templates = self._config.get_model_templates()
        models = templates.get(provider, [])

        # 获取已存在的模型 ID
        existing_ids = {m["id"] for m in self._config.litellm_models}

        # 只显示未添加的模型
        for model in models:
            if model["id"] not in existing_ids:
                self._model_list.addItem(model["name"])
                # 将完整的模型数据存储在 item 的 data 中
                item = self._model_list.item(self._model_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, model)

    def _add_models(self):
        """批量添加选中的模型"""
        selected_items = self._model_list.selectedItems()

        if not selected_items:
            QMessageBox.warning(self, "未选择模型", "请至少选择一个模型")
            return

        provider = self._provider_combo.currentData()
        added_count = 0
        errors = []

        for item in selected_items:
            model_data = item.data(Qt.ItemDataRole.UserRole)
            try:
                self._config.add_litellm_model(
                    model_id=model_data["id"],
                    name=model_data["name"],
                    provider=provider,
                    enabled=False,
                )
                added_count += 1
            except ValueError as e:
                errors.append(str(e))

        if errors:
            QMessageBox.warning(
                self,
                "部分添加失败",
                f"成功添加 {added_count} 个模型\n\n失败:\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "添加成功", f"成功添加 {added_count} 个模型"
            )

        self.accept()
