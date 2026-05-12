"""
搜索栏组件 - 使用 Fluent SearchLineEdit。
"""

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import SearchLineEdit


class SearchBar(QWidget):
    """搜索栏组件，带防抖功能。"""

    search_triggered = pyqtSignal(str)  # 发送搜索关键词

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._search_input = SearchLineEdit()
        self._search_input.setPlaceholderText("搜索笔记...")
        self._search_input.textChanged.connect(self._on_text_changed)
        self._search_input.searchSignal.connect(self._on_search_signal)
        self._search_input.clearSignal.connect(lambda: self.search_triggered.emit(""))
        layout.addWidget(self._search_input, 1)

        # 防抖定时器（300ms）
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._trigger_search)

    def _on_text_changed(self, text: str):
        self._debounce_timer.start()

    def _on_search_signal(self, text: str):
        self._debounce_timer.stop()
        self.search_triggered.emit(text.strip())

    def _trigger_search(self):
        keyword = self._search_input.text().strip()
        self.search_triggered.emit(keyword)

    def text(self) -> str:
        return self._search_input.text().strip()

    def clear(self):
        self._search_input.clear()
