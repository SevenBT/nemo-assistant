"""问题锚点导航轨道。

覆盖在聊天滚动区右侧（滚动条内侧）的竖向圆点轨道，模仿 DeepSeek 的问题导航：
每个用户问题对应一个圆点，在窗口垂直居中位置等距排列（只保留对话顺序）。
鼠标移入轨道即在左侧弹出一个列出全部问题的面板（整体带边框与主题背景），
当前滚动所在项与鼠标悬停项分别高亮，点击面板某行或某个圆点平滑跳转。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from app.ui import style


class _AnchorPanel(QWidget):
    """悬停时弹出的问题列表面板，自绘以完全控制配色（替代黑底 QToolTip）。"""

    row_clicked = pyqtSignal(int)   # 点击某行 → 锚点索引
    entered = pyqtSignal()          # 鼠标进入面板
    left = pyqtSignal()             # 鼠标离开面板

    _ROW_H = 28
    _PAD_V = 8
    _PAD_H = 12
    _RADIUS = 8
    _MAX_W = 220
    _MIN_W = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._texts: list[str] = []
        self._hover_row = -1
        self._active_row = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def set_items(self, texts: list[str], active: int, max_width: int):
        self._texts = texts
        self._active_row = active
        self._hover_row = -1
        self._relayout(max_width)

    def set_active(self, active: int):
        if active != self._active_row:
            self._active_row = active
            self.update()

    def _relayout(self, max_width: int):
        fm = self.fontMetrics()
        cap = max(self._MIN_W, min(self._MAX_W, max_width))
        longest = max((fm.horizontalAdvance(t) for t in self._texts), default=0)
        w = min(cap, longest + 2 * self._PAD_H)
        w = max(self._MIN_W, w)
        h = len(self._texts) * self._ROW_H + 2 * self._PAD_V
        self.resize(w, h)
        self.update()

    # -- 绘制 --------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = style.get_current_theme()
        dark = style._current_dark_mode

        bg = QColor(theme.get("surface_raised", theme.get("surface_solid", "#2A2A2A")))
        border = QColor(theme.get("border_solid", "#3A3A3A"))
        text_color = QColor(theme.get("text", "#E0E0E0"))
        accent = QColor(theme.get("accent", "#888888"))

        # 整体面板：圆角背景 + 边框
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, self._RADIUS, self._RADIUS)

        fm = painter.fontMetrics()
        avail_w = self.width() - 2 * self._PAD_H
        for i, text in enumerate(self._texts):
            top = self._PAD_V + i * self._ROW_H
            row_rect = QRectF(
                4, top, self.width() - 8, self._ROW_H
            )
            is_hover = i == self._hover_row
            is_active = i == self._active_row

            if is_hover:
                hl = QColor(accent)
                hl.setAlpha(40 if dark else 32)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(hl)
                painter.drawRoundedRect(row_rect, 5, 5)

            # 当前项左侧竖条标记
            if is_active:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(6, top + 6, 3, self._ROW_H - 12), 1.5, 1.5)

            painter.setPen(accent if is_active else text_color)
            elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail_w)
            painter.drawText(
                QRectF(self._PAD_H, top, avail_w, self._ROW_H),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                elided,
            )

    # -- 交互 --------------------------------------------------------------

    def _row_at(self, y: int) -> int:
        idx = (y - self._PAD_V) // self._ROW_H
        return idx if 0 <= idx < len(self._texts) else -1

    def mouseMoveEvent(self, event):
        row = self._row_at(event.pos().y())
        if row != self._hover_row:
            self._hover_row = row
            self.update()

    def mousePressEvent(self, event):
        row = self._row_at(event.pos().y())
        if row >= 0:
            self.row_clicked.emit(row)

    def enterEvent(self, _event):
        self.entered.emit()

    def leaveEvent(self, _event):
        if self._hover_row != -1:
            self._hover_row = -1
            self.update()
        self.left.emit()


class AnchorRail(QWidget):
    """问题锚点轨道，作为 viewport 的覆盖子控件。"""

    anchor_clicked = pyqtSignal(QWidget)  # 点击圆点 → 对应气泡
    hover_anchor = pyqtSignal(int)        # 悬停圆点索引变化（-1 表示无）
    entered = pyqtSignal()                # 鼠标移入轨道
    left = pyqtSignal()                   # 鼠标移出轨道

    _WIDTH = 14
    _DOT_R = 3
    _DOT_R_ACTIVE = 4
    _GAP = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        # (气泡 widget, 问题文本) 列表，顺序即对话顺序
        self._anchors: list[tuple[QWidget, str]] = []
        self._dot_ys: list[int] = []
        self._hover_idx = -1
        self._active_idx = -1
        self.setFixedWidth(self._WIDTH)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- 公开 API ----------------------------------------------------------

    def set_anchors(self, anchors: list[tuple[QWidget, str]]):
        self._anchors = list(anchors)
        if self._hover_idx >= len(self._anchors):
            self._hover_idx = -1
        self.setVisible(len(self._anchors) > 0)
        self._recompute()

    def anchors(self) -> list[tuple[QWidget, str]]:
        return self._anchors

    def active_index(self) -> int:
        return self._active_idx

    def refresh(self):
        """滚动位置变化后刷新当前高亮。"""
        self._update_active()
        self.update()

    def relayout(self):
        """轨道尺寸变化后重新居中排列圆点。"""
        self._recompute()

    # -- 布局 --------------------------------------------------------------

    def _recompute(self):
        n = len(self._anchors)
        self._dot_ys = []
        if n:
            total = (n - 1) * self._GAP
            start = self.height() / 2 - total / 2
            self._dot_ys = [int(start + i * self._GAP) for i in range(n)]
        self._update_active()
        self.update()

    def _update_active(self):
        scroll_area = self._scroll_area()
        if scroll_area is None or not self._anchors:
            self._active_idx = -1
            return
        inner = scroll_area.widget()
        sb = scroll_area.verticalScrollBar()
        viewport_top = sb.value()
        active = -1
        for i, (bubble, _) in enumerate(self._anchors):
            by = bubble.mapTo(inner, QPoint(0, 0)).y() if inner else 0
            if by <= viewport_top + 4:
                active = i
            else:
                break
        self._active_idx = active

    def _scroll_area(self):
        vp = self.parent()
        return vp.parent() if vp is not None else None

    # -- 绘制 --------------------------------------------------------------

    def paintEvent(self, _event):
        if not self._dot_ys:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        accent = QColor(style.get_current_theme().get("accent", "#888888"))
        dark = style._current_dark_mode
        idle = QColor(accent)
        idle.setAlpha(90 if dark else 110)
        strong = QColor(accent)
        strong.setAlpha(255)

        cx = self.width() / 2
        for i, y in enumerate(self._dot_ys):
            is_focus = i == self._hover_idx or i == self._active_idx
            r = self._DOT_R_ACTIVE if is_focus else self._DOT_R
            painter.setBrush(strong if is_focus else idle)
            painter.drawEllipse(QRectF(cx - r, y - r, 2 * r, 2 * r))

    # -- 交互 --------------------------------------------------------------

    def _hit_test(self, pos: QPoint) -> int:
        best, best_d = -1, 1e9
        for i, y in enumerate(self._dot_ys):
            d = abs(pos.y() - y)
            if d < best_d:
                best, best_d = i, d
        return best if best_d <= self._GAP / 2 + self._DOT_R_ACTIVE else -1

    def set_hover(self, idx: int):
        """由外部（面板联动）设置高亮圆点。"""
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def enterEvent(self, _event):
        self.entered.emit()

    def mouseMoveEvent(self, event):
        idx = self._hit_test(event.pos())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
            self.hover_anchor.emit(idx)

    def leaveEvent(self, _event):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()
        self.left.emit()

    def mousePressEvent(self, event):
        idx = self._hit_test(event.pos())
        if idx >= 0:
            self.anchor_clicked.emit(self._anchors[idx][0])
