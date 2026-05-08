"""
横向标签栏组件。

显示标签为横向按钮，类似浏览器标签页。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QMenu,
)


# 固定显示的标签
FIXED_TAGS = ["学习", "工作", "生活"]


# 标签颜色方案
TAG_COLORS = [
    "#6B7280",  # 灰色（全部笔记）
    "#3B82F6",  # 蓝色（学习）
    "#10B981",  # 绿色（工作）
    "#F59E0B",  # 橙色（生活）
    "#8B5CF6",  # 紫色（自定义）
    "#EF4444",  # 红色
    "#EC4899",  # 粉色
    "#14B8A6",  # 青色
]


class HorizontalTagBar(QWidget):
    """
    横向标签栏组件。

    功能：
    - 横向显示标签按钮
    - 每个标签用不同颜色
    - 显示笔记数量
    - 支持点击切换
    """

    tag_selected = pyqtSignal(str)  # 标签被选中时发出信号，空字符串表示"全部笔记"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._current_tag: str | None = None
        self._custom_tags: list[tuple[str, int]] = []  # 存储自定义标签
        self._custom_button: QPushButton | None = None  # "自定义"按钮
        self._build()

    def _build(self):
        """构建 UI。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)  # 添加下边距，避免遮挡下方内容
        layout.setSpacing(0)

        # 使用滚动区域支持大量标签
        scroll = QScrollArea()
        scroll.setObjectName("tagBarScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(42)

        # 标签容器
        self._container = QWidget()
        self._container_layout = QHBoxLayout(self._container)
        self._container_layout.setContentsMargins(4, 4, 4, 4)
        self._container_layout.setSpacing(6)
        self._container_layout.addStretch()

        scroll.setWidget(self._container)
        layout.addWidget(scroll)

    def _get_tag_color(self, index: int) -> str:
        """
        获取标签颜色。

        Args:
            index: 标签索引

        Returns:
            str: 颜色代码
        """
        return TAG_COLORS[index % len(TAG_COLORS)]

    def _on_tag_clicked(self, tag_name: str | None):
        """处理标签点击。"""
        self._current_tag = tag_name
        self._update_button_states()
        self.tag_selected.emit(tag_name or "")

    def _update_button_states(self):
        """更新按钮选中状态。"""
        for tag_name, btn in self._buttons.items():
            is_selected = tag_name == self._current_tag
            btn.setProperty("selected", is_selected)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_tags(self, tags_with_count: list[tuple[str, int]]):
        """
        设置标签列表。

        Args:
            tags_with_count: (标签名, 笔记数量) 元组列表
        """
        # 清空现有按钮
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        if self._custom_button:
            self._custom_button.deleteLater()
            self._custom_button = None

        # 移除所有 widget（除了 stretch）
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 分离固定标签和自定义标签
        fixed_tags_dict = {}
        custom_tags = []

        for tag_name, count in tags_with_count:
            if tag_name in FIXED_TAGS:
                fixed_tags_dict[tag_name] = count
            else:
                custom_tags.append((tag_name, count))

        self._custom_tags = sorted(custom_tags, key=lambda x: x[0])  # 按字母顺序排序

        # 添加"全部笔记"按钮
        all_btn = QPushButton("全部笔记")
        all_btn.setObjectName("tagBarButton")
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.clicked.connect(lambda: self._on_tag_clicked(None))
        all_btn.setStyleSheet(f"""
            QPushButton#tagBarButton {{
                background-color: {TAG_COLORS[0]};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#tagBarButton:hover {{
                background-color: {TAG_COLORS[0]}dd;
            }}
            QPushButton#tagBarButton[selected="true"] {{
                background-color: {TAG_COLORS[0]};
                border: 2px solid white;
            }}
        """)
        self._buttons[None] = all_btn
        self._container_layout.insertWidget(self._container_layout.count() - 1, all_btn)

        # 添加固定标签按钮（按 FIXED_TAGS 顺序）
        for i, tag_name in enumerate(FIXED_TAGS):
            count = fixed_tags_dict.get(tag_name, 0)
            color = TAG_COLORS[i + 1]  # 从索引1开始（0是全部笔记）
            btn = QPushButton(f"{tag_name} ({count})")
            btn.setObjectName("tagBarButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, t=tag_name: self._on_tag_clicked(t))
            btn.setStyleSheet(f"""
                QPushButton#tagBarButton {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }}
                QPushButton#tagBarButton:hover {{
                    background-color: {color}dd;
                }}
                QPushButton#tagBarButton[selected="true"] {{
                    background-color: {color};
                    border: 2px solid white;
                }}
            """)
            self._buttons[tag_name] = btn
            self._container_layout.insertWidget(self._container_layout.count() - 1, btn)

        # 添加"自定义"按钮（如果有自定义标签）
        if self._custom_tags:
            custom_btn = QPushButton("自定义 ▼")
            custom_btn.setObjectName("tagBarButton")
            custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            custom_btn.clicked.connect(self._show_custom_menu)
            custom_btn.setStyleSheet(f"""
                QPushButton#tagBarButton {{
                    background-color: {TAG_COLORS[4]};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-weight: bold;
                }}
                QPushButton#tagBarButton:hover {{
                    background-color: {TAG_COLORS[4]}dd;
                }}
            """)
            self._custom_button = custom_btn
            self._container_layout.insertWidget(self._container_layout.count() - 1, custom_btn)

        # 默认选中"全部笔记"
        if self._current_tag is None:
            self._update_button_states()

    def _show_custom_menu(self):
        """显示自定义标签下拉菜单。"""
        if not self._custom_tags or not self._custom_button:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D3748;
                color: white;
                border: 1px solid #4A5568;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 12px;
                border-radius: 2px;
            }
            QMenu::item:selected {
                background-color: #4A5568;
            }
        """)

        for tag_name, count in self._custom_tags:
            action = menu.addAction(f"{tag_name} ({count})")
            action.triggered.connect(lambda checked, t=tag_name: self._on_tag_clicked(t))

        # 在按钮下方显示菜单
        menu.exec(self._custom_button.mapToGlobal(self._custom_button.rect().bottomLeft()))

    def clear_selection(self):
        """清除选中状态。"""
        self._current_tag = None
        self._update_button_states()

