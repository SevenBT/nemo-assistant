"""
查找替换对话框。
Adapted from noteration (MIT): noteration/editor/find_replace.py，适配 PyQt6 + qfluentwidgets。
See THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

from qfluentwidgets import LineEdit, PushButton, CheckBox

from app.i18n import t


class FindReplaceDialog(QDialog):
    """查找替换对话框。"""

    find_next_requested = pyqtSignal(str, bool, bool, bool)
    replace_requested = pyqtSignal(str, str, bool, bool, bool)
    replace_all_requested = pyqtSignal(str, str, bool, bool, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("find.title"))
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
        find_layout.addWidget(QLabel(t("find.findLabel")))
        self._find_input = LineEdit()
        self._find_input.setPlaceholderText(t("find.findPlaceholder"))
        self._find_input.setClearButtonEnabled(True)
        find_layout.addWidget(self._find_input)
        layout.addLayout(find_layout)

        # Replace row
        replace_layout = QHBoxLayout()
        replace_layout.addWidget(QLabel(t("find.replaceLabel")))
        self._replace_input = LineEdit()
        self._replace_input.setPlaceholderText(t("find.replacePlaceholder"))
        self._replace_input.setClearButtonEnabled(True)
        replace_layout.addWidget(self._replace_input)
        layout.addLayout(replace_layout)

        # Options
        options_group = QGroupBox(t("find.options"))
        options_layout = QHBoxLayout(options_group)
        self._case_cb = CheckBox(t("find.caseSensitive"))
        self._whole_cb = CheckBox(t("find.wholeWord"))
        self._regex_cb = CheckBox(t("find.regex"))
        options_layout.addWidget(self._case_cb)
        options_layout.addWidget(self._whole_cb)
        options_layout.addWidget(self._regex_cb)
        layout.addWidget(options_group)

        # Buttons
        btn_layout = QHBoxLayout()
        self._find_btn = PushButton(t("find.findNext"))
        self._find_btn.clicked.connect(self._on_find_next)
        self._replace_btn = PushButton(t("find.replace"))
        self._replace_btn.clicked.connect(self._on_replace)
        self._replace_all_btn = PushButton(t("find.replaceAll"))
        self._replace_all_btn.clicked.connect(self._on_replace_all)
        self._close_btn = PushButton(t("common.close"))
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
