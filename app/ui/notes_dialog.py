import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
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
    RoundMenu,
    TextEdit,
    TogglePushButton,
    TransparentToolButton,
)

from app.core.config import NOTES_IMAGES_DIR
from app.core.note_manager import NoteManager
from app.models.note import Folder
from app.ui.components.markdown_editor import MarkdownEditor
from app.ui.components.markdown_preview import MarkdownPreview
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


def _html_to_plain(html: str) -> str:
    """Strip HTML tags to get plain text (for clipboard copy)."""
    text = re.sub(r"<[^>]+>", "", html)
    return text.strip()


class _NoteList(ListWidget):
    """Simple note list widget without drag-to-reorder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def mouseMoveEvent(self, event):
        # Suppress rubber-band selection on mouse drag to prevent
        # accidental deselection that clears the editor.
        # Multi-select is still available via Ctrl+click / Shift+click.
        pass


class _NoteItemWidget(QWidget):
    """List item widget with a colored left stripe, title, and date."""

    def __init__(self, title: str, date_str: str, color: str, indent: bool = False, parent=None):
        super().__init__(parent)
        self._color = color
        layout = QHBoxLayout(self)
        left_margin = 28 if indent else 10
        layout.setContentsMargins(left_margin, 6, 8, 6)
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

        # Let all child widgets pass mouse events through to the viewport
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def update_text(self, title: str, date_str: str):
        self._title_lbl.setText(title)
        self._date_lbl.setText(date_str)



class _FolderItem(QWidget):
    """List item widget for a folder entry with expand/collapse arrow."""

    def __init__(self, name: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 8, 5)
        layout.setSpacing(6)

        self._arrow = QLabel("▾" if expanded else "▸")
        self._arrow.setStyleSheet("font-size: 18px; color: #9CA3AF; background: transparent; min-width: 14px;")
        layout.addWidget(self._arrow, alignment=Qt.AlignmentFlag.AlignVCenter)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon_lbl.setStyleSheet("background: transparent;")
        icon_lbl.setPixmap(FluentIcon.FOLDER.icon().pixmap(16, 16))
        layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._name_lbl = QLabel(name)
        self._name_lbl.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
        self._name_lbl.setWordWrap(False)
        layout.addWidget(self._name_lbl, 1)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_expanded(self, expanded: bool):
        self._arrow.setText("▾" if expanded else "▸")

    def update_name(self, name: str):
        self._name_lbl.setText(name)


class _UncategorizedSection(QWidget):
    """Section header for uncategorized notes — acts as a drop target for moving notes out of folders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 8, 5)
        layout.setSpacing(6)

        spacer = QLabel("")
        spacer.setFixedWidth(14)
        spacer.setStyleSheet("background: transparent;")
        layout.addWidget(spacer, alignment=Qt.AlignmentFlag.AlignVCenter)

        name_lbl = QLabel("未分类")
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 500; color: #9CA3AF; background: transparent;")
        name_lbl.setWordWrap(False)
        layout.addWidget(name_lbl, 1)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class NotesPanel(QWidget):
    """笔记面板 - Fluent Design 风格。"""

    note_updated = pyqtSignal(int, str, str)

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_note_id: str | None = None
        self._trash_mode = False
        self._pin_windows: list = []
        self._current_search_keyword: str = ""
        self._current_folder_id: int | None = None  # used only for new-note placement
        self._expanded_folders: set[int] = set()
        self._saved_list_width: int | None = None
        self._preview_mode = False
        self._build()
        self._load()

    def _top_window(self):
        """获取真正的顶层窗口，避免 FluentWindow StackedWidget 内部窗口问题。"""
        w = self
        while w.parent():
            w = w.parent()
        return w

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── Toolbar (top, left-aligned) ──────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.setContentsMargins(0, 0, 0, 0)

        # Normal mode buttons — left-aligned
        self._new_note_btn = PushButton(FluentIcon.EDIT, "新建笔记")
        self._new_note_btn.clicked.connect(lambda: self._on_new("note"))
        toolbar.addWidget(self._new_note_btn)

        self._new_sticky_btn = PushButton(FluentIcon.PIN, "新建便签")
        self._new_sticky_btn.clicked.connect(lambda: self._on_new("sticky"))
        toolbar.addWidget(self._new_sticky_btn)

        self._trash_btn = PushButton(FluentIcon.DELETE, "回收站")
        self._trash_btn.clicked.connect(self._enter_trash)
        toolbar.addWidget(self._trash_btn)

        self._preview_btn = TogglePushButton(FluentIcon.VIEW, "预览")
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_btn.hide()
        toolbar.addWidget(self._preview_btn)

        self._line_num_btn = TogglePushButton(FluentIcon.ALIGNMENT, "行号")
        self._line_num_btn.setChecked(True)
        self._line_num_btn.clicked.connect(self._on_line_num_toggle)
        self._line_num_btn.hide()
        toolbar.addWidget(self._line_num_btn)

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
        list_panel_layout.setSpacing(4)

        # List header: new-folder icon button (right-aligned)
        list_header = QHBoxLayout()
        list_header.setContentsMargins(2, 0, 2, 0)
        list_header.addStretch()
        self._new_folder_btn = TransparentToolButton(FluentIcon.FOLDER_ADD)
        self._new_folder_btn.setFixedSize(24, 24)
        self._new_folder_btn.setToolTip("新建文件夹")
        self._new_folder_btn.clicked.connect(self._on_new_folder)
        list_header.addWidget(self._new_folder_btn)
        list_panel_layout.addLayout(list_header)

        self._list = _NoteList()
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemClicked.connect(self._on_item_clicked)
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

        # Apply note editor font size from config
        from app.core.config import ConfigManager
        _cfg = ConfigManager()
        _note_font_size = _cfg.note_editor_font_size
        from PyQt6.QtGui import QFont
        _editor_font = QFont()
        _editor_font.setPointSize(_note_font_size)

        # Markdown editor (for note type)
        self._md_editor = MarkdownEditor(images_dir=NOTES_IMAGES_DIR)
        self._md_editor.setPlaceholderText("在此输入 Markdown 内容…")
        self._md_editor.setFont(_editor_font)
        self._md_editor.wiki_link_activated.connect(self._on_wiki_link_clicked)
        right_layout.addWidget(self._md_editor, 1)

        # Markdown preview (QWebEngineView, replaces QTextBrowser)
        self._md_preview = MarkdownPreview()
        self._md_preview.link_clicked.connect(self._on_wiki_link_clicked)
        self._md_preview.hide()
        right_layout.addWidget(self._md_preview, 1)

        # Rich text editor (for sticky type — HTML with images)
        self._sticky_edit = TextEdit()
        self._sticky_edit.setPlaceholderText("在此输入便签内容…")
        self._sticky_edit.setFont(_editor_font)
        self._sticky_edit.hide()
        right_layout.addWidget(self._sticky_edit, 1)

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

        # Auto-save: flush on focus-out; also a 5s idle timer as safety net
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(5000)
        self._auto_save_timer.timeout.connect(self._flush_current)

        self._title_edit.textChanged.connect(lambda _: self._auto_save_timer.start())
        self._md_editor.textChanged.connect(self._auto_save_timer.start)
        self._sticky_edit.textChanged.connect(self._auto_save_timer.start)

        self._title_edit.editingFinished.connect(self._flush_current)
        self._md_editor.installEventFilter(self)
        self._sticky_edit.installEventFilter(self)
        self._sticky_edit.viewport().installEventFilter(self)

    # ------------------------------------------------------------------ preview toggle
    def _on_preview_clicked(self):
        checked = self._preview_btn.isChecked()
        self._preview_mode = checked
        if not self._current_note_id:
            return
        note = self._mgr.get(self._current_note_id)
        if not note or note.note_type not in ("note", "todo"):
            return
        if checked:
            content = self._md_editor.toPlainText()
            from app.ui.style import _current_dark_mode
            self._md_preview.set_content(content, base_path=NOTES_IMAGES_DIR.parent, dark=_current_dark_mode)
            self._md_editor.hide()
            self._md_preview.show()
        else:
            self._md_preview.hide()
            self._md_editor.show()

    def _on_line_num_toggle(self):
        self._md_editor.set_line_numbers_visible(self._line_num_btn.isChecked())

    def _on_wiki_link_clicked(self, target: str):
        """Navigate to a wiki-linked note by title match."""
        notes = self._mgr.search_notes(keyword=target, note_types=["note"])
        for note in notes:
            if note.title.lower() == target.lower():
                self._flush_current()
                self._current_note_id = note.id
                self._load()
                self._load_note_into_editor(note.id)
                return
        self._show_status(f"未找到笔记: {target}")

    # ------------------------------------------------------------------ load
    def _load(self):
        self._list.blockSignals(True)
        self._list.clear()

        if self._trash_mode:
            notes = self._mgr.get_trash()
            for note in notes:
                self._add_note_item(note, indent=False)
        elif self._current_search_keyword:
            notes = self._mgr.search_notes(keyword=self._current_search_keyword, note_types=None)
            for note in notes:
                self._add_note_item(note, indent=False)
        else:
            # Top-level: folders (with inline expansion) then uncategorized notes
            folders = self._mgr.get_folders()
            for folder in folders:
                expanded = folder.id in self._expanded_folders
                f_item = QListWidgetItem()
                f_item.setData(Qt.ItemDataRole.UserRole, folder.id)
                f_item.setData(Qt.ItemDataRole.UserRole + 1, "folder")
                f_item.setToolTip(folder.name)
                f_item.setFlags(
                    (f_item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsDragEnabled)
                    | Qt.ItemFlag.ItemIsDropEnabled
                )
                self._list.addItem(f_item)
                widget = _FolderItem(folder.name, expanded=expanded)
                f_item.setSizeHint(widget.sizeHint())
                self._list.setItemWidget(f_item, widget)

                if expanded:
                    folder_notes = self._mgr.get_notes_in_folder(folder.id)
                    for note in folder_notes:
                        self._add_note_item(note, indent=True)

            # Uncategorized notes (folder_id IS NULL)
            all_notes = self._mgr.get_notes()
            uncategorized = [n for n in all_notes if n.folder_id is None]

            # Add "未分类" section header when folders exist (provides a drop target)
            if folders:
                uc_item = QListWidgetItem()
                uc_item.setData(Qt.ItemDataRole.UserRole, None)
                uc_item.setData(Qt.ItemDataRole.UserRole + 1, "uncategorized")
                uc_item.setFlags(
                    uc_item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsDragEnabled
                )
                self._list.addItem(uc_item)
                widget = _UncategorizedSection()
                uc_item.setSizeHint(widget.sizeHint())
                self._list.setItemWidget(uc_item, widget)

            for note in uncategorized:
                self._add_note_item(note, indent=False)

        self._list.blockSignals(False)

        # Restore selection
        restore_item = None
        if self._current_note_id is not None and not self._trash_mode:
            for i in range(self._list.count()):
                it = self._list.item(i)
                if (it.data(Qt.ItemDataRole.UserRole + 1) == "note"
                        and it.data(Qt.ItemDataRole.UserRole) == self._current_note_id):
                    restore_item = it
                    break

        if restore_item:
            self._list.blockSignals(True)
            self._list.setCurrentItem(restore_item)
            self._list.blockSignals(False)
            self._load_note_into_editor(self._current_note_id)
        else:
            self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()

    def _add_note_item(self, note, indent: bool):
        """Add a note QListWidgetItem to self._list."""
        date_str = datetime.fromisoformat(note.updated_at).strftime("%m-%d %H:%M")
        short = note.title[:20] + "…" if len(note.title) > 20 else note.title
        color = _note_color(note.id)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, note.id)
        item.setData(Qt.ItemDataRole.UserRole + 1, "note")
        item.setData(Qt.ItemDataRole.UserRole + 2, note.folder_id)  # for drag-drop folder resolution
        item.setToolTip(note.title)
        self._list.addItem(item)
        widget = _NoteItemWidget(short, date_str, color, indent=indent)
        item.setSizeHint(widget.sizeHint())
        self._list.setItemWidget(item, widget)

    def _on_new_folder(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称:")
        if ok and name.strip():
            self._mgr.create_folder(name.strip())
            self._load()

    def _on_folder_selected(self, folder_id):
        """Set current folder context for new-note placement."""
        self._current_folder_id = folder_id

    def _on_folder_renamed(self, folder_id: int, name: str):
        self._mgr.rename_folder(folder_id, name)
        self._load()

    def _on_folder_deleted(self, folder_id: int):
        self._mgr.delete_folder(folder_id)
        if self._current_folder_id == folder_id:
            self._current_folder_id = None
        self._load()

    def _rename_folder_dialog(self, folder_id: int, current_name: str):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "重命名文件夹", "新名称:", text=current_name)
        if ok and name.strip():
            self._on_folder_renamed(folder_id, name.strip())

    def _delete_folder_confirm(self, folder_id: int):
        w = MessageBox("删除文件夹", "删除文件夹后，其中的笔记将移至顶层。确定继续吗？", self._top_window())
        if w.exec():
            self._on_folder_deleted(folder_id)

    def _on_tag_filter_changed(self, tag_name: str):
        pass  # tags removed

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

        if note.note_type == "sticky":
            self._md_editor.hide()
            self._md_preview.hide()
            self._sticky_edit.show()
            self._preview_btn.hide()
            self._line_num_btn.hide()

            self._sticky_edit.blockSignals(True)
            content = note.content
            if "images/" in content:
                def replace_path(m):
                    rel_path = m.group(1)
                    abs_path = NOTES_IMAGES_DIR.parent / rel_path
                    return f'<img src="{abs_path}"'
                content = re.sub(r'<img src="(images/[^"]+)"', replace_path, content)
            self._sticky_edit.setHtml(content)
            self._sticky_edit.blockSignals(False)
        elif note.note_type == "todo":
            # Legacy todo notes — show as plain text in markdown editor, read-only feel
            self._sticky_edit.hide()
            self._md_preview.hide()
            self._preview_btn.show()
            self._line_num_btn.show()
            self._md_editor.blockSignals(True)
            self._md_editor.setPlainText(note.content)
            self._md_editor.blockSignals(False)
            self._md_editor.show()
        else:
            # note type — Markdown
            self._sticky_edit.hide()
            self._preview_btn.show()
            self._line_num_btn.show()

            self._md_editor.blockSignals(True)
            self._md_editor.setPlainText(note.content)
            self._md_editor.blockSignals(False)

            if self._preview_mode:
                from app.ui.style import _current_dark_mode
                self._md_preview.set_content(note.content, base_path=NOTES_IMAGES_DIR.parent, dark=_current_dark_mode)
                self._md_editor.hide()
                self._md_preview.show()
            else:
                self._md_preview.hide()
                self._md_editor.show()

    # ------------------------------------------------------------------ item clicked (folder toggle)
    def _on_item_clicked(self, item: QListWidgetItem):
        if item.data(Qt.ItemDataRole.UserRole + 1) not in ("folder",):
            return
        folder_id = item.data(Qt.ItemDataRole.UserRole)
        if folder_id in self._expanded_folders:
            self._expanded_folders.discard(folder_id)
        else:
            self._expanded_folders.add(folder_id)
        self._load()

    # ------------------------------------------------------------------ selection
    def _on_selection_changed(self):
        selected = self._list.selectedItems()
        n = len(selected)

        if not self._trash_mode and n == 1:
            item_type = selected[0].data(Qt.ItemDataRole.UserRole + 1)
            item_id = selected[0].data(Qt.ItemDataRole.UserRole)

            if item_type in ("folder", "uncategorized"):
                return  # handled by _on_item_clicked or non-selectable
            else:
                note_id = item_id
                if note_id != self._current_note_id:
                    self._flush_current()
                    self._current_note_id = note_id
                    self._load_note_into_editor(note_id)
        else:
            self._flush_current()
            self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()

    # ------------------------------------------------------------------ editor visibility
    def _update_editor_visibility(self):
        selected = self._list.selectedItems()
        has_note_selection = (
            not self._trash_mode
            and len(selected) == 1
            and selected[0].data(Qt.ItemDataRole.UserRole + 1) == "note"
        )
        self._set_editor_enabled(has_note_selection)
        if not has_note_selection:
            self._clear_editor()

    def _set_editor_enabled(self, enabled: bool):
        self._title_edit.setEnabled(enabled)
        self._md_editor.setEnabled(enabled)
        self._sticky_edit.setEnabled(enabled)

        if not enabled:
            self._title_edit.setPlaceholderText("请从左侧列表选择笔记…")
            self._md_editor.setPlaceholderText("请从左侧列表选择笔记…")
            self._sticky_edit.setPlaceholderText("请从左侧列表选择笔记…")
        else:
            self._title_edit.setPlaceholderText("标题…")
            self._md_editor.setPlaceholderText("在此输入 Markdown 内容…")
            self._sticky_edit.setPlaceholderText("在此输入便签内容…")

    # ------------------------------------------------------------------ toolbar state
    def _update_toolbar(self):
        selected_n = len(self._list.selectedItems())
        if self._trash_mode:
            self._new_note_btn.hide()
            self._new_sticky_btn.hide()
            self._trash_btn.hide()
            self._preview_btn.hide()
            self._line_num_btn.hide()
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
            self._new_sticky_btn.show()
            tc = self._mgr.trash_count()
            self._trash_btn.setText(f"回收站({tc})" if tc > 0 else "回收站")
            self._trash_btn.show()
            # Preview button visibility is managed by _load_note_into_editor

    # ------------------------------------------------------------------ normal actions
    def _on_new(self, note_type: str = "note"):
        self._flush_current()
        if note_type == "sticky":
            note = self._mgr.create(title="新便签", content="", note_type="sticky")
        else:
            note = self._mgr.create(title="新笔记", content="", note_type="note")

        self._current_note_id = note.id
        self._load()
        self._title_edit.setFocus()

    def _on_delete(self):
        selected = self._list.selectedItems()
        if not selected:
            return
        n = len(selected)
        msg = f"确定要将选中的 {n} 条笔记移入回收站吗？" if n > 1 else "确定要将这条笔记移入回收站吗？"

        w = MessageBox("移入回收站", msg, self._top_window())
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
        self._load()

    def _exit_trash(self):
        self._trash_mode = False
        self._current_search_keyword = ""
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
        w = MessageBox("永久删除", msg, self._top_window())
        if w.exec():
            for item in selected:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _on_purge_all(self):
        tc = self._mgr.trash_count()
        if tc == 0:
            return
        w = MessageBox("清空回收站", f"确定要永久删除回收站中全部 {tc} 条笔记吗？此操作不可撤销！", self._top_window())
        if w.exec():
            self._mgr.purge_all()
            self._load()

    # ------------------------------------------------------------------ save
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.FocusOut:
            if obj is self._md_editor or obj is self._sticky_edit:
                self._auto_save_timer.stop()
                self._flush_current()
        if event.type() == QEvent.Type.FocusIn:
            if obj is self._sticky_edit or obj is self._sticky_edit.viewport():
                self._apply_sticky_text_color()
        return super().eventFilter(obj, event)

    def _apply_sticky_text_color(self):
        """Force sticky editor text color to follow theme."""
        try:
            from app.ui.style import get_text_color
            color = get_text_color()
        except Exception:
            color = "#000000"
        from PyQt6.QtGui import QColor, QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        self._sticky_edit.setCurrentCharFormat(fmt)
        self._sticky_edit.setTextColor(QColor(color))

    def _flush_current(self):
        if not self._current_note_id:
            return
        current_note = self._mgr.get(self._current_note_id)
        if not current_note:
            return

        title = self._title_edit.text().strip() or "无标题"

        if current_note.note_type == "sticky":
            content = self._sticky_edit.toHtml()
            if str(NOTES_IMAGES_DIR) in content:
                content = content.replace(str(NOTES_IMAGES_DIR) + "/", "images/")
                content = content.replace(str(NOTES_IMAGES_DIR.parent) + "/images/", "images/")
        else:
            content = self._md_editor.toPlainText()

        note = self._mgr.update(self._current_note_id, title, content)

        if note:
            self._status_label.setText("已保存")
            self._status_timer.start()
            self.note_updated.emit(self._current_note_id, title, content)
            for i in range(self._list.count()):
                item = self._list.item(i)
                if (item.data(Qt.ItemDataRole.UserRole + 1) == "note"
                        and item.data(Qt.ItemDataRole.UserRole) == self._current_note_id):
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

    def _clear_editor(self):
        self._title_edit.blockSignals(True)
        self._md_editor.blockSignals(True)
        self._sticky_edit.blockSignals(True)
        self._title_edit.clear()
        self._md_editor.clear()
        self._sticky_edit.clear()
        self._title_edit.blockSignals(False)
        self._md_editor.blockSignals(False)
        self._sticky_edit.blockSignals(False)
        self._md_preview.hide()
        self._sticky_edit.hide()
        self._md_editor.show()
        self._preview_btn.hide()

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
            item_type = item.data(Qt.ItemDataRole.UserRole + 1)
            item_id = item.data(Qt.ItemDataRole.UserRole)

            if item_type == "folder":
                folder_id = item_id
                widget = self._list.itemWidget(item)
                folder_name = widget._name_lbl.text() if widget else ""
                menu.addAction(Action(FluentIcon.EDIT, "重命名",
                                      triggered=lambda: self._rename_folder_dialog(folder_id, folder_name)))
                menu.addSeparator()
                menu.addAction(Action(FluentIcon.DELETE, "删除文件夹",
                                      triggered=lambda: self._delete_folder_confirm(folder_id)))
                menu.exec(global_pos)
                return
            elif item_type in ("uncategorized", "back"):
                return
            # Note item
            note_id = item_id
            note = self._mgr.get(note_id)

            # Only sticky notes can be pinned to screen
            if note and note.note_type == "sticky":
                if note.is_pinned:
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
            if note and note.note_type == "note":
                menu.addAction(Action(FluentIcon.DOCUMENT, "导出 .md",
                                      triggered=lambda: self._export_note_md(note_id)))
            # Move to folder submenu
            folders = self._mgr.get_folders()
            if folders:
                move_menu = RoundMenu("移入文件夹", menu)
                menu.addMenu(move_menu)
                move_menu.addAction(Action(FluentIcon.FOLDER, "无文件夹",
                                           triggered=lambda: self._move_to_folder(note_id, None)))
                for f in folders:
                    move_menu.addAction(Action(FluentIcon.FOLDER, f.name,
                                               triggered=lambda checked=False, fid=f.id: self._move_to_folder(note_id, fid)))
            menu.addSeparator()
            menu.addAction(Action(FluentIcon.DELETE, "删除",
                                  triggered=lambda: (
                                      self._on_delete() if len(self._list.selectedItems()) > 1
                                      else self._on_delete_by_id(note_id)
                                  )))
        else:
            menu.addAction(Action(FluentIcon.EDIT, "新建笔记",
                                  triggered=lambda: self._on_new("note")))
            menu.addAction(Action(FluentIcon.PIN, "新建便签",
                                  triggered=lambda: self._on_new("sticky")))

        menu.exec(global_pos)

    def _copy_note_content(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
        if note.note_type == "sticky":
            text = _html_to_plain(note.content)
        else:
            text = note.content
        QGuiApplication.clipboard().setText(text)
        self._show_status("已复制到剪贴板")

    def _duplicate_note(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
        self._flush_current()
        new_note = self._mgr.create(note_type=note.note_type)
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
        if note.note_type == "sticky":
            body = _html_to_plain(note.content)
        else:
            body = note.content
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{note.title}\n{'─' * 40}\n{body}\n")
            self._show_status("已导出")
        except OSError:
            MessageBox("导出失败", "无法写入文件，请检查路径权限。", self._top_window()).exec()

    def _export_note_md(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
        safe_name = note.title[:40].replace("/", "-").replace("\\", "-") or "笔记"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Markdown", f"{safe_name}.md", "Markdown 文件 (*.md)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {note.title}\n\n{note.content}\n")
            self._show_status("已导出")
        except OSError:
            MessageBox("导出失败", "无法写入文件，请检查路径权限。", self._top_window()).exec()

    def _on_delete_by_id(self, note_id: str):
        w = MessageBox("移入回收站", "确定要将这条笔记移入回收站吗？", self._top_window())
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
        w = MessageBox("永久删除", msg, self._top_window())
        if w.exec():
            for item in items:
                self._mgr.purge(item.data(Qt.ItemDataRole.UserRole))
            self._load()

    def _show_status(self, msg: str):
        self._status_label.setText(msg)
        self._status_timer.start()

    def _move_to_folder(self, note_id, folder_id):
        self._flush_current()
        self._mgr.move_note_to_folder(note_id, folder_id)
        if folder_id is not None:
            self._expanded_folders.add(folder_id)
        self._current_note_id = note_id
        self._load()
        self._show_status("已移动")

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

    def toggle_list(self):
        """Public: toggle note list visibility (called from TitleBar)."""
        self._toggle_note_list()

    def apply_search(self, keyword: str):
        """Public: apply search filter (called from TitleBar)."""
        self._on_search(keyword)

    def refresh(self):
        if not self._trash_mode:
            self._load()

    def refresh_note(self, note_id: int):
        if self._current_note_id == note_id:
            editor_has_focus = (
                self._title_edit.hasFocus()
                or self._md_editor.hasFocus()
                or self._sticky_edit.hasFocus()
            )
            if not editor_has_focus:
                note = self._mgr.get(note_id)
                if note:
                    self._title_edit.blockSignals(True)
                    self._title_edit.setText(note.title)
                    self._title_edit.blockSignals(False)
                    if note.note_type == "sticky":
                        self._sticky_edit.blockSignals(True)
                        content = note.content
                        if "images/" in content:
                            def replace_path(m):
                                rel_path = m.group(1)
                                abs_path = NOTES_IMAGES_DIR.parent / rel_path
                                return f'<img src="{abs_path}"'
                            content = re.sub(r'<img src="(images/[^"]+)"', replace_path, content)
                        self._sticky_edit.setHtml(content)
                        self._sticky_edit.blockSignals(False)
                    else:
                        self._md_editor.blockSignals(True)
                        self._md_editor.setPlainText(note.content)
                        self._md_editor.blockSignals(False)

        for i in range(self._list.count()):
            item = self._list.item(i)
            if (item.data(Qt.ItemDataRole.UserRole + 1) == "note"
                    and item.data(Qt.ItemDataRole.UserRole) == note_id):
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
