"""
查找替换对话框。
移植自 noteration/editor/find_replace.py，适配 PyQt6 + qfluentwidgets。
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

from qfluentwidgets import LineEdit, PushButton, CheckBox


class FindReplaceDialog(QDialog):
    """查找替换对话框。"""

    find_next_requested = pyqtSignal(str, bool, bool, bool)
    replace_requested = pyqtSignal(str, str, bool, bool, bool)
    replace_all_requested = pyqtSignal(str, str, bool, bool, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("查找和替换")
        self.setMinimumWidth(420)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Find row
        find_layout = QHBoxLayout()
        find_layout.addWidget(QLabel("查找:"))
        self._find_input = LineEdit()
        self._find_input.setPlaceholderText("输入查找内容...")
        self._find_input.setClearButtonEnabled(True)
        find_layout.addWidget(self._find_input)
        layout.addLayout(find_layout)

        # Replace row
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel("替换:"))
        self._replace_input = LineEdit()
        self._replace_input.setPlaceholderText("输入替换内容...")
        self._replace_input.setClearButtonEnabled(True)
        replace_layout.addWidget(self._replace_input)
        layout.addLayout(replace_layout)

        # Options
        options_group = QGroupBox("选项")
        options_layout = QHBoxLayout(options_group)
        self._case_cb = CheckBox("区分大小写")
        self._whole_cb = CheckBox("全词匹配")
        self._regex_cb = CheckBox("正则表达式")
        options_layout.addWidget(self._case_cb)
        options_layout.addWidget(self._whole_cb)
        options_layout.addWidget(self._regex_cb)
        layout.addWidget(options_group)

        # Buttons
        btn_layout = QHBoxLayout()
        self._find_btn = PushButton("查找下一个")
        self._find_btn.clicked.connect(self._on_find_next)
        self._replace_btn = PushButton("替换")
        self._replace_btn.clicked.connect(self._on_replace)
        self._replace_all_btn = PushButton("全部替换")
        self._replace_all_btn.clicked.connect(self._on_replace_all)
        self._close_btn = PushButton("关闭")
        self._close_btn.clicked.connect(self.close)

        btn_layout.addWidget(self._find_btn)
        btn_layout.addWidget(self._replace_btn)
        btn_layout.addWidget(self._replace_all_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._close_btn)
        layout.addLayout(btn_layout)

        self._find_input.setFocus()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)
        self._find_input.returnPressed.connect(self._on_find_next)
        self._replace_input.returnPressed.connect(self._on_replace)

    def _on_find_next(self) -> None:
        query = self._find_input.text()
        if not query:
            return
        self.find_next_requested.emit(
            query,
            self._case_cb.isChecked(),
            self._whole_cb.isChecked(),
            self._regex_cb.isChecked(),
        )

    def _on_replace(self) -> None:
        query = self._find_input.text()
        if not query:
            return
        self.replace_requested.emit(
            query,
            self._replace_input.text(),
            self._case_cb.isChecked(),
            self._whole_cb.isChecked(),
            self._regex_cb.isChecked(),
        )

    def _on_replace_all(self) -> None:
        query = self._find_input.text()
        if not query:
            return
        self.replace_all_requested.emit(
            query,
            self._replace_input.text(),
            self._case_cb.isChecked(),
            self._whole_cb.isChecked(),
            self._regex_cb.isChecked(),
        )

    def set_initial_text(self, text: str) -> None:
        """设置初始查找文本（如从选区获取）。"""
        if text:
            self._find_input.setText(text)
            self._find_input.selectAll()
