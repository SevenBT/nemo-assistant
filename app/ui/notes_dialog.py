import re
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    MessageBox,
    PushButton,
    TextEdit,
    TransparentToolButton,
    ToolTipFilter,
    ToolTipPosition,
)

from app.core.config import NOTES_IMAGES_DIR
from app.core.note_manager import NoteManager
from app.ui.sticky_note_window import _html_to_plain
from app.ui.components.tag_input import TagInput
from app.ui.components.horizontal_tag_bar import HorizontalTagBar
from app.ui.components.search_bar import SearchBar
from app.ui.components.checklist_editor import ChecklistEditor
from app.ui.components.context_menu import ContextMenu


# Palette for note color dots — cycles by note id
_NOTE_DOT_COLORS = [
    "#F87171",  # red
    "#FB923C",  # orange
    "#FBBF24",  # yellow
    "#34D399",  # green
    "#60A5FA",  # blue
    "#A78BFA",  # purple
    "#F472B6",  # pink
    "#2DD4BF",  # teal
]


def _note_color(note_id) -> str:
    """Return a stable color for a note based on its id."""
    try:
        idx = int(str(note_id)) % len(_NOTE_DOT_COLORS)
    except (ValueError, TypeError):
        idx = hash(str(note_id)) % len(_NOTE_DOT_COLORS)
    return _NOTE_DOT_COLORS[idx]


class _NoteItemWidget(QWidget):
    """List item widget with a colored left stripe, title, and date."""

    def __init__(self, title: str, date_str: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)

        # Colored dot indicator
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(
            f"background: {color}; border-radius: 4px; min-width: 8px; max-width: 8px;"
        )
        layout.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Text block
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
        self._title_lbl.setWordWrap(False)
        text_col.addWidget(self._title_lbl)

        self._date_lbl = QLabel(date_str)
        self._date_lbl.setStyleSheet("font-size: 10px; color: #9CA3AF; background: transparent;")
        text_col.addWidget(self._date_lbl)

        layout.addLayout(text_col, 1)

    def update_text(self, title: str, date_str: str):
        self._title_lbl.setText(title)
        self._date_lbl.setText(date_str)


