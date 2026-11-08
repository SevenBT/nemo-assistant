"""Annotation model and renderer for screenshot editing."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen


class ScreenshotTool(str, Enum):
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    PEN = "pen"
    HIGHLIGHTER = "highlighter"
    TEXT = "text"
    NUMBER = "number"


@dataclass
class ScreenshotAnnotation:
    """One editable annotation in selection-local logical coordinates."""

    tool: ScreenshotTool
    points: list[QPoint]
    color: QColor = field(default_factory=lambda: QColor("#FF4D4F"))
    width: float = 3.0
    text: str = ""
    font_size: int = 20

    def draw(self, painter: QPainter) -> None:
        if not self.points:
            return

        color = QColor(self.color)
        width = max(1.0, float(self.width))
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        if self.tool is ScreenshotTool.HIGHLIGHTER:
            color.setAlpha(95)
            pen = QPen(color, max(10.0, width * 5.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        elif self.tool is ScreenshotTool.TEXT:
            font = QFont()
            font.setPixelSize(max(10, int(self.font_size)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(self.points[0], self.text)
            return
        elif self.tool is ScreenshotTool.NUMBER:
            self._draw_number(painter, color, width)
            return

        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.tool is ScreenshotTool.RECTANGLE:
            if len(self.points) >= 2:
                painter.drawRect(_rect(self.points[0], self.points[1]))
        elif self.tool is ScreenshotTool.ELLIPSE:
            if len(self.points) >= 2:
                painter.drawEllipse(_rect(self.points[0], self.points[1]))
        elif self.tool is ScreenshotTool.ARROW:
            if len(self.points) >= 2:
                self._draw_arrow(painter, self.points[0], self.points[-1], width)
        elif self.tool in (ScreenshotTool.PEN, ScreenshotTool.HIGHLIGHTER):
            if len(self.points) == 1:
                painter.drawPoint(self.points[0])
            else:
                painter.drawPolyline(self.points)

    def _draw_arrow(
        self,
        painter: QPainter,
        start: QPoint,
        end: QPoint,
        width: float,
    ) -> None:
        painter.drawLine(start, end)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        head = max(10.0, width * 4.0)
        angle = math.atan2(dy, dx)
        spread = math.radians(28)
        left = QPoint(
            round(end.x() - head * math.cos(angle - spread)),
            round(end.y() - head * math.sin(angle - spread)),
        )
        right = QPoint(
            round(end.x() - head * math.cos(angle + spread)),
            round(end.y() - head * math.sin(angle + spread)),
        )
        painter.drawLine(end, left)
        painter.drawLine(end, right)

    def _draw_number(self, painter: QPainter, color: QColor, width: float) -> None:
        center = self.points[0]
        radius = max(10.0, width * 4.0)
        painter.setPen(QPen(color, max(2.0, width)))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(center), radius, radius)
        font = QFont()
        font.setPixelSize(max(10, round(radius * 1.15)))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#1A1A1A"))
        box = QRect(
            round(center.x() - radius),
            round(center.y() - radius),
            round(radius * 2),
            round(radius * 2),
        )
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self.text)


def _rect(start: QPoint, end: QPoint) -> QRect:
    return QRect(start, end).normalized()
