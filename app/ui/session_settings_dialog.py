"""
会话设置对话框

允许编辑会话级 System Prompt 或选择预设角色。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
)

from app.core.preset_manager import PresetManager
from app.models.session import Session


class SessionSettingsDialog(QDialog):
    """会话设置对话框"""

    def __init__(self, session: Session, preset_mgr: PresetManager, parent=None):
        super().__init__(parent)
        self._session = session
        self._preset_mgr = preset_mgr
        self.setWindowTitle("会话设置")
        self.setMinimumSize(500, 400)
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel(f"会话：{self._session.title}")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #d8dee9;")
        layout.addWidget(title)

        # 选择模式
        mode_label = QLabel("System Prompt 来源:")
        layout.addWidget(mode_label)

        self._mode_group = QButtonGroup(self)
        self._preset_radio = QRadioButton("使用预设角色")
        self._custom_radio = QRadioButton("自定义 Prompt")
        self._mode_group.addButton(self._preset_radio, 0)
        self._mode_group.addButton(self._custom_radio, 1)
        layout.addWidget(self._preset_radio)
        layout.addWidget(self._custom_radio)

        # 预设角色选择
        form = QFormLayout()
        self._preset_combo = QComboBox()
        for preset in self._preset_mgr.get_all():
            self._preset_combo.addItem(f"{preset.icon} {preset.name}", preset.id)
        form.addRow("预设角色:", self._preset_combo)
        layout.addLayout(form)

        # 自定义 Prompt 编辑器
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText("自定义 System Prompt…")
        self._prompt_edit.setMinimumHeight(200)
        layout.addWidget(self._prompt_edit)

        # 连接信号
        self._preset_radio.toggled.connect(self._on_mode_changed)
        self._custom_radio.toggled.connect(self._on_mode_changed)

        # 底部按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        """加载会话设置"""
        if self._session.preset_id:
            # 使用预设角色
            self._preset_radio.setChecked(True)
            for i in range(self._preset_combo.count()):
                if self._preset_combo.itemData(i) == self._session.preset_id:
                    self._preset_combo.setCurrentIndex(i)
                    break
        elif self._session.system_prompt:
            # 自定义 Prompt
            self._custom_radio.setChecked(True)
            self._prompt_edit.setPlainText(self._session.system_prompt)
        else:
            # 默认使用预设角色
            self._preset_radio.setChecked(True)

        self._on_mode_changed()

    def _on_mode_changed(self):
        """模式切换"""
        use_preset = self._preset_radio.isChecked()
        self._preset_combo.setEnabled(use_preset)
        self._prompt_edit.setEnabled(not use_preset)

    def _on_save(self):
        """保存设置"""
        if self._preset_radio.isChecked():
            # 使用预设角色
            self._session.preset_id = self._preset_combo.currentData()
            self._session.system_prompt = ""
        else:
            # 自定义 Prompt
            self._session.system_prompt = self._prompt_edit.toPlainText().strip()
            self._session.preset_id = ""

        self.accept()

