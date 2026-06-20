"""
Fullscreen screenshot overlay with region selection and action toolbar.

Actions after selection: pin (贴图), copy (复制), save (保存), ocr (识别文字), cancel.
"""

import threading

from PyQt6.QtCore import (
    QEvent,
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

from app.ui import style

OVERLAY_ALPHA = 80
BORDER_WIDTH = 2
RESIZE_MARGIN = 8  # pixels from edge that trigger resize cursor


def _toolbar_style(theme: dict) -> str:
    """根据主题构造工具栏 / OCR 面板 QSS。"""
    return f"""
    #snipToolbar, #ocrPanel {{
        background: {theme["surface_solid"]};
        border-radius: 8px;
        border: 1px solid {theme["border_solid"]};
    }}
    #snipToolbar QPushButton, #ocrPanel QPushButton {{
        background: transparent;
        border: none;
        color: {theme["text"]};
        font-size: 13px;
        padding: 8px 14px;
        border-radius: 6px;
    }}
    #snipToolbar QPushButton {{
        padding: 4px 8px;
    }}
    #snipToolbar QPushButton:hover, #ocrPanel QPushButton:hover {{
        background: {theme["accent_subtle"]};
        color: {theme["accent"]};
    }}
    #snipToolbar QPushButton#snipCloseBtn:hover, #ocrPanel QPushButton#snipCloseBtn:hover {{
        background: {theme["error"]};
        color: #FFFFFF;
    }}
    #ocrPanel QPushButton#ocrConfirmBtn {{
        background: {theme["accent"]};
        color: #FFFFFF;
        padding: 6px 18px;
    }}
    #ocrPanel QPushButton#ocrConfirmBtn:hover {{
        background: {theme["accent"]}dd;
    }}
    #ocrPanel QPushButton#ocrCloseBtn {{
        background: transparent;
        border: 1px solid {theme["border_solid"]};
        padding: 6px 18px;
    }}
    #ocrPanel QPushButton#ocrCloseBtn:hover {{
        background: {theme["accent_subtle"]};
        color: {theme["accent"]};
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


# ── OCR layout reconstruction ──────────────────────────────────────────
#
# RapidOCR returns a list of [box, text, score] where *box* is four
# (x, y) corner points.  The engine emits one entry per detected text
# box, NOT per visual line — a single on-screen line is often split into
# several boxes.  Joining everything with "\n" therefore breaks lines
# apart.  We rebuild the original layout from box geometry: group boxes
# into rows by vertical overlap, order each row left→right, and infer
# inter-word spacing and leading indentation from horizontal gaps.

# A box joins a row if its vertical center sits within this fraction of
# the row's mean glyph height. Larger merges adjacent lines; smaller
# over-splits. 0.5 keeps a comfortable margin for the common case.
_ROW_OVERLAP_RATIO = 0.5
# If the gap between two boxes on the same row exceeds this fraction of
# the mean glyph height, insert a space. Below it the boxes are treated
# as touching (no space) — important for CJK where boxes abut tightly.
_WORD_GAP_RATIO = 0.4
# Leading whitespace: one space per this many "glyph widths" of left
# offset relative to the leftmost box in the block. Approximates indent.
_INDENT_GAP_RATIO = 0.9


def _box_metrics(box) -> dict:
    """Extract geometry from a RapidOCR 4-point box."""
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    return {
        "left": left,
        "right": right,
        "cy": (top + bottom) / 2.0,
        "height": max(bottom - top, 1.0),
    }


def _reconstruct_layout(result) -> str:
    """Rebuild text preserving the visual row/column structure of the image."""
    items = []
    for entry in result:
        # entry is [box, text, score]; tolerate score-less variants
        box, text = entry[0], entry[1]
        if not text:
            continue
        m = _box_metrics(box)
        m["text"] = text
        items.append(m)

    if not items:
        return ""

    # Order top→bottom so rows form in reading order.
    items.sort(key=lambda it: it["cy"])

    rows: list[list[dict]] = []
    for it in items:
        placed = False
        for row in rows:
            avg_cy = sum(b["cy"] for b in row) / len(row)
            avg_h = sum(b["height"] for b in row) / len(row)
            if abs(it["cy"] - avg_cy) <= avg_h * _ROW_OVERLAP_RATIO:
                row.append(it)
                placed = True
                break
        if not placed:
            rows.append([it])

    # Common left anchor + glyph width estimate for indentation.
    block_left = min(it["left"] for it in items)
    avg_glyph_w = _estimate_glyph_width(items)

    lines = []
    for row in rows:
        row.sort(key=lambda b: b["left"])
        lines.append(_assemble_row(row, block_left, avg_glyph_w))
    return "\n".join(lines)


def _estimate_glyph_width(items) -> float:
    """Rough mean glyph width: box width divided by character count."""
    widths = []
    for it in items:
        n = max(len(it["text"]), 1)
        widths.append((it["right"] - it["left"]) / n)
    widths = [w for w in widths if w > 0]
    return sum(widths) / len(widths) if widths else 1.0


def _assemble_row(row: list[dict], block_left: float, glyph_w: float) -> str:
    """Join one row's boxes, inferring indentation and inter-box spacing."""
    parts = []

    # Leading indentation relative to the block's left edge.
    indent = round((row[0]["left"] - block_left) / (glyph_w * _INDENT_GAP_RATIO))
    if indent > 0:
        parts.append(" " * indent)

    prev_right = None
    for b in row:
        if prev_right is not None:
            gap = b["left"] - prev_right
            if gap > b["height"] * _WORD_GAP_RATIO:
                # Scale spaces with gap size so wide columns stay separated.
                spaces = max(1, round(gap / (glyph_w * _INDENT_GAP_RATIO)))
                parts.append(" " * spaces)
        parts.append(b["text"])
        prev_right = b["right"]

    return "".join(parts)


class ScreenshotOverlay(QWidget):
    """Fullscreen region-selection overlay.

    Emits ``captured(pixmap, action, ocr_text)`` when user picks an action,
    then closes.  *ocr_text* is only set for ``"ocr"`` action.
    """

    captured = pyqtSignal(QPixmap, str, str, QPoint)  # (pixmap, action, ocr_text, capture_pos)
    _ocr_done = pyqtSignal(str)  # internal signal for thread-safe OCR result delivery

    def __init__(self, parent=None):
        super().__init__(parent)
        # Snapshot theme so toolbar, OCR panel and selection accents all match
        # the active app theme.
        self._theme = style.get_current_theme()
        self._toolbar_qss = _toolbar_style(self._theme)
        self._border_color = QColor(self._theme["accent"])
        self._start = QPoint()
        self._end = QPoint()
        self._state = "IDLE"  # IDLE | DRAGGING | SELECTED | RESIZING | OCR_EDIT
        # Frozen full-desktop snapshot. Captured the instant the overlay opens
        # and painted as the background, so selection happens on a still image —
        # transient UI (menus/tooltips/video frames) stays exactly as the user
        # framed it instead of changing under a live, see-through overlay.
        self._frozen: QPixmap = QPixmap()
        self._toolbar: QFrame | None = None
        self._ocr_panel: QFrame | None = None
        self._ocr_edit: QTextEdit | None = None
        self._dragging_panel = False
        self._panel_drag_offset = QPoint()
        # Resize state
        self._resize_edge: str = ""  # "N","S","E","W","NW","NE","SW","SE"
        self._resize_start_mouse = QPoint()
        self._resize_start_rect = QRect()
        self._resize_cursor_shape: Qt.CursorShape | None = None

        self._setup_window()
        self._capture_frozen()
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

    def _edge_at(self, pos: QPoint) -> str:
        """Return which resize edge/corner *pos* (local coords) is near, or ''."""
        r = self._normalized_rect_local()
        if not r.isValid():
            return ""
        m = RESIZE_MARGIN
        x, y = pos.x(), pos.y()
        on_left   = abs(x - r.left())   <= m
        on_right  = abs(x - r.right())  <= m
        on_top    = abs(y - r.top())    <= m
        on_bottom = abs(y - r.bottom()) <= m
        in_x = r.left() - m <= x <= r.right()  + m
        in_y = r.top()  - m <= y <= r.bottom() + m

        if on_top    and on_left:  return "NW"
        if on_top    and on_right: return "NE"
        if on_bottom and on_left:  return "SW"
        if on_bottom and on_right: return "SE"
        if on_top    and in_x:     return "N"
        if on_bottom and in_x:     return "S"
        if on_left   and in_y:     return "W"
        if on_right  and in_y:     return "E"
        return ""

    _EDGE_CURSORS = {
        "N":  Qt.CursorShape.SizeVerCursor,
        "S":  Qt.CursorShape.SizeVerCursor,
        "W":  Qt.CursorShape.SizeHorCursor,
        "E":  Qt.CursorShape.SizeHorCursor,
        "NW": Qt.CursorShape.SizeFDiagCursor,
        "SE": Qt.CursorShape.SizeFDiagCursor,
        "NE": Qt.CursorShape.SizeBDiagCursor,
        "SW": Qt.CursorShape.SizeBDiagCursor,
    }

    def _set_resize_cursor(self, shape: Qt.CursorShape):
        if self._resize_cursor_shape is None:
            QApplication.setOverrideCursor(shape)
        elif shape != self._resize_cursor_shape:
            QApplication.changeOverrideCursor(shape)
        self._resize_cursor_shape = shape

    def _clear_resize_cursor(self):
        if self._resize_cursor_shape is not None:
            QApplication.restoreOverrideCursor()
            self._resize_cursor_shape = None

    # ── Screen capture ─────────────────────────────────────────────────

    def _capture_frozen(self):
        """Grab the whole virtual desktop once, before the overlay is shown.

        This still image becomes the overlay background and the source every
        action crops from — nothing is re-grabbed from the live screen, so the
        result always matches what the user framed.
        """
        self._frozen = self._grab_rect(self.geometry())

    def _crop_frozen(self, rect: QRect) -> QPixmap:
        """Crop *rect* (global coords) out of the frozen desktop snapshot."""
        if self._frozen.isNull():
            # Fallback: no snapshot (shouldn't happen) → live grab.
            return self._grab_rect(rect)
        dpr = self._frozen.devicePixelRatio()
        origin = self.geometry().topLeft()
        # Map the global rect into frozen-pixmap device pixels.
        src = QRect(
            round((rect.x() - origin.x()) * dpr),
            round((rect.y() - origin.y()) * dpr),
            round(rect.width() * dpr),
            round(rect.height() * dpr),
        )
        piece = self._frozen.copy(src)
        piece.setDevicePixelRatio(dpr)
        return piece

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
        self._toolbar.setStyleSheet(self._toolbar_qss)
        self._toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        root = QVBoxLayout(self._toolbar)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        from app.ui.vision_actions import VISION_ACTIONS

        # AI 行：识图动作，发图片像素给多模态模型
        ai_actions = [
            (a.action_id, f"{a.icon} {a.label}") for a in VISION_ACTIONS
        ]
        # 本地行：不走 AI 的动作（贴图 / 本地 OCR 识字 / 复制 / 保存 / 取消）
        local_actions = [
            ("pin",  "📌 贴图"),
            ("ocr",  "📝 识字"),
            ("copy", "📋 复制"),
            ("save", "💾 保存"),
            ("cancel", "✕"),
        ]

        def _add_row(actions):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)
            for key, label in actions:
                btn = QPushButton(label)
                if key == "cancel":
                    btn.setObjectName("snipCloseBtn")
                btn.clicked.connect(lambda checked, k=key: self._on_action(k))
                row.addWidget(btn)
            # Trailing stretch keeps buttons at natural width and left-aligned,
            # so the two rows share the same left edge instead of stretching
            # each row's buttons to fill differing widths.
            row.addStretch()
            root.addLayout(row)

        _add_row(ai_actions)
        _add_row(local_actions)

        sh = self._toolbar.sizeHint()
        self._toolbar.setFixedSize(max(sh.width(), 200), max(sh.height(), 36))
        self._toolbar.installEventFilter(self)
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
        self._clear_resize_cursor()
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

        # pin / copy / save / vision:* — crop the frozen snapshot & emit.
        # vision actions carry the screenshot pixmap through to the AI path;
        # OCR (above) is a separate path that extracts text locally.
        pixmap = self._crop_frozen(r)
        self.captured.emit(pixmap, action, "", QPoint(r.topLeft()))
        self.hide()
        QTimer.singleShot(0, self.close)

    # ── OCR ────────────────────────────────────────────────────────────

    def _do_ocr(self):
        import numpy as np

        self._clear_resize_cursor()
        r = self._normalized_rect()
        # Crop from the frozen snapshot — no need to hide/re-grab the live screen.
        pixmap = self._crop_frozen(r)

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
                return _reconstruct_layout(result).strip() or "[未识别到文字]"
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
        self._ocr_panel.setStyleSheet(self._toolbar_qss)
        self._ocr_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        root = QVBoxLayout(self._ocr_panel)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("OCR 识别结果（可编辑）")
        title.setStyleSheet(
            f"color: {self._theme['text_secondary']}; font-size: 12px;"
            "background: transparent; border: none;"
        )
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
        self._ocr_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {self._theme["surface_raised"]};
                color: {self._theme["text"]};
                border: 1px solid {self._theme["border_solid"]};
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
            }}
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
        self._ocr_panel.installEventFilter(self)
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

        # Draw the frozen desktop snapshot as the base layer; the dim overlay
        # and selection chrome paint on top. This is what makes the screen look
        # "locked" — selection happens against a still image, not the live screen.
        if not self._frozen.isNull():
            p.drawPixmap(self.rect(), self._frozen)

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
            border_color = QColor("#FFFFFF") if is_dragging else self._border_color
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
        bg = QColor("#FFFFFF") if bright else self._border_color
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

    def eventFilter(self, obj, event):
        # The resize cursor is a *global* override (QApplication.setOverrideCursor).
        # When the pointer crosses straight from the selection edge onto the
        # toolbar/panel, the overlay stops getting mouseMove events, so the
        # override never gets cleared and the resize cursor sticks on the
        # buttons. Clear it the moment the pointer enters a panel.
        if event.type() == QEvent.Type.Enter and obj in (self._toolbar, self._ocr_panel):
            self._clear_resize_cursor()
        return super().eventFilter(obj, event)

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

            # Check for resize handle in SELECTED state
            if self._state == "SELECTED":
                edge = self._edge_at(pos)
                if edge:
                    self._resize_edge = edge
                    self._resize_start_mouse = gpos
                    self._resize_start_rect = self._normalized_rect()
                    self._state = "RESIZING"
                    self._set_resize_cursor(self._EDGE_CURSORS[edge])
                    return
                # Click inside selection → start new selection
                if self._normalized_rect_local().contains(pos):
                    pass  # fall through to start new selection

            self._clear_resize_cursor()
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

        if self._state == "RESIZING":
            self._do_resize(event.globalPosition().toPoint())
            return

        if self._state == "DRAGGING":
            self._end = event.globalPosition().toPoint()
            self.update()
            return

        # SELECTED: update cursor based on proximity to edges
        if self._state == "SELECTED":
            pos = event.position().toPoint()
            if not self._is_on_panel(pos):
                edge = self._edge_at(pos)
                if edge:
                    self._set_resize_cursor(self._EDGE_CURSORS[edge])
                else:
                    self._clear_resize_cursor()
            else:
                self._clear_resize_cursor()

    def _do_resize(self, gpos: QPoint):
        """Update _start/_end based on the active resize edge."""
        dx = gpos.x() - self._resize_start_mouse.x()
        dy = gpos.y() - self._resize_start_mouse.y()
        r = self._resize_start_rect

        # Work with the four sides of the original rect
        left   = r.left()
        top    = r.top()
        right  = r.right()
        bottom = r.bottom()

        edge = self._resize_edge
        if "W" in edge: left   = min(left + dx, right - 4)
        if "E" in edge: right  = max(right + dx, left + 4)
        if "N" in edge: top    = min(top + dy, bottom - 4)
        if "S" in edge: bottom = max(bottom + dy, top + 4)

        # Store as global coords (same coordinate space as _start/_end)
        self._start = QPoint(left, top)
        self._end   = QPoint(right, bottom)
        self.update()
        # Reposition toolbar without recreating it
        QTimer.singleShot(0, self._position_toolbar)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging_panel:
                self._dragging_panel = False
                return
            if self._state == "RESIZING":
                self._clear_resize_cursor()
                self._state = "SELECTED"
                self._resize_edge = ""
                self.update()
                # Reposition toolbar after resize
                QTimer.singleShot(0, self._position_toolbar)
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
            self._clear_resize_cursor()
            self.captured.emit(QPixmap(), "cancel", "", QPoint())
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._clear_resize_cursor()
        super().closeEvent(event)
