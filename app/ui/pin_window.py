"""
Frameless pin window — displays a screenshot pinned on top of other windows.

Features:
- Draggable (startSystemMove after small threshold)
- Resizable from all edges and corners (QApplication event filter)
- Scroll wheel adjusts size (maintains aspect ratio)
- Ctrl+scroll wheel adjusts opacity (0.3 ~ 1.0)
- Right-click context menu: copy / save-as / close
- Double-click to close
- Placed at the capture position, full resolution
- Blue glow only while the pin is the active window

Follows the frameless window conventions from CLAUDE.md.
"""

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QWidget,
)

from app.i18n import t

_RESIZE_BORDER = 8
_MIN_W = 80
_MIN_H = 60
_GLOW_MARGIN = 10
_FRAME_PADDING = _GLOW_MARGIN * 2
_GLOW_STOPS = ((0.0, 155), (0.15, 110), (0.4, 52), (0.7, 13), (1.0, 0))


class PinWindow(QWidget):
    """A frameless, always-on-top window displaying a pinned screenshot."""

    closed = pyqtSignal()

    def __init__(self, pixmap: QPixmap, pos: QPoint | None = None, parent=None):
        super().__init__(parent)
        if pixmap.isNull():
            raise ValueError("PinWindow requires a valid pixmap")
        self._pixmap = pixmap
        self._opacity = 1.0
        self._capture_pos = QPoint(pos) if pos is not None else None

        # Drag state — don't startSystemMove immediately; wait for threshold
        self._drag_pos = QPoint()
        self._drag_started = False

        # Resize state
        self._resize_active = False
        self._resize_edges = Qt.Edge(0)
        self._resize_start_geo = QRect()
        self._resize_start_pos = QPoint()
        self._resize_cursor_shape = None

        self._build_window()
        self._install_resize_filter()

    # ── Window setup ───────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # Use logical (device-independent) pixel size so the window matches
        # the original selection exactly on HiDPI screens.
        dpr = self._pixmap.devicePixelRatio()
        pw = round(self._pixmap.width() / dpr)
        ph = round(self._pixmap.height() / dpr)

        # Cap to screen size to avoid window spilling off-screen
        sg = QApplication.primaryScreen().availableGeometry()
        available_w = max(1, sg.width() - _FRAME_PADDING)
        available_h = max(1, sg.height() - _FRAME_PADDING)
        if pw > available_w or ph > available_h:
            scale = min(available_w / pw, available_h / ph)
            pw = int(pw * scale)
            ph = int(ph * scale)

        self.setMinimumSize(_MIN_W + _FRAME_PADDING, _MIN_H + _FRAME_PADDING)
        self.resize(pw + _FRAME_PADDING, ph + _FRAME_PADDING)

        # Position at capture location or center
        if self._capture_pos is not None:
            self.move(self._capture_pos - QPoint(_GLOW_MARGIN, _GLOW_MARGIN))
        else:
            self.move(
                (sg.width() - self.width()) // 2 + sg.x(),
                (sg.height() - self.height()) // 2 + sg.y(),
            )

    # ── Paint — draw pixmap directly, no QLabel ────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        image_rect = self._image_rect()
        if self.isActiveWindow():
            self._draw_glow(p, QRectF(image_rect))
        p.drawPixmap(image_rect, self._pixmap)
        # The bright core sits just outside the image; the pixels being pinned
        # remain intact, and only the transparent window margin carries chrome.
        if self.isActiveWindow():
            p.setPen(QPen(QColor("#398BF2"), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(image_rect).adjusted(-0.5, -0.5, 0.5, 0.5))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            self.update()

    def _image_rect(self) -> QRect:
        return self.rect().adjusted(
            _GLOW_MARGIN, _GLOW_MARGIN, -_GLOW_MARGIN, -_GLOW_MARGIN
        )

    @staticmethod
    def _draw_glow(p: QPainter, rect: QRectF) -> None:
        """Continuous falloff on the sides and radial falloff at the corners."""
        left, top = rect.left(), rect.top()
        right, bottom = rect.right(), rect.bottom()
        margin = _GLOW_MARGIN

        def add_stops(gradient):
            for offset, alpha in _GLOW_STOPS:
                gradient.setColorAt(offset, QColor(51, 136, 255, alpha))
            return gradient

        for area, gradient in (
            (QRectF(left - margin, top, margin, rect.height()),
             QLinearGradient(left, top, left - margin, top)),
            (QRectF(right, top, margin, rect.height()),
             QLinearGradient(right, top, right + margin, top)),
            (QRectF(left, top - margin, rect.width(), margin),
             QLinearGradient(left, top, left, top - margin)),
            (QRectF(left, bottom, rect.width(), margin),
             QLinearGradient(left, bottom, left, bottom + margin)),
        ):
            p.fillRect(area, add_stops(gradient))
        for cx, cy, x, y in (
            (left, top, left - margin, top - margin),
            (right, top, right, top - margin),
            (left, bottom, left - margin, bottom),
            (right, bottom, right, bottom),
        ):
            gradient = add_stops(QRadialGradient(cx, cy, margin))
            p.fillRect(QRectF(x, y, margin, margin), gradient)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    # ── Drag (threshold to allow double-click) ────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_started = False
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._drag_started and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = (event.globalPosition().toPoint() - self._drag_pos).manhattanLength()
            if delta > 4:
                self._drag_started = True
                self.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_started = False
            self.close()

    # ── Size via scroll wheel (Ctrl+wheel for opacity) ──────────────────

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y() / 120.0
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+wheel: adjust opacity
            self._opacity = max(0.3, min(1.0, self._opacity + delta * 0.05))
            self.setWindowOpacity(self._opacity)
        else:
            # Wheel: adjust size — maintain image aspect ratio
            dpr = self._pixmap.devicePixelRatio()
            img_w = round(self._pixmap.width() / dpr)
            img_h = round(self._pixmap.height() / dpr)
            aspect = img_w / img_h if img_h > 0 else 1.0
            scale = 1.1 if delta > 0 else 0.9
            new_w = max(_MIN_W, int(self._image_rect().width() * scale))
            new_h = round(new_w / aspect)
            if new_h < _MIN_H:
                new_h = _MIN_H
                new_w = max(_MIN_W, round(new_h * aspect))
            new_w += _FRAME_PADDING
            new_h += _FRAME_PADDING
            # Keep center position
            cx = self.x() + self.width() // 2
            cy = self.y() + self.height() // 2
            self.setGeometry(cx - new_w // 2, cy - new_h // 2, new_w, new_h)

    # ── Context menu ───────────────────────────────────────────────────

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction(t("pin.copy"), self._copy_to_clipboard)
        menu.addAction(t("pin.saveAs"), self._save_as)
        menu.addSeparator()
        menu.addAction(t("pin.zoomHint"), lambda: None)  # hint
        menu.addAction(t("pin.opacityHint"), lambda: None)  # hint
        menu.addSeparator()
        menu.addAction(t("pin.close"), self.close)
        menu.exec(event.globalPos())

    def _copy_to_clipboard(self):
        QApplication.clipboard().setPixmap(self._pixmap)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, t("pin.saveDialogTitle"), "screenshot.png", "PNG (*.png)"
        )
        if path:
            self._pixmap.save(path, "PNG")

    # ── Resize (QApplication event filter) ─────────────────────────────

    def _resize_edges_at(self, win_pos: QPoint):
        x, y, w, h = win_pos.x(), win_pos.y(), self.width(), self.height()
        B = _RESIZE_BORDER + _GLOW_MARGIN
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
            Qt.Edge.LeftEdge,
            Qt.Edge.RightEdge,
            Qt.Edge.TopEdge,
            Qt.Edge.BottomEdge,
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
        sg = QApplication.primaryScreen().availableGeometry()
        e = self._resize_edges
        nx, ny, nw, nh = x, y, w, h
        if bool(e & Qt.Edge.RightEdge):
            nw = max(self.minimumWidth(), min(sg.width(), w + dx))
        if bool(e & Qt.Edge.BottomEdge):
            nh = max(self.minimumHeight(), min(sg.height(), h + dy))
        if bool(e & Qt.Edge.LeftEdge):
            nw = max(self.minimumWidth(), min(sg.width(), w - dx))
            nx = x + w - nw
        if bool(e & Qt.Edge.TopEdge):
            nh = max(self.minimumHeight(), min(sg.height(), h - dy))
            ny = y + h - nh
        self.setGeometry(nx, ny, nw, nh)

    def eventFilter(self, obj, event):
        etype = event.type()

        # 过滤器装在 QApplication 上会收到所有顶层窗口的鼠标事件。本窗口被
        # 别的窗口遮挡时，鼠标落在被遮挡的矩形区域内不应触发本窗口的 resize。
        if etype in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
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

    # ── Cleanup ────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._clear_resize_cursor()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        self.closed.emit()
        super().closeEvent(event)
