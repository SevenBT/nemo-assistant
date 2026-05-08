"""
标签输入组件。

支持标签云显示、自动补全、添加和删除标签。
"""

import re
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QCompleter,
    QLabel,
)


class TagButton(QPushButton):
    """单个标签按钮，带删除功能。"""

    removed = pyqtSignal(str)  # 标签被删除时发出信号

    def __init__(self, display_text: str, tag_name: str, parent=None):
        super().__init__(display_text, parent)
        self.tag_name = tag_name
        self.setObjectName("tagButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: self.removed.emit(self.tag_name))


class TagInput(QWidget):
    """
    标签输入组件。

    功能：
    - 标签云显示（已添加的标签显示为可删除的按钮）
    - 输入框支持自动补全（已有标签）
    - 按 Enter 或逗号添加标签
    - 点击标签按钮删除标签
    """

    tags_changed = pyqtSignal(list)  # 标签列表变化时发出信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tags: list[str] = []
        self._all_tags: list[str] = []
        self._build()

    def _build(self):
        """构建 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 标签云容器
        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_layout.addStretch()
        layout.addWidget(self._tags_container)

        # 输入框
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        label = QLabel("标签:")
        label.setObjectName("tagInputLabel")
        input_row.addWidget(label)

        self._input = QLineEdit()
        self._input.setObjectName("tagInputEdit")
        self._input.setPlaceholderText("输入标签名，按 Enter 添加...")
        self._input.returnPressed.connect(self._on_add_tag)
        self._input.textChanged.connect(self._on_text_changed)
        input_row.addWidget(self._input, 1)

        layout.addLayout(input_row)

        # 自动补全
        self._completer = QCompleter()
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._input.setCompleter(self._completer)

    def _validate_tag_name(self, name: str) -> bool:
        """
        验证标签名是否合法。

        只允许字母、数字、中文、下划线、连字符。

        Args:
            name: 标签名

        Returns:
            bool: 是否合法
        """
        if not name:
            return False
        return bool(re.match(r'^[\w\u4e00-\u9fa5-]+$', name))

    def _on_text_changed(self, text: str):
        """处理输入框文本变化，支持逗号分隔。"""
        if ',' in text:
            parts = text.split(',')
            for part in parts[:-1]:
                tag = part.strip()
                if tag:
                    self._add_tag(tag)
            self._input.setText(parts[-1].strip())

    def _on_add_tag(self):
        """处理 Enter 键添加标签。"""
        tag = self._input.text().strip()
        if tag:
            self._add_tag(tag)
            self._input.clear()

    def _add_tag(self, tag: str):
        """
        添加标签到列表。

        Args:
            tag: 标签名
        """
        if not self._validate_tag_name(tag):
            return

        # 标签名不区分大小写，但保留用户输入的大小写
        tag_lower = tag.lower()
        if any(t.lower() == tag_lower for t in self._tags):
            return

        self._tags.append(tag)
        self._refresh_tags_display()
        self.tags_changed.emit(self._tags)

    def _remove_tag(self, tag: str):
        """
        从列表中移除标签。

        Args:
            tag: 标签名
        """
        if tag in self._tags:
            self._tags.remove(tag)
            self._refresh_tags_display()
            self.tags_changed.emit(self._tags)

    def _refresh_tags_display(self):
        """刷新标签云显示。"""
        # 清空现有标签按钮
        while self._tags_layout.count() > 1:
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 添加新标签按钮
        for tag in self._tags:
            btn = TagButton(f"{tag} ×", tag)
            btn.removed.connect(self._remove_tag)
            self._tags_layout.insertWidget(self._tags_layout.count() - 1, btn)

    def set_tags(self, tags: list[str]):
        """
        设置标签列表。

        Args:
            tags: 标签名列表
        """
        self._tags = [t for t in tags if self._validate_tag_name(t)]
        self._refresh_tags_display()

    def get_tags(self) -> list[str]:
        """
        获取当前标签列表。

        Returns:
            list[str]: 标签名列表
        """
        return self._tags.copy()

    def set_all_tags(self, all_tags: list[str]):
        """
        设置所有可用标签（用于自动补全）。

        Args:
            all_tags: 所有标签名列表
        """
        self._all_tags = all_tags
        self._completer.setModel(None)
        from PyQt6.QtCore import QStringListModel
        model = QStringListModel(all_tags)
        self._completer.setModel(model)

