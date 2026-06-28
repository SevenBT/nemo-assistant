"""
标签输入组件 - Fluent Design 风格。
"""

import re
from PyQt6.QtCore import Qt, QStringListModel, pyqtSignal
from PyQt6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, LineEdit, PillPushButton


class TagButton(PillPushButton):
    """单个标签 pill 按钮，点击删除。"""

    removed = pyqtSignal(str)

    def __init__(self, display_text: str, tag_name: str, parent=None):
        # 注意：qfluentwidgets 的 PushButton 系用 @singledispatchmethod 分派构造，
        # 其 text 重载体内会调 self.__init__(parent=parent)，在子类上会按子类签名
        # 重新分派 → 命中本签名缺参崩溃。故走 parent-only 重载再 setText 绕开递归。
        super().__init__(parent)
        self.setText(display_text)
        self.tag_name = tag_name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: self.removed.emit(self.tag_name))


class TagInput(QWidget):
    """标签输入组件 - pill 按钮 + 自动补全输入框。"""

    tags_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tags: list[str] = []
        self._all_tags: list[str] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Tag cloud container
        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        self._tags_layout.addStretch()
        layout.addWidget(self._tags_container)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        label = CaptionLabel("标签:")
        input_row.addWidget(label)

        self._input = LineEdit()
        self._input.setPlaceholderText("输入标签名，按 Enter 添加...")
        self._input.returnPressed.connect(self._on_add_tag)
        self._input.textChanged.connect(self._on_text_changed)
        input_row.addWidget(self._input, 1)

        layout.addLayout(input_row)

        # Autocomplete
        self._completer = QCompleter()
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._input.setCompleter(self._completer)

    def _validate_tag_name(self, name: str) -> bool:
        if not name:
            return False
        return bool(re.match(r'^[\w\u4e00-\u9fa5-]+$', name))

    def _on_text_changed(self, text: str):
        if ',' in text:
            parts = text.split(',')
            for part in parts[:-1]:
                tag = part.strip()
                if tag:
                    self._add_tag(tag)
            self._input.setText(parts[-1].strip())

    def _on_add_tag(self):
        tag = self._input.text().strip()
        if tag:
            self._add_tag(tag)
            self._input.clear()

    def _add_tag(self, tag: str):
        if not self._validate_tag_name(tag):
            return
        tag_lower = tag.lower()
        if any(t.lower() == tag_lower for t in self._tags):
            return
        self._tags.append(tag)
        self._refresh_tags_display()
        self.tags_changed.emit(self._tags)

    def _remove_tag(self, tag: str):
        if tag in self._tags:
            self._tags.remove(tag)
            self._refresh_tags_display()
            self.tags_changed.emit(self._tags)

    def _refresh_tags_display(self):
        while self._tags_layout.count() > 1:
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for tag in self._tags:
            btn = TagButton(f"{tag} ×", tag)
            btn.removed.connect(self._remove_tag)
            self._tags_layout.insertWidget(self._tags_layout.count() - 1, btn)

    def set_tags(self, tags: list[str]):
        self._tags = [t for t in tags if self._validate_tag_name(t)]
        self._refresh_tags_display()

    def get_tags(self) -> list[str]:
        return self._tags.copy()

    def set_all_tags(self, all_tags: list[str]):
        self._all_tags = all_tags
        self._completer.setModel(None)
        model = QStringListModel(all_tags)
        self._completer.setModel(model)
