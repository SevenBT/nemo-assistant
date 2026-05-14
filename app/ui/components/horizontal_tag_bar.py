"""
横向标签栏组件 - Fluent Design 风格。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QScrollArea, QWidget
from qfluentwidgets import PillPushButton, FluentIcon, Action
from app.ui.components.context_menu import ContextMenu


# 固定显示的标签
FIXED_TAGS = ["学习", "工作", "生活"]

# 标签颜色方案
TAG_COLORS = [
    "#6B7280",  # 灰色（全部笔记）
    "#3B82F6",  # 蓝色（学习）
    "#10B981",  # 绿色（工作）
    "#F59E0B",  # 橙色（生活）
    "#8B5CF6",  # 紫色（自定义）
]


class HorizontalTagBar(QWidget):
    """横向标签栏，Fluent Pill 按钮风格。"""

    tag_selected = pyqtSignal(str)  # 空字符串表示"全部笔记"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str | None, PillPushButton] = {}
        self._current_tag: str | None = None
        self._custom_tags: list[tuple[str, int]] = []
        self._custom_button: PillPushButton | None = None
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(42)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.viewport().setStyleSheet("background: transparent;")

        self._container = QWidget()
        self._container_layout = QHBoxLayout(self._container)
        self._container_layout.setContentsMargins(4, 4, 4, 4)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch()

        scroll.setWidget(self._container)
        layout.addWidget(scroll)

    def _on_tag_clicked(self, tag_name: str | None):
        self._current_tag = tag_name
        self._update_button_states()
        self.tag_selected.emit(tag_name or "")

    def _update_button_states(self):
        for tag_name, btn in self._buttons.items():
            is_selected = tag_name == self._current_tag
            btn.setChecked(is_selected)

    def set_tags(self, tags_with_count: list[tuple[str, int]]):
        # Clear existing
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        if self._custom_button:
            self._custom_button.deleteLater()
            self._custom_button = None

        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Separate fixed and custom tags
        fixed_tags_dict = {}
        custom_tags = []
        for tag_name, count in tags_with_count:
            if tag_name in FIXED_TAGS:
                fixed_tags_dict[tag_name] = count
            else:
                custom_tags.append((tag_name, count))
        self._custom_tags = sorted(custom_tags, key=lambda x: x[0])

        # "全部笔记" button
        all_btn = PillPushButton("全部笔记")
        all_btn.setCheckable(True)
        all_btn.setChecked(self._current_tag is None)
        all_btn.clicked.connect(lambda: self._on_tag_clicked(None))
        self._buttons[None] = all_btn
        self._container_layout.insertWidget(self._container_layout.count() - 1, all_btn)

        # Fixed tag buttons
        for tag_name in FIXED_TAGS:
            count = fixed_tags_dict.get(tag_name, 0)
            btn = PillPushButton(f"{tag_name} ({count})")
            btn.setCheckable(True)
            btn.setChecked(self._current_tag == tag_name)
            btn.clicked.connect(lambda checked, t=tag_name: self._on_tag_clicked(t))
            self._buttons[tag_name] = btn
            self._container_layout.insertWidget(self._container_layout.count() - 1, btn)

        # Custom tags dropdown
        if self._custom_tags:
            custom_btn = PillPushButton("自定义 ▼")
            custom_btn.clicked.connect(self._show_custom_menu)
            self._custom_button = custom_btn
            self._container_layout.insertWidget(self._container_layout.count() - 1, custom_btn)

    def _show_custom_menu(self):
        if not self._custom_tags or not self._custom_button:
            return
        menu = ContextMenu(parent=self)
        for tag_name, count in self._custom_tags:
            menu.addAction(Action(
                FluentIcon.TAG, f"{tag_name} ({count})",
                triggered=lambda checked, t=tag_name: self._on_tag_clicked(t)
            ))
        menu.exec(self._custom_button.mapToGlobal(self._custom_button.rect().bottomLeft()))

    def clear_selection(self):
        self._current_tag = None
        self._update_button_states()
