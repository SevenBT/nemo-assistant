"""笔记回收站设置页 — 查看 / 恢复 / 彻底删除已软删除的笔记与便签。

笔记/便签删除默认移入回收站（is_deleted=1）而非物理删除：从笔记列表移除但数据
保留，在此页可恢复回列表，或确认后彻底删除。恢复 / 删除后通过 on_changed 回调让
笔记面板列表同步。

确认对话框用标准 QMessageBox（不用 qfluentwidgets 的 MessageBox）：本页嵌在
SettingsWindow 的 QStackedWidget 中，MaskDialogBase 要求 parent 为顶层窗口，
嵌入式面板里连续弹出会卡死（见 CLAUDE.md 经验）。
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ListWidget,
    PushButton,
    StrongBodyLabel,
    TransparentToolButton,
    FluentIcon,
)

from app.core.note_manager import NoteManager


class TrashPage(QWidget):
    """笔记回收站列表，支持恢复、彻底删除与清空。"""

    def __init__(self, note_mgr: NoteManager, on_changed: Callable | None = None, parent=None):
        super().__init__(parent)
        self._mgr = note_mgr
        self._on_changed = on_changed
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("回收站", self))
        header.addStretch()
        self._purge_all_btn = PushButton(FluentIcon.BROOM, "清空回收站", self)
        self._purge_all_btn.clicked.connect(self._purge_all)
        header.addWidget(self._purge_all_btn)
        layout.addLayout(header)

        hint = BodyLabel("删除的笔记和便签会移到这里。可恢复回笔记列表，或彻底删除。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._empty = BodyLabel("回收站是空的。", self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        self._list = ListWidget(self)
        layout.addWidget(self._list, 1)

    def reload(self):
        """从管理器重新拉取回收站列表并重渲染。"""
        self._list.clear()
        trash = self._mgr.get_trash()
        self._empty.setVisible(not trash)
        self._list.setVisible(bool(trash))
        self._purge_all_btn.setEnabled(bool(trash))
        for note in trash:
            self._add_row(note)

    def _add_row(self, note):
        item = QListWidgetItem()
        widget = self._make_row(note)
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _make_row(self, note) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        tag = "便签" if note.note_type == "sticky" else "笔记"
        title = note.title or "（无标题）"
        label = BodyLabel(f"{title}  ·  {tag}", row)
        label.setToolTip(title)
        layout.addWidget(label, 1)

        restore_btn = TransparentToolButton(FluentIcon.RETURN, row)
        restore_btn.setToolTip("恢复到笔记列表")
        restore_btn.clicked.connect(lambda: self._restore(note.id))
        layout.addWidget(restore_btn)

        delete_btn = TransparentToolButton(FluentIcon.DELETE, row)
        delete_btn.setToolTip("彻底删除")
        delete_btn.clicked.connect(lambda: self._purge(note.id, title))
        layout.addWidget(delete_btn)

        return row

    def _restore(self, note_id):
        self._mgr.restore(note_id)
        self.reload()
        if self._on_changed:
            self._on_changed()

    def _purge(self, note_id, title: str):
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("彻底删除")
        confirm.setText(f"确定彻底删除「{title}」？\n此操作不可恢复。")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        self._mgr.purge(note_id)
        self.reload()
        if self._on_changed:
            self._on_changed()

    def _purge_all(self):
        tc = self._mgr.trash_count()
        if tc == 0:
            return
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("清空回收站")
        confirm.setText(f"确定彻底删除回收站中全部 {tc} 条吗？\n此操作不可恢复。")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        self._mgr.purge_all()
        self.reload()
        if self._on_changed:
            self._on_changed()
