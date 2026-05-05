"""
Fullscreen screenshot overlay with region selection and action toolbar.

Actions after selection: pin (贴图), copy (复制), save (保存), ocr (识别文字), cancel.
"""

import threading

from PyQt6.QtCore import (
    QPoint,
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

OVERLAY_ALPHA = 80
BORDER_COLOR = QColor("#4A9EFF")
BORDER_WIDTH = 2
TOOLBAR_BG = QColor("#2D2D2D")

TOOLBAR_STYLE = f"""
    #snipToolbar, #ocrPanel {{
        background: {TOOLBAR_BG.name()};
        border-radius: 8px;
        border: 1px solid #3D3D3D;
    }}
    #snipToolbar QPushButton, #ocrPanel QPushButton {{
        background: transparent;
        border: none;
        color: #FFFFFF;
        font-size: 13px;
        padding: 8px 14px;
        border-radius: 6px;
    }}
    #snipToolbar QPushButton:hover, #ocrPanel QPushButton:hover {{
        background: #3D3D3D;
    }}
    #snipToolbar QPushButton#snipCloseBtn:hover, #ocrPanel QPushButton#snipCloseBtn:hover {{
        background: #C62828;
    }}
    #ocrPanel QPushButton#ocrConfirmBtn {{
        background: {BORDER_COLOR.name()};
        padding: 6px 18px;
    }}
    #ocrPanel QPushButton#ocrConfirmBtn:hover {{
        background: #3A8EDB;
    }}
    #ocrPanel QPushButton#ocrCloseBtn {{
        background: transparent;
        border: 1px solid #555;
        padding: 6px 18px;
    }}
    #ocrPanel QPushButton#ocrCloseBtn:hover {{
        background: #3D3D3D;
    }}
"""


# Module-level RapidOCR singleton — loaded once, reused across calls
_rapid_ocr_engine = None


def _get_rapid_ocr():
    global _rapid_ocr_engine
    if _rapid_ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid_ocr_engine = RapidOCR()
    return _rapid_ocr_engine


class ScreenshotOverlay(QWidget):
    """Fullscreen region-selection overlay.

    Emits ``captured(pixmap, action, ocr_text)`` when user picks an action,
    then closes.  *ocr_text* is only set for ``"ocr"`` action.
    """

    captured = pyqtSignal(QPixmap, str, str, QPoint)  # (pixmap, action, ocr_text, capture_pos)
    _ocr_done = pyqtSignal(str)  # internal signal for thread-safe OCR result delivery

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start = QPoint()
        self._end = QPoint()
        self._state = "IDLE"  # IDLE | DRAGGING | SELECTED | OCR_EDIT
        self._toolbar: QFrame | None = None
        self._ocr_panel: QFrame | None = None
        self._ocr_edit: QTextEdit | None = None
        self._dragging_panel = False
        self._panel_drag_offset = QPoint()

        self._setup_window()
        self._ocr_done.connect(self._on_ocr_ready)
        # Warm up OCR engine in background so first recognition is instant
        threading.Thread(target=_get_rapid_ocr, daemon=True).start()

    # ── Window ─────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        screens = QApplication.screens()
        rect = QRect()
        for screen in screens:
            rect = rect.united(screen.geometry())
        self.setGeometry(rect)

    # ── Selection rects ────────────────────────────────────────────────

    def _normalized_rect(self) -> QRect:
        r = QRect(self._start, self._end).normalized()
        if r.width() < 4 and r.height() < 4:
            return QRect()
        return r

    def _normalized_rect_local(self) -> QRect:
        r = QRect(
            self.mapFromGlobal(self._start),
            self.mapFromGlobal(self._end),
        ).normalized()
        if r.width() < 4 and r.height() < 4:
            return QRect()
        return r

    def _has_selection(self) -> bool:
        return self._normalized_rect().isValid()

    # ── Screen capture ─────────────────────────────────────────────────

    def _grab_rect(self, rect: QRect) -> QPixmap:
        """Capture at native device-pixel resolution for maximum quality."""
        # Use the highest DPR among screens intersecting the rect
        dpr = max(
            (s.devicePixelRatio() for s in QApplication.screens()
             if s.geometry().intersects(rect)),
            default=1.0,
        )
        dpr = max(dpr, 1.0)

        # Allocate at device-pixel size — ceil ensures logical size rounds back to rect
        import math
        pw = max(1, math.ceil(rect.width() * dpr))
        ph = max(1, math.ceil(rect.height() * dpr))
        result = QPixmap(pw, ph)
        result.setDevicePixelRatio(dpr)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)

        for screen in QApplication.screens():
            sg = screen.geometry()
            intersection = sg.intersected(rect)
            if not intersection.isValid():
                continue
            piece = screen.grabWindow(
                0,
                intersection.x() - sg.x(),
                intersection.y() - sg.y(),
                intersection.width(),
                intersection.height(),
            )
            # drawPixmap uses logical coords; QPainter maps to device pixels
            # automatically via the result pixmap's devicePixelRatio
            painter.drawPixmap(
                QRect(
                    intersection.x() - rect.x(),
                    intersection.y() - rect.y(),
                    intersection.width(),
                    intersection.height(),
                ),
                piece,
            )

        painter.end()
        return result

    # ── Toolbar ────────────────────────────────────────────────────────

    def _show_toolbar(self):
        if self._toolbar:
            return

        self._hide_ocr_panel()
        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("snipToolbar")
        self._toolbar.setStyleSheet(TOOLBAR_STYLE)
        self._toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        layout = QHBoxLayout(self._toolbar)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        actions = [
            ("pin",  "📌 贴图"),
            ("ocr",  "📝 识字"),
            ("copy", "📋 复制"),
            ("save", "💾 保存"),
            ("cancel", "✕"),
        ]
        for key, label in actions:
            btn = QPushButton(label)
            if key == "cancel":
                btn.setObjectName("snipCloseBtn")
            btn.clicked.connect(lambda checked, k=key: self._on_action(k))
            layout.addWidget(btn)

        sh = self._toolbar.sizeHint()
        self._toolbar.setFixedSize(max(sh.width(), 200), max(sh.height(), 36))
        self._toolbar.show()
        self._toolbar.raise_()
        QTimer.singleShot(0, self._position_toolbar)

    def _position_toolbar(self):
        self._position_panel(self._toolbar)

    def _position_panel(self, panel: QFrame | None):
        """Position *panel* near the selection, preferring below."""
        r = self._normalized_rect_local()
        if not r.isValid() or not panel:
            return
        tw = panel.width()
        th = panel.height()
        margin = 6

        x = r.right() - tw
        y = r.bottom() + margin

        if y + th > self.height():
            y = r.top() - th - margin
        if y < 0:
            y = r.bottom() + margin
        if x < margin:
            x = margin
        if x + tw > self.width():
            x = self.width() - tw - margin

        panel.move(int(x), int(y))

    def _hide_toolbar(self):
        if self._toolbar:
            self._toolbar.hide()
            self._toolbar.deleteLater()
            self._toolbar = None

    def _on_action(self, action: str):
        if action == "cancel":
            self.captured.emit(QPixmap(), "cancel", "", QPoint())
            self.close()
            return

        r = self._normalized_rect()
        if not r.isValid():
            return

        if action == "ocr":
            self._do_ocr()
            return

        # pin / copy / save — capture & emit immediately
        self.hide()
        QApplication.processEvents()
        pixmap = self._grab_rect(r)
        self.captured.emit(pixmap, action, "", QPoint(r.topLeft()))
        QTimer.singleShot(0, self.close)

    # ── OCR ────────────────────────────────────────────────────────────

    def _do_ocr(self):
        import numpy as np

        r = self._normalized_rect()
        self.hide()
        QApplication.processEvents()
        pixmap = self._grab_rect(r)
        self.show()
        self.raise_()
        self.activateWindow()

        # Extract pixel data in main thread (Qt objects can't cross threads)
        img = pixmap.toImage()
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr.asstring(), dtype=np.uint8).reshape(
            img.height(), img.width(), 4
        )
        bgr = arr[:, :, :3][:, :, ::-1].copy()

        self._hide_toolbar()
        self._state = "OCR_EDIT"
        self._show_ocr_panel("[识别中...]")

        def _worker():
            try:
                text = self._run_ocr_from_array(bgr)
            except Exception as e:
                text = f"[OCR 错误: {e}]"
            self._ocr_done.emit(text)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_ocr_from_array(self, bgr) -> str:
        """Run OCR on a BGR numpy array. Safe to call from any thread."""
        try:
            engine = _get_rapid_ocr()
            result, _ = engine(bgr)
            if result:
                return "\n".join(line[1] for line in result).strip()
            return "[未识别到文字]"
        except Exception as e:
            return f"[OCR 错误: {e}]"

    def _on_ocr_ready(self, text: str):
        if self._ocr_edit is not None:
            self._ocr_edit.setPlainText(text)
            self._ocr_edit.moveCursor(QTextCursor.MoveOperation.Start)
            self._ocr_edit.moveCursor(
                QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
            )


    # ── OCR editor panel ───────────────────────────────────────────────

    def _show_ocr_panel(self, text: str):
        if self._ocr_panel:
            return

        self._ocr_panel = QFrame(self)
        self._ocr_panel.setObjectName("ocrPanel")
        self._ocr_panel.setStyleSheet(TOOLBAR_STYLE)
        self._ocr_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        root = QVBoxLayout(self._ocr_panel)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("OCR 识别结果（可编辑）")
        title.setStyleSheet("color: #AAA; font-size: 12px; background: transparent; border: none;")
        header.addWidget(title)
        header.addStretch()

        cancel_btn = QPushButton("✕")
        cancel_btn.setObjectName("snipCloseBtn")
        cancel_btn.setFixedSize(28, 28)
        cancel_btn.clicked.connect(lambda: (self.captured.emit(QPixmap(), "cancel", "", QPoint()), self.close()))
        header.addWidget(cancel_btn)
        root.addLayout(header)

        # Text editor
        self._ocr_edit = QTextEdit()
        self._ocr_edit.setPlainText(text)
        self._ocr_edit.setMinimumSize(340, 120)
        self._ocr_edit.setMaximumHeight(300)
        self._ocr_edit.setStyleSheet("""
            QTextEdit {
                background: #1A1A1A;
                color: #E0E0E0;
                border: 1px solid #3D3D3D;
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
            }
        """)
        root.addWidget(self._ocr_edit)

        # Footer: close and confirm buttons
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("ocrCloseBtn")
        close_btn.clicked.connect(lambda: (self.captured.emit(QPixmap(), "cancel", "", QPoint()), self.close()))
        footer.addWidget(close_btn)
        confirm_btn = QPushButton("复制并关闭")
        confirm_btn.setObjectName("ocrConfirmBtn")
        confirm_btn.clicked.connect(self._on_ocr_confirm)
        footer.addWidget(confirm_btn)
        root.addLayout(footer)

        self._ocr_panel.adjustSize()
        sh = self._ocr_panel.sizeHint()
        self._ocr_panel.setFixedSize(max(sh.width(), 400), max(sh.height(), 200))
        self._ocr_panel.show()
        self._ocr_panel.raise_()
        self._ocr_edit.setFocus()
        # Select all for easy replacement
        self._ocr_edit.moveCursor(QTextCursor.MoveOperation.Start)
        self._ocr_edit.moveCursor(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)

        QTimer.singleShot(0, lambda: self._position_panel(self._ocr_panel))

    def _on_ocr_confirm(self):
        text = self._ocr_edit.toPlainText().strip()
        self.captured.emit(QPixmap(), "ocr", text, QPoint())
        self.close()

    def _hide_ocr_panel(self):
        if self._ocr_panel:
            self._ocr_panel.hide()
            self._ocr_panel.deleteLater()
            self._ocr_panel = None

    # ── Paint ──────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r_local = self._normalized_rect_local()

        if self._state in ("IDLE", "OCR_EDIT"):
            if self._state == "OCR_EDIT":
                # Show a lighter overlay during OCR editing
                p.fillRect(self.rect(), QColor(0, 0, 0, OVERLAY_ALPHA))
                if r_local.isValid():
                    full = QPainterPath()
                    full.addRect(self.rect().toRectF())
                    cutout = QPainterPath()
                    cutout.addRect(r_local.toRectF())
                    p.fillPath(full.subtracted(cutout), QColor(0, 0, 0, OVERLAY_ALPHA))
            else:
                p.fillRect(self.rect(), QColor(0, 0, 0, OVERLAY_ALPHA))
                p.setPen(QColor(255, 255, 255, 160))
                font = QFont()
                font.setPointSize(14)
                p.setFont(font)
                p.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "拖拽鼠标框选截图区域 · 右键或 Esc 取消",
                )
            return

        overlay = QColor(0, 0, 0, OVERLAY_ALPHA)
        if r_local.isValid():
            # Mask outside selection
            full = QPainterPath()
            full.addRect(self.rect().toRectF())
            cutout = QPainterPath()
            cutout.addRect(r_local.toRectF())
            p.fillPath(full.subtracted(cutout), overlay)

            # ── Selection border ──
            is_dragging = self._state == "DRAGGING"
            border_w = 3 if is_dragging else BORDER_WIDTH
            border_color = QColor("#FFFFFF") if is_dragging else BORDER_COLOR
            pen_style = Qt.PenStyle.SolidLine if is_dragging else Qt.PenStyle.DashLine

            pen = QPen(border_color, border_w, pen_style)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Inset by half the pen width so it sits inside the selection
            off = border_w / 2.0
            p.drawRect(r_local.toRectF().adjusted(off, off, -off, -off))

            # ── Corner brackets (like Win11 snip) ──
            self._draw_corners(p, r_local, border_color, border_w, is_dragging)

            # ── Size label ──
            self._draw_size_label(p, r_local, is_dragging)
        else:
            p.fillRect(self.rect(), overlay)

    def _draw_size_label(self, p: QPainter, r: QRect, bright: bool = False):
        label = f"{r.width()} × {r.height()}"
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(label) + 12
        text_h = fm.height() + 6

        label_x = r.left() + 4
        label_y = r.top() - text_h - 4
        if label_y < 0:
            label_y = r.top() + 4
        if label_x + text_w > self.width():
            label_x = self.width() - text_w - 4

        label_rect = QRect(int(label_x), int(label_y), text_w, text_h)
        bg = QColor("#FFFFFF") if bright else BORDER_COLOR
        fg = QColor("#1A1A1A") if bright else QColor("#FFFFFF")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(label_rect.toRectF(), 4, 4)
        p.setPen(fg)
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_corners(self, p: QPainter, r: QRect, color: QColor, bw: int, bright: bool):
        """Draw L-shaped corner bracket highlights."""
        arm = 16  # arm length in pixels
        w = 3 if bright else 2  # corner line width
        c = QColor("#FFFFFF") if bright else color

        pen = QPen(c, w, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        x, y, rw, rh = r.x(), r.y(), r.width(), r.height()
        # Offset corners inward so brackets sit just inside the border
        off = bw

        # Top-left
        p.drawLine(x + off, y + off + arm, x + off, y + off)
        p.drawLine(x + off, y + off, x + off + arm, y + off)

        # Top-right
        p.drawLine(x + rw - off - arm, y + off, x + rw - off, y + off)
        p.drawLine(x + rw - off, y + off, x + rw - off, y + off + arm)

        # Bottom-left
        p.drawLine(x + off, y + rh - off - arm, x + off, y + rh - off)
        p.drawLine(x + off, y + rh - off, x + off + arm, y + rh - off)

        # Bottom-right
        p.drawLine(x + rw - off - arm, y + rh - off, x + rw - off, y + rh - off)
        p.drawLine(x + rw - off, y + rh - off, x + rw - off, y + rh - off - arm)

    # ── Mouse ──────────────────────────────────────────────────────────

    def _is_on_panel(self, pos) -> bool:
        for panel in (self._toolbar, self._ocr_panel):
            if panel and panel.isVisible() and panel.geometry().contains(pos):
                return True
        return False

    def _is_interactive_at(self, gpos: QPoint) -> bool:
        """Return True if the widget under gpos should receive events directly."""
        w = QApplication.widgetAt(gpos)
        return w is not None and isinstance(w, (QAbstractButton, QAbstractScrollArea))

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        gpos = event.globalPosition().toPoint()

        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_on_panel(pos):
                if self._ocr_panel and not self._is_interactive_at(gpos):
                    # Non-interactive area of the panel → start drag
                    self._dragging_panel = True
                    self._panel_drag_offset = pos - self._ocr_panel.pos()
                else:
                    super().mousePressEvent(event)
                return
            if self._state == "OCR_EDIT":
                return  # Block new selection during OCR editing
            self._hide_toolbar()
            self._hide_ocr_panel()
            self._start = event.globalPosition().toPoint()
            self._end = self._start
            self._state = "DRAGGING"
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            if self._is_on_panel(pos):
                # Allow context menu inside the panel (e.g. text selection)
                super().mousePressEvent(event)
                return
            self.captured.emit(QPixmap(), "cancel", "", QPoint())
            self.close()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging_panel and self._ocr_panel:
            new_pos = event.position().toPoint() - self._panel_drag_offset
            pw, ph = self._ocr_panel.width(), self._ocr_panel.height()
            x = max(0, min(new_pos.x(), self.width() - pw))
            y = max(0, min(new_pos.y(), self.height() - ph))
            self._ocr_panel.move(x, y)
            return
        if self._state == "DRAGGING":
            self._end = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging_panel:
                self._dragging_panel = False
                return
            if self._state == "DRAGGING":
                self._end = event.globalPosition().toPoint()
                self._state = "SELECTED"
                self.update()
                if self._has_selection():
                    self._show_toolbar()

    # ── Keyboard ───────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.captured.emit(QPixmap(), "cancel", "", QPoint())
            self.close()
            return
        super().keyPressEvent(event)
