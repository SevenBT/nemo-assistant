"""QApplication-level event filter for frameless window resizing.

Extracted from main_window.py. Installed on QApplication so it can
intercept mouse events over any child widget (not just the window itself).

See CLAUDE.md §2 for why this approach is required.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QScrollBar

from qfluentwidgets.components.widgets.scroll_bar import ScrollBar as FluentScrollBar

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow

_RESIZE_BORDER = 12  # pixels from window edge that trigger resize
_RESIZE_PRIORITY = 4  # outermost pixels always reserved for resize (even over scrollbar)


class ResizeFilter(QObject):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._win = window
        self._active = False
        self._edges_active = None
        self._start_geo = None
        self._start_pos = None
        self._cursor_shape = None
        self._recently_resized = False
        self._enabled = True

    def set_enabled(self, enabled: bool):
        """Enable/disable edge-resize handling (mini mode uses a fixed size)."""
        self._enabled = enabled
        if not enabled:
            self._active = False
            self._clear_cursor()

    @property
    def is_resizing(self) -> bool:
        return self._active

    @property
    def recently_resized(self) -> bool:
        """True for a short period after a resize operation ends."""
        return self._recently_resized

    def install(self):
        QApplication.instance().installEventFilter(self)

    # ── helpers ───────────────────────────────────────────────────────

    def _is_scrollbar_widget(self, widget) -> bool:
        """Check if widget or any of its ancestors is a scrollbar."""
        w = widget
        while w is not None and w is not self._win:
            if isinstance(w, (QScrollBar, FluentScrollBar)):
                return True
            w = w.parent()
        return False

    def _in_priority_zone(self, win_pos) -> bool:
        """True if position is in the outermost pixels reserved for resize."""
        x, y = win_pos.x(), win_pos.y()
        w, h = self._win.width(), self._win.height()
        P = _RESIZE_PRIORITY
        return x < P or x > w - P or y < P or y > h - P

    # ── edge detection ────────────────────────────────────────────────

    def _resize_edges(self, win_pos):
        """Return Qt.Edge flags for window-local position, or None if not on any edge."""
        x, y = win_pos.x(), win_pos.y()
        w, h = self._win.width(), self._win.height()
        B = _RESIZE_BORDER
        on_l, on_r = x < B, x > w - B
        on_t, on_b = y < B, y > h - B
        if not (on_l or on_r or on_t or on_b):
            return None
        edges = Qt.Edge(0)
        if on_l: edges |= Qt.Edge.LeftEdge
        if on_r: edges |= Qt.Edge.RightEdge
        if on_t: edges |= Qt.Edge.TopEdge
        if on_b: edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges):
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        has = lambda e: bool(edges & e)  # noqa: E731
        if (has(T) and has(L)) or (has(B) and has(R)): return Qt.CursorShape.SizeFDiagCursor
        if (has(T) and has(R)) or (has(B) and has(L)): return Qt.CursorShape.SizeBDiagCursor
        if has(L) or has(R): return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    # ── cursor management ─────────────────────────────────────────────

    def _apply_cursor(self, edges):
        shape = self._cursor_for_edges(edges)
        if self._cursor_shape is None:
            QApplication.setOverrideCursor(shape)
        elif shape != self._cursor_shape:
            QApplication.changeOverrideCursor(shape)
        else:
            return
        self._cursor_shape = shape

    def _clear_cursor(self):
        if self._cursor_shape is not None:
            QApplication.restoreOverrideCursor()
            self._cursor_shape = None

    # ── resize ────────────────────────────────────────────────────────

    def _do_resize(self, global_pos):
        geo = self._start_geo
        dx = global_pos.x() - self._start_pos.x()
        dy = global_pos.y() - self._start_pos.y()
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        min_w, min_h = self._win.minimumWidth(), self._win.minimumHeight()
        e = self._edges_active
        nx, ny, nw, nh = x, y, w, h
        if bool(e & Qt.Edge.RightEdge):  nw = max(min_w, w + dx)
        if bool(e & Qt.Edge.BottomEdge): nh = max(min_h, h + dy)
        if bool(e & Qt.Edge.LeftEdge):   nw = max(min_w, w - dx); nx = x + w - nw
        if bool(e & Qt.Edge.TopEdge):    nh = max(min_h, h - dy); ny = y + h - nh
        self._win.setGeometry(nx, ny, nw, nh)

    # ── event filter ──────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        etype = event.type()

        # Disabled (e.g. mini mode uses a fixed window size)
        if not self._enabled:
            return False

        # 只处理发生在主窗口里的鼠标事件。过滤器装在 QApplication 上会收到
        # 所有顶层窗口（如设置对话框）的事件——若不区分，鼠标在对话框边缘
        # 仍会被映射到主窗口的 resize 边框，显示双向箭头并吞掉点击。
        if etype in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            gpos = event.globalPosition().toPoint()
            top = QApplication.topLevelAt(gpos)
            if top is not None and top is not self._win and not self._active:
                return False

        # Suppress resize while snapped or animating
        snap = self._win._snap_mgr
        if snap is not None and (snap.is_snapped or snap.is_animating):
            return False

        if etype == QEvent.Type.MouseMove:
            gpos = event.globalPosition().toPoint()
            if self._active:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._do_resize(gpos)
                else:
                    self._active = False  # button released outside window
                return True
            local = self._win.mapFromGlobal(gpos)
            edges = self._resize_edges(local) if self._win.rect().contains(local) else None
            if edges is not None:
                # Don't show resize cursor when hovering over a scrollbar
                # (unless in the outermost priority zone reserved for resize)
                widget_under = QApplication.widgetAt(gpos)
                if (widget_under is not None
                        and self._is_scrollbar_widget(widget_under)
                        and not self._in_priority_zone(local)):
                    self._clear_cursor()
                else:
                    self._apply_cursor(edges)
            else:
                self._clear_cursor()

        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                gpos = event.globalPosition().toPoint()
                local = self._win.mapFromGlobal(gpos)
                edges = self._resize_edges(local) if self._win.rect().contains(local) else None
                if edges is not None:
                    # Don't intercept clicks on scrollbars
                    # (unless in the outermost priority zone reserved for resize)
                    widget_under = QApplication.widgetAt(gpos)
                    if (widget_under is not None
                            and self._is_scrollbar_widget(widget_under)
                            and not self._in_priority_zone(local)):
                        return False
                    self._active = True
                    self._edges_active = edges
                    self._start_geo = self._win.geometry()
                    self._start_pos = gpos
                    self._clear_cursor()
                    # 用户手动拖边调整大小即视为退出最大化状态，
                    # 否则 is_maximized 残留为 True 会导致标题栏拖动被禁用。
                    if self._win.is_maximized:
                        self._win._is_maximized = False
                        self._win._title_bar.update_max_btn(False)
                    return True

        elif etype == QEvent.Type.MouseButtonRelease:
            if self._active:
                self._active = False
                self._recently_resized = True
                self._win._user_has_resized = True
                QTimer.singleShot(300, self._clear_recently_resized)
                return True

        return False

    def _clear_recently_resized(self):
        self._recently_resized = False
