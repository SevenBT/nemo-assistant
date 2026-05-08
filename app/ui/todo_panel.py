"""
待办面板，嵌入主窗口 QStackedWidget 中。

支持：待办列表显示、创建、编辑、完成状态切换、标签过滤。
"""

from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QAbstractItemView,
)

from app.core.note_manager import NoteManager
from app.ui.components.todo_item_widget import TodoItemWidget
from app.ui.components.todo_editor import TodoEditor
from app.ui.components.tag_filter_panel import TagFilterPanel
from app.ui.components.search_bar import SearchBar


class TodoPanel(QWidget):
    """
    待办面板。

    功能：
    - 待办列表显示（按优先级和日期排序）
    - 创建新待办
    - 编辑待办
    - 切换完成状态
    - 标签过滤
    """

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_todo_id: int | None = None
        self._current_filter_tag: str | None = None
        self._current_search_keyword: str = ""  # 当前搜索关键词
        self._build()
        self._load()

    def _build(self):
        """构建 UI。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._new_btn = QPushButton("新建待办")
        self._new_btn.setObjectName("noteToolBtn")
        self._new_btn.clicked.connect(self._on_new)
        toolbar.addWidget(self._new_btn)

        toolbar.addStretch()

        self._status_label = QLabel()
        self._status_label.setObjectName("noteStatusLabel")
        toolbar.addWidget(self._status_label)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._status_label.clear)

        layout.addLayout(toolbar)

        # Splitter: list | editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Left: tag filter + todo list
        left = QWidget()
        left.setObjectName("noteListPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)

        # Tag filter
        self._tag_filter = TagFilterPanel()
        self._tag_filter.tag_selected.connect(self._on_tag_filter_changed)
        left_layout.addWidget(self._tag_filter)

        # Search bar
        self._search_bar = SearchBar()
        self._search_bar.search_triggered.connect(self._on_search)
        left_layout.addWidget(self._search_bar)

        # Todo list
        self._list = QListWidget()
        self._list.setObjectName("noteList")
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._list, 1)
        splitter.addWidget(left)

        # Right: editor
        self._editor_widget = QWidget()
        editor_layout = QVBoxLayout(self._editor_widget)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)

        self._editor = TodoEditor()
        self._editor.content_changed.connect(self._on_content_changed)
        editor_layout.addWidget(self._editor)

        self._editor_widget.hide()
        splitter.addWidget(self._editor_widget)
        splitter.setSizes([200, 460])

        layout.addWidget(splitter, 1)

        # Auto-save timer
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1500)
        self._auto_save_timer.timeout.connect(self._flush_current)

    def _on_content_changed(self):
        """内容变化时启动自动保存。"""
        self._auto_save_timer.start()

    def _load(self):
        """加载待办列表。"""
        self._list.blockSignals(True)
        self._list.clear()

        # 根据过滤条件获取待办
        if self._current_search_keyword:
            # 搜索模式：结合搜索关键词和标签过滤
            tags = [self._current_filter_tag] if self._current_filter_tag else None
            all_results = self._mgr.search_notes(
                keyword=self._current_search_keyword,
                tags=tags,
                note_types=["todo"]
            )
            todos = all_results
        elif self._current_filter_tag:
            all_todos = self._mgr.search_by_tag(self._current_filter_tag)
            todos = [t for t in all_todos if t.note_type == "todo"]
        else:
            todos = self._mgr.get_notes_by_type("todo")

        restore_item = None
        for todo in todos:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, todo.id)
            self._list.addItem(item)

            # 创建自定义 widget
            widget = TodoItemWidget(todo)
            widget.completed_toggled.connect(self._on_todo_completed)
            self._list.setItemWidget(item, widget)
            item.setSizeHint(widget.sizeHint())

            if todo.id == self._current_todo_id:
                restore_item = item

        self._list.blockSignals(False)

        if restore_item:
            self._list.setCurrentItem(restore_item)
        else:
            self._current_todo_id = None

        self._update_editor_visibility()
        self._refresh_tag_filter()

    def _refresh_tag_filter(self):
        """刷新标签过滤面板。"""
        tags_with_count = self._mgr.get_all_tags_with_count()
        self._tag_filter.set_tags(tags_with_count)

    def _on_tag_filter_changed(self, tag_name: str):
        """处理标签过滤变化。"""
        self._current_filter_tag = tag_name if tag_name else None
        self._load()

    def _on_search(self, keyword: str):
        """处理搜索触发。"""
        self._current_search_keyword = keyword
        self._load()

    def _on_selection_changed(self):
        """处理选择变化。"""
        selected = self._list.selectedItems()
        if len(selected) == 1:
            todo_id = selected[0].data(Qt.ItemDataRole.UserRole)
            if todo_id != self._current_todo_id:
                self._flush_current()
                self._current_todo_id = todo_id
                self._load_todo_into_editor(todo_id)
        else:
            self._flush_current()
            self._current_todo_id = None

        self._update_editor_visibility()

    def _update_editor_visibility(self):
        """更新编辑器可见性。"""
        selected = self._list.selectedItems()
        visible = len(selected) == 1
        self._editor_widget.setVisible(visible)

    def _load_todo_into_editor(self, todo_id: int):
        """加载待办到编辑器。"""
        todo = self._mgr.get(todo_id)
        if not todo:
            return

        self._editor.set_title(todo.title)
        self._editor.set_content(todo.content)
        self._editor.set_priority(todo.priority)
        self._editor.set_due_date(todo.due_date)
        self._editor.set_recurrence(todo.recurrence)
        self._editor.set_tags(todo.tags)
        self._editor.set_all_tags(self._mgr.get_all_tags())

    def _on_new(self):
        """创建新待办。"""
        self._flush_current()
        todo = self._mgr.create(title="新待办", content="", note_type="todo")
        self._current_todo_id = todo.id
        self._load()
        # 选中新创建的待办
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == todo.id:
                self._list.clearSelection()
                self._list.setCurrentRow(i)
                break
        # 清空编辑器
        self._editor.clear()

    def _on_todo_completed(self, todo_id: int, is_completed: bool):
        """处理待办完成状态切换。"""
        self._mgr.toggle_todo_completed(todo_id)
        # 刷新列表项显示
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == todo_id:
                widget = self._list.itemWidget(item)
                if widget:
                    todo = self._mgr.get(todo_id)
                    if todo:
                        widget.update_note(todo)
                        # 更新列表项大小提示
                        item.setSizeHint(widget.sizeHint())
                break

    def _flush_current(self):
        """保存当前编辑的待办。"""
        if not self._current_todo_id:
            return

        title = self._editor.get_title() or "无标题"
        content = self._editor.get_content()
        priority = self._editor.get_priority()
        due_date = self._editor.get_due_date()
        recurrence = self._editor.get_recurrence()
        tags = self._editor.get_tags()

        todo = self._mgr.update(
            self._current_todo_id,
            title,
            content,
            tags,
            priority,
            due_date,
            recurrence,
        )
        if todo:
            self._status_label.setText("已保存")
            self._status_timer.start()
            # 更新列表项显示
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_todo_id:
                    widget = self._list.itemWidget(item)
                    if widget:
                        widget.update_note(todo)
                        # 更新列表项大小提示
                        item.setSizeHint(widget.sizeHint())
                    break
            # 刷新标签过滤
            self._refresh_tag_filter()

    def hideEvent(self, event):
        """切换视图时强制保存。"""
        self._auto_save_timer.stop()
        self._flush_current()
        super().hideEvent(event)

    def refresh(self):
        """外部调用：刷新列表。"""
        self._load()




