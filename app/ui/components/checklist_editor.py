"""
待办 Checklist 编辑器。

每行是一个可勾选的任务项，内容以纯文本存储：
  [ ] 未完成任务
  [x] 已完成任务
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QHBoxLayout,
    QCheckBox,
    QLineEdit,
    QPushButton,
)


class _CheckItem(QWidget):
    """单个 checklist 行：checkbox + 文本输入。"""

    changed = pyqtSignal()
    delete_requested = pyqtSignal(object)  # self
    enter_pressed = pyqtSignal(object)     # self，按 Enter 时在下方插入新行

    def __init__(self, text: str = "", checked: bool = False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self._checkbox = QCheckBox()
        self._checkbox.setChecked(checked)
        self._checkbox.stateChanged.connect(self._on_state_changed)
        layout.addWidget(self._checkbox)

        self._edit = QLineEdit(text)
        self._edit.setObjectName("checkItemEdit")
        self._edit.textChanged.connect(self.changed)
        self._edit.returnPressed.connect(lambda: self.enter_pressed.emit(self))
        layout.addWidget(self._edit, 1)

        self._del_btn = QPushButton("×")
        self._del_btn.setObjectName("checkItemDelBtn")
        self._del_btn.setFixedSize(20, 20)
        self._del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        layout.addWidget(self._del_btn)

        self._update_style()

    def _on_state_changed(self):
        self._update_style()
        self.changed.emit()

    def _update_style(self):
        if self._checkbox.isChecked():
            self._edit.setStyleSheet(
                "color: #9CA3AF; text-decoration: line-through;"
            )
        else:
            self._edit.setStyleSheet("")

    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

    def text(self) -> str:
        return self._edit.text()

    def set_focus(self):
        self._edit.setFocus()
        self._edit.setCursorPosition(len(self._edit.text()))

    def set_enabled_editing(self, enabled: bool):
        self._checkbox.setEnabled(enabled)
        self._edit.setEnabled(enabled)
        self._del_btn.setVisible(enabled)


class ChecklistEditor(QWidget):
    """
    Checklist 编辑器。

    内容格式（纯文本，每行一项）：
      [ ] 未完成
      [x] 已完成
    """

    content_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[_CheckItem] = []
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("checklistScroll")

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(0)
        self._layout.addStretch()

        scroll.setWidget(self._container)
        outer.addWidget(scroll, 1)

        # 底部"添加项目"按钮
        self._add_btn = QPushButton("+ 添加项目")
        self._add_btn.setObjectName("checklistAddBtn")
        self._add_btn.clicked.connect(lambda: self._add_item("", False, focus=True))
        outer.addWidget(self._add_btn)

    def _add_item(self, text: str, checked: bool, focus: bool = False, after: _CheckItem = None):
        item = _CheckItem(text, checked)
        item.changed.connect(self.content_changed)
        item.delete_requested.connect(self._remove_item)
        item.enter_pressed.connect(self._on_enter_pressed)

        # stretch 始终在最后，所以插入位置是 count-1
        stretch_index = self._layout.count() - 1

        if after is not None:
            idx = self._items.index(after)
            self._items.insert(idx + 1, item)
            self._layout.insertWidget(idx + 1, item)
        else:
            self._items.append(item)
            self._layout.insertWidget(stretch_index, item)

        if focus:
            item.set_focus()

        self.content_changed.emit()
        return item

    def _remove_item(self, item: _CheckItem):
        if item in self._items:
            self._items.remove(item)
            self._layout.removeWidget(item)
            item.deleteLater()
            self.content_changed.emit()

    def _on_enter_pressed(self, item: _CheckItem):
        self._add_item("", False, focus=True, after=item)

    # ── 公开接口 ──────────────────────────────────────────────────────────

    def get_content(self) -> str:
        """返回纯文本格式内容。"""
        lines = []
        for item in self._items:
            prefix = "[x]" if item.is_checked() else "[ ]"
            lines.append(f"{prefix} {item.text()}")
        return "\n".join(lines)

    def set_content(self, content: str):
        """从纯文本格式加载内容。"""
        # 清空现有项
        for item in self._items[:]:
            self._layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("[x] ") or line.startswith("[X] "):
                self._add_item(line[4:], True)
            elif line.startswith("[ ] "):
                self._add_item(line[4:], False)
            elif line:
                # 兼容旧格式（无前缀的行）
                self._add_item(line, False)

    def clear(self):
        """清空所有项。"""
        for item in self._items[:]:
            self._layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()

    def set_enabled_editing(self, enabled: bool):
        """启用/禁用编辑。"""
        self._add_btn.setVisible(enabled)
        for item in self._items:
            item.set_enabled_editing(enabled)
