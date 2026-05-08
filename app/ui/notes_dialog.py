import re
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config import NOTES_IMAGES_DIR
from app.core.note_manager import NoteManager
from app.ui.sticky_note_window import _html_to_plain
from app.ui.components.tag_input import TagInput
from app.ui.components.horizontal_tag_bar import HorizontalTagBar
from app.ui.components.search_bar import SearchBar
from app.ui.components.checklist_editor import ChecklistEditor


class NotesPanel(QWidget):
    """笔记面板，嵌入主窗口 QStackedWidget 中。
    支持：多选删除、回收站、无笔记时隐藏编辑区、右键将便签贴到屏幕上、待办整合。
    """

    # Signal emitted when note content is updated (note_id, title, content)
    note_updated = pyqtSignal(int, str, str)

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_note_id: str | None = None
        self._trash_mode = False
        self._pin_windows: list = []
        self._current_filter_tag: str | None = None
        self._current_search_keyword: str = ""
        self._saved_list_width: int | None = None  # 保存列表宽度用于恢复
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)  # 增加组件间距，避免遮挡

        # ── 横向标签栏（顶部）──────────────────────────────────────────
        self._tag_bar = HorizontalTagBar()
        self._tag_bar.tag_selected.connect(self._on_tag_filter_changed)
        layout.addWidget(self._tag_bar)

        # ── toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # 切换笔记列表按钮（最左侧，始终可见）
        self._toggle_btn = QPushButton("☰")
        self._toggle_btn.setObjectName("toggleBtn")
        self._toggle_btn.setFixedSize(64, 36)
        self._toggle_btn.setToolTip("显示/隐藏笔记列表")
        self._toggle_btn.clicked.connect(self._toggle_note_list)
        toolbar.addWidget(self._toggle_btn)

        # 搜索栏
        self._search_bar = SearchBar()
        self._search_bar.search_triggered.connect(self._on_search)
        toolbar.addWidget(self._search_bar)

        toolbar.addStretch()

        # 独立按钮：新建笔记和新建待办
        self._new_note_btn = QPushButton("📝 新建笔记")
        self._new_note_btn.setObjectName("noteToolBtn")
        self._new_note_btn.clicked.connect(lambda: self._on_new("note"))
        toolbar.addWidget(self._new_note_btn)

        self._new_todo_btn = QPushButton("☑ 新建待办")
        self._new_todo_btn.setObjectName("noteToolBtn")
        self._new_todo_btn.clicked.connect(lambda: self._on_new("todo"))
        toolbar.addWidget(self._new_todo_btn)

        self._trash_btn = QPushButton("回收站")
        self._trash_btn.setObjectName("noteToolBtn")
        self._trash_btn.clicked.connect(self._enter_trash)
        toolbar.addWidget(self._trash_btn)

        # Trash-mode buttons (hidden by default)
        self._back_btn = QPushButton("← 返回")
        self._back_btn.setObjectName("noteToolBtn")
        self._back_btn.clicked.connect(self._exit_trash)
        self._back_btn.hide()
        toolbar.addWidget(self._back_btn)

        self._restore_btn = QPushButton("恢复")
        self._restore_btn.setObjectName("noteToolBtn")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.hide()
        toolbar.addWidget(self._restore_btn)

        self._purge_btn = QPushButton("永久删除")
        self._purge_btn.setObjectName("noteToolBtn")
        self._purge_btn.clicked.connect(self._on_purge)
        self._purge_btn.hide()
        toolbar.addWidget(self._purge_btn)

        self._purge_all_btn = QPushButton("清空回收站")
        self._purge_all_btn.setObjectName("noteToolBtn")
        self._purge_all_btn.clicked.connect(self._on_purge_all)
        self._purge_all_btn.hide()
        toolbar.addWidget(self._purge_all_btn)

        toolbar.addStretch()

        self._status_label = QLabel()
        self._status_label.setObjectName("noteStatusLabel")
        toolbar.addWidget(self._status_label)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._status_label.clear)

        layout.addLayout(toolbar)

        # ── list | editor ─────────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(True)  # 允许折叠以支持隐藏功能

        # Left: note list panel
        self._list_panel = QWidget()
        self._list_panel.setObjectName("noteListPanel")
        self._list_panel.setMinimumWidth(120)
        list_panel_layout = QVBoxLayout(self._list_panel)
        list_panel_layout.setContentsMargins(6, 6, 6, 6)
        list_panel_layout.setSpacing(6)

        self._list = QListWidget()
        self._list.setObjectName("noteList")
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        list_panel_layout.addWidget(self._list)

        self._splitter.addWidget(self._list_panel)

        # Right: editor (always visible, disabled when no note selected)
        self._editor_widget = QWidget()
        self._editor_widget.setMinimumWidth(300)
        right_layout = QVBoxLayout(self._editor_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # 标题（笔记和待办共用）
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("noteTitleEdit")
        self._title_edit.setPlaceholderText("标题…")
        right_layout.addWidget(self._title_edit)

        # 普通笔记内容编辑器
        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("noteContentEdit")
        self._content_edit.setPlaceholderText("在此输入笔记内容…")
        right_layout.addWidget(self._content_edit, 1)

        # 待办 checklist 编辑器（初始隐藏）
        self._checklist_editor = ChecklistEditor()
        self._checklist_editor.content_changed.connect(lambda: self._auto_save_timer.start())
        self._checklist_editor.hide()
        right_layout.addWidget(self._checklist_editor, 1)

        # 标签输入（笔记和待办共用）
        self._tag_input = TagInput()
        self._tag_input.tags_changed.connect(self._on_tags_changed)
        right_layout.addWidget(self._tag_input)

        # 编辑器始终可见，但初始状态禁用
        self._set_editor_enabled(False)
        self._splitter.addWidget(self._editor_widget)

        # 保存 splitter 引用并设置初始尺寸
        # 从配置读取列表宽度和可见性
        from app.core.config import ConfigManager
        config = ConfigManager()
        wcfg = config.window_config
        list_width = wcfg.get("note_list_width", 250)
        editor_width = wcfg.get("width", 1000) - list_width

        # 如果配置说列表应该隐藏，则设置为 0
        if not wcfg.get("note_list_visible", True):
            self._splitter.setSizes([0, list_width + editor_width])
        else:
            self._splitter.setSizes([list_width, editor_width])

        layout.addWidget(self._splitter, 1)

        # ── auto-save timer (1.5s debounce) ──────────────────────────
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1500)
        self._auto_save_timer.timeout.connect(self._flush_current)

        self._title_edit.textChanged.connect(self._auto_save_timer.start)
        self._content_edit.textChanged.connect(self._auto_save_timer.start)

    # ------------------------------------------------------------------ load
    def _load(self):
        """从管理器重新加载列表，保留当前选中项（若仍存在）。"""
        self._list.blockSignals(True)
        self._list.clear()

        # 根据过滤条件获取笔记
        if self._trash_mode:
            notes = self._mgr.get_trash()
        elif self._current_search_keyword:
            # 搜索模式：结合搜索关键词和标签过滤
            tags = [self._current_filter_tag] if self._current_filter_tag else None
            notes = self._mgr.search_notes(
                keyword=self._current_search_keyword,
                tags=tags,
                note_types=None  # 不过滤类型，显示所有
            )
        elif self._current_filter_tag:
            notes = self._mgr.search_by_tag(self._current_filter_tag)
        else:
            notes = self._mgr.get_notes()

        restore_item = None
        for note in notes:
            date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
            short = note.title[:20] + "…" if len(note.title) > 20 else note.title
            item = QListWidgetItem(f"{short}\n{date_str}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(note.title)
            self._list.addItem(item)

            if not self._trash_mode and note.id == self._current_note_id:
                restore_item = item

        self._list.blockSignals(False)

        if restore_item:
            self._list.blockSignals(True)
            self._list.setCurrentItem(restore_item)
            self._list.blockSignals(False)
            # 手动加载内容，不触发 _on_selection_changed
            self._load_note_into_editor(self._current_note_id)
        else:
            self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()
        self._refresh_tag_filter()

    def _refresh_tag_filter(self):
        """刷新标签过滤面板和搜索栏。"""
        if self._trash_mode:
            self._tag_bar.hide()
            self._search_bar.hide()
        else:
            self._tag_bar.show()
            self._search_bar.show()
            tags_with_count = self._mgr.get_all_tags_with_count()
            self._tag_bar.set_tags(tags_with_count)

    def _on_tag_filter_changed(self, tag_name: str):
        """处理标签过滤变化。"""
        self._current_filter_tag = tag_name if tag_name else None
        self._load()

    def _on_search(self, keyword: str):
        """处理搜索触发。"""
        self._current_search_keyword = keyword
        self._load()

    def _load_note_into_editor(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return

        self._title_edit.blockSignals(True)
        self._title_edit.setText(note.title)
        self._title_edit.blockSignals(False)

        self._tag_input.blockSignals(True)
        self._tag_input.set_tags(note.tags)
        self._tag_input.set_all_tags(self._mgr.get_all_tags())
        self._tag_input.blockSignals(False)

        if note.note_type == "todo":
            self._content_edit.hide()
            self._checklist_editor.show()
            self._checklist_editor.set_content(note.content)
        else:
            self._checklist_editor.hide()
            self._content_edit.show()

            self._content_edit.blockSignals(True)
            content = note.content
            if "images/" in content:
                def replace_path(m):
                    rel_path = m.group(1)
                    abs_path = NOTES_IMAGES_DIR.parent / rel_path
                    return f'<img src="{abs_path}"'
                content = re.sub(r'<img src="(images/[^"]+)"', replace_path, content)
            self._content_edit.setHtml(content)
            self._content_edit.blockSignals(False)

    def _on_tags_changed(self, tags: list[str]):
        """处理标签变化，触发自动保存。"""
        self._auto_save_timer.start()

    # ------------------------------------------------------------------ selection
    def _on_selection_changed(self):
        selected = self._list.selectedItems()
        n = len(selected)

        if not self._trash_mode and n == 1:
            note_id = selected[0].data(Qt.ItemDataRole.UserRole)
            if note_id != self._current_note_id:
                self._flush_current()
                self._current_note_id = note_id
                self._load_note_into_editor(note_id)
        else:
            # Multi-select or empty: flush pending then hide editor
            self._flush_current()
            if n == 0:
                self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()

    # ------------------------------------------------------------------ editor visibility
    def _update_editor_visibility(self):
        """更新编辑器的启用/禁用状态（不改变可见性）。"""
        selected = self._list.selectedItems()
        has_selection = (not self._trash_mode) and len(selected) == 1
        self._set_editor_enabled(has_selection)

        # 如果没有选择，清空编辑器显示
        if not has_selection:
            self._clear_editor()

    def _set_editor_enabled(self, enabled: bool):
        """设置编辑器的启用/禁用状态。"""
        self._title_edit.setEnabled(enabled)
        self._content_edit.setEnabled(enabled)
        self._tag_input.setEnabled(enabled)
        self._checklist_editor.set_enabled_editing(enabled)

        if not enabled:
            self._title_edit.setPlaceholderText("请从左侧列表选择笔记…")
            self._content_edit.setPlaceholderText("请从左侧列表选择笔记…")
        else:
            self._title_edit.setPlaceholderText("标题…")
            self._content_edit.setPlaceholderText("在此输入笔记内容…")

    # ------------------------------------------------------------------ toolbar state
    def _update_toolbar(self):
        selected_n = len(self._list.selectedItems())
        if self._trash_mode:
            self._new_note_btn.hide()
            self._new_todo_btn.hide()
            self._trash_btn.hide()
            self._back_btn.show()
            self._restore_btn.show()
            self._restore_btn.setEnabled(selected_n > 0)
            self._purge_btn.show()
            self._purge_btn.setEnabled(selected_n > 0)
            self._purge_all_btn.show()
            self._purge_all_btn.setEnabled(self._mgr.trash_count() > 0)
        else:
            self._back_btn.hide()
            self._restore_btn.hide()
            self._purge_btn.hide()
            self._purge_all_btn.hide()
            self._new_note_btn.show()
            self._new_todo_btn.show()
            tc = self._mgr.trash_count()
            self._trash_btn.setText(f"回收站({tc})" if tc > 0 else "回收站")
            self._trash_btn.show()

    # ------------------------------------------------------------------ normal actions
    def _on_new(self, note_type: str = "note"):
        """创建新笔记或待办。如果当前有选中的标签（非"全部笔记"），自动为新笔记添加该标签。"""
        self._flush_current()

        # 创建笔记
        if note_type == "todo":
            note = self._mgr.create(title="新待办", content="", note_type="todo")
        else:
            note = self._mgr.create(title="新笔记", content="", note_type="note")

        # 如果当前有选中的标签（非"全部笔记"），自动添加该标签
        if self._current_filter_tag and self._current_filter_tag != "全部笔记":
            self._mgr.update(note.id, note.title, note.content, [self._current_filter_tag])

        self._current_note_id = note.id
        self._load()
        # 新建后聚焦标题
        self._title_edit.setFocus()

    def _on_delete(self):
        """多选删除：移入回收站（供回收站以外的多选场景使用）。"""
        selected = self._list.selectedItems()
        if not selected:
            return
        n = len(selected)
        msg = f"确定要将选中的 {n} 条笔记移入回收站吗？" if n > 1 else "确定要将这条笔记移入回收站吗？"
        reply = QMessageBox.question(
            self, "移入回收站", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._auto_save_timer.stop()
        deleted_current = False
        for item in selected:
            note_id = item.data(Qt.ItemDataRole.UserRole)
            if note_id == self._current_note_id:
                deleted_current = True
            self._mgr.delete(note_id)

        if deleted_current:
            self._current_note_id = None
            self._clear_editor()

        self._load()

    # ------------------------------------------------------------------ trash mode
    def _enter_trash(self):
        self._flush_current()
        self._trash_mode = True
        self._current_search_keyword = ""  # 清空搜索
        self._search_bar.clear()
        self._load()

    def _exit_trash(self):
        self._trash_mode = False
        self._current_search_keyword = ""  # 清空搜索
        self._search_bar.clear()
        self._load()

    def _on_restore(self):
        selected = self._list.selectedItems()
        if not selected:
            return
        for item in selected:
            self._mgr.restore(item.data(Qt.ItemDataRole.UserRole))
        self._load()

    def _on_purge(self):
        selected = self._list.selectedItems()
        if not selected:
            return
        n = len(selected)
        msg = (f"确定要永久删除选中的 {n} 条笔记吗？此操作不可撤销！"
               if n > 1 else "确定要永久删除这条笔记吗？此操作不可撤销！")
        reply = QMessageBox.question(
            self, "永久删除", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in selected:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _on_purge_all(self):
        tc = self._mgr.trash_count()
        if tc == 0:
            return
        reply = QMessageBox.question(
            self, "清空回收站",
            f"确定要永久删除回收站中全部 {tc} 条笔记吗？此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.purge_all()
            self._load()

    # ------------------------------------------------------------------ save
    def _flush_current(self):
        """将当前编辑器内容立即写盘。"""
        if not self._current_note_id:
            return

        current_note = self._mgr.get(self._current_note_id)
        if not current_note:
            return

        title = self._title_edit.text().strip() or "无标题"
        tags = self._tag_input.get_tags()

        if current_note.note_type == "todo":
            content = self._checklist_editor.get_content()
            note = self._mgr.update(self._current_note_id, title, content, tags)
        else:
            content = self._content_edit.toHtml()
            if str(NOTES_IMAGES_DIR) in content:
                content = content.replace(str(NOTES_IMAGES_DIR) + "/", "images/")
                content = content.replace(str(NOTES_IMAGES_DIR.parent) + "/images/", "images/")
            note = self._mgr.update(self._current_note_id, title, content, tags)

        if note:
            self._status_label.setText("已保存")
            self._status_timer.start()
            self.note_updated.emit(self._current_note_id, title, content)
            # 更新列表项文本
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_note_id:
                    date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
                    short = note.title[:20] + "…" if len(note.title) > 20 else note.title
                    self._list.blockSignals(True)
                    item.setText(f"{short}\n{date_str}")
                    item.setToolTip(note.title)
                    self._list.blockSignals(False)
                    break
            self._refresh_tag_filter()

    def _clear_editor(self):
        self._title_edit.blockSignals(True)
        self._content_edit.blockSignals(True)
        self._tag_input.blockSignals(True)
        self._title_edit.clear()
        self._content_edit.clear()
        self._tag_input.set_tags([])
        self._title_edit.blockSignals(False)
        self._content_edit.blockSignals(False)
        self._tag_input.blockSignals(False)
        self._checklist_editor.clear()
        # 默认显示普通内容编辑器
        self._content_edit.show()
        self._checklist_editor.hide()

    def hideEvent(self, event):
        """切换视图或窗口隐藏时强制保存，防止数据丢失。"""
        self._auto_save_timer.stop()
        self._flush_current()

        # 保存列表宽度和可见性配置
        from app.core.config import ConfigManager
        sizes = self._splitter.sizes()
        list_width = sizes[0] if sizes[0] > 0 else (self._saved_list_width or 250)
        list_visible = sizes[0] > 0
        ConfigManager().update_window_config(
            note_list_width=max(list_width, 120),
            note_list_visible=list_visible,
        )

        super().hideEvent(event)

    # ------------------------------------------------------------------ context menu
    def _on_list_context_menu(self, pos):
        """便签列表右键菜单。"""
        item = self._list.itemAt(pos)
        global_pos = self._list.viewport().mapToGlobal(pos)

        if self._trash_mode:
            if not item:
                return
            note_id = item.data(Qt.ItemDataRole.UserRole)
            menu = QMenu(self)
            restore_action = menu.addAction("↩ 恢复")
            menu.addSeparator()
            purge_action = menu.addAction("🗑 永久删除")
            action = menu.exec(global_pos)
            if action == restore_action:
                self._mgr.restore(note_id)
                self._load()
            elif action == purge_action:
                self._confirm_purge([item])
            return

        # Normal mode — item required for most actions
        menu = QMenu(self)

        if item:
            note_id = item.data(Qt.ItemDataRole.UserRole)
            # Always fetch fresh note from database to get latest is_pinned state
            note = self._mgr.get(note_id)

            # Check if note is already pinned
            if note and note.is_pinned:
                unpin_action = menu.addAction("📌 取消固定")
            else:
                pin_action = menu.addAction("📌 贴到屏幕")

            menu.addSeparator()
            copy_content_action = menu.addAction("📋 复制内容")
            duplicate_action = menu.addAction("📄 创建副本")
            export_action = menu.addAction("💾 导出 .txt")
            menu.addSeparator()
            delete_action = menu.addAction("🗑 删除")
        else:
            note_id = None
            note = None
            pin_action = unpin_action = copy_content_action = duplicate_action = export_action = delete_action = None
            new_action = menu.addAction("✏ 新建便签")
            action = menu.exec(global_pos)
            if action == new_action:
                self._on_new()
            return

        action = menu.exec(global_pos)

        if note and note.is_pinned and action == unpin_action:
            self._unpin_note(note_id)
        elif note and not note.is_pinned and action == pin_action:
            self._pin_note_to_screen(note_id)
        elif action == copy_content_action:
            self._copy_note_content(note_id)
        elif action == duplicate_action:
            self._duplicate_note(note_id)
        elif action == export_action:
            self._export_note_txt(note_id)
        elif action == delete_action:
            self._on_delete_by_id(note_id)

    def _copy_note_content(self, note_id: str):
        """复制笔记纯文本内容到剪贴板。"""
        note = self._mgr.get(note_id)
        if not note:
            return
        QGuiApplication.clipboard().setText(_html_to_plain(note.content))
        self._show_status("已复制到剪贴板")

    def _duplicate_note(self, note_id: str):
        """创建便签副本。"""
        note = self._mgr.get(note_id)
        if not note:
            return
        self._flush_current()
        new_note = self._mgr.create()
        self._mgr.update(new_note.id, f"{note.title} (副本)", note.content)
        self._load()
        self._show_status("已创建副本")

    def _export_note_txt(self, note_id: str):
        """将笔记导出为 .txt 文件。"""
        note = self._mgr.get(note_id)
        if not note:
            return
        safe_name = note.title[:40].replace("/", "-").replace("\\", "-") or "笔记"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出笔记", f"{safe_name}.txt", "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{note.title}\n{'─' * 40}\n{_html_to_plain(note.content)}\n")
            self._show_status("已导出")
        except OSError:
            QMessageBox.warning(self, "导出失败", "无法写入文件，请检查路径权限。")

    def _on_delete_by_id(self, note_id: str):
        """右键删除单条便签（移入回收站）。"""
        reply = QMessageBox.question(
            self, "移入回收站", "确定要将这条笔记移入回收站吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._auto_save_timer.stop()
        if note_id == self._current_note_id:
            self._current_note_id = None
            self._clear_editor()
        self._mgr.delete(note_id)
        self._load()

    def _confirm_purge(self, items: list):
        """永久删除（回收站模式）。"""
        n = len(items)
        msg = (f"确定要永久删除选中的 {n} 条笔记吗？此操作不可撤销！"
               if n > 1 else "确定要永久删除这条笔记吗？此操作不可撤销！")
        reply = QMessageBox.question(
            self, "永久删除", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for item in items:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _show_status(self, msg: str):
        self._status_label.setText(msg)
        self._status_timer.start()

    def _pin_note_to_screen(self, note_id: str):
        """将指定便签独立显示为屏幕浮窗。"""
        from app.ui.sticky_note_window import StickyNoteWindow
        note = self._mgr.get(note_id)
        if not note:
            return

        # Calculate default position (center with slight offset for multiple windows)
        sg = QApplication.primaryScreen().availableGeometry()
        offset = len(self._pin_windows) * 30
        x = (sg.width() - 240) // 2 + sg.x() + offset
        y = (sg.height() - 200) // 2 + sg.y() + offset

        # Pin note to desktop
        try:
            self._mgr.pin_note(note_id, x, y)
        except Exception as e:
            print(f"Failed to pin note: {e}")
            return

        win = StickyNoteWindow(
            note_id=note.id,
            title=note.title,
            content=note.content,
            note_mgr=self._mgr,
        )
        win.move(x, y)
        win.show()
        self._pin_windows.append(win)
        win.closed.connect(
            lambda w=win: self._on_pin_window_closed(w)
        )
        # Connect content change signal for bidirectional sync
        win.content_changed.connect(self.note_updated)

    def _unpin_note(self, note_id: str):
        """取消固定笔记并关闭对应浮窗。"""
        try:
            self._mgr.unpin_note(note_id)
        except Exception as e:
            print(f"Failed to unpin note: {e}")
            return

        # Close corresponding window if exists
        for win in self._pin_windows[:]:
            if hasattr(win, '_note_id') and win._note_id == note_id:
                win.close()
                break

    def _on_pin_window_closed(self, win):
        """浮窗关闭时从列表移除。"""
        if win in self._pin_windows:
            self._pin_windows.remove(win)

    # ------------------------------------------------------------------ screenshot (removed)

    def _toggle_note_list(self):
        """切换笔记列表的显示/隐藏。"""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        list_width = sizes[0]

        if list_width > 0:
            # 隐藏列表：保存当前宽度并设置为 0
            self._saved_list_width = list_width
            self._splitter.setSizes([0, total])
        else:
            # 显示列表：从保存的宽度或配置恢复
            from app.core.config import ConfigManager
            width = self._saved_list_width or ConfigManager().window_config.get("note_list_width", 250)
            self._splitter.setSizes([width, total - width])

    def refresh(self):
        """外部调用：AI 工具写入新笔记后刷新列表。"""
        if not self._trash_mode:
            self._load()

    def refresh_note(self, note_id: int):
        """外部调用：刷新指定笔记的显示（用于同步浮窗更新）。"""
        # If this note is currently being edited, reload it
        if self._current_note_id == note_id:
            note = self._mgr.get(note_id)
            if note:
                # Block signals to prevent triggering another update
                self._title_edit.blockSignals(True)
                self._content_edit.blockSignals(True)
                self._title_edit.setText(note.title)
                # Convert relative image paths to absolute for display
                content = note.content
                if "images/" in content:
                    def replace_path(m):
                        rel_path = m.group(1)
                        abs_path = NOTES_IMAGES_DIR.parent / rel_path
                        return f'<img src="{abs_path}"'
                    content = re.sub(r'<img src="(images/[^"]+)"', replace_path, content)
                self._content_edit.setHtml(content)
                self._title_edit.blockSignals(False)
                self._content_edit.blockSignals(False)

        # Update list item if visible
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == note_id:
                note = self._mgr.get(note_id)
                if note:
                    date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
                    short = note.title[:20] + "…" if len(note.title) > 20 else note.title
                    self._list.blockSignals(True)
                    item.setText(f"{short}\n{date_str}")
                    item.setToolTip(note.title)
                    self._list.blockSignals(False)
                break
