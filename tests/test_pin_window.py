"""Pin chrome must glow outside the image without altering capture pixels."""

from math import floor

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget

from app.ui.pin_window import PinWindow


@pytest.fixture
def make_pin(qtbot):
    def create(dpr=1.0, pos=QPoint(150, 120)):
        pixmap = QPixmap(round(200 * dpr), round(120 * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(QColor("#F7EFE2"))
        window = PinWindow(pixmap, pos=pos)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        qtbot.addWidget(window)
        return window

    return create


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("pos", [QPoint(150, 120), QPoint(0, 0)])
def test_frame_preserves_capture_position_and_logical_size(make_pin, dpr, pos):
    window = make_pin(dpr, pos)
    image_rect = window._image_rect()
    assert window.mapToGlobal(image_rect.topLeft()) == pos
    assert image_rect.width() == 200
    assert image_rect.height() == 120


@pytest.mark.parametrize("source_dpr", [1.0, 1.5, 2.0])
def test_glow_fades_to_transparency_outside_unchanged_image(make_pin, source_dpr):
    window = make_pin(source_dpr)
    window.show()
    QApplication.setActiveWindow(window)
    rendered = window.grab().toImage()
    rect = window._image_rect()
    dpr = rendered.devicePixelRatio()

    def pixel(x, y):
        # Select the physical pixel containing this logical pixel's center.
        # Rounding can cross the image boundary at the right/bottom edge.
        return rendered.pixelColor(floor((x + 0.5) * dpr), floor((y + 0.5) * dpr))

    for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(), rect.center()):
        assert pixel(point.x(), point.y()) == QColor("#F7EFE2")
    y = rect.center().y()
    near = pixel(rect.left() - 2, y)
    middle = pixel(rect.left() - 4, y)
    far = pixel(rect.left() - 7, y)
    assert near.alpha() > middle.alpha() > far.alpha() >= 0
    assert near.blue() > near.red()
    assert pixel(0, 0).alpha() == 0
    assert window._pixmap.toImage().pixelColor(0, 0) == QColor("#F7EFE2")


def test_frame_disappears_on_deactivation_and_returns_on_activation(make_pin, qtbot):
    window = make_pin()
    window.show()
    QApplication.setActiveWindow(window)
    geometry = window.geometry()
    content = window._image_rect()
    active = window.grab().toImage()
    ratio = active.devicePixelRatio()
    sample = QPoint(round((content.left() - 2) * ratio), round(content.center().y() * ratio))
    assert active.pixelColor(sample).alpha() > 0

    other = QWidget()
    other.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    qtbot.addWidget(other)
    other.show()
    QApplication.setActiveWindow(other)
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.Enter))
    inactive = window.grab().toImage()
    assert not window.isActiveWindow()
    assert inactive.pixelColor(sample).alpha() == 0
    crop = content.toRectF()
    crop.setX(crop.x() * ratio)
    crop.setY(crop.y() * ratio)
    crop.setWidth(content.width() * ratio)
    crop.setHeight(content.height() * ratio)
    assert active.copy(crop.toRect()) == inactive.copy(crop.toRect())
    assert window.geometry() == geometry

    QApplication.setActiveWindow(window)
    assert window.grab().toImage().pixelColor(sample).alpha() > 0


def test_zoom_uses_content_aspect_ratio_and_keeps_center(make_pin):
    window = make_pin()
    center = window.geometry().center()
    window.wheelEvent(QWheelEvent(
        QPointF(50, 50), QPointF(200, 170), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    ))
    rect = window._image_rect()
    assert rect.width() == 220
    assert rect.height() == 132
    assert window.geometry().center() == center
    assert window._resize_edges_at(rect.topLeft()) == Qt.Edge.LeftEdge | Qt.Edge.TopEdge
