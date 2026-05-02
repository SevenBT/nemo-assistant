from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.session import Session


class SessionPanel(QFrame):
    """Left sidebar – inherits QFrame so QSS background renders correctly."""

    session_selected = pyqtSignal(str)
    session_create_requested = pyqtSignal()
    session_delete_requested = pyqtSignal(str)
    session_rename_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionPanel")
        self.setFixedWidth(165)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # header row
        header = QHBoxLayout()
        title = QLabel("会话")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch()
        new_btn = QPushButton("＋ 新建")
        new_btn.setObjectName("newSessionBtn")
        new_btn.setFixedHeight(26)
        new_btn.setToolTip("新建会话")
        new_btn.clicked.connect(self.session_create_requested)
        header.addWidget(new_btn)
        layout.addLayout(header)

        # list
        self._list = QListWidget()
        self._list.setObjectName("sessionList")
        self._list.currentItemChanged.connect(self._on_change)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ data
    def load(self, sessions: list[Session], selected_id: str = ""):
        self._list.blockSignals(True)
        self._list.clear()
        for s in sessions:
            item = QListWidgetItem(self._short(s.title))
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            item.setToolTip(s.title)
            self._list.addItem(item)
            if s.id == selected_id:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)

    def update_title(self, session_id: str, title: str):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                item.setText(self._short(title))
                item.setToolTip(title)
                break

    def select(self, session_id: str):
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self._list.setCurrentItem(item)
                break
        self._list.blockSignals(False)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _short(title: str) -> str:
        return title[:18] + "…" if len(title) > 18 else title

    def _on_change(self, current, _previous):
        if current:
            self.session_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)

        rename_act = QAction("重命名", self)
        rename_act.triggered.connect(lambda: self._do_rename(sid, item))
        menu.addAction(rename_act)

        del_act = QAction("删除", self)
        del_act.triggered.connect(lambda: self.session_delete_requested.emit(sid))
        menu.addAction(del_act)

        menu.exec(self._list.mapToGlobal(pos))

    def _do_rename(self, sid: str, item: QListWidgetItem):
        text, ok = QInputDialog.getText(self, "重命名", "新名称:", text=item.toolTip())
        if ok and text.strip():
            self.session_rename_requested.emit(sid, text.strip())
