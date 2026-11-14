"""
Sticky note window — displays a note as a floating, always-on-top editable widget.

Features:
- Frameless, always-on-top, translucent background
- Draggable via title bar (startSystemMove)
- Resizable from all edges/corners (QApplication event filter)
- Editable title and content in-place
- Auto-saves changes back to NoteManager on close / focus-out
- Right-click context menu: close / pin-on-top toggle
- Double-click title bar to rename

Follows the frameless window conventions from CLAUDE.md.
"""

import logging

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui import style
from app.i18n import t
from app.ui.components.sticky_editor import StickyEditor
from app.ui.sticky_note_features import StickyNoteFeatures
from app.storage.sticky_store import DEFAULT_STICKY_SETTINGS

logger = logging.getLogger(__name__)

_RESIZE_BORDER = 6
_MIN_W = 180
_MIN_H = 120
_TITLE_H = 40

# Per-note tints cycle on creation. Two palettes — soft pastels for light
# themes, desaturated deep tints for dark themes — so the sticky-note variety
# survives while staying legible under either mode.
_NOTE_COLORS_LIGHT = [
    "#FFFDE7",  # warm yellow
    "#E8F5E9",  # mint green
    "#E3F2FD",  # sky blue
    "#FCE4EC",  # rose pink
    "#F3E5F5",  # lavender
    "#FFF3E0",  # peach
]
_NOTE_COLORS_DARK = [
    "#3A3526",  # warm yellow
    "#26352A",  # mint green
    "#243240",  # sky blue
    "#3A2730",  # rose pink
    "#322A3C",  # lavender
    "#3A3026",  # peach
]
_color_index = 0


def _note_palette() -> list[str]:
    """根据当前主题深浅返回对应的便签纸色板。"""
    dark = style._current_dark_mode
    return _NOTE_COLORS_DARK if dark else _NOTE_COLORS_LIGHT


def _next_color() -> str:
    global _color_index
    palette = _note_palette()
    c = palette[_color_index % len(palette)]
    _color_index += 1
    return c


def _ink_colors(bg_hex: str) -> tuple[str, str, str]:
    """按纸张明度返回 (主文字, 次要/标题, 淡色) 三档前景色（rgba 字符串）。

    深色纸用浅墨、浅色纸用深墨，保证任意主题下文字都清晰。
    """
    lightness = QColor(bg_hex).lightness()
    if lightness < 128:
        return (
            "rgba(255,255,255,0.88)",
            "rgba(255,255,255,0.65)",
            "rgba(255,255,255,0.45)",
        )
    return (
        "rgba(0,0,0,0.75)",
        "rgba(0,0,0,0.55)",
        "rgba(0,0,0,0.45)",
    )


