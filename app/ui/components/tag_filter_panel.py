"""
标签过滤面板组件。

显示所有标签列表，支持点击过滤笔记。
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
)


class TagFilterPanel(QWidget):
    """
    标签过滤面板。

    功能：
    - 显示所有标签列表
    - 显示每个标签的笔记数量
    - 点击标签过滤笔记列表
    - "全部笔记"选项（清除过滤）
    """

    tag_selected = pyqtSignal(str)  # 标签被选中时发出信号，空字符串表示"全部笔记"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        """构建 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标题
        title = QLabel("标签筛选")
        title.setObjectName("tagFilterTitle")
        layout.addWidget(title)

        # 标签列表
        self._list = QListWidget()
        self._list.setObjectName("tagFilterList")
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

    def _on_item_clicked(self, item: QListWidgetItem):
        """处理标签项点击。"""
        tag_name = item.data(Qt.ItemDataRole.UserRole)
        self.tag_selected.emit(tag_name or "")

    def set_tags(self, tags_with_count: list[tuple[str, int]]):
        """
        设置标签列表。

        Args:
            tags_with_count: (标签名, 笔记数量) 元组列表
        """
        self._list.clear()

        # 添加"全部笔记"选项
        all_item = QListWidgetItem("📋 全部笔记")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(all_item)

        # 添加标签项
        for tag_name, count in tags_with_count:
            item = QListWidgetItem(f"#{tag_name} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, tag_name)
            self._list.addItem(item)

    def clear_selection(self):
        """清除选中状态。"""
        self._list.clearSelection()
