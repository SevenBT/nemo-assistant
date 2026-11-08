"""Tests for screenshot annotation rendering and history operations."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from app.ui.screenshot_annotations import ScreenshotAnnotation, ScreenshotTool
from app.ui.screenshot_overlay import ScreenshotOverlay


def _render(annotation: ScreenshotAnnotation) -> QImage:
    image = QImage(120, 120, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    annotation.draw(painter)
    painter.end()
    return image


def test_rectangle_annotation_renders_its_border():
    image = _render(
        ScreenshotAnnotation(
            tool=ScreenshotTool.RECTANGLE,
            points=[QPoint(10, 10), QPoint(80, 60)],
            color=QColor("#FF4D4F"),
            width=3,
        )
    )

    border = image.pixelColor(10, 10)
    center = image.pixelColor(45, 35)
    assert border.alpha() > 0
    assert border.red() > border.green()
    assert center.alpha() == 0


def test_number_annotation_renders_opaque_marker():
    image = _render(
        ScreenshotAnnotation(
            tool=ScreenshotTool.NUMBER,
            points=[QPoint(60, 60)],
            color=QColor("#3388FF"),
            width=3,
            text="1",
        )
    )

    assert image.pixelColor(60, 60).alpha() > 0
    assert image.pixelColor(60, 48).alpha() > 0


@pytest.mark.parametrize("tool", list(ScreenshotTool))
def test_all_annotation_types_render(tool):
    annotation = ScreenshotAnnotation(
        tool=tool,
        points=[QPoint(20, 20), QPoint(90, 70)],
        color=QColor("#FF4D4F"),
        width=4,
        text="1" if tool is ScreenshotTool.NUMBER else "测试文字",
    )

    image = _render(annotation)

    assert not image.isNull()


def test_undo_and_redo_move_annotations_between_stacks():
    annotation = ScreenshotAnnotation(
        tool=ScreenshotTool.ARROW,
        points=[QPoint(0, 0), QPoint(10, 10)],
    )
    owner = SimpleNamespace(
        _annotations=[annotation],
        _redo_annotations=[],
        _update_history_buttons=lambda: None,
        update=lambda: None,
    )

    ScreenshotOverlay._undo_annotation(owner)
    assert owner._annotations == []
    assert owner._redo_annotations == [annotation]

    ScreenshotOverlay._redo_annotation(owner)
    assert owner._annotations == [annotation]
    assert owner._redo_annotations == []


def test_all_toolbar_icons_are_generated():
    for name in (
        "rectangle",
        "ellipse",
        "arrow",
        "pen",
        "highlighter",
        "text",
        "number",
        "ocr",
        "ai",
        "undo",
        "redo",
        "pin",
        "copy",
        "save",
        "close",
    ):
        assert not ScreenshotOverlay._toolbar_icon(name).isNull()


def test_annotations_are_baked_at_export_resolution():
    annotation = ScreenshotAnnotation(
        tool=ScreenshotTool.RECTANGLE,
        points=[QPoint(10, 10), QPoint(40, 30)],
        color=QColor("#FF4D4F"),
        width=3,
    )
    base = QPixmap(200, 120)
    base.fill(QColor("#FFFFFF"))
    owner = SimpleNamespace(
        _annotations=[annotation],
        _crop_frozen=lambda _rect: base,
    )

    result = ScreenshotOverlay._annotated_crop(
        owner,
        QRect(0, 0, 100, 60),
    )

    assert result.width() == 200
    assert result.toImage().pixelColor(20, 20).alpha() > 0
