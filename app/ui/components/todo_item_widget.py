"""
待办列表项组件。

显示单个待办项，支持完成状态切换、优先级显示、截止日期显示。
"""

from datetime import datetime
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QCheckBox,
    QLabel,
)

from app.models.note import Note


class TodoItemWidget(QWidget):
    """
    待办列表项组件。

    功能：
    - Checkbox 切换完成状态
    - 显示标题、优先级、截止日期
    - 已完成显示删除线和灰色
    - 过期显示红色高亮
    """

    completed_toggled = pyqtSignal(int, bool)  # (note_id, is_completed)

    def __init__(self, note: Note, parent=None):
        super().__init__(parent)
        self._note = note
        self._build()
        self._update_display()

    def _build(self):
        """构建 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Checkbox
        self._checkbox = QCheckBox()
        self._checkbox.setObjectName("todoCheckbox")
        self._checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self._checkbox)

        # 标题标签
        self._title_label = QLabel()
        self._title_label.setObjectName("todoTitleLabel")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label, 1)

        # 优先级标签
        self._priority_label = QLabel()
        self._priority_label.setObjectName("todoPriorityLabel")
        layout.addWidget(self._priority_label)

        # 截止日期标签
        self._due_label = QLabel()
        self._due_label.setObjectName("todoDueLabel")
        layout.addWidget(self._due_label)

    def _on_checkbox_changed(self, state):
        """处理 Checkbox 状态变化。"""
        is_completed = state == Qt.CheckState.Checked.value
        self.completed_toggled.emit(self._note.id, is_completed)
        self._update_display()

    def _update_display(self):
        """更新显示状态。"""
        # 标题
        title = self._note.title or "无标题"
        if self._note.is_completed:
            # 已完成：灰色文字 + 半透明 + ✓ 图标
            self._title_label.setText(f"<span style='color: #9CA3AF;'>✓ {title}</span>")
            self._title_label.setStyleSheet("opacity: 0.7;")
        else:
            # 未完成：正常显示
            self._title_label.setText(title)
            self._title_label.setStyleSheet("")

        # Checkbox
        self._checkbox.blockSignals(True)
        self._checkbox.setChecked(self._note.is_completed)
        self._checkbox.blockSignals(False)

        # 优先级
        if self._note.priority:
            priority_colors = {
                "P1": "#ff4444",
                "P2": "#ff8800",
                "P3": "#4488ff",
            }
            color = priority_colors.get(self._note.priority, "#888")
            self._priority_label.setText(
                f"<span style='color: {color}; font-weight: bold;'>[{self._note.priority}]</span>"
            )
            self._priority_label.show()
        else:
            self._priority_label.hide()

        # 截止日期
        if self._note.due_date:
            try:
                due_dt = datetime.fromisoformat(self._note.due_date)
                now = datetime.now()
                is_overdue = due_dt < now and not self._note.is_completed

                date_str = due_dt.strftime("%m-%d %H:%M")
                if is_overdue:
                    self._due_label.setText(
                        f"<span style='color: #ff4444; font-weight: bold;'>⚠ {date_str}</span>"
                    )
                else:
                    self._due_label.setText(date_str)
                self._due_label.show()
            except ValueError:
                self._due_label.hide()
        else:
            self._due_label.hide()

        # 通知布局更新大小
        self.updateGeometry()

    def update_note(self, note: Note):
        """更新笔记数据并刷新显示。"""
        self._note = note
        self._update_display()

    def sizeHint(self) -> QSize:
        """返回推荐的组件大小。"""
        # 计算实际需要的高度
        # 基础高度：上下边距(4+4) + checkbox高度(~20) + 额外空间
        base_height = 40

        # 如果标题需要换行，增加高度
        if self._title_label.wordWrap():
            # 获取标题文本的实际高度
            text_height = self._title_label.sizeHint().height()
            if text_height > 20:  # 如果超过单行高度
                base_height = max(base_height, text_height + 16)  # 16 = 上下边距 + 额外空间

        return QSize(self.width(), base_height)


