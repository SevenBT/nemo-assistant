"""Cursor transitions between capture content, resize handles, and panels."""

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from app.content.ocr_engine import OcrEngineService
from app.ui.screenshot_annotations import ScreenshotTool
from app.ui.screenshot_overlay import ScreenshotOverlay


@pytest.fixture
def overlay(qtbot, monkeypatch):
    monkeypatch.setattr(ScreenshotOverlay, "_capture_frozen", lambda self: None)
    widget = ScreenshotOverlay(ocr_engine_service=OcrEngineService())
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.setGeometry(0, 0, 1000, 700)
    widget._start = widget.mapToGlobal(QPoint(100, 100))
    widget._end = widget.mapToGlobal(QPoint(650, 400))
    widget._state = "SELECTED"
    qtbot.addWidget(widget)
    widget.show()
    widget._show_toolbar()
    widget._position_toolbar()
    yield widget
    widget.close()


def _move(widget, pos):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QCoreApplication.sendEvent(widget, event)


@pytest.mark.parametrize("tool", [None, ScreenshotTool.PEN, ScreenshotTool.TEXT])
def test_cursor_switches_between_selection_and_outside(overlay, tool):
    if tool is not None:
        overlay._on_tool_clicked(tool)
    _move(overlay, QPoint(300, 250))
    assert overlay.cursor().shape() == Qt.CursorShape.CrossCursor
    _move(overlay, QPoint(50, 50))
    assert overlay.cursor().shape() == Qt.CursorShape.ArrowCursor
    _move(overlay, QPoint(300, 250))
    assert overlay.cursor().shape() == Qt.CursorShape.CrossCursor


def test_panel_entry_clears_resize_cursor_and_buttons_use_arrow(overlay):
    overlay._on_tool_clicked(ScreenshotTool.PEN)
    overlay._position_toolbar()
    for panel in (overlay._toolbar, overlay._property_bar):
        _move(overlay, QPoint(100, 250))
        assert QApplication.overrideCursor().shape() == Qt.CursorShape.SizeHorCursor
        QCoreApplication.sendEvent(panel, QEvent(QEvent.Type.Enter))
        assert overlay._resize_cursor_shape is None
        assert overlay.cursor().shape() == Qt.CursorShape.ArrowCursor
        assert panel.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert overlay._tool_buttons[ScreenshotTool.PEN].cursor().shape() == Qt.CursorShape.ArrowCursor
    assert next(iter(overlay._color_buttons.values())).cursor().shape() == Qt.CursorShape.ArrowCursor
    _move(overlay, QPoint(300, 250))
    assert overlay.cursor().shape() == Qt.CursorShape.CrossCursor


def test_moving_outside_clears_resize_override(overlay):
    _move(overlay, QPoint(100, 250))
    assert QApplication.overrideCursor().shape() == Qt.CursorShape.SizeHorCursor
    _move(overlay, QPoint(50, 50))
    assert overlay._resize_cursor_shape is None
    assert overlay.cursor().shape() == Qt.CursorShape.ArrowCursor
