from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    TransparentToolButton,
    ToolTipFilter,
    ToolTipPosition,
    MessageBox,
)
from app.ui.components.context_menu import ContextMenu

from app.models.session import Session


class SessionPanel(QFrame):
    """Left sidebar – session list with Fluent Design components."""

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
        self._search_keyword = ""
        self._build()

        from app.core.config import cfg
        from app.ui.components.font_delegate import FontAwareListDelegate
        self._list.setItemDelegate(FontAwareListDelegate(self._list))
        self._apply_font_size()
        cfg.navigationFontSize.valueChanged.connect(self._apply_font_size)

    def _apply_font_size(self, _value=None):
        from app.core.config import cfg
        from PyQt6.QtGui import QFont
        size = cfg.get(cfg.navigationFontSize)
        font = self._list.font()
        font.setPixelSize(size)
        self._list.setFont(font)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        # header row
        header = QHBoxLayout()
        header.setSpacing(6)
        title = CaptionLabel("会话")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch()

        new_btn = TransparentToolButton(FluentIcon.ADD)
        new_btn.setFixedSize(30, 30)
        new_btn.setToolTip("新建会话")
        new_btn.installEventFilter(
            ToolTipFilter(new_btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        new_btn.clicked.connect(self.session_create_requested)
        header.addWidget(new_btn)
        layout.addLayout(header)

        # list – Fluent ListWidget with drag-drop for reordering
        self._list = ListWidget()
        self._list.setObjectName("sessionList")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.currentItemChanged.connect(self._on_change)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------ search
    def apply_search(self, keyword: str):
        self._search_keyword = keyword
        self._reload_list()

    def _reload_list(self):
        """Reload list applying current search filter, preserving selection."""
        current_id = ""
        cur = self._list.currentItem()
        if cur:
            current_id = cur.data(Qt.ItemDataRole.UserRole)

        kw = self._search_keyword.lower()
        self._list.blockSignals(True)
        self._list.clear()
        for s in self._sessions:
            if kw and kw not in s.title.lower():
                continue
            item = self._make_item(s)
            self._list.addItem(item)
            if s.id == current_id:
                self._list.setCurrentItem(item)
        self._list.blockSignals(False)

    # ------------------------------------------------------------------ data
    def load(self, sessions: list[Session], selected_id: str = ""):
        self._sessions = sessions
        self._list.blockSignals(True)
        self._list.clear()
        kw = self._search_keyword.lower()
        for s in sessions:
            if kw and kw not in s.title.lower():
                continue
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

        menu = ContextMenu(parent=self)

        pin_icon = FluentIcon.UNPIN if pinned else FluentIcon.PIN
        pin_text = "取消置顶" if pinned else "置顶"
        menu.addAction(Action(pin_icon, pin_text,
                              triggered=lambda: self.session_pin_requested.emit(sid, not pinned)))

        menu.addAction(Action(FluentIcon.SETTING, "会话设置",
                              triggered=lambda: self.session_settings_requested.emit(sid)))
        menu.addSeparator()

        menu.addAction(Action(FluentIcon.EDIT, "重命名",
                              triggered=lambda: self._do_rename(sid, item)))

        menu.addAction(Action(FluentIcon.DELETE, "删除",
                              triggered=lambda: self.session_delete_requested.emit(sid)))

        menu.exec(self._list.mapToGlobal(pos))

    def _do_rename(self, sid: str, item: QListWidgetItem):
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, LineEdit

        class RenameBox(MessageBoxBase):
            def __init__(self, title: str, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel("重命名会话")
                self.viewLayout.addWidget(self.titleLabel)
                self.lineEdit = LineEdit()
                self.lineEdit.setText(title)
                self.lineEdit.selectAll()
                self.viewLayout.addWidget(self.lineEdit)
                self.yesButton.setText("确定")
                self.cancelButton.setText("取消")

        box = RenameBox(item.toolTip(), self.window())
        if box.exec():
            text = box.lineEdit.text().strip()
            if text:
                self.session_rename_requested.emit(sid, text)
