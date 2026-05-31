"""会话设置对话框。"""

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.models.session import Session


class SessionSettingsDialog(QDialog):
    """会话设置对话框"""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._session = session
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

        layout.addWidget(QLabel("System Prompt:"))
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlaceholderText("留空则使用全局 System Prompt")
        self._prompt_edit.setMinimumHeight(200)
        layout.addWidget(self._prompt_edit)

        # 底部按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        """加载会话设置"""
        self._prompt_edit.setPlainText(self._session.system_prompt)

    def _on_save(self):
        """保存设置"""
        self._session.system_prompt = self._prompt_edit.toPlainText().strip()
        self.accept()

