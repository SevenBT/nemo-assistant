import re
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
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


class NotesPanel(QWidget):
    """笔记面板，嵌入主窗口 QStackedWidget 中。
    支持：多选删除、回收站、无笔记时隐藏编辑区、右键将便签贴到屏幕上。
    """

    def __init__(self, note_mgr: NoteManager, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._current_note_id: str | None = None
        self._trash_mode = False
        self._pin_windows: list = []
        self._build()
        self._load()

    # ------------------------------------------------------------------ build
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── toolbar ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # Normal-mode buttons
        self._new_btn = QPushButton("新建")
        self._new_btn.setObjectName("noteToolBtn")
        self._new_btn.clicked.connect(self._on_new)
        toolbar.addWidget(self._new_btn)

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
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Left: note list (multi-select)
        left = QWidget()
        left.setObjectName("noteListPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(0)
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
        left_layout.addWidget(self._list)
        splitter.addWidget(left)

        # Right: editor (hidden when no note selected)
        self._editor_widget = QWidget()
        right_layout = QVBoxLayout(self._editor_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("noteTitleEdit")
        self._title_edit.setPlaceholderText("笔记标题…")
        right_layout.addWidget(self._title_edit)
        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("noteContentEdit")
        self._content_edit.setPlaceholderText("在此输入笔记内容…")
        right_layout.addWidget(self._content_edit)
        self._editor_widget.hide()  # hidden until a note is selected
        splitter.addWidget(self._editor_widget)
        splitter.setSizes([200, 460])

        layout.addWidget(splitter, 1)

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
        notes = self._mgr.get_trash() if self._trash_mode else self._mgr.get_notes()
        restore_item = None
        for note in notes:
            date_str = datetime.fromtimestamp(note.updated_at).strftime("%m-%d %H:%M")
            short = note.title[:20] + "…" if len(note.title) > 20 else note.title
            item = QListWidgetItem(f"{short}\n{date_str}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(note.title)
            self._list.addItem(item)
            if not self._trash_mode and note.id == self._current_note_id:
                restore_item = item
        self._list.blockSignals(False)

        if restore_item:
            self._list.setCurrentItem(restore_item)
        else:
            self._current_note_id = None

        self._update_editor_visibility()
        self._update_toolbar()

    def _load_note_into_editor(self, note_id: str):
        note = self._mgr.get(note_id)
        if not note:
            return
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
        selected = self._list.selectedItems()
        visible = (not self._trash_mode) and len(selected) == 1
        self._editor_widget.setVisible(visible)

    # ------------------------------------------------------------------ toolbar state
    def _update_toolbar(self):
        selected_n = len(self._list.selectedItems())
        if self._trash_mode:
            self._new_btn.hide()
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
            self._new_btn.show()
            tc = self._mgr.trash_count()
            self._trash_btn.setText(f"回收站({tc})" if tc > 0 else "回收站")
            self._trash_btn.show()

    # ------------------------------------------------------------------ normal actions
    def _on_new(self):
        self._flush_current()
        note = self._mgr.create()
        self._current_note_id = note.id
        self._load()
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == note.id:
                self._list.clearSelection()
                self._list.setCurrentRow(i)
                break
        self._title_edit.blockSignals(True)
        self._title_edit.clear()
        self._title_edit.blockSignals(False)
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
        self._load()

    def _exit_trash(self):
        self._trash_mode = False
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
        title = self._title_edit.text().strip() or "无标题"
        # Get HTML content and convert absolute paths back to relative
        content = self._content_edit.toHtml()
        if str(NOTES_IMAGES_DIR) in content:
            # Convert absolute paths back to relative
            content = content.replace(str(NOTES_IMAGES_DIR) + "/", "images/")
            content = content.replace(str(NOTES_IMAGES_DIR.parent) + "/images/", "images/")
        note = self._mgr.update(self._current_note_id, title, content)
        if note:
            self._status_label.setText("已保存")
            self._status_timer.start()
            # Update list item text without re-sorting
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_note_id:
                    date_str = datetime.fromtimestamp(note.updated_at).strftime("%m-%d %H:%M")
                    short = note.title[:20] + "…" if len(note.title) > 20 else note.title
                    self._list.blockSignals(True)
                    item.setText(f"{short}\n{date_str}")
                    item.setToolTip(note.title)
                    self._list.blockSignals(False)
                    break

    def _clear_editor(self):
        self._title_edit.blockSignals(True)
        self._content_edit.blockSignals(True)
        self._title_edit.clear()
        self._content_edit.clear()
        self._title_edit.blockSignals(False)
        self._content_edit.blockSignals(False)

    def hideEvent(self, event):
        """切换视图或窗口隐藏时强制保存，防止数据丢失。"""
        self._auto_save_timer.stop()
        self._flush_current()
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
            pin_action = menu.addAction("📌 贴到屏幕")
            menu.addSeparator()
            copy_content_action = menu.addAction("📋 复制内容")
            duplicate_action = menu.addAction("📄 创建副本")
            export_action = menu.addAction("💾 导出 .txt")
            menu.addSeparator()
            delete_action = menu.addAction("🗑 删除")
        else:
            note_id = None
            pin_action = copy_content_action = duplicate_action = export_action = delete_action = None
            new_action = menu.addAction("✏ 新建便签")
            action = menu.exec(global_pos)
            if action == new_action:
                self._on_new()
            return

        action = menu.exec(global_pos)

        if action == pin_action:
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
        win = StickyNoteWindow(
            note_id=note.id,
            title=note.title,
            content=note.content,
            note_mgr=self._mgr,
        )
        win.show()
        self._pin_windows.append(win)
        win.closed.connect(
            lambda w=win: self._pin_windows.remove(w) if w in self._pin_windows else None
        )

    # ------------------------------------------------------------------ screenshot (removed)

    def refresh(self):
        """外部调用：AI 工具写入新笔记后刷新列表。"""
        if not self._trash_mode:
            self._load()
