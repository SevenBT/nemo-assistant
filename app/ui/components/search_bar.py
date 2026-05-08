"""
搜索栏组件，支持实时搜索和防抖。
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class SearchBar(QWidget):
    """搜索栏组件，带防抖和清除按钮。"""

    search_triggered = pyqtSignal(str)  # 发送搜索关键词

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 搜索输入框
        self._search_input = QLineEdit()
        self._search_input.setObjectName("searchInput")
        self._search_input.setPlaceholderText("搜索笔记...")
        self._search_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._search_input, 1)

        # 清除按钮（初始隐藏）
        self._clear_btn = QPushButton("✕")
        self._clear_btn.setObjectName("searchClearBtn")
        self._clear_btn.setFixedSize(24, 24)
        self._clear_btn.clicked.connect(self._on_clear)
        self._clear_btn.hide()
        layout.addWidget(self._clear_btn)

        # 防抖定时器（300ms）
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._trigger_search)

    def _on_text_changed(self, text: str):
        """输入框文本变化时，重启防抖定时器。"""
        # 显示/隐藏清除按钮
        self._clear_btn.setVisible(bool(text))
        # 重启防抖定时器
        self._debounce_timer.start()

    def _trigger_search(self):
        """防抖定时器触发，发送搜索信号。"""
        keyword = self._search_input.text().strip()
        self.search_triggered.emit(keyword)

    def _on_clear(self):
        """清除按钮点击，清空输入并触发搜索。"""
        self._search_input.clear()
        self.search_triggered.emit("")

    def text(self) -> str:
        """获取当前搜索关键词。"""
        return self._search_input.text().strip()

    def clear(self):
        """清空搜索框。"""
        self._search_input.clear()
