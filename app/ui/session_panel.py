from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView,
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
    session_settings_requested = pyqtSignal(str)
    session_pin_requested = pyqtSignal(str, bool)   # sid, pinned
    session_reorder_requested = pyqtSignal(list)    # ordered list[str] of pinned ids

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionPanel")
        self.setMinimumWidth(120)
        self._sessions: list[Session] = []
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

        # list – internal drag-drop for reordering
        self._list = QListWidget()
        self._list.setObjectName("sessionList")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentItemChanged.connect(self._on_change)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ data
    def load(self, sessions: list[Session], selected_id: str = ""):
        self._sessions = sessions
        self._list.blockSignals(True)
        self._list.clear()
        for s in sessions:
            item = self._make_item(s)
            self._list.addItem(item)
            if s.id == selected_id:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)

    def _make_item(self, s: Session) -> QListWidgetItem:
        title = self._short(s.title)
        if s.pinned:
            title = f"📌 {title}"
        item = QListWidgetItem(title)
        item.setData(Qt.ItemDataRole.UserRole, s.id)
        item.setData(Qt.ItemDataRole.UserRole + 1, s.pinned)
        item.setToolTip(s.title)
        return item

    def update_title(self, session_id: str, title: str):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                pinned = item.data(Qt.ItemDataRole.UserRole + 1)
                display = self._short(title)
                if pinned:
                    display = f"📌 {display}"
                item.setText(display)
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
        return title[:20] + "…" if len(title) > 20 else title

    def _on_change(self, current, _previous):
        if current:
            self.session_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _on_rows_moved(self, *_):
        """Emit new order of all sessions after drag-drop reorder."""
        ordered_ids = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            sid = item.data(Qt.ItemDataRole.UserRole)
            pinned = item.data(Qt.ItemDataRole.UserRole + 1)
            if pinned:
                ordered_ids.append(sid)
        if ordered_ids:
            self.session_reorder_requested.emit(ordered_ids)

    def _context_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        pinned = item.data(Qt.ItemDataRole.UserRole + 1)
        menu = QMenu(self)

        pin_act = QAction("取消置顶" if pinned else "置顶", self)
        pin_act.triggered.connect(lambda: self.session_pin_requested.emit(sid, not pinned))
        menu.addAction(pin_act)

        settings_act = QAction("会话设置", self)
        settings_act.triggered.connect(lambda: self.session_settings_requested.emit(sid))
        menu.addAction(settings_act)

        menu.addSeparator()

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
