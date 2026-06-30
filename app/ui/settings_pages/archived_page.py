"""归档会话设置页 — 查看 / 恢复 / 彻底删除已归档（软删除）的会话。

删除会话默认归档而非物理删除：从会话列表移除但数据保留，在此页可恢复回
列表，或确认后彻底删除。恢复 / 删除后通过 on_changed 回调让主窗列表同步。

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

from app.models.session import SOURCE_READING
from app.i18n import t


class ArchivedPage(QWidget):
    """已归档会话列表，支持恢复与彻底删除。"""

    def __init__(self, session_mgr, on_changed: Callable | None = None, parent=None):
        super().__init__(parent)
        self._sessions = session_mgr
        self._on_changed = on_changed
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(t("settings.archived.title"), self))
        header.addStretch()
        layout.addLayout(header)

        hint = BodyLabel(t("settings.archived.hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._empty = BodyLabel(t("settings.archived.empty"), self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        self._list = ListWidget(self)
        layout.addWidget(self._list, 1)

    def reload(self):
        """从管理器重新拉取归档列表并重渲染。"""
        self._list.clear()
        archived = self._sessions.get_archived_sessions()
        self._empty.setVisible(not archived)
        self._list.setVisible(bool(archived))
        for s in archived:
            self._add_row(s)

    def _add_row(self, session):
        item = QListWidgetItem()
        widget = self._make_row(session)
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _make_row(self, session) -> QWidget:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        tag = t("settings.archived.tag_reading") if session.source == SOURCE_READING else t("settings.archived.tag_session")
        title = session.title or t("common.untitled")
        label = BodyLabel(t("settings.archived.row", title=title, tag=tag), row)
        label.setToolTip(title)
        layout.addWidget(label, 1)

        restore_btn = TransparentToolButton(FluentIcon.RETURN, row)
        restore_btn.setToolTip(t("settings.archived.restore_tip"))
        restore_btn.clicked.connect(lambda: self._restore(session.id))
        layout.addWidget(restore_btn)

        delete_btn = TransparentToolButton(FluentIcon.DELETE, row)
        delete_btn.setToolTip(t("common.purge"))
        delete_btn.clicked.connect(lambda: self._purge(session.id, title))
        layout.addWidget(delete_btn)

        return row

    def _restore(self, sid: str):
        self._sessions.unarchive(sid)
        self.reload()
        if self._on_changed:
            self._on_changed()

    def _purge(self, sid: str, title: str):
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle(t("common.purge"))
        confirm.setText(t("common.purge_confirm", title=title))
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        self._sessions.delete(sid)
        self.reload()
        if self._on_changed:
            self._on_changed()
