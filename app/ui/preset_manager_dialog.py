"""
预设角色管理对话框

左侧列表 + 右侧编辑器布局。
"""
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.preset_manager import PresetManager
from app.models.preset import Preset


class PresetManagerDialog(QDialog):
    """预设角色管理对话框"""

    def __init__(self, preset_mgr: PresetManager, parent=None):
        super().__init__(parent)
        self._preset_mgr = preset_mgr
        self.setWindowTitle("管理预设角色")
        self.setMinimumSize(800, 600)
        self._current_preset: Preset | None = None
        self._build()
        self._load_list()

    def _build(self):
        layout = QVBoxLayout(self)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        self._new_btn = QPushButton("新建")
        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self._on_delete)
        self._import_btn = QPushButton("导入")
        self._import_btn.clicked.connect(self._on_import)
        self._export_btn = QPushButton("导出")
        self._export_btn.clicked.connect(self._on_export)

        toolbar.addWidget(self._new_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._import_btn)
        toolbar.addWidget(self._export_btn)
        layout.addLayout(toolbar)

        # 分割器：左侧列表 + 右侧编辑器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # 左侧列表
        self._list = QListWidget()
        self._list.setMinimumWidth(200)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._list)

        # 右侧编辑器
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)

        # 表单
        form_layout = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("角色名称")
        form_layout.addRow("名称:", self._name_edit)

        self._icon_edit = QLineEdit()
        self._icon_edit.setPlaceholderText("🤖")
        form_layout.addRow("图标:", self._icon_edit)

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText("System Prompt…")
        self._prompt_edit.setMinimumHeight(300)
        form_layout.addRow("提示词:", self._prompt_edit)

        editor_layout.addLayout(form_layout)

        # 恢复默认按钮（仅内置预设且被修改时显示）
        self._restore_btn = QPushButton("恢复默认")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.setVisible(False)
        self._restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEF3C7;
                color: #92400E;
                border: 1px solid #FCD34D;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #FDE68A;
            }
        """)
        editor_layout.addWidget(self._restore_btn)

        editor_widget.setMinimumWidth(400)
        splitter.addWidget(editor_widget)

        splitter.setSizes([250, 550])
        layout.addWidget(splitter)

        # 底部按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        self._save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._set_editor_enabled(False)

    def _load_list(self):
        """加载预设角色列表"""
        self._list.clear()
        for preset in self._preset_mgr.get_all():
            # 显示格式：图标 + 名称
            display_text = f"{preset.icon} {preset.name}"

            # 如果是被修改的内置预设，添加警告图标
            if preset.is_builtin and self._preset_mgr.is_modified(preset.id):
                display_text = f"⚠️ {display_text}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            if preset.is_builtin:
                item.setToolTip("内置角色（不可删除，可编辑）")
            self._list.addItem(item)

    def _set_editor_enabled(self, enabled: bool):
        """设置编辑器启用/禁用状态"""
        self._name_edit.setEnabled(enabled)
        self._icon_edit.setEnabled(enabled)
        self._prompt_edit.setEnabled(enabled)

    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        """选择变化"""
        if not current:
            self._set_editor_enabled(False)
            self._current_preset = None
            self._restore_btn.setVisible(False)
            return

        preset_id = current.data(Qt.ItemDataRole.UserRole)
        preset = self._preset_mgr.get(preset_id)
        if not preset:
            return

        self._current_preset = preset
        self._name_edit.setText(preset.name)
        self._icon_edit.setText(preset.icon)
        self._prompt_edit.setPlainText(preset.system_prompt)

        # 所有预设都可编辑
        self._set_editor_enabled(True)
        self._delete_btn.setEnabled(not preset.is_builtin)  # 内置预设不可删除
        self._save_btn.setEnabled(True)

        # 如果是内置预设且被修改，显示"恢复默认"按钮
        if preset.is_builtin and self._preset_mgr.is_modified(preset_id):
            self._restore_btn.setVisible(True)
        else:
            self._restore_btn.setVisible(False)

    def _on_new(self):
        """新建预设角色"""
        preset = Preset(
            id=str(uuid.uuid4()),
            name="新角色",
            icon="🤖",
            system_prompt="",
            params={},
            is_builtin=False,
        )
        self._preset_mgr.create(preset)
        self._load_list()
        # 选中新建的项
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == preset.id:
                self._list.setCurrentItem(item)
                break

    def _on_delete(self):
        """删除预设角色"""
        if not self._current_preset:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除预设角色「{self._current_preset.name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._preset_mgr.delete(self._current_preset.id)
                self._load_list()
            except ValueError as e:
                QMessageBox.warning(self, "错误", str(e))

    def _on_restore(self):
        """恢复内置预设到默认状态"""
        if not self._current_preset:
            return

        preset = self._current_preset
        if not preset.is_builtin:
            return

        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认恢复",
            f"确定要将「{preset.name}」恢复到默认状态吗？\n当前的修改将丢失。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self._preset_mgr.restore_builtin(preset.id)
                self._load_list()
                # 重新选中该预设
                for i in range(self._list.count()):
                    item = self._list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == preset.id:
                        self._list.setCurrentItem(item)
                        break
                QMessageBox.information(self, "成功", "已恢复到默认状态")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"恢复失败: {str(e)}")

    def _on_save(self):
        """保存当前编辑"""
        print("[PresetManagerDialog] Save button clicked")

        if not self._current_preset:
            print("[PresetManagerDialog] No current preset")
            QMessageBox.warning(self, "错误", "请先选择一个预设")
            return

        # 验证输入
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "角色名称不能为空")
            return

        icon = self._icon_edit.text().strip()
        if not icon:
            icon = "🤖"

        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "错误", "System Prompt 不能为空")
            return

        print(f"[PresetManagerDialog] Saving preset: {name}")

        # 更新预设对象
        self._current_preset.name = name
        self._current_preset.icon = icon
        self._current_preset.system_prompt = prompt

        try:
            # 显示保存中状态
            self._save_btn.setEnabled(False)
            self._save_btn.setText("保存中...")

            # 强制刷新 UI
            QApplication.processEvents()

            print("[PresetManagerDialog] Calling preset_mgr.update()")
            self._preset_mgr.update(self._current_preset)
            print("[PresetManagerDialog] Update completed")

            # 保存当前预设 ID（因为 _load_list 会清空 _current_preset）
            current_preset_id = self._current_preset.id
            print(f"[PresetManagerDialog] Saved preset ID: {current_preset_id}")

            # 重新加载列表
            self._load_list()

            # 重新选中当前预设
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == current_preset_id:
                    self._list.setCurrentItem(item)
                    print(f"[PresetManagerDialog] Reselected preset at index {i}")
                    break

            print("[PresetManagerDialog] Save successful")
            QMessageBox.information(self, "成功", "保存成功")

        except IOError as e:
            print(f"[PresetManagerDialog] IOError: {e}")
            QMessageBox.critical(self, "保存失败", str(e))
        except Exception as e:
            print(f"[PresetManagerDialog] Exception: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"保存时发生未知错误：{str(e)}")
        finally:
            # 恢复按钮状态
            self._save_btn.setEnabled(True)
            self._save_btn.setText("保存")
            print("[PresetManagerDialog] Button state restored")

    def _on_import(self):
        """导入预设角色"""
        file_path, _ = QFileDialog.getOpenFileName(self, "导入预设角色", "", "JSON Files (*.json)")
        if file_path:
            try:
                from pathlib import Path
                self._preset_mgr.import_from_file(Path(file_path))
                self._load_list()
                QMessageBox.information(self, "成功", "导入成功")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _on_export(self):
        """导出预设角色"""
        file_path, _ = QFileDialog.getSaveFileName(self, "导出预设角色", "presets.json", "JSON Files (*.json)")
        if file_path:
            try:
                from pathlib import Path
                self._preset_mgr.export_to_file(Path(file_path))
                QMessageBox.information(self, "成功", "导出成功")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")



