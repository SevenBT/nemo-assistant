import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QEvent, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPen, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    ListItemDelegate,
    ListWidget,
    PushButton,
    RoundMenu,
    SegmentedWidget,
    TextEdit,
    TogglePushButton,
    TransparentToolButton,
)

from app.core.config import NOTES_IMAGES_DIR, cfg
from app.core.note_manager import NoteManager
from app.models.note import Folder
from app.ui.components.markdown_editor import MarkdownEditor
from app.ui.components.markdown_preview import MarkdownPreview
from app.ui.components.context_menu import ContextMenu


# Note type tabs shown in the list header
_TAB_NOTE = "note"
_TAB_STICKY = "sticky"

# Item data roles (UserRole+N) shared by the list and its delegate.
# Rows are plain QListWidgetItems painted by NoteItemDelegate — no setItemWidget,
# so dragging only repaints the lightweight delegate (mirrors the chat session list).
_ROLE_ID = Qt.ItemDataRole.UserRole          # note id / folder id / None
_ROLE_KIND = Qt.ItemDataRole.UserRole + 1    # "note" | "folder" | "uncategorized"
_ROLE_FOLDER = Qt.ItemDataRole.UserRole + 2  # note's folder_id (drag-drop resolution)
_ROLE_TITLE = Qt.ItemDataRole.UserRole + 3   # display title / folder name
_ROLE_DATE = Qt.ItemDataRole.UserRole + 4    # formatted date (notes only)
_ROLE_COLOR = Qt.ItemDataRole.UserRole + 5   # dot color (notes only)
_ROLE_INDENT = Qt.ItemDataRole.UserRole + 6  # bool: indented inside a folder
_ROLE_EXPANDED = Qt.ItemDataRole.UserRole + 7  # bool: folder expanded


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
    """Note list with drag-to-reorder, mirroring the (smooth) session list.

    The session list (see SessionPanel) drags smoothly because it lets Qt move
    the row natively (default ``dropEvent`` → ``model().rowsMoved``) and adds no
    overrides. This list earlier overrode ``mouseMoveEvent`` / ``startDrag`` /
    ``dropEvent`` (the latter ``event.ignore()``-d and rebuilt the whole list);
    profiling showed paint was 0.4% of drag time, so the overrides were the only
    thing differing from the smooth session list — they are gone now.

    Folders are preserved: folder / "未分类" headers are non-draggable, so they
    keep their relative order during a native move. After the move the panel
    re-derives each note's folder from its row position (nearest folder header
    above it) and persists — see ``NotesPanel._on_rows_moved``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_drag_enabled(False)

    def set_drag_enabled(self, enabled: bool):
        if enabled:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)


class NoteItemDelegate(ListItemDelegate):
    """Paints note / folder / uncategorized rows without per-row widgets.

    Using a delegate instead of ``setItemWidget`` keeps drag-reorder smooth: a
    drag only repaints this lightweight delegate rather than moving and
    re-laying-out nested QWidgets for every visible row.

    Fonts, metrics, pens and theme colors are cached and only rebuilt when the
    nav font size or theme changes — ``paint``/``sizeHint`` allocate nothing, so
    repainting every visible row each frame during a drag stays cheap.
    """

    _ROW_VPAD = 8       # vertical padding per row
    _LINE_GAP = 3       # gap between title and date lines
    _DOT = 8            # color dot diameter
    _NOTE_LEFT = 10     # left margin for a top-level note
    _NOTE_INDENT = 28   # left margin for a note inside a folder
    _HEADER_LEFT = 10   # left margin for folder / section rows
    _ARROW_W = 14
    _ICON = 16
    _GAP = 6
    _MUTED = QColor("#9CA3AF")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder_pixmap = FluentIcon.FOLDER.icon().pixmap(self._ICON, self._ICON)
        self._cached_fs = -1
        self._cached_dark = None
        self._rebuild_cache()

    def _rebuild_cache(self):
        """Recompute cached fonts/metrics/pens for the current font size + theme."""
        fs = cfg.get(cfg.navigationFontSize)
        self._cached_fs = fs
        self._title_font = QFont()
        self._title_font.setPixelSize(fs)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._date_font = QFont()
        self._date_font.setPixelSize(max(fs - 3, 9))
        self._title_fm = QFontMetrics(self._title_font)
        self._date_fm = QFontMetrics(self._date_font)
        self._title_h = self._title_fm.height()
        self._date_h = self._date_fm.height()
        try:
            from app.ui.style import get_text_color, _current_dark_mode
            self._cached_dark = _current_dark_mode
            self._text_pen = QPen(QColor(get_text_color()))
        except Exception:
            self._cached_dark = False
            self._text_pen = QPen(QColor("#000000"))
        self._muted_pen = QPen(self._MUTED)
        self._sel_overlay = (QColor(255, 255, 255, 28) if self._cached_dark
                             else QColor(0, 0, 0, 18))
        self._note_row_h = self._ROW_VPAD * 2 + self._title_h + self._LINE_GAP + self._date_h
        self._header_row_h = self._ROW_VPAD * 2 + max(self._title_h, self._ICON)

    def _ensure_cache(self):
        if cfg.get(cfg.navigationFontSize) != self._cached_fs:
            self._rebuild_cache()

    def refresh_theme(self):
        """Called by the panel when the theme changes."""
        self._rebuild_cache()

    # -- sizing ------------------------------------------------------------
    def sizeHint(self, option, index):
        self._ensure_cache()
        kind = index.data(_ROLE_KIND)
        h = self._note_row_h if kind == "note" else self._header_row_h
        return QSize(option.rect.width(), h)

    # -- painting ----------------------------------------------------------
    def paint(self, painter, option, index):
        self._ensure_cache()
        kind = index.data(_ROLE_KIND)
        rect = option.rect
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)

        # Selection background (only meaningful for note rows)
        if kind == "note" and (option.state & QStyle.StateFlag.State_Selected):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._sel_overlay)
            painter.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 5, 5)

        if kind == "note":
            self._paint_note(painter, index, rect)
        elif kind == "folder":
            self._paint_folder(painter, index, rect)
        else:
            self._paint_uncategorized(painter, rect)
        painter.restore()

    def _paint_note(self, painter, index, rect):
        indent = bool(index.data(_ROLE_INDENT))
        left = self._NOTE_INDENT if indent else self._NOTE_LEFT
        color = index.data(_ROLE_COLOR) or "#60A5FA"
        title = index.data(_ROLE_TITLE) or ""
        date = index.data(_ROLE_DATE) or ""

        # Color dot, vertically centered
        dot_x = rect.left() + left
        dot_y = rect.center().y() - self._DOT // 2 + 1
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(dot_x, dot_y, self._DOT, self._DOT,
                                self._DOT / 2, self._DOT / 2)

        text_x = dot_x + self._DOT + self._GAP + 2
        text_w = max(rect.right() - text_x - 8, 0)
        top = rect.top() + self._ROW_VPAD

        # Title (elided by pixel width)
        painter.setFont(self._title_font)
        painter.setPen(self._text_pen)
        elided = self._title_fm.elidedText(title, Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(QRect(text_x, top, text_w, self._title_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

        # Date
        painter.setFont(self._date_font)
        painter.setPen(self._muted_pen)
        painter.drawText(QRect(text_x, top + self._title_h + self._LINE_GAP, text_w, self._date_h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, date)

    def _paint_folder(self, painter, index, rect):
        expanded = bool(index.data(_ROLE_EXPANDED))
        name = index.data(_ROLE_TITLE) or ""
        x = rect.left() + self._HEADER_LEFT
        cy = rect.center().y()

        # Arrow
        painter.setFont(self._date_font)
        painter.setPen(self._muted_pen)
        painter.drawText(QRect(x, rect.top(), self._ARROW_W, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "▾" if expanded else "▸")
        x += self._ARROW_W + self._GAP

        # Folder icon
        painter.drawPixmap(x, cy - self._ICON // 2, self._folder_pixmap)
        x += self._ICON + self._GAP

        # Name
        painter.setFont(self._title_font)
        painter.setPen(self._text_pen)
        w = max(rect.right() - x - 8, 0)
        elided = self._title_fm.elidedText(name, Qt.TextElideMode.ElideRight, w)
        painter.drawText(QRect(x, rect.top(), w, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

    def _paint_uncategorized(self, painter, rect):
        x = rect.left() + self._HEADER_LEFT + self._ARROW_W + self._GAP
        painter.setFont(self._title_font)
        painter.setPen(self._muted_pen)
        w = max(rect.right() - x - 8, 0)
        painter.drawText(QRect(x, rect.top(), w, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "未分类")



class NotesPanel(QWidget):
    """笔记面板 - Fluent Design 风格。"""

    note_updated = pyqtSignal(int, str, str)

    _MAX_EDITOR_WIDTH = 760  # content column max width; centered when editor is wider

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_note_id: int | None = None
        self._pin_windows: list = []
        self._current_search_keyword: str = ""
        self._current_folder_id: int | None = None  # used only for new-note placement
        self._expanded_folders: set[int] = set()
        self._saved_list_width: int | None = None
        self._preview_mode = False
        self._current_tab = _TAB_NOTE  # list filter: note | sticky
        self._build()
        self._load()

    def _confirm(self, title: str, msg: str) -> bool:
        """显示确认对话框，返回用户是否确认。"""
        reply = QMessageBox.question(self, title, msg)
        return reply == QMessageBox.StandardButton.Yes

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Status label + timer (shown in the editor header row, see below)
        self._status_label = CaptionLabel()
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._status_label.clear)

        # ── List | Editor splitter ───────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(False)

        # Left: note list
        self._list_panel = QWidget()
        self._list_panel.setObjectName("noteListPanel")
        self._list_panel.setMinimumWidth(120)
        list_panel_layout = QVBoxLayout(self._list_panel)
        list_panel_layout.setContentsMargins(6, 6, 6, 6)
        list_panel_layout.setSpacing(6)

        # Type tabs + new (+) button on one row (mirror the session panel header)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(2, 0, 2, 0)
        header_row.setSpacing(6)

        self._pivot = SegmentedWidget()
        self._pivot.addItem(_TAB_NOTE, "笔记")
        self._pivot.addItem(_TAB_STICKY, "便签")
        self._pivot.setCurrentItem(self._current_tab)
        self._pivot.currentItemChanged.connect(self._on_tab_changed)
        header_row.addWidget(self._pivot)
        header_row.addStretch()

        self._new_btn = TransparentToolButton(FluentIcon.ADD)
        self._new_btn.setFixedSize(28, 28)
        self._new_btn.setToolTip("新建")
        self._new_btn.clicked.connect(lambda: self._on_new(self._current_tab))
        header_row.addWidget(self._new_btn)
        list_panel_layout.addLayout(header_row)

        self._list = _NoteList()
        self._list.setObjectName("noteList")
        # No word-wrap: titles are single-line elided by the delegate. Word-wrap
        # forces expensive per-row layout measurement that makes dragging laggy.
        self._list.setWordWrap(False)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        # Native row move (like the session list). After Qt moves the rows we
        # re-derive each note's folder + order from the new row layout.
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.set_drag_enabled(self._current_tab == _TAB_NOTE)
        list_panel_layout.addWidget(self._list)

        self._splitter.addWidget(self._list_panel)

        # Right: editor
        self._editor_widget = QWidget()
        self._editor_widget.setObjectName("noteEditorPanel")
        self._editor_widget.setMinimumWidth(300)
        self._editor_widget.installEventFilter(self)
        right_layout = QVBoxLayout(self._editor_widget)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(6)

        # Editor header: preview toggle + status, level with the list tabs
        editor_header = QHBoxLayout()
        editor_header.setContentsMargins(0, 0, 0, 0)
        editor_header.setSpacing(6)

        self._preview_btn = TogglePushButton(FluentIcon.VIEW, "预览")
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._preview_btn.hide()
        editor_header.addWidget(self._preview_btn)

        editor_header.addStretch()
        editor_header.addWidget(self._status_label)
        right_layout.addLayout(editor_header)

        self._title_edit = LineEdit()
        self._title_edit.setPlaceholderText("标题…")
        right_layout.addWidget(self._title_edit)

        # Apply note editor font size from config
        _note_font_size = cfg.get(cfg.editorFontSize)
        from PyQt6.QtGui import QFont
        _editor_font = QFont()
        _editor_font.setPointSize(_note_font_size)

        # Markdown editor (for note type)
        self._md_editor = MarkdownEditor(images_dir=NOTES_IMAGES_DIR)
        self._md_editor.setObjectName("noteMarkdownEditor")
        self._md_editor.setPlaceholderText("在此输入 Markdown 内容…")
        self._md_editor.setFont(_editor_font)
        self._md_editor.wiki_link_activated.connect(self._on_wiki_link_clicked)
        right_layout.addWidget(self._md_editor, 1)

        # Markdown preview (QTextBrowser)
        self._md_preview = MarkdownPreview()
        self._md_preview.setObjectName("noteMarkdownPreview")
        self._md_preview.link_clicked.connect(self._on_wiki_link_clicked)
        self._md_preview.hide()
        right_layout.addWidget(self._md_preview, 1)

        # Rich text editor (for sticky type — HTML with images)
        self._sticky_edit = TextEdit()
        self._sticky_edit.setObjectName("noteStickyEdit")
        self._sticky_edit.setPlaceholderText("在此输入便签内容…")
        self._sticky_edit.setFont(_editor_font)
        # qfluentwidgets' built-in TextEditMenu fails to restore the selection
        # (its _onItemClicked builds a cursor but never setTextCursor), so
        # Cut/Copy/Paste silently no-op once the popup steals focus. Use our own
        # plain-QMenu menu (same exec-return pattern as the sticky note window).
        self._sticky_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sticky_edit.customContextMenuRequested.connect(self._show_sticky_context_menu)
        self._sticky_edit.hide()
        right_layout.addWidget(self._sticky_edit, 1)

        self._set_editor_enabled(False)
        self._splitter.addWidget(self._editor_widget)
        self._splitter.setStretchFactor(0, 0)  # note list: fixed width
        self._splitter.setStretchFactor(1, 1)  # editor: take all extra space

        # Custom delegate paints rows (no per-row widgets) for smooth dragging
        self._delegate = NoteItemDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._apply_list_font_size()
        cfg.navigationFontSize.valueChanged.connect(self._apply_list_font_size)

        # Live editor font size update
        cfg.editorFontSize.valueChanged.connect(self._apply_editor_font_size)

        # Restore splitter sizes from config
        list_width = cfg.get(cfg.noteListWidth)
        editor_width = cfg.get(cfg.windowWidth) - list_width

        if not cfg.get(cfg.noteListVisible):
            self._set_list_collapsed(True, list_width + editor_width)
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
        # Refresh the delegate's cached theme colors once per reload (cheap),
        # so a theme switch is picked up without per-paint theme lookups.
        self._delegate.refresh_theme()
        self._list.blockSignals(True)
        self._list.clear()

        if self._current_search_keyword:
            notes = self._mgr.search_notes(keyword=self._current_search_keyword, note_types=None)
            for note in notes:
                self._add_note_item(note, indent=False)
        elif self._current_tab == _TAB_STICKY:
            # 便签 tab: flat list of all stickies (no folder structure)
            stickies = [n for n in self._mgr.get_notes() if n.note_type == _TAB_STICKY]
            for note in stickies:
                self._add_note_item(note, indent=False)
        else:
            # 笔记 tab — folders (with inline expansion) then uncategorized notes
            folders = self._mgr.get_folders()
            for folder in folders:
                expanded = folder.id in self._expanded_folders
                f_item = QListWidgetItem()
                f_item.setData(_ROLE_ID, folder.id)
                f_item.setData(_ROLE_KIND, "folder")
                f_item.setData(_ROLE_TITLE, folder.name)
                f_item.setData(_ROLE_EXPANDED, expanded)
                # Folder headers are non-selectable, non-draggable and non-drop:
                # they stay put during a native row move and serve as group
                # boundaries. A note dragged below a header (into its run of
                # child rows) is re-assigned to that folder by position in
                # _on_rows_moved — so drag-into-folder works without Qt nesting.
                f_item.setFlags(
                    f_item.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsDragEnabled
                    & ~Qt.ItemFlag.ItemIsDropEnabled
                )
                self._list.addItem(f_item)

                if expanded:
                    folder_notes = [
                        n for n in self._mgr.get_notes_in_folder(folder.id)
                        if n.note_type != _TAB_STICKY
                    ]
                    for note in folder_notes:
                        self._add_note_item(note, indent=True)

            # Uncategorized notes (folder_id IS NULL), stickies excluded
            all_notes = self._mgr.get_notes()
            uncategorized = [
                n for n in all_notes
                if n.folder_id is None and n.note_type != _TAB_STICKY
            ]

            # "未分类" section header (purely a visual divider now — no longer a
            # drop target, matching folders/notes; drag only reorders).
            if folders:
                uc_item = QListWidgetItem()
                uc_item.setData(_ROLE_ID, None)
                uc_item.setData(_ROLE_KIND, "uncategorized")
                uc_item.setFlags(
                    uc_item.flags()
                    & ~Qt.ItemFlag.ItemIsSelectable
                    & ~Qt.ItemFlag.ItemIsDragEnabled
                    & ~Qt.ItemFlag.ItemIsDropEnabled
                )
                self._list.addItem(uc_item)

            for note in uncategorized:
                self._add_note_item(note, indent=False)

        self._list.blockSignals(False)

        # Restore selection
        restore_item = None
        if self._current_note_id is not None:
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
        item = QListWidgetItem()
        item.setData(_ROLE_ID, note.id)
        item.setData(_ROLE_KIND, "note")
        item.setData(_ROLE_FOLDER, note.folder_id)  # for drag-drop folder resolution
        item.setData(_ROLE_TITLE, note.title)
        item.setData(_ROLE_DATE, date_str)
        item.setData(_ROLE_COLOR, _note_color(note.id))
        item.setData(_ROLE_INDENT, indent)
        item.setToolTip(note.title)
        # Notes are draggable (default ItemIsDragEnabled) but NOT drop targets:
        # clearing ItemIsDropEnabled stops Qt from treating "drop ONTO this note"
        # as nesting — between-row insertion (the reorder we want) still works via
        # the list's root item. Folder membership is re-derived from the row's
        # position after the move (see _on_rows_moved).
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        self._list.addItem(item)

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
        if self._confirm("删除文件夹", "删除文件夹后，其中的笔记将移至顶层。确定继续吗？"):
            self._on_folder_deleted(folder_id)

    def _on_tag_filter_changed(self, tag_name: str):
        pass  # tags removed

    def _on_search(self, keyword: str):
        self._current_search_keyword = keyword
        self._update_drag_enabled()
        self._load()

    def _on_tab_changed(self, key: str):
        """Switch the list between 笔记 / 便签 views."""
        if key == self._current_tab:
            return
        self._current_tab = key
        self._update_drag_enabled()
        self._load()

    def _update_drag_enabled(self):
        """Drag-reorder/move only makes sense on the 笔记 tab, outside search."""
        enabled = self._current_tab == _TAB_NOTE and not self._current_search_keyword
        self._list.set_drag_enabled(enabled)

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
            self._md_editor.blockSignals(True)
            self._md_editor.setPlainText(note.content)
            self._md_editor.blockSignals(False)
            self._md_editor.show()
        else:
            # note type — Markdown
            self._sticky_edit.hide()
            self._preview_btn.show()

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

        if n == 1:
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
            len(selected) == 1
            and selected[0].data(Qt.ItemDataRole.UserRole + 1) == "note"
        )
        self._set_editor_enabled(has_note_selection)
        if not has_note_selection:
            self._clear_editor()

    def _apply_list_font_size(self, _value=None):
        self._load()

    def _apply_editor_font_size(self, _value=None):
        from PyQt6.QtGui import QFont
        size = cfg.get(cfg.editorFontSize)
        font = QFont()
        font.setPointSize(size)
        self._md_editor.setFont(font)
        self._sticky_edit.setFont(font)

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
        # Preview button visibility is managed by _load_note_into_editor
        pass

    # ------------------------------------------------------------------ normal actions
    def _on_new(self, note_type: str = "note"):
        self._flush_current()
        if note_type == "sticky":
            note = self._mgr.create(title="新便签", content="", note_type="sticky")
            target_tab = _TAB_STICKY
        else:
            note = self._mgr.create(title="新笔记", content="", note_type="note")
            target_tab = _TAB_NOTE

        # Keep the list on the tab matching the new item so it stays visible
        if self._current_tab != target_tab:
            self._current_tab = target_tab
            self._pivot.setCurrentItem(target_tab)

        self._current_note_id = note.id
        self._load()
        self._title_edit.setFocus()

    def _on_delete(self):
        selected = self._list.selectedItems()
        if not selected:
            return
        n = len(selected)
        msg = f"确定要将选中的 {n} 条笔记移入回收站吗？" if n > 1 else "确定要将这条笔记移入回收站吗？"

        if not self._confirm("移入回收站", msg):
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

    def _update_editor_margins(self, width: int):
        """Keep editor content centered with equal side margins when wider than max width."""
        side = max(16, (width - self._MAX_EDITOR_WIDTH) // 2)
        self._editor_widget.layout().setContentsMargins(side, 12, side, 12)

    # ------------------------------------------------------------------ save
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._editor_widget and event.type() == QEvent.Type.Resize:
            self._update_editor_margins(event.size().width())
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
            self._update_note_item_text(self._current_note_id, note.title, note.updated_at)

    def _update_note_item_text(self, note_id, title: str, updated_at: str):
        """Refresh a note row's title/date in place (delegate repaints from data)."""
        date_str = datetime.fromisoformat(updated_at).strftime("%m-%d %H:%M")
        for i in range(self._list.count()):
            item = self._list.item(i)
            if (item.data(_ROLE_KIND) == "note"
                    and item.data(_ROLE_ID) == note_id):
                item.setData(_ROLE_TITLE, title)
                item.setData(_ROLE_DATE, date_str)
                item.setToolTip(title)
                self._list.update(self._list.indexFromItem(item))
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
        sizes = self._splitter.sizes()
        list_width = sizes[0] if sizes[0] > 0 else (self._saved_list_width or 250)
        list_visible = sizes[0] > 0
        cfg.set(cfg.noteListWidth, max(list_width, 120))
        cfg.set(cfg.noteListVisible, list_visible)
        super().hideEvent(event)

    # ------------------------------------------------------------------ context menu
    def _on_list_context_menu(self, pos):
        item = self._list.itemAt(pos)
        global_pos = self._list.viewport().mapToGlobal(pos)

        menu = ContextMenu(parent=self)

        if item:
            item_type = item.data(Qt.ItemDataRole.UserRole + 1)
            item_id = item.data(Qt.ItemDataRole.UserRole)

            if item_type == "folder":
                folder_id = item_id
                folder_name = item.data(_ROLE_TITLE) or ""
                menu.addAction(Action(FluentIcon.FOLDER_ADD, "新建文件夹",
                                      triggered=self._on_new_folder))
                menu.addSeparator()
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
            # New folder only applies to the 笔记 view (stickies have no folders)
            if self._current_tab == _TAB_NOTE:
                menu.addSeparator()
                menu.addAction(Action(FluentIcon.FOLDER_ADD, "新建文件夹",
                                      triggered=self._on_new_folder))

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
            QMessageBox.warning(self, "导出失败", "无法写入文件，请检查路径权限。")

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
            QMessageBox.warning(self, "导出失败", "无法写入文件，请检查路径权限。")

    def _on_delete_by_id(self, note_id: str):
        if not self._confirm("移入回收站", "确定要将这条笔记移入回收站吗？"):
            return
        self._auto_save_timer.stop()
        if note_id == self._current_note_id:
            self._current_note_id = None
            self._clear_editor()
        self._mgr.delete(note_id)
        self._load()

    def _show_status(self, msg: str):
        self._status_label.setText(msg)
        self._status_timer.start()

    def _show_sticky_context_menu(self, pos):
        """Reliable Cut/Copy/Paste/SelectAll menu for the sticky editor.

        Mirrors the sticky-note window's menu: build a plain QMenu, exec it, and
        act on the returned QAction. This avoids qfluentwidgets' TextEditMenu,
        whose selection-restore is a no-op so Cut/Copy/Paste silently fail.
        """
        edit = self._sticky_edit
        menu = QMenu(self)
        # Match the markdown editor's themed menu so it has clear contrast
        # (a bare QMenu inherits low-contrast defaults under FluentWindow).
        try:
            from app.ui.style import get_text_color, _current_dark_mode
            text_color = get_text_color()
            bg_color = "#2D2D2D" if _current_dark_mode else "#FFFFFF"
            hover_bg = "#3D3D3D" if _current_dark_mode else "#F3F4F6"
        except Exception:
            text_color, bg_color, hover_bg = "#000000", "#FFFFFF", "#F3F4F6"
        menu.setStyleSheet(
            f"QMenu {{ color: {text_color}; background: {bg_color}; border: 1px solid rgba(128,128,128,0.3); }}"
            f"QMenu::item:selected {{ background: {hover_bg}; }}"
        )

        undo_act = menu.addAction("撤销")
        undo_act.setEnabled(edit.document().isUndoAvailable())
        redo_act = menu.addAction("重做")
        redo_act.setEnabled(edit.document().isRedoAvailable())
        menu.addSeparator()

        has_selection = edit.textCursor().hasSelection()
        cut_act = menu.addAction("剪切")
        cut_act.setEnabled(has_selection)
        copy_act = menu.addAction("复制")
        copy_act.setEnabled(has_selection)
        paste_act = menu.addAction("粘贴")
        paste_act.setEnabled(edit.canPaste())
        menu.addSeparator()
        select_all_act = menu.addAction("全选")
        select_all_act.setEnabled(not edit.document().isEmpty())

        action = menu.exec(edit.mapToGlobal(pos))
        if action == undo_act:
            edit.undo()
        elif action == redo_act:
            edit.redo()
        elif action == cut_act:
            edit.cut()
        elif action == copy_act:
            edit.copy()
        elif action == paste_act:
            edit.paste()
        elif action == select_all_act:
            edit.selectAll()

    def _move_to_folder(self, note_id, folder_id):
        self._flush_current()
        self._mgr.move_note_to_folder(note_id, folder_id)
        if folder_id is not None:
            self._expanded_folders.add(folder_id)
        self._current_note_id = note_id
        self._load()
        self._show_status("已移动")

    # ------------------------------------------------------------------ drag & drop
    def _on_rows_moved(self, *_):
        """Persist order/folders after Qt natively moved rows.

        Walk the list top-to-bottom. Folder / "未分类" headers are non-draggable
        so they keep their positions and act as group boundaries: every note row
        belongs to the nearest header above it (a folder header → that folder; an
        "未分类" header or the top of the list → top level). We rebuild each
        group's ordered note ids and persist via ``reorder_notes`` (which also
        rewrites folder_id, so notes dragged across a boundary move folders).
        """
        groups: dict[int | None, list[int]] = {}
        current_folder: int | None = None
        touched_folders: set[int | None] = set()

        for i in range(self._list.count()):
            it = self._list.item(i)
            kind = it.data(_ROLE_KIND)
            if kind == "folder":
                current_folder = it.data(_ROLE_ID)
                touched_folders.add(current_folder)
            elif kind == "uncategorized":
                current_folder = None
            elif kind == "note":
                groups.setdefault(current_folder, []).append(it.data(_ROLE_ID))

        for folder_id, ordered in groups.items():
            self._mgr.reorder_notes(ordered, folder_id)
        # A collapsed folder shows no child rows, so it won't appear in `groups`;
        # leave its stored order untouched (notes never left it during this move).

        for folder_id in touched_folders:
            if folder_id is not None:
                self._expanded_folders.add(folder_id)

        # Reload off the event loop: rebuilding the list inside the model's
        # rowsMoved emission re-enters the model mid-drop. Defer one tick.
        QTimer.singleShot(0, self._reload_after_move)

    def _reload_after_move(self):
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

    def _set_list_collapsed(self, collapsed: bool, total: int | None = None):
        """Collapse/expand the list panel reliably.

        ``setChildrenCollapsible(False)`` + the panel's ``minimumWidth`` keep the
        user from accidentally dragging the splitter to 0, but they also clamp a
        programmatic ``setSizes([0, …])`` back up to the minimum. So we drop the
        constraints only for the duration of a programmatic collapse, then restore
        them once the panel is visible again.
        """
        if total is None:
            total = sum(self._splitter.sizes()) or cfg.get(cfg.windowWidth)
        if collapsed:
            self._list_panel.setMinimumWidth(0)
            self._splitter.setChildrenCollapsible(True)
            self._splitter.setSizes([0, total])
        else:
            self._list_panel.setMinimumWidth(120)
            self._splitter.setChildrenCollapsible(False)
            width = self._saved_list_width or cfg.get(cfg.noteListWidth)
            self._splitter.setSizes([width, total - width])

    def _toggle_note_list(self):
        sizes = self._splitter.sizes()
        total = sum(sizes)
        if sizes[0] > 0:
            self._saved_list_width = sizes[0]
            self._set_list_collapsed(True, total)
        else:
            self._set_list_collapsed(False, total)

    def toggle_list(self):
        """Public: toggle note list visibility (called from TitleBar)."""
        self._toggle_note_list()

    def apply_search(self, keyword: str):
        """Public: apply search filter (called from TitleBar)."""
        self._on_search(keyword)

    def refresh(self):
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
                        # 仅当内容确有变化时才重置编辑器，且保留光标/滚动位置。
                        # setPlainText 会把光标弹回开头（pos 0）——若无脑调用，
                        # 划词翻译回填等链路触发的 refresh 会让正在编辑的光标乱跳。
                        # 外部应用（如 Codex）不是本进程 Qt 控件，不经此路径，故只在
                        # 我们自己的笔记编辑器里复现。
                        if self._md_editor.toPlainText() != note.content:
                            cursor = self._md_editor.textCursor()
                            saved_pos = cursor.position()
                            saved_anchor = cursor.anchor()
                            scrollbar = self._md_editor.verticalScrollBar()
                            saved_scroll = scrollbar.value()
                            self._md_editor.blockSignals(True)
                            self._md_editor.setPlainText(note.content)
                            # 还原光标（夹到新文本长度内）与滚动位置。
                            new_cursor = self._md_editor.textCursor()
                            doc_len = len(self._md_editor.toPlainText())
                            new_cursor.setPosition(min(saved_anchor, doc_len))
                            new_cursor.setPosition(
                                min(saved_pos, doc_len),
                                QTextCursor.MoveMode.KeepAnchor,
                            )
                            self._md_editor.setTextCursor(new_cursor)
                            scrollbar.setValue(saved_scroll)
                            self._md_editor.blockSignals(False)

        note = self._mgr.get(note_id)
        if note:
            self._update_note_item_text(note_id, note.title, note.updated_at)
