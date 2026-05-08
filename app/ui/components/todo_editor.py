"""
待办编辑器组件。

提供待办项的完整编辑功能：标题、内容、优先级、截止日期、重复、标签。
"""

from datetime import datetime
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QDateTimeEdit,
    QPushButton,
    QLabel,
)

from app.ui.components.tag_input import TagInput


class TodoEditor(QWidget):
    """
    待办编辑器组件。

    功能：
    - 标题输入
    - 内容编辑
    - 优先级选择（无/P1/P2/P3）
    - 截止日期选择（可清除）
    - 重复设置（无/每日/每周/每月）
    - 标签输入
    """

    content_changed = pyqtSignal()  # 内容变化信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        """构建 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 标题输入
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("todoTitleEdit")
        self._title_edit.setPlaceholderText("待办标题...")
        self._title_edit.textChanged.connect(self.content_changed)
        layout.addWidget(self._title_edit)

        # 内容编辑
        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("todoContentEdit")
        self._content_edit.setPlaceholderText("待办详情...")
        self._content_edit.textChanged.connect(self.content_changed)
        layout.addWidget(self._content_edit, 1)

        # 优先级和截止日期行
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)

        # 优先级
        priority_label = QLabel("优先级:")
        meta_row.addWidget(priority_label)

        self._priority_combo = QComboBox()
        self._priority_combo.setObjectName("todoPriorityCombo")
        self._priority_combo.addItems(["无", "P1", "P2", "P3"])
        self._priority_combo.currentTextChanged.connect(self.content_changed)
        meta_row.addWidget(self._priority_combo)

        meta_row.addSpacing(16)

        # 截止日期
        due_label = QLabel("截止日期:")
        meta_row.addWidget(due_label)

        self._set_due_btn = QPushButton("设置")
        self._set_due_btn.setObjectName("todoClearDueBtn")
        self._set_due_btn.clicked.connect(self._on_set_due_date)
        meta_row.addWidget(self._set_due_btn)

        self._due_edit = QDateTimeEdit()
        self._due_edit.setObjectName("todoDueEdit")
        self._due_edit.setCalendarPopup(True)
        self._due_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._due_edit.dateTimeChanged.connect(self.content_changed)
        meta_row.addWidget(self._due_edit)

        self._clear_due_btn = QPushButton("清除")
        self._clear_due_btn.setObjectName("todoClearDueBtn")
        self._clear_due_btn.clicked.connect(self._on_clear_due_date)
        meta_row.addWidget(self._clear_due_btn)
        self._clear_due_btn.clicked.connect(self._on_clear_due_date)
        meta_row.addWidget(self._clear_due_btn)

        meta_row.addSpacing(16)

        # 重复设置
        recurrence_label = QLabel("重复:")
        meta_row.addWidget(recurrence_label)

        self._recurrence_combo = QComboBox()
        self._recurrence_combo.setObjectName("todoRecurrenceCombo")
        self._recurrence_combo.addItems(["无", "每日", "每周", "每月"])
        self._recurrence_combo.currentTextChanged.connect(self.content_changed)
        meta_row.addWidget(self._recurrence_combo)

        meta_row.addStretch()
        layout.addLayout(meta_row)

        # 标签输入
        self._tag_input = TagInput()
        self._tag_input.tags_changed.connect(self.content_changed)
        layout.addWidget(self._tag_input)

        # 初始状态
        self._has_due_date = False
        self._due_edit.hide()
        self._clear_due_btn.hide()

    def _on_set_due_date(self):
        """设置截止日期。"""
        from datetime import datetime
        self._has_due_date = True
        self._due_edit.setDateTime(datetime.now())
        self._set_due_btn.hide()
        self._due_edit.show()
        self._clear_due_btn.show()
        self.content_changed.emit()

    def _on_clear_due_date(self):
        """清除截止日期。"""
        self._has_due_date = False
        self._set_due_btn.show()
        self._due_edit.hide()
        self._clear_due_btn.hide()
        self.content_changed.emit()

    def get_title(self) -> str:
        """获取标题。"""
        return self._title_edit.text().strip()

    def get_content(self) -> str:
        """获取内容。"""
        return self._content_edit.toPlainText().strip()

    def get_priority(self) -> str | None:
        """获取优先级。"""
        priority = self._priority_combo.currentText()
        return priority if priority != "无" else None

    def get_due_date(self) -> str | None:
        """获取截止日期（ISO 格式）。"""
        if not self._has_due_date:
            return None
        return self._due_edit.dateTime().toPyDateTime().isoformat()

    def get_recurrence(self) -> str | None:
        """获取重复设置。"""
        recurrence = self._recurrence_combo.currentText()
        return recurrence if recurrence != "无" else None

    def get_tags(self) -> list[str]:
        """获取标签列表。"""
        return self._tag_input.get_tags()

    def set_title(self, title: str):
        """设置标题。"""
        self._title_edit.blockSignals(True)
        self._title_edit.setText(title)
        self._title_edit.blockSignals(False)

    def set_content(self, content: str):
        """设置内容。"""
        self._content_edit.blockSignals(True)
        self._content_edit.setPlainText(content)
        self._content_edit.blockSignals(False)

    def set_priority(self, priority: str | None):
        """设置优先级。"""
        self._priority_combo.blockSignals(True)
        if priority and priority in ["P1", "P2", "P3"]:
            self._priority_combo.setCurrentText(priority)
        else:
            self._priority_combo.setCurrentText("无")
        self._priority_combo.blockSignals(False)

    def set_due_date(self, due_date: str | None):
        """设置截止日期（ISO 格式）。"""
        self._due_edit.blockSignals(True)
        if due_date:
            try:
                dt = datetime.fromisoformat(due_date)
                self._due_edit.setDateTime(dt)
                self._has_due_date = True
                self._set_due_btn.hide()
                self._due_edit.show()
                self._clear_due_btn.show()
            except ValueError:
                self._has_due_date = False
                self._set_due_btn.show()
                self._due_edit.hide()
                self._clear_due_btn.hide()
        else:
            self._has_due_date = False
            self._set_due_btn.show()
            self._due_edit.hide()
            self._clear_due_btn.hide()
        self._due_edit.blockSignals(False)

    def set_recurrence(self, recurrence: str | None):
        """设置重复。"""
        self._recurrence_combo.blockSignals(True)
        if recurrence and recurrence in ["每日", "每周", "每月"]:
            self._recurrence_combo.setCurrentText(recurrence)
        else:
            self._recurrence_combo.setCurrentText("无")
        self._recurrence_combo.blockSignals(False)

    def set_tags(self, tags: list[str]):
        """设置标签。"""
        self._tag_input.set_tags(tags)

    def set_all_tags(self, all_tags: list[str]):
        """设置所有可用标签（用于自动补全）。"""
        self._tag_input.set_all_tags(all_tags)

    def clear(self):
        """清空所有输入。"""
        self._title_edit.blockSignals(True)
        self._content_edit.blockSignals(True)
        self._priority_combo.blockSignals(True)
        self._recurrence_combo.blockSignals(True)
        self._tag_input.blockSignals(True)

        self._title_edit.clear()
        self._content_edit.clear()
        self._priority_combo.setCurrentText("无")
        self._recurrence_combo.setCurrentText("无")
        self._has_due_date = False
        self._set_due_btn.show()
        self._due_edit.hide()
        self._clear_due_btn.hide()
        self._tag_input.set_tags([])

        self._title_edit.blockSignals(False)
        self._content_edit.blockSignals(False)
        self._priority_combo.blockSignals(False)
        self._recurrence_combo.blockSignals(False)
        self._tag_input.blockSignals(False)




