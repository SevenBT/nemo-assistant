"""
Fullscreen screenshot overlay with region selection and action toolbar.

Actions after selection: pin (贴图), copy (复制), save (保存), ocr (识别文字), cancel.
"""

import threading

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.ocr_engine import OcrEngineService
from app.i18n import t
from app.ui import style
from app.ui.screenshot_annotations import ScreenshotAnnotation, ScreenshotTool

OVERLAY_ALPHA = 80
BORDER_WIDTH = 2
HANDLE_RADIUS = 6
SELECTION_ACCENT = QColor("#3388FF")
ANNOTATION_COLORS = (
    "#FF4D4F",
    "#FFC53D",
    "#3388FF",
    "#52C41A",
    "#FFFFFF",
)
ANNOTATION_WIDTHS = (2.0, 4.0, 7.0)
RESIZE_MARGIN = 8  # pixels from edge that trigger resize cursor


def _toolbar_style(theme: dict) -> str:
    """根据主题构造工具栏 / OCR 面板 QSS。"""
    return f"""
    #snipToolbar, #ocrPanel {{
        background: {theme["surface_solid"]};
        border-radius: 8px;
        border: 1px solid {theme["border_solid"]};
    }}
    #snipToolbar {{
        background: rgba(18, 20, 23, 0.97);
        border: 1px solid #3388FF;
        border-radius: 4px;
    }}
    #snipProperties {{
        background: rgba(18, 20, 23, 0.98);
        border: 1px solid #3388FF;
        border-radius: 4px;
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
    #snipToolbar QToolButton, #snipProperties QToolButton {{
        background: transparent;
        border: none;
        border-radius: 5px;
        color: #F5F7FA;
        padding: 4px;
    }}
    #snipToolbar QToolButton:hover, #snipProperties QToolButton:hover {{
        background: rgba(255, 255, 255, 0.10);
    }}
    #snipToolbar QToolButton:checked {{
        background: #3388FF;
    }}
    #snipProperties QToolButton:checked {{
        background: rgba(51, 136, 255, 0.30);
        border: 1px solid #3388FF;
    }}
    #snipToolbar QToolButton:disabled {{
        color: #747A82;
    }}
    #snipToolbar QLabel, #snipProperties QLabel {{
        color: #C5C8CC;
        font-size: 12px;
        background: transparent;
    }}
    #snipToolbar QLineEdit, #snipToolbar QSpinBox,
    #snipProperties QLineEdit, #snipProperties QSpinBox {{
        color: {theme["text"]};
        background: {theme["surface_raised"]};
        border: 1px solid {theme["border_solid"]};
        border-radius: 4px;
        padding: 3px 6px;
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

    def __init__(
        self,
        parent=None,
        *,
        ocr_engine_service: OcrEngineService,
    ):
        super().__init__(parent)
        self._ocr_engine_service = ocr_engine_service
        # Snapshot theme so toolbar, OCR panel and selection accents all match
        # the active app theme.
        self._theme = style.get_current_theme()
        self._toolbar_qss = _toolbar_style(self._theme)
        self._start = QPoint()
        self._end = QPoint()
        self._state = "IDLE"  # IDLE | DRAGGING | SELECTED | RESIZING | OCR_EDIT
        self._guide_opacity = 0.0
        self._guide_fade = QVariantAnimation(self)
        self._guide_fade.setDuration(240)
        self._guide_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._guide_fade.valueChanged.connect(self._set_guide_opacity)
        # Frozen full-desktop snapshot. Captured the instant the overlay opens
        # and painted as the background, so selection happens on a still image —
        # transient UI (menus/tooltips/video frames) stays exactly as the user
        # framed it instead of changing under a live, see-through overlay.
        self._frozen: QPixmap = QPixmap()
        self._toolbar: QFrame | None = None
        self._property_bar: QFrame | None = None
        self._ocr_panel: QFrame | None = None
        self._ocr_edit: QTextEdit | None = None
        self._tool_buttons: dict[ScreenshotTool, QToolButton] = {}
        self._color_buttons: dict[str, QToolButton] = {}
        self._width_buttons: dict[float, QToolButton] = {}
        self._font_size_label: QLabel | None = None
        self._font_size_spin: QSpinBox | None = None
        self._undo_btn: QToolButton | None = None
        self._redo_btn: QToolButton | None = None
        self._active_tool: ScreenshotTool | None = None
        self._annotation_color = QColor(ANNOTATION_COLORS[0])
        self._annotation_width = ANNOTATION_WIDTHS[1]
        self._annotation_font_size = 20
        self._annotations: list[ScreenshotAnnotation] = []
        self._redo_annotations: list[ScreenshotAnnotation] = []
        self._draft_annotation: ScreenshotAnnotation | None = None
        self._next_number = 1
        self._text_editor: QLineEdit | None = None
        self._text_editor_pos = QPoint()
        self._dragging_panel = False
        self._panel_drag_offset = QPoint()
        # Resize state
        self._resize_edge: str = ""  # "N","S","E","W","NW","NE","SW","SE"
        self._resize_start_mouse = QPoint()
        self._resize_start_rect = QRect()
        self._resize_cursor_shape: Qt.CursorShape | None = None
        self._resize_annotation_snapshot: list[
            tuple[ScreenshotAnnotation, list[QPoint]]
        ] = []

        self._setup_window()
        self._capture_frozen()
        self._ocr_done.connect(self._on_ocr_ready)

    # ── Window ─────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

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

    def _update_hover_cursor(self, pos: QPoint) -> None:
        if self._is_on_panel(pos):
            self._clear_resize_cursor()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._state == "SELECTED":
            edge = self._edge_at(pos) if self._draft_annotation is None else ""
            if edge:
                self._set_resize_cursor(self._EDGE_CURSORS[edge])
                return
            self._clear_resize_cursor()
            inside = self._normalized_rect_local().contains(pos)
            self.setCursor(
                Qt.CursorShape.CrossCursor if inside else Qt.CursorShape.ArrowCursor
            )

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
        # Convert to QImage before cropping to match the paste path encoding
        # and avoid GPU-specific metadata that may confuse vision APIs.
        image = self._frozen.toImage()
        cropped_image = image.copy(src)
        # Convert back to QPixmap for display (keeps interface unchanged)
        piece = QPixmap.fromImage(cropped_image)
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
        self._toolbar.setCursor(Qt.CursorShape.ArrowCursor)
        self._toolbar.setObjectName("snipToolbar")
        self._toolbar.setStyleSheet(self._toolbar_qss)
        self._toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        root = QVBoxLayout(self._toolbar)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(2)
        root.addLayout(main_row)

        tool_specs = (
            (ScreenshotTool.RECTANGLE, t("screenshot.tool.rectangle"), "R"),
            (ScreenshotTool.ELLIPSE, t("screenshot.tool.ellipse"), "O"),
            (ScreenshotTool.ARROW, t("screenshot.tool.arrow"), "A"),
            (ScreenshotTool.PEN, t("screenshot.tool.pen"), "P"),
            (ScreenshotTool.HIGHLIGHTER, t("screenshot.tool.highlighter"), "H"),
            (ScreenshotTool.TEXT, t("screenshot.tool.text"), "T"),
            (ScreenshotTool.NUMBER, t("screenshot.tool.number"), "N"),
        )
        for tool, label, shortcut in tool_specs:
            btn = self._make_tool_button(
                tool.value,
                f"{label} ({shortcut})",
            )
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _checked=False, current=tool: self._on_tool_clicked(current)
            )
            self._tool_buttons[tool] = btn
            main_row.addWidget(btn)

        main_row.addWidget(self._separator())

        ocr_btn = self._make_tool_button(
            "ocr",
            t("screenshot.localOcrTooltip"),
        )
        ocr_btn.clicked.connect(lambda: self._on_action("ocr"))
        main_row.addWidget(ocr_btn)

        ai_btn = self._make_tool_button(
            "ai",
            t("screenshot.aiTooltip"),
            text=t("screenshot.ai"),
            text_beside=True,
        )
        ai_menu = QMenu(ai_btn)
        from app.ui.vision_actions import VISION_ACTIONS

        for action in VISION_ACTIONS:
            item = QAction(
                self._toolbar_icon("ai"),
                action.label,
                ai_menu,
            )
            item.triggered.connect(
                lambda _checked=False, action_id=action.action_id: self._on_action(
                    action_id
                )
            )
            ai_menu.addAction(item)
        ai_btn.setMenu(ai_menu)
        ai_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        main_row.addWidget(ai_btn)

        main_row.addWidget(self._separator())

        self._undo_btn = self._make_tool_button(
            "undo",
            f"{t('screenshot.tool.undo')} (Ctrl+Z)",
        )
        self._undo_btn.clicked.connect(self._undo_annotation)
        main_row.addWidget(self._undo_btn)
        self._redo_btn = self._make_tool_button(
            "redo",
            f"{t('screenshot.tool.redo')} (Ctrl+Y)",
        )
        self._redo_btn.clicked.connect(self._redo_annotation)
        main_row.addWidget(self._redo_btn)
        self._update_history_buttons()

        main_row.addWidget(self._separator())

        for action, icon, label in (
            ("pin", "pin", t("screenshot.pin")),
            ("copy", "copy", t("screenshot.copy")),
            ("save", "save", t("screenshot.save")),
            ("cancel", "close", t("screenshot.cancel")),
        ):
            btn = self._make_tool_button(icon, label)
            btn.clicked.connect(
                lambda _checked=False, current=action: self._on_action(current)
            )
            main_row.addWidget(btn)

        self._property_bar = QFrame(self)
        self._property_bar.setCursor(Qt.CursorShape.ArrowCursor)
        self._property_bar.setObjectName("snipProperties")
        self._property_bar.setStyleSheet(self._toolbar_qss)
        self._property_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        property_row = QHBoxLayout(self._property_bar)
        property_row.setContentsMargins(7, 4, 7, 4)
        property_row.setSpacing(5)
        for color in ANNOTATION_COLORS:
            btn = QToolButton(self._property_bar)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(30, 30)
            btn.setToolTip(t("screenshot.tool.color", value=color))
            btn.setIcon(self._color_icon(color))
            btn.setIconSize(QSize(22, 22))
            btn.clicked.connect(
                lambda _checked=False, value=color: self._set_annotation_color(value)
            )
            self._color_buttons[color] = btn
            property_row.addWidget(btn)

        property_row.addWidget(self._separator(self._property_bar))
        for width in ANNOTATION_WIDTHS:
            btn = QToolButton(self._property_bar)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(30, 30)
            btn.setToolTip(t("screenshot.tool.width", value=f"{width:g}"))
            btn.setIcon(self._width_icon(width))
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(
                lambda _checked=False, value=width: self._set_annotation_width(value)
            )
            self._width_buttons[width] = btn
            property_row.addWidget(btn)

        self._font_size_label = QLabel(
            t("screenshot.tool.fontSize"),
            self._property_bar,
        )
        property_row.addWidget(self._font_size_label)
        self._font_size_spin = QSpinBox(self._property_bar)
        self._font_size_spin.setRange(10, 72)
        self._font_size_spin.setValue(self._annotation_font_size)
        self._font_size_spin.setFixedWidth(58)
        self._font_size_spin.valueChanged.connect(self._set_annotation_font_size)
        property_row.addWidget(self._font_size_spin)
        property_row.addStretch()
        self._property_bar.hide()
        self._property_bar.installEventFilter(self)
        self._update_annotation_property_buttons()

        self._resize_toolbar()
        self._toolbar.installEventFilter(self)
        self._toolbar.show()
        self._toolbar.raise_()
        QTimer.singleShot(0, self._position_toolbar)

    def _make_tool_button(
        self,
        icon_name: str,
        tooltip: str,
        *,
        text: str = "",
        text_beside: bool = False,
    ) -> QToolButton:
        button = QToolButton(self._toolbar)
        button.setIcon(self._toolbar_icon(icon_name))
        button.setIconSize(QSize(22, 22))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if text_beside:
            button.setText(text)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setMinimumWidth(60)
            button.setFixedHeight(36)
        else:
            button.setFixedSize(34, 36)
        return button

    @staticmethod
    def _toolbar_icon(name: str) -> QIcon:
        pixpin_action = name in ("undo", "redo", "pin")
        # Keep these thin outlines sharp on scaled Windows displays.
        scale = 3 if pixpin_action else 1
        pixmap = QPixmap(24 * scale, 24 * scale)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        glyph = ""
        p.setBrush(Qt.BrushStyle.NoBrush)

        if name == "rectangle":
            path.addRect(4, 5, 16, 14)
        elif name == "ellipse":
            path.addEllipse(4, 5, 16, 14)
        elif name == "arrow":
            path.moveTo(5, 19)
            path.lineTo(19, 5)
            path.lineTo(12, 6)
            path.moveTo(19, 5)
            path.lineTo(18, 12)
        elif name == "pen":
            path.moveTo(4, 19)
            path.lineTo(7, 14)
            path.lineTo(17, 4)
            path.lineTo(21, 8)
            path.lineTo(11, 18)
            path.closeSubpath()
            path.moveTo(7, 14)
            path.lineTo(11, 18)
        elif name == "highlighter":
            path.moveTo(5, 15)
            path.lineTo(14, 6)
            path.lineTo(19, 11)
            path.lineTo(10, 20)
            path.lineTo(5, 19)
            path.closeSubpath()
            path.moveTo(8, 18)
            path.lineTo(16, 10)
        elif name == "text":
            glyph = "T"
        elif name == "number":
            path.addEllipse(3, 3, 18, 18)
            glyph = "1"
        elif name in ("undo", "redo"):
            path.arcMoveTo(4, 4, 16, 16, 145)
            path.arcTo(4, 4, 16, 16, 145, -280)
            path.moveTo(5, 3.5)
            path.lineTo(5, 8)
            path.lineTo(9.5, 8)
            if name == "redo":
                mirrored = QTransform()
                mirrored.translate(24, 0)
                mirrored.scale(-1, 1)
                path = mirrored.map(path)
        elif name == "ocr":
            path.addRect(4, 5, 16, 14)
            glyph = "T"
        elif name == "ai":
            path.moveTo(12, 3)
            path.lineTo(12, 9)
            path.moveTo(12, 15)
            path.lineTo(12, 21)
            path.moveTo(3, 12)
            path.lineTo(9, 12)
            path.moveTo(15, 12)
            path.lineTo(21, 12)
            path.moveTo(6, 6)
            path.lineTo(9, 9)
            path.moveTo(15, 15)
            path.lineTo(18, 18)
            path.moveTo(18, 6)
            path.lineTo(15, 9)
            path.moveTo(9, 15)
            path.lineTo(6, 18)
        elif name == "pin":
            path.moveTo(15, 3)
            path.lineTo(21, 9)
            path.lineTo(18, 9)
            path.lineTo(14, 16)
            path.lineTo(14.5, 20)
            path.lineTo(10.5, 16.5)
            path.lineTo(3, 22)
            path.lineTo(8, 14)
            path.lineTo(4.5, 10)
            path.lineTo(8.5, 10.5)
            path.lineTo(15, 6)
            path.closeSubpath()
        elif name == "copy":
            path.addRect(4, 4, 11, 11)
            path.addRect(9, 9, 11, 11)
        elif name == "save":
            path.moveTo(12, 3)
            path.lineTo(12, 15)
            path.moveTo(8, 11)
            path.lineTo(12, 15)
            path.lineTo(16, 11)
            path.moveTo(4, 16)
            path.lineTo(4, 20)
            path.lineTo(20, 20)
            path.lineTo(20, 16)
        elif name == "close":
            path.moveTo(5, 5)
            path.lineTo(19, 19)
            path.moveTo(19, 5)
            path.lineTo(5, 19)

        glow = QPen(QColor(110, 183, 255, 30), 2.8)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(glow)
        if name == "ocr":
            glow.setStyle(Qt.PenStyle.DashLine)
            p.setPen(glow)
        if not pixpin_action:
            p.drawPath(path)

        stroke = QPen(QColor("#ECECEC" if pixpin_action else "#F4F8FF"), 1.65)
        stroke.setCapStyle(
            Qt.PenCapStyle.SquareCap if pixpin_action else Qt.PenCapStyle.RoundCap
        )
        stroke.setJoinStyle(
            Qt.PenJoinStyle.MiterJoin if pixpin_action else Qt.PenJoinStyle.RoundJoin
        )
        if name == "ocr":
            stroke.setStyle(Qt.PenStyle.DashLine)
        p.setPen(stroke)
        p.drawPath(path)

        if glyph:
            font = QFont()
            font.setPixelSize(17 if name == "text" else 11)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor("#F4F8FF"))
            p.drawText(
                QRect(3, 2, 18, 20),
                Qt.AlignmentFlag.AlignCenter,
                glyph,
            )
        p.end()
        icon = QIcon(pixmap)
        if name in ("undo", "redo"):
            disabled = QPixmap(pixmap.size())
            disabled.setDevicePixelRatio(scale)
            disabled.fill(Qt.GlobalColor.transparent)
            painter = QPainter(disabled)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            stroke.setColor(QColor("#858585"))
            painter.setPen(stroke)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.end()
            icon.addPixmap(disabled, QIcon.Mode.Disabled)
        return icon

    @staticmethod
    def _color_icon(color: str) -> QIcon:
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 190), 1.0))
        p.setBrush(QColor(color))
        p.drawRect(1, 1, 20, 20)
        p.end()
        return QIcon(pixmap)

    @staticmethod
    def _width_icon(width: float) -> QIcon:
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#F5F7FA"), max(1.0, width)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPoint(4, 10), QPoint(16, 10))
        p.end()
        return QIcon(pixmap)

    def _separator(self, parent: QWidget | None = None) -> QFrame:
        line = QFrame(parent or self._toolbar)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet(
            "border: none; background: rgba(255,255,255,0.18);"
        )
        return line

    def _resize_toolbar(self) -> None:
        if self._toolbar is None:
            return
        hint = self._toolbar.sizeHint()
        self._toolbar.setFixedSize(
            max(hint.width(), 200),
            max(hint.height(), 44),
        )
        if self._property_bar is not None:
            self._property_bar.adjustSize()

    def _on_tool_clicked(self, tool: ScreenshotTool) -> None:
        if self._active_tool is tool:
            self._deactivate_tool()
            return
        self._finish_text_edit()
        self._guide_fade.stop()
        self._set_guide_opacity(0.0)
        self._active_tool = tool
        for current, button in self._tool_buttons.items():
            button.setChecked(current is tool)
        if self._property_bar is not None:
            self._property_bar.show()
        self._update_annotation_property_buttons()
        self._resize_toolbar()
        self._update_hover_cursor(self.mapFromGlobal(QCursor.pos()))
        self.update()
        QTimer.singleShot(0, self._position_toolbar)

    def _deactivate_tool(self) -> None:
        self._finish_text_edit()
        self._active_tool = None
        self._draft_annotation = None
        for button in self._tool_buttons.values():
            button.setChecked(False)
        if self._property_bar is not None:
            self._property_bar.hide()
        self._resize_toolbar()
        self._update_hover_cursor(self.mapFromGlobal(QCursor.pos()))
        self.update()
        QTimer.singleShot(0, self._position_toolbar)

    def _update_annotation_property_buttons(self) -> None:
        for color, button in self._color_buttons.items():
            button.setChecked(
                QColor(color).rgb() == self._annotation_color.rgb()
            )
            button.setStyleSheet(
                "QToolButton { border: 1px solid rgba(255,255,255,0.25);"
                " border-radius: 3px; }"
                "QToolButton:checked { border: 2px solid #FFFFFF;"
                " background: rgba(51,136,255,0.30); }"
            )
        for width, button in self._width_buttons.items():
            button.setChecked(abs(width - self._annotation_width) < 0.01)
            button.setStyleSheet(
                "QToolButton { border: 1px solid transparent;"
                " border-radius: 3px; }"
                "QToolButton:checked { border: 1px solid #FFFFFF;"
                " background: rgba(51,136,255,0.45); }"
            )
        is_text = self._active_tool is ScreenshotTool.TEXT
        if self._font_size_label is not None:
            self._font_size_label.setVisible(is_text)
        if self._font_size_spin is not None:
            self._font_size_spin.setVisible(is_text)

    def _set_annotation_color(self, color: str) -> None:
        self._annotation_color = QColor(color)
        self._update_annotation_property_buttons()

    def _set_annotation_width(self, width: float) -> None:
        self._annotation_width = width
        self._update_annotation_property_buttons()

    def _set_annotation_font_size(self, size: int) -> None:
        self._annotation_font_size = size

    def _undo_annotation(self) -> None:
        if not self._annotations:
            return
        self._redo_annotations.append(self._annotations.pop())
        self._update_history_buttons()
        self.update()

    def _redo_annotation(self) -> None:
        if not self._redo_annotations:
            return
        self._annotations.append(self._redo_annotations.pop())
        self._update_history_buttons()
        self.update()

    def _update_history_buttons(self) -> None:
        if self._undo_btn is not None:
            self._undo_btn.setEnabled(bool(self._annotations))
        if self._redo_btn is not None:
            self._redo_btn.setEnabled(bool(self._redo_annotations))

    def _local_annotation_point(self, pos: QPoint) -> QPoint | None:
        rect = self._normalized_rect_local()
        if not rect.isValid() or not rect.contains(pos):
            return None
        return QPoint(pos.x() - rect.left(), pos.y() - rect.top())

    def _begin_annotation(self, pos: QPoint) -> None:
        tool = self._active_tool
        if tool is None:
            return
        local = self._local_annotation_point(pos)
        if local is None:
            return

        if tool is ScreenshotTool.TEXT:
            self._begin_text_edit(pos, local)
            return
        if tool is ScreenshotTool.NUMBER:
            self._annotations.append(
                ScreenshotAnnotation(
                    tool=tool,
                    points=[local],
                    color=QColor(self._annotation_color),
                    width=self._annotation_width,
                    text=str(self._next_number),
                )
            )
            self._next_number += 1
            self._redo_annotations.clear()
            self._update_history_buttons()
            self.update()
            return

        self._draft_annotation = ScreenshotAnnotation(
            tool=tool,
            points=[local, QPoint(local)],
            color=QColor(self._annotation_color),
            width=self._annotation_width,
            font_size=self._annotation_font_size,
        )

    def _update_annotation_drag(self, pos: QPoint) -> None:
        draft = self._draft_annotation
        if draft is None:
            return
        local = self._local_annotation_point(pos)
        if local is None:
            rect = self._normalized_rect_local()
            local = QPoint(
                min(max(pos.x(), rect.left()), rect.right()) - rect.left(),
                min(max(pos.y(), rect.top()), rect.bottom()) - rect.top(),
            )
        if draft.tool in (ScreenshotTool.PEN, ScreenshotTool.HIGHLIGHTER):
            if draft.points[-1] != local:
                draft.points.append(local)
        else:
            draft.points[-1] = local
        self.update()

    def _finish_annotation_drag(self) -> None:
        draft = self._draft_annotation
        self._draft_annotation = None
        if draft is None:
            return
        if draft.tool in (ScreenshotTool.RECTANGLE, ScreenshotTool.ELLIPSE):
            rect = QRect(draft.points[0], draft.points[-1]).normalized()
            valid = rect.width() >= 3 and rect.height() >= 3
        else:
            start = draft.points[0]
            end = draft.points[-1]
            valid = abs(start.x() - end.x()) + abs(start.y() - end.y()) >= 3
        if valid:
            self._annotations.append(draft)
            self._redo_annotations.clear()
            self._update_history_buttons()
        self.update()

    def _begin_text_edit(self, pos: QPoint, local: QPoint) -> None:
        self._finish_text_edit()
        editor = QLineEdit(self)
        editor.setObjectName("annotationTextEditor")
        editor.setPlaceholderText(t("screenshot.tool.textPlaceholder"))
        editor.setStyleSheet(
            "QLineEdit { color: white; background: rgba(30,30,30,0.94);"
            " border: 1px solid #3388FF; border-radius: 4px;"
            " padding: 3px 6px; font-size: 14px; }"
        )
        width = min(260, max(120, self.width() - pos.x() - 8))
        editor.setFixedSize(width, 32)
        x = min(pos.x(), self.width() - width - 4)
        y = min(max(0, pos.y()), self.height() - 36)
        editor.move(x, y)
        self._text_editor = editor
        self._text_editor_pos = local
        editor.returnPressed.connect(self._finish_text_edit)
        editor.editingFinished.connect(self._finish_text_edit)
        editor.show()
        editor.setFocus()

    def _finish_text_edit(self) -> None:
        editor = self._text_editor
        if editor is None:
            return
        self._text_editor = None
        text = editor.text().strip()
        editor.hide()
        editor.deleteLater()
        if not text:
            return
        self._annotations.append(
            ScreenshotAnnotation(
                tool=ScreenshotTool.TEXT,
                points=[QPoint(self._text_editor_pos)],
                color=QColor(self._annotation_color),
                width=self._annotation_width,
                text=text,
                font_size=self._annotation_font_size,
            )
        )
        self._redo_annotations.clear()
        self._update_history_buttons()
        self.update()

    def _annotated_crop(self, rect: QRect) -> QPixmap:
        """Crop the frozen image and bake annotations into physical pixels."""
        pixmap = self._crop_frozen(rect)
        if not self._annotations or pixmap.isNull():
            return pixmap
        image = pixmap.toImage()
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sx = image.width() / max(1, rect.width())
        sy = image.height() / max(1, rect.height())
        p.scale(sx, sy)
        for annotation in self._annotations:
            annotation.draw(p)
        p.end()
        result = QPixmap.fromImage(image)
        result.setDevicePixelRatio(pixmap.devicePixelRatio())
        return result

    def _position_toolbar(self):
        self._position_panel(self._toolbar)
        if self._property_bar is None or not self._property_bar.isVisible():
            return
        toolbar = self._toolbar.geometry() if self._toolbar else QRect()
        selection = self._normalized_rect_local()
        gap = 6
        property_height = self._property_bar.height()
        if selection.isValid() and toolbar.top() >= selection.bottom():
            y = toolbar.bottom() + gap
        else:
            y = toolbar.top() - property_height - gap
        x = max(6, min(toolbar.left(), self.width() - self._property_bar.width() - 6))
        self._property_bar.move(int(x), int(max(6, y)))
        self._property_bar.raise_()

    def _position_panel(self, panel: QFrame | None):
        """Position *panel* near the selection, preferring below."""
        r = self._normalized_rect_local()
        if not r.isValid() or not panel:
            return
        tw = panel.width()
        th = panel.height()
        margin = 6

        x = r.left()
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
        self._finish_text_edit()
        self._active_tool = None
        self._draft_annotation = None
        self._tool_buttons.clear()
        self._color_buttons.clear()
        self._width_buttons.clear()
        self._undo_btn = None
        self._redo_btn = None
        self._font_size_label = None
        self._font_size_spin = None
        if self._property_bar:
            self._property_bar.hide()
            self._property_bar.deleteLater()
            self._property_bar = None
        if self._toolbar:
            self._toolbar.hide()
            self._toolbar.deleteLater()
            self._toolbar = None

    def _cancel_capture(self):
        """Close the screenshot overlay without requiring Esc or right-click."""
        self._clear_resize_cursor()
        self.hide()
        self.captured.emit(QPixmap(), "cancel", "", QPoint())
        self.close()

    def _on_action(self, action: str):
        self._clear_resize_cursor()
        if action == "cancel":
            self._cancel_capture()
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
        self._finish_text_edit()
        pixmap = self._annotated_crop(r)
        self.hide()
        # Hide the topmost overlay before the synchronous consumer runs. The
        # save action opens a modal native file dialog; emitting first leaves
        # that dialog behind the fullscreen overlay while it holds focus.
        self.captured.emit(pixmap, action, "", QPoint(r.topLeft()))
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
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._show_ocr_panel(t("screenshot.ocr.recognizing"))

        def _worker():
            try:
                text = self._run_ocr_from_array(bgr)
            except Exception as e:
                text = t("screenshot.ocr.error", error=e)
            self._ocr_done.emit(text)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_ocr_from_array(self, bgr) -> str:
        """Run OCR on a BGR numpy array. Safe to call from any thread."""
        try:
            engine = self._ocr_engine_service.get_engine()
            result, _ = engine(bgr)
            if result:
                return _reconstruct_layout(result).strip() or t("screenshot.ocr.empty")
            return t("screenshot.ocr.empty")
        except Exception as e:
            return t("screenshot.ocr.error", error=e)

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
        self._ocr_panel.setCursor(Qt.CursorShape.ArrowCursor)
        self._ocr_panel.setObjectName("ocrPanel")
        self._ocr_panel.setStyleSheet(self._toolbar_qss)
        self._ocr_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        root = QVBoxLayout(self._ocr_panel)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel(t("screenshot.ocr.panelTitle"))
        title.setStyleSheet(
            f"color: {self._theme['text_secondary']}; font-size: 12px;"
            "background: transparent; border: none;"
        )
        header.addWidget(title)
        header.addStretch()

        cancel_btn = QPushButton(t("screenshot.cancel"))
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
        close_btn = QPushButton(t("common.close"))
        close_btn.setObjectName("ocrCloseBtn")
        close_btn.clicked.connect(lambda: (self.captured.emit(QPixmap(), "cancel", "", QPoint()), self.close()))
        footer.addWidget(close_btn)
        confirm_btn = QPushButton(t("screenshot.ocr.copyAndClose"))
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
                    t("screenshot.selectHint"),
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

            is_dragging = self._state == "DRAGGING"
            if self._state in ("DRAGGING", "RESIZING") or (
                self._active_tool is None and self._guide_opacity > 0
            ):
                self._draw_center_guides(p, r_local)

            p.save()
            p.setClipRect(r_local)
            p.translate(r_local.left(), r_local.top())
            for annotation in self._annotations:
                annotation.draw(p)
            if self._draft_annotation is not None:
                self._draft_annotation.draw(p)
            p.restore()

            # ── Selection border ──
            border_w = 3 if is_dragging else BORDER_WIDTH
            border_pen = QPen(SELECTION_ACCENT, border_w)
            border_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(border_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Inset by half the pen width so it sits inside the selection
            off = border_w / 2.0
            p.drawRect(r_local.toRectF().adjusted(off, off, -off, -off))

            # ── Corner and edge-midpoint handles ──
            self._draw_handles(p, r_local)

            # ── Size label ──
            self._draw_size_label(p, r_local)
        else:
            p.fillRect(self.rect(), overlay)

    def _set_guide_opacity(self, value: float) -> None:
        self._guide_opacity = float(value)
        self.update()

    def _show_center_guides(self) -> None:
        self._guide_fade.stop()
        self._set_guide_opacity(1.0)

    def _fade_center_guides(self) -> None:
        self._guide_fade.stop()
        self._guide_fade.setStartValue(self._guide_opacity)
        self._guide_fade.setEndValue(0.0)
        self._guide_fade.start()

    def _draw_center_guides(self, p: QPainter, r: QRect):
        """Draw the full-screen dashed cross through the selection center."""
        p.save()
        color = QColor("#83B9FF")
        color.setAlpha(round(150 * self._guide_opacity))
        pen = QPen(color, 1, Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([5, 5])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        center = r.center()
        p.drawLine(center.x(), 0, center.x(), self.height())
        p.drawLine(0, center.y(), self.width(), center.y())
        p.restore()

    def _draw_handles(self, p: QPainter, r: QRect):
        """Draw circular handles at all four corners and edge midpoints."""
        points = (
            r.topLeft(),
            QPoint(r.center().x(), r.top()),
            r.topRight(),
            QPoint(r.left(), r.center().y()),
            QPoint(r.right(), r.center().y()),
            r.bottomLeft(),
            QPoint(r.center().x(), r.bottom()),
            r.bottomRight(),
        )
        p.setPen(QPen(SELECTION_ACCENT, 2))
        p.setBrush(SELECTION_ACCENT)
        for point in points:
            p.drawEllipse(QPointF(point), HANDLE_RADIUS, HANDLE_RADIUS)

    def _draw_size_label(self, p: QPainter, r: QRect):
        dpr = max(1.0, self._frozen.devicePixelRatio())
        origin = self.mapToGlobal(r.topLeft())
        label = self._format_pixel_label(origin, r, dpr)
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(label) + 20
        text_h = fm.height() + 12

        label_x = r.left()
        label_y = r.top() - text_h
        if label_y < 0:
            label_y = r.top() + 4
        if label_x + text_w > self.width():
            label_x = self.width() - text_w - 4

        label_rect = QRect(int(label_x), int(label_y), text_w, text_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 16, 19, 242))
        p.drawRect(label_rect)
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(label_rect.adjusted(0, 0, -1, -1))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(
            label_rect.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )

    @staticmethod
    def _format_pixel_label(origin: QPoint, rect: QRect, dpr: float) -> str:
        x = round(origin.x() * dpr)
        y = round(origin.y() * dpr)
        width = round(rect.width() * dpr)
        height = round(rect.height() * dpr)
        return f"{x},{y}  {width} × {height} px"

    # ── Mouse ──────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        # The resize cursor is a *global* override (QApplication.setOverrideCursor).
        # When the pointer crosses straight from the selection edge onto the
        # toolbar/panel, the overlay stops getting mouseMove events, so the
        # override never gets cleared and the resize cursor sticks on the
        # buttons. Clear it the moment the pointer enters a panel.
        if event.type() == QEvent.Type.Enter and obj in (
            self._toolbar,
            self._property_bar,
            self._ocr_panel,
        ):
            self._clear_resize_cursor()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        return super().eventFilter(obj, event)

    def _is_on_panel(self, pos) -> bool:
        for panel in (self._toolbar, self._property_bar, self._ocr_panel):
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
                self._finish_text_edit()
                edge = self._edge_at(pos)
                if edge:
                    self._resize_edge = edge
                    self._resize_start_mouse = gpos
                    self._resize_start_rect = self._normalized_rect()
                    self._resize_annotation_snapshot = [
                        (
                            annotation,
                            [QPoint(point) for point in annotation.points],
                        )
                        for annotation in self._annotations
                    ]
                    self._state = "RESIZING"
                    self._show_center_guides()
                    self._set_resize_cursor(self._EDGE_CURSORS[edge])
                    return
                if not self._normalized_rect_local().contains(pos):
                    self._cancel_capture()
                    return
                if self._active_tool is not None:
                    self._begin_annotation(pos)
                    return
                # With no annotation tool active, clicking inside starts a new
                # selection while retaining the previous annotation history.

            self._clear_resize_cursor()
            self._hide_toolbar()
            self._hide_ocr_panel()
            if self._state == "SELECTED":
                self._annotations.clear()
                self._redo_annotations.clear()
                self._next_number = 1
                self._update_history_buttons()
            self._start = event.globalPosition().toPoint()
            self._end = self._start
            self._state = "DRAGGING"
            self.setCursor(Qt.CursorShape.CrossCursor)
            self._show_center_guides()
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            if self._is_on_panel(pos):
                # Allow context menu inside the panel (e.g. text selection)
                super().mousePressEvent(event)
                return
            self._cancel_capture()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._draft_annotation is not None:
            self._update_hover_cursor(event.position().toPoint())
            self._update_annotation_drag(event.position().toPoint())
            return

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

        # Use an arrow outside the selection and on panels, while retaining
        # crosshair and resize cursors where the capture can be edited.
        if self._state == "SELECTED":
            self._update_hover_cursor(event.position().toPoint())

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
        new_rect = QRect(self._start, self._end).normalized()
        dx = self._resize_start_rect.left() - new_rect.left()
        dy = self._resize_start_rect.top() - new_rect.top()
        for annotation, original_points in self._resize_annotation_snapshot:
            annotation.points = [
                QPoint(point.x() + dx, point.y() + dy)
                for point in original_points
            ]
        self.update()
        # Reposition toolbar without recreating it
        QTimer.singleShot(0, self._position_toolbar)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._draft_annotation is not None:
                self._finish_annotation_drag()
                return
            if self._dragging_panel:
                self._dragging_panel = False
                return
            if self._state == "RESIZING":
                self._clear_resize_cursor()
                self._state = "SELECTED"
                self._resize_edge = ""
                self._resize_annotation_snapshot = []
                self._fade_center_guides()
                self._update_hover_cursor(event.position().toPoint())
                self.update()
                # Reposition toolbar after resize
                QTimer.singleShot(0, self._position_toolbar)
                return
            if self._state == "DRAGGING":
                self._end = event.globalPosition().toPoint()
                if self._has_selection():
                    self._state = "SELECTED"
                    self._fade_center_guides()
                    self.update()
                    self._show_toolbar()
                    self._update_hover_cursor(event.position().toPoint())
                else:
                    # A plain left click without a drag is an explicit cancel.
                    self._cancel_capture()

    # ── Keyboard ───────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self._redo_annotation()
                else:
                    self._undo_annotation()
                return
            if event.key() == Qt.Key.Key_Y:
                self._redo_annotation()
                return

        tool_shortcuts = {
            Qt.Key.Key_R: ScreenshotTool.RECTANGLE,
            Qt.Key.Key_O: ScreenshotTool.ELLIPSE,
            Qt.Key.Key_A: ScreenshotTool.ARROW,
            Qt.Key.Key_P: ScreenshotTool.PEN,
            Qt.Key.Key_H: ScreenshotTool.HIGHLIGHTER,
            Qt.Key.Key_T: ScreenshotTool.TEXT,
            Qt.Key.Key_N: ScreenshotTool.NUMBER,
        }
        if (
            self._state == "SELECTED"
            and self._toolbar is not None
            and not (modifiers & Qt.KeyboardModifier.ControlModifier)
            and event.key() in tool_shortcuts
        ):
            self._on_tool_clicked(tool_shortcuts[event.key()])
            return

        if event.key() == Qt.Key.Key_Escape:
            if self._text_editor is not None:
                self._finish_text_edit()
            elif self._active_tool is not None:
                self._deactivate_tool()
            else:
                self._cancel_capture()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._guide_fade.stop()
        self._clear_resize_cursor()
        super().closeEvent(event)
