"""
Custom sliding toast notifications.

Card colours follow the active app theme (surface / border / text).
New toasts slide in from the bottom-right; older ones push upward.
Click or wait 4 s to dismiss.
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import style

_W          = 300
_H          = 72
_MARGIN     = 20
_GAP        = 10
_IN_MS  = 250
_OUT_MS     = 180


class Toast(QWidget):
    """One toast card.  Manages its own lifetime and stack position."""

    _stack: list["Toast"] = []  # class-level; oldest first, newest last

    def __init__(self, title: str, body: str, accent: str):
        super().__init__(None)
        self._closing = False
        # Snapshot theme colours at creation so paint + children stay consistent.
        theme = style.get_current_theme()
        self._bg = QColor(theme["surface_solid"])
        self._border = QColor(theme["border_solid"])
        self._text = theme["text"]
        self._muted = theme["text_secondary"]
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedSize(_W, _H)

        self._build(title, body, accent)
        Toast._stack.append(self)
        self._enter()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build(self, title: str, body: str, accent: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 9, 9)
        root.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(6)

        dot = QLabel("●")
        dot.setFixedWidth(10)
        dot.setStyleSheet(
            f"color:{accent};font-size:7px;background:transparent;border:none;"
        )
        row.addWidget(dot)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color:{self._text};font-size:13px;font-weight:600;"
            "background:transparent;border:none;"
        )
        row.addWidget(lbl, 1)

        btn = QPushButton("✕")
        btn.setFixedSize(20, 20)
        btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{self._muted};"
            f"border:none;border-radius:4px;font-size:10px;}}"
            f"QPushButton:hover{{background:{self._border.name()};color:{self._text};}}"
        )
        btn.clicked.connect(self._dismiss)
        row.addWidget(btn)
        root.addLayout(row)

        msg = QLabel(body)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color:{self._muted};font-size:12px;background:transparent;"
            "border:none;padding-left:16px;"
        )
        root.addWidget(msg)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().toRectF().adjusted(.5, .5, -.5, -.5), 10, 10)
        p.fillPath(path, self._bg)
        p.setPen(self._border)
        p.drawPath(path)

    def mousePressEvent(self, _):
        self._dismiss()

    # ── Positioning ─────────────────────────────────────────────────────

    @staticmethod
    def _geo():
        return QApplication.primaryScreen().availableGeometry()

    @classmethod
    def _slot_y(cls, idx_from_bottom: int) -> int:
        """Y coordinate for the idx_from_bottom-th slot (0 = lowest / newest)."""
        return cls._geo().bottom() - _MARGIN - (_H + _GAP) * (idx_from_bottom + 1)

    @classmethod
    def _final_x(cls) -> int:
        return cls._geo().right() - _W - _MARGIN

    # ── Animation ───────────────────────────────────────────────────────

    def _enter(self):
        # Push all previous toasts up by one slot
        for i, t in enumerate(reversed(Toast._stack[:-1])):
            _slide_to(t, QPoint(t.x(), Toast._slot_y(i + 1)))

        y = Toast._slot_y(0)
        self.move(Toast._geo().right() + 10, y)
        self.show()
        _slide_to(self, QPoint(Toast._final_x(), y), _IN_MS)

    def _dismiss(self):
        if self._closing:
            return
        self._closing = True
        if self in Toast._stack:
            Toast._stack.remove(self)

        # Shift remaining toasts back down to fill the gap
        for i, t in enumerate(reversed(Toast._stack)):
            _slide_to(t, QPoint(t.x(), Toast._slot_y(i)))

        # Do NOT use DeleteWhenStopped here: combined with finished→deleteLater
        # it schedules two deleteLater events for the same child object, causing
        # a double-free crash.  Let the parent (self) own the animation and clean
        # it up naturally when self is destroyed.
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(_OUT_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()


# ── Helpers ─────────────────────────────────────────────────────────────

def _slide_to(widget: QWidget, pos: QPoint, duration: int = 160):
    a = QPropertyAnimation(widget, b"pos", widget)
    a.setDuration(duration)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.setEndValue(pos)
    a.start()  # parent widget owns and cleans up the animation


def show_toast(title: str, body: str, accent: str | None = None) -> None:
    """Create and display a toast notification.  Must be called on the main thread."""
    if accent is None:
        accent = style.get_current_theme()["accent"]
    Toast(title, body, accent)
