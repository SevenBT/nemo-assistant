"""Theme regressions: actual popup palettes and contrast across every preset."""
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QMenu, QPushButton
from qfluentwidgets import PrimaryPushButton

from app.models.session import Session
from app.ui import style
from app.ui.screenshot_overlay import ScreenshotOverlay
from app.ui.session_settings_dialog import SessionSettingsDialog


def contrast(first, second):
    # Independent sRGB computation, so incorrect production math fails the test.
    def luminance(value):
        color = QColor(value)
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


@pytest.fixture
def theme_session(qapp):
    previous = style._current_theme_name
    yield
    style.apply_theme(previous)


@pytest.mark.parametrize("name", style.THEMES)
def test_popup_dialog_and_primary_buttons_are_readable(name, theme_session, qtbot, monkeypatch):
    theme = style.THEMES[name]
    qss = style.apply_theme(name)
    monkeypatch.setattr(style, "get_current_theme", lambda: theme)
    monkeypatch.setattr(ScreenshotOverlay, "_capture_frozen", lambda self: None)
    overlay = ScreenshotOverlay(ocr_engine_service=SimpleNamespace())
    qtbot.addWidget(overlay)
    overlay._start, overlay._end = QPoint(40, 40), QPoint(440, 300)
    overlay._show_toolbar()
    menu = overlay.findChild(QMenu, "snipAiMenu")
    assert menu is not None and len(menu.actions()) == 5
    menu.ensurePolished()
    assert contrast(menu.palette().color(QPalette.ColorRole.WindowText),
                    menu.palette().color(QPalette.ColorRole.Window)) >= 4.5
    # The screenshot icons are white even in light application themes.
    assert menu.palette().color(QPalette.ColorRole.Window).lightness() < 80
    assert "::item:selected" in menu.styleSheet()
    overlay._show_ocr_panel("Recognized text")
    confirm = overlay.findChild(QPushButton, "ocrConfirmBtn")
    confirm.ensurePolished()
    assert contrast(confirm.palette().color(QPalette.ColorRole.ButtonText),
                    confirm.palette().color(QPalette.ColorRole.Button)) >= 4.5

    dialog = SessionSettingsDialog(Session(title="Theme test"))
    qtbot.addWidget(dialog)
    dialog.setStyleSheet(qss)
    primary = PrimaryPushButton("Install", dialog)
    status = QLabel("Ready", dialog)
    style.set_text_role(status, "success")
    dialog.layout().insertWidget(1, primary)
    dialog.layout().insertWidget(2, status)
    dialog.show()
    qtbot.waitUntil(primary.isVisible)
    for button in (primary, *dialog.findChildren(QDialogButtonBox)[0].findChildren(QPushButton)):
        assert contrast(button.palette().color(QPalette.ColorRole.ButtonText),
                        button.palette().color(QPalette.ColorRole.Button)) >= 4.5
    title = dialog.findChildren(QLabel)[0]
    assert contrast(title.palette().color(QPalette.ColorRole.WindowText), theme["surface_solid"]) >= 4.5
    assert contrast(status.palette().color(QPalette.ColorRole.WindowText), theme["surface_solid"]) >= 4.5
    primary.setEnabled(False)
    assert contrast(primary.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText),
                    primary.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button)) >= 4.5


@pytest.mark.parametrize("name", style.THEMES)
def test_colored_text_and_send_button_states_meet_contrast(name, theme_session):
    theme = style.THEMES[name]
    style.apply_theme(name)
    for role in ("accent", "success", "error", "warning", "text_secondary"):
        assert contrast(style.theme_text_color(role, theme), theme["surface_solid"]) >= 4.5
    ink = style.get_accent_text_color()
    for background in (style.get_accent_button_bg(), style.get_accent_button_bg_hover(),
                       style.get_accent_button_bg_pressed()):
        assert contrast(ink, background) >= 4.5


def test_existing_status_and_primary_button_follow_theme_switch(theme_session, qtbot):
    dialog = SessionSettingsDialog(Session(title="Live theme"))
    qtbot.addWidget(dialog)
    primary = PrimaryPushButton("Generate", dialog)
    status = QLabel("Error", dialog)
    style.set_text_role(status, "error")
    dialog.layout().insertWidget(1, primary)
    dialog.layout().insertWidget(2, status)
    for name in ("almond", "everforest", "morandi_haze", "obsidian"):
        dialog.setStyleSheet(style.apply_theme(name))
        dialog.show()
        qtbot.waitUntil(primary.isVisible)
        theme = style.THEMES[name]
        assert contrast(status.palette().color(QPalette.ColorRole.WindowText), theme["surface_solid"]) >= 4.5
        assert contrast(primary.palette().color(QPalette.ColorRole.ButtonText),
                        primary.palette().color(QPalette.ColorRole.Button)) >= 4.5


def test_trace_status_badges_pair_text_with_their_status_background(qtbot):
    from app.ui.settings_pages.trace_page import _OverviewCard
    card = _OverviewCard()
    qtbot.addWidget(card)
    for status in ("ok", "error", "cancelled", "running", "unknown"):
        card.set_trace({"status": status})
        card._badge.ensurePolished()
        assert contrast(card._badge.palette().color(QPalette.ColorRole.WindowText),
                        card._badge._backgroundColor()) >= 4.5