class _TitleBar(QWidget):
    """Drag handle + close button for the sticky note."""

    close_requested = pyqtSignal()
    double_clicked = pyqtSignal()
    hide_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    toggle_top_requested = pyqtSignal()

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedHeight(_TITLE_H)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        _, ink_secondary, _ = _ink_colors(color)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(4)

        self._label = QLabel(t("sticky.label"))
        self._label.setStyleSheet(
            f"color: {ink_secondary}; font-size: 11px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._label.setMinimumWidth(0)
        layout.addWidget(self._label)

        for text, key, callback in (
            ("+", "sticky.new", lambda: self.window().new_requested.emit("empty")),
            ("…", "sticky.more", lambda: self.window().show_note_menu(self.mapToGlobal(self.rect().bottomRight()))),
        ):
            button = QPushButton(text)
            button.setFixedSize(32, 28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(t(key))
            button.clicked.connect(callback)
            layout.addWidget(button)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(32, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip(t("sticky.menu.hide"))
        close_btn.clicked.connect(self.hide_requested)
        layout.addWidget(close_btn)
        self.refresh_colors(color)

    def refresh_colors(self, color):
        self._color = color
        ink, secondary, _ = _ink_colors(color)
        dark = QColor(color).lightness() < 128
        hover = "rgba(255,255,255,0.14)" if dark else "rgba(0,0,0,0.09)"
        pressed = "rgba(255,255,255,0.23)" if dark else "rgba(0,0,0,0.16)"
        self._label.setStyleSheet(f"color:{secondary};background:transparent;border:none;font-size:11px;font-weight:600")
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(
                f"QPushButton{{color:{ink};background:transparent;border:none;border-radius:5px;padding:0;font-size:20px}}"
                f"QPushButton:hover{{background:{hover}}}QPushButton:pressed{{background:{pressed}}}"
            )
        self.update()

    def set_title(self, title: str):
        short = title[:18] + "…" if len(title) > 18 else title
        self._label.setText(short or t("sticky.label"))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        # Rounded top corners only
        path = QPainterPath()
        radius = 10.0
        path.moveTo(r.left(), r.bottom())
        path.lineTo(r.left(), r.top() + radius)
        path.quadTo(r.left(), r.top(), r.left() + radius, r.top())
        path.lineTo(r.right() - radius, r.top())
        path.quadTo(r.right(), r.top(), r.right(), r.top() + radius)
        path.lineTo(r.right(), r.bottom())
        path.closeSubpath()
        # Darken the title bar slightly
        base = QColor(self._color)
        base = base.darker(108)
        p.fillPath(path, base)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._show_title_menu(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_started = False
            self._press_pos = event.globalPosition().toPoint()

    def _show_title_menu(self, global_pos: QPoint):
        self.window().show_note_menu(global_pos)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if not getattr(self, "_drag_started", False):
                delta = (
                    event.globalPosition().toPoint() - self._press_pos
                ).manhattanLength()
                if delta > 4:
                    self.window()._edge_restore()
                    self._drag_started = True
                    self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()


class StickyNoteWindow(StickyNoteFeatures, QWidget):
    """A frameless, always-on-top sticky note window with editable content."""

    closed = pyqtSignal()
    # Signal emitted when content changes (note_id, title, content)
    content_changed = pyqtSignal(int, str, str)
    # Signal emitted when user requests deletion from title bar menu
    delete_requested = pyqtSignal(int)
    new_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(int)
    manager_requested = pyqtSignal()
    reminder_requested = pyqtSignal(int)
    settings_changed = pyqtSignal(int)

    def __init__(self, note_id: int, title: str, content: str,
                 note_mgr=None, parent=None):
        super().__init__(parent)
        self._note_id = note_id
        self._note_mgr = note_mgr
        self._settings = (note_mgr.get_sticky_settings(note_id) if note_mgr else dict(DEFAULT_STICKY_SETTINGS))
        self._title = title
        self._dirty = False
        self._last_content = content
        self._edge_geometry = None
        self._edge_side = None
        self._edge_mutating = False
        self._menu_open = False
        self._applying_settings = False
        self._color = _next_color()

        # Resize state
        self._resize_active = False
        self._resize_edges = Qt.Edge(0)
        self._resize_start_geo = QRect()
        self._resize_start_pos = QPoint()
        self._resize_cursor_shape = None

        self._build_window()
        self._build_ui(title, content)
        self._install_resize_filter()

        # Auto-save timer (1.5 s debounce)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1500)
        self._save_timer.timeout.connect(self._flush)
        self._content_edit.textChanged.connect(self._save_timer.start)
        self._content_edit.textChanged.connect(self._mark_dirty)

        # Position save timer (500ms debounce for move events)
        self._pos_timer = QTimer(self)
        self._pos_timer.setSingleShot(True)
        self._pos_timer.setInterval(500)
        self._pos_timer.timeout.connect(self._save_position)
        self._edge_timer = QTimer(self)
        self._edge_timer.setSingleShot(True)
        self._edge_timer.setInterval(700)
        self._edge_timer.timeout.connect(self._edge_hide)
        self._apply_settings()
        self._content_edit.document().setModified(False)
        self._saved_editor_content = self._content_edit.toHtml()

    # ── Window setup ───────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(self._settings["width"], self._settings["height"])
        self.setMinimumSize(_MIN_W, _MIN_H)

        # Center on screen
        sg = QApplication.primaryScreen().availableGeometry()
        self.move(
            (sg.width() - self.width()) // 2 + sg.x(),
            (sg.height() - self.height()) // 2 + sg.y(),
        )

    def _build_ui(self, title: str, content: str):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Inner container (draws the rounded background)
        self._container = _NoteContainer(self._color, self)
        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Title bar
        self._title_bar = _TitleBar(self._color, self._container)
        self._title_bar.set_title(title)
        self._title_bar.close_requested.connect(self.hide_note)
        self._title_bar.double_clicked.connect(self.rename_note)
        self._title_bar.hide_requested.connect(self.hide_note)
        self._title_bar.toggle_top_requested.connect(self._toggle_always_on_top)
        self._title_bar.delete_requested.connect(self._on_delete_requested)
        container_layout.addWidget(self._title_bar)

        # Content editor
        self._content_edit = StickyEditor(self._container)
        self._content_edit.setFrameShape(QTextEdit.Shape.NoFrame)
        ink = _ink_colors(self._color)[0]
        self._content_edit.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {ink};"
            f"border: none; padding: 8px 10px; font-size: 13px; line-height: 1.5; }}"
        )
        self._content_edit.setPlaceholderText(t("sticky.placeholder"))
        # Sticky notes store HTML (supports text + images)
        self._content_edit.load_content(content)
        # Enable context menu
        self._content_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._content_edit.customContextMenuRequested.connect(self._show_context_menu)
        container_layout.addWidget(self._content_edit, 1)
        self._reminder_label = QPushButton(self._container)
        self._reminder_label.setFlat(True)
        self._reminder_label.clicked.connect(lambda: self.reminder_requested.emit(self._note_id))
        self._reminder_label.hide()
        container_layout.addWidget(self._reminder_label)

        outer.addWidget(self._container)

    # ── Save ───────────────────────────────────────────────────────────

    def _mark_dirty(self):
        self._dirty = True

    def _flush(self):
        self._save_timer.stop()
        if not self._note_mgr or not self._note_id:
            return
        if not self._dirty:
            return True
        note = self._note_mgr.get(self._note_id)
        if note:
            # Stickies use rich text; regular notes keep their Markdown source
            # as plain text, just like the app's Markdown editor.
            content = (
                self._content_edit.toHtml()
                if note.note_type == "sticky"
                else self._content_edit.toPlainText()
            )
            if content == note.content or self._content_edit.toHtml() == self._saved_editor_content:
                self._dirty = False
                self._content_edit.document().setModified(False)
                return True
            try:
                self._note_mgr.update(self._note_id, note.title, content,
                                      priority=note.priority, due_date=note.due_date, recurrence=note.recurrence)
            except Exception:
                logger.exception("Could not save sticky %s", self._note_id)
                self._title_bar._label.setText(t("sticky.saveFailed"))
                return False
            self._last_content = content
            self._saved_editor_content = self._content_edit.toHtml()
            self._dirty = False
            self._content_edit.document().setModified(False)
            self._title = note.title
            self._title_bar.set_title(note.title)
            self.content_changed.emit(self._note_id, note.title, content)
        return True

    def _save_position(self):
        """保存浮窗位置到数据库。"""
        if not self._note_mgr or not self._note_id:
            return
        try:
            geo = self._edge_geometry or self.geometry()
            pos = geo.topLeft()
            self._note_mgr.update_pin_position(self._note_id, pos.x(), pos.y())
            changes = {"width": geo.width(), "visible": self.isVisible()}
            if not self._settings["collapsed"]:
                changes["height"] = geo.height()
            self._settings = self._note_mgr.set_sticky_settings(self._note_id, **changes)
        except Exception:
            logger.exception("Failed to save sticky note position for note %s", self._note_id)

    def update_content(self, title: str, content: str):
        """外部调用：更新浮窗内容（用于同步笔记面板的编辑）。"""
        if self._dirty:
            return
        if content != self._last_content:
            cursor = self._content_edit.textCursor().position()
            scroll = self._content_edit.verticalScrollBar().value()
            self._content_edit.blockSignals(True)
            self._content_edit.load_content(content)
            caret = self._content_edit.textCursor()
            caret.setPosition(min(cursor, self._content_edit.document().characterCount() - 1))
            self._content_edit.setTextCursor(caret)
            self._content_edit.verticalScrollBar().setValue(scroll)
            self._content_edit.document().setModified(False)
            self._content_edit.blockSignals(False)
            self._last_content = content
            self._saved_editor_content = self._content_edit.toHtml()
        self._title = title
        self._title_bar.set_title(title)

    def _toggle_always_on_top(self):
        """切换窗口置顶状态。"""
        flags = self.windowFlags()
        if flags & Qt.WindowType.WindowStaysOnTopHint:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        self.show()  # setWindowFlags hides the window, must re-show
        self._set_pref("top", bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))

    def _on_delete_requested(self):
        """用户从标题栏菜单请求删除便签。"""
        if self._flush() is False:
            return
        if self._note_mgr and self._note_id:
            self._note_mgr.delete(self._note_id)
        self.delete_requested.emit(self._note_id)
        self.dispose()

    # ── Resize (QApplication event filter) ─────────────────────────────

    def _resize_edges_at(self, win_pos: QPoint):
        x, y, w, h = win_pos.x(), win_pos.y(), self.width(), self.height()
        B = _RESIZE_BORDER
        on_l = x < B
        on_r = x > w - B
        on_t = y < B
        on_b = y > h - B
        if not (on_l or on_r or on_t or on_b):
            return None
        edges = Qt.Edge(0)
        if on_l:
            edges |= Qt.Edge.LeftEdge
        if on_r:
            edges |= Qt.Edge.RightEdge
        if on_t:
            edges |= Qt.Edge.TopEdge
        if on_b:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for_edges(edges):
        L, R, T, B = (
            Qt.Edge.LeftEdge, Qt.Edge.RightEdge,
            Qt.Edge.TopEdge, Qt.Edge.BottomEdge,
        )
        has = lambda e: bool(edges & e)
        if (has(T) and has(L)) or (has(B) and has(R)):
            return Qt.CursorShape.SizeFDiagCursor
        if (has(T) and has(R)) or (has(B) and has(L)):
            return Qt.CursorShape.SizeBDiagCursor
        if has(L) or has(R):
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _apply_resize_cursor(self, edges):
        shape = self._cursor_for_edges(edges)
        if self._resize_cursor_shape is None:
            QApplication.setOverrideCursor(shape)
        elif shape != self._resize_cursor_shape:
            QApplication.changeOverrideCursor(shape)
        else:
            return
        self._resize_cursor_shape = shape

    def _clear_resize_cursor(self):
        if self._resize_cursor_shape is not None:
            QApplication.restoreOverrideCursor()
            self._resize_cursor_shape = None

    def _do_manual_resize(self, global_pos: QPoint):
        geo = self._resize_start_geo
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        e = self._resize_edges
        nx, ny, nw, nh = x, y, w, h
        if bool(e & Qt.Edge.RightEdge):
            nw = max(_MIN_W, w + dx)
        if bool(e & Qt.Edge.BottomEdge):
            nh = max(_MIN_H, h + dy)
        if bool(e & Qt.Edge.LeftEdge):
            nw = max(_MIN_W, w - dx)
            nx = x + w - nw
        if bool(e & Qt.Edge.TopEdge):
            nh = max(_MIN_H, h - dy)
            ny = y + h - nh
        self.setGeometry(nx, ny, nw, nh)

    def eventFilter(self, obj, event):
        if not self.isVisible():
            self._clear_resize_cursor()
            return False
        etype = event.type()

        # 过滤器装在 QApplication 上会收到所有顶层窗口的鼠标事件。本窗口被
        # 别的窗口遮挡时，鼠标落在被遮挡的矩形区域内不应触发本窗口的 resize。
        if etype in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            if isinstance(obj, QPushButton) and self._title_bar.isAncestorOf(obj) and not self._resize_active:
                self._clear_resize_cursor()
                return False
            gpos = event.globalPosition().toPoint()
            top = QApplication.topLevelAt(gpos)
            if top is not None and top is not self and not self._resize_active:
                # 指针离开本窗口进入其它顶层窗口时，清掉可能残留的 resize
                # 覆盖光标——它是 QApplication 级全局覆盖，不清会盖住其它窗口
                # 控件自己的光标（表现为在别处停留仍显示上下/斜向箭头）。
                self._clear_resize_cursor()
                return False

        if etype == QEvent.Type.MouseMove:
            gpos = event.globalPosition().toPoint()
            if self._resize_active:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._do_manual_resize(gpos)
                else:
                    self._resize_active = False
                return True
            local = self.mapFromGlobal(gpos)
            edges = (
                self._resize_edges_at(local)
                if self.rect().contains(local)
                else None
            )
            if edges is not None:
                self._apply_resize_cursor(edges)
            else:
                self._clear_resize_cursor()

        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                gpos = event.globalPosition().toPoint()
                local = self.mapFromGlobal(gpos)
                edges = (
                    self._resize_edges_at(local)
                    if self.rect().contains(local)
                    else None
                )
                if edges is not None:
                    self._resize_active = True
                    self._resize_edges = edges
                    self._resize_start_geo = self.geometry()
                    self._resize_start_pos = gpos
                    self._clear_resize_cursor()
                    return True

        elif etype == QEvent.Type.MouseButtonRelease:
            if self._resize_active:
                self._resize_active = False
                return True

        return super().eventFilter(obj, event)

    def _install_resize_filter(self):
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def moveEvent(self, event):
        """窗口移动时触发位置保存（防抖）。"""
        super().moveEvent(event)
        if hasattr(self, '_pos_timer') and not self._edge_mutating and not self._applying_settings:
            self._pos_timer.start()
            self._edge_timer.start()

    # ── Cleanup ────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if not getattr(self, "_disposing", False):
            event.ignore()
            self.hide_note()
            return
        self._save_timer.stop()
        self._pos_timer.stop()
        self._edge_timer.stop()
        self._flush()
        self._save_position()
        self._clear_resize_cursor()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        self.closed.emit()
        super().closeEvent(event)


class _NoteContainer(QWidget):
    """Inner container that paints the rounded, drop-shadowed background."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)

        # Soft drop shadow
        shadow_color = QColor(0, 0, 0, 40)
        for i in range(4, 0, -1):
            sr = r.adjusted(-i, -i, i, i + 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shadow_color)
            p.setOpacity(0.06 * i)
            p.drawRoundedRect(sr, 12, 12)

        p.setOpacity(1.0)
        p.setBrush(QColor(self._color))
        p.setPen(QPen(QColor(0, 0, 0, 20), 1))
        p.drawRoundedRect(r, 10, 10)


def _html_to_plain(html: str) -> str:
    """Strip HTML tags and embedded style/script blocks for plain-text display."""
    import re
    if not html or "<" not in html:
        return html
    # Remove <style>...</style> and <head>...</head> blocks first
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<head[^>]*>.*?</head>", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Replace block-level tags with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&nbsp;", " ").replace("&quot;", '"'))
    return text.strip()