class NotesPanel(QWidget):
    """笔记面板 - Fluent Design 风格。"""

    note_updated = pyqtSignal(int, str, str)

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_note_id: str | None = None
        self._trash_mode = False
        self._pin_windows: list = []
        self._current_filter_tag: str | None = None
        self._current_search_keyword: str = ""
        self._saved_list_width: int | None = None
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Tag bar (top) ────────────────────────────────────────────
        self._tag_bar = HorizontalTagBar()
        self._tag_bar.tag_selected.connect(self._on_tag_filter_changed)
        layout.addWidget(self._tag_bar)

        # ── Toolbar ──────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._toggle_btn = TransparentToolButton(FluentIcon.MENU)
        self._toggle_btn.setFixedSize(36, 32)
        self._toggle_btn.setToolTip("显示/隐藏笔记列表")
        self._toggle_btn.installEventFilter(
            ToolTipFilter(self._toggle_btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        self._toggle_btn.clicked.connect(self._toggle_note_list)
        toolbar.addWidget(self._toggle_btn)

        self._search_bar = SearchBar()
        self._search_bar.search_triggered.connect(self._on_search)
        toolbar.addWidget(self._search_bar)

        toolbar.addStretch()

        # Normal mode buttons
        self._new_note_btn = PushButton(FluentIcon.EDIT, "新建笔记")
        self._new_note_btn.clicked.connect(lambda: self._on_new("note"))
        toolbar.addWidget(self._new_note_btn)

        self._new_todo_btn = PushButton(FluentIcon.CHECKBOX, "新建待办")
        self._new_todo_btn.clicked.connect(lambda: self._on_new("todo"))
        toolbar.addWidget(self._new_todo_btn)

        self._trash_btn = PushButton(FluentIcon.DELETE, "回收站")
        self._trash_btn.clicked.connect(self._enter_trash)
        toolbar.addWidget(self._trash_btn)

        # Trash mode buttons (hidden by default)
        self._back_btn = PushButton(FluentIcon.RETURN, "返回")
        self._back_btn.clicked.connect(self._exit_trash)
        self._back_btn.hide()
        toolbar.addWidget(self._back_btn)

        self._restore_btn = PushButton(FluentIcon.HISTORY, "恢复")
        self._restore_btn.clicked.connect(self._on_restore)
        self._restore_btn.hide()
        toolbar.addWidget(self._restore_btn)

        self._purge_btn = PushButton(FluentIcon.DELETE, "永久删除")
        self._purge_btn.clicked.connect(self._on_purge)
        self._purge_btn.hide()
        toolbar.addWidget(self._purge_btn)

        self._purge_all_btn = PushButton(FluentIcon.BROOM, "清空回收站")
        self._purge_all_btn.clicked.connect(self._on_purge_all)
        self._purge_all_btn.hide()
        toolbar.addWidget(self._purge_all_btn)

        toolbar.addStretch()

        self._status_label = CaptionLabel()
        toolbar.addWidget(self._status_label)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._status_label.clear)

        layout.addLayout(toolbar)

        # ── List | Editor splitter ───────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(True)

        # Left: note list
        self._list_panel = QWidget()
        self._list_panel.setObjectName("noteListPanel")
        self._list_panel.setMinimumWidth(120)
        list_panel_layout = QVBoxLayout(self._list_panel)
        list_panel_layout.setContentsMargins(6, 6, 6, 6)
        list_panel_layout.setSpacing(6)

        self._list = ListWidget()
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        list_panel_layout.addWidget(self._list)

        self._splitter.addWidget(self._list_panel)

        # Right: editor
        self._editor_widget = QWidget()
        self._editor_widget.setMinimumWidth(300)
        right_layout = QVBoxLayout(self._editor_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._title_edit = LineEdit()
        self._title_edit.setPlaceholderText("标题…")
        right_layout.addWidget(self._title_edit)

        self._content_edit = TextEdit()
        self._content_edit.setPlaceholderText("在此输入笔记内容…")
        right_layout.addWidget(self._content_edit, 1)

        self._checklist_editor = ChecklistEditor()
        self._checklist_editor.content_changed.connect(lambda: self._auto_save_timer.start())
        self._checklist_editor.hide()
        right_layout.addWidget(self._checklist_editor, 1)

        self._tag_input = TagInput()
        self._tag_input.tags_changed.connect(self._on_tags_changed)
        right_layout.addWidget(self._tag_input)

        self._set_editor_enabled(False)
        self._splitter.addWidget(self._editor_widget)

        # Restore splitter sizes from config
        from app.core.config import ConfigManager
        config = ConfigManager()
        wcfg = config.window_config
        list_width = wcfg.get("note_list_width", 250)
        editor_width = wcfg.get("width", 1000) - list_width

        if not wcfg.get("note_list_visible", True):
            self._splitter.setSizes([0, list_width + editor_width])
        else:
            self._splitter.setSizes([list_width, editor_width])

        layout.addWidget(self._splitter, 1)

        # Auto-save timer (1.5s debounce)
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1500)
        self._auto_save_timer.timeout.connect(self._flush_current)

        self._title_edit.textChanged.connect(lambda _: self._auto_save_timer.start())
        self._content_edit.textChanged.connect(self._auto_save_timer.start)

    # ------------------------------------------------------------------ load
    def _load(self):
        self._list.blockSignals(True)
        self._list.clear()

        if self._trash_mode:
            notes = self._mgr.get_trash()
        elif self._current_search_keyword:
            tags = [self._current_filter_tag] if self._current_filter_tag else None
            notes = self._mgr.search_notes(keyword=self._current_search_keyword, tags=tags, note_types=None)
        elif self._current_filter_tag:
            notes = self._mgr.search_by_tag(self._current_filter_tag)
        else:
            notes = self._mgr.get_notes()

        restore_item = None
        for note in notes:
            date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
            short = note.title[:20] + "…" if len(note.title) > 20 else note.title
            color = _note_color(note.id)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(note.title)
            self._list.addItem(item)

            widget = _NoteItemWidget(short, date_str, color)
            item.setSizeHint(widget.sizeHint())
            self._list.setItemWidget(item, widget)

            if not self._trash_mode and note.id == self._current_note_id:
                restore_item = item

        self._list.blockSignals(False)

        if restore_item:
            self._list.blockSignals(True)
            self._list.setCurrentItem(restore_item)
            self._list.blockSignals(False)
            self._load_note_into_editor(self._current_note_id)
        else:
            self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()
        self._refresh_tag_filter()

    def _refresh_tag_filter(self):
        if self._trash_mode:
            self._tag_bar.hide()
            self._search_bar.hide()
        else:
            self._tag_bar.show()
            self._search_bar.show()
            tags_with_count = self._mgr.get_all_tags_with_count()
            self._tag_bar.set_tags(tags_with_count)

    def _on_tag_filter_changed(self, tag_name: str):
        self._current_filter_tag = tag_name if tag_name else None
        self._load()

    def _on_search(self, keyword: str):
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
            self._flush_current()
            if n == 0:
                self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()

    # ------------------------------------------------------------------ editor visibility
    def _update_editor_visibility(self):
        selected = self._list.selectedItems()
        has_selection = (not self._trash_mode) and len(selected) == 1
        self._set_editor_enabled(has_selection)
        if not has_selection:
            self._clear_editor()

    def _set_editor_enabled(self, enabled: bool):
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
        self._flush_current()
        if note_type == "todo":
            note = self._mgr.create(title="新待办", content="", note_type="todo")
        else:
            note = self._mgr.create(title="新笔记", content="", note_type="note")

        if self._current_filter_tag and self._current_filter_tag != "全部笔记":
            self._mgr.update(note.id, note.title, note.content, [self._current_filter_tag])

        self._current_note_id = note.id
        self._load()
        self._title_edit.setFocus()

    def _on_delete(self):
        selected = self._list.selectedItems()
        if not selected:
            return
        n = len(selected)
        msg = f"确定要将选中的 {n} 条笔记移入回收站吗？" if n > 1 else "确定要将这条笔记移入回收站吗？"

        w = MessageBox("移入回收站", msg, self.window())
        if not w.exec():
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
        self._current_search_keyword = ""
        self._search_bar.clear()
        self._load()

    def _exit_trash(self):
        self._trash_mode = False
        self._current_search_keyword = ""
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
        w = MessageBox("永久删除", msg, self.window())
        if w.exec():
            for item in selected:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _on_purge_all(self):
        tc = self._mgr.trash_count()
        if tc == 0:
            return
        w = MessageBox("清空回收站", f"确定要永久删除回收站中全部 {tc} 条笔记吗？此操作不可撤销！", self.window())
        if w.exec():
            self._mgr.purge_all()
            self._load()

    # ------------------------------------------------------------------ save
    def _flush_current(self):
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
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_note_id:
                    date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
                    short = note.title[:20] + "…" if len(note.title) > 20 else note.title
                    self._list.blockSignals(True)
                    widget = self._list.itemWidget(item)
                    if isinstance(widget, _NoteItemWidget):
                        widget.update_text(short, date_str)
                        item.setSizeHint(widget.sizeHint())
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
        self._content_edit.show()
        self._checklist_editor.hide()

    def hideEvent(self, event):
        self._auto_save_timer.stop()
        self._flush_current()
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
        item = self._list.itemAt(pos)
        global_pos = self._list.viewport().mapToGlobal(pos)

        if self._trash_mode:
            if not item:
                return
            note_id = item.data(Qt.ItemDataRole.UserRole)
            menu = ContextMenu(parent=self)
            menu.addAction(Action(FluentIcon.HISTORY, "恢复",
                                  triggered=lambda: (self._mgr.restore(note_id), self._load())))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.DELETE, "永久删除",
                                  triggered=lambda: self._confirm_purge([item])))
            menu.exec(global_pos)
            return

        menu = ContextMenu(parent=self)

        if item:
            note_id = item.data(Qt.ItemDataRole.UserRole)
            note = self._mgr.get(note_id)

            if note and note.is_pinned:
                menu.addAction(Action(FluentIcon.UNPIN, "取消固定",
                                      triggered=lambda: self._unpin_note(note_id)))
            else:
                menu.addAction(Action(FluentIcon.PIN, "贴到屏幕",
                                      triggered=lambda: self._pin_note_to_screen(note_id)))

            menu.addSeparator()
            menu.addAction(Action(FluentIcon.COPY, "复制内容",
                                  triggered=lambda: self._copy_note_content(note_id)))
            menu.addAction(Action(FluentIcon.DOCUMENT, "创建副本",
                                  triggered=lambda: self._duplicate_note(note_id)))
            menu.addAction(Action(FluentIcon.SAVE, "导出 .txt",
                                  triggered=lambda: self._export_note_txt(note_id)))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.DELETE, "删除",
                                  triggered=lambda: (
                                      self._on_delete() if len(self._list.selectedItems()) > 1
                                      else self._on_delete_by_id(note_id)
                                  )))
        else:
            menu.addAction(Action(FluentIcon.EDIT, "新建便签",
                                  triggered=self._on_new))

        menu.exec(global_pos)

    def _copy_note_content(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
        QGuiApplication.clipboard().setText(_html_to_plain(note.content))
        self._show_status("已复制到剪贴板")

    def _duplicate_note(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
        self._flush_current()
        new_note = self._mgr.create()
        self._mgr.update(new_note.id, f"{note.title} (副本)", note.content)
        self._load()
        self._show_status("已创建副本")

    def _export_note_txt(self, note_id: str):
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
            w = MessageBox("导出失败", "无法写入文件，请检查路径权限。", self.window())
            w.exec()

    def _on_delete_by_id(self, note_id: str):
        w = MessageBox("移入回收站", "确定要将这条笔记移入回收站吗？", self.window())
        if not w.exec():
            return
        self._auto_save_timer.stop()
        if note_id == self._current_note_id:
            self._current_note_id = None
            self._clear_editor()
        self._mgr.delete(note_id)
        self._load()

    def _confirm_purge(self, items: list):
        n = len(items)
        msg = (f"确定要永久删除选中的 {n} 条笔记吗？此操作不可撤销！"
               if n > 1 else "确定要永久删除这条笔记吗？此操作不可撤销！")
        w = MessageBox("永久删除", msg, self.window())
        if w.exec():
            for item in items:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _show_status(self, msg: str):
        self._status_label.setText(msg)
        self._status_timer.start()

    def _pin_note_to_screen(self, note_id: str):
        from app.ui.sticky_note_window import StickyNoteWindow
        note = self._mgr.get(note_id)
        if not note:
            return

        sg = QApplication.primaryScreen().availableGeometry()
        offset = len(self._pin_windows) * 30
        x = (sg.width() - 240) // 2 + sg.x() + offset
        y = (sg.height() - 200) // 2 + sg.y() + offset

        try:
            self._mgr.pin_note(note_id, x, y)
        except Exception as e:
            print(f"Failed to pin note: {e}")
            return

        win = StickyNoteWindow(
            note_id=note.id, title=note.title, content=note.content, note_mgr=self._mgr,
        )
        win.move(x, y)
        win.show()
        self._pin_windows.append(win)
        win.closed.connect(lambda w=win: self._on_pin_window_closed(w))
        win.content_changed.connect(self.note_updated)

    def _unpin_note(self, note_id: str):
        try:
            self._mgr.unpin_note(note_id)
        except Exception as e:
            print(f"Failed to unpin note: {e}")
            return
        for win in self._pin_windows[:]:
            if hasattr(win, '_note_id') and win._note_id == note_id:
                win.close()
                break

    def _on_pin_window_closed(self, win):
        if win in self._pin_windows:
            self._pin_windows.remove(win)

    def _toggle_note_list(self):
        sizes = self._splitter.sizes()
        total = sum(sizes)
        list_width = sizes[0]

        if list_width > 0:
            self._saved_list_width = list_width
            self._splitter.setSizes([0, total])
        else:
            from app.core.config import ConfigManager
            width = self._saved_list_width or ConfigManager().window_config.get("note_list_width", 250)
            self._splitter.setSizes([width, total - width])

    def refresh(self):
        if not self._trash_mode:
            self._load()

    def refresh_note(self, note_id: int):
        if self._current_note_id == note_id:
            note = self._mgr.get(note_id)
            if note:
                self._title_edit.blockSignals(True)
                self._content_edit.blockSignals(True)
                self._title_edit.setText(note.title)
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

        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == note_id:
                note = self._mgr.get(note_id)
                if note:
                    date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
                    short = note.title[:20] + "…" if len(note.title) > 20 else note.title
                    self._list.blockSignals(True)
                    widget = self._list.itemWidget(item)
                    if isinstance(widget, _NoteItemWidget):
                        widget.update_text(short, date_str)
                        item.setSizeHint(widget.sizeHint())
                    item.setToolTip(note.title)
                    self._list.blockSignals(False)
                break
