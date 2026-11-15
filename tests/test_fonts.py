"""Application font rendering and Fluent-widget inheritance regressions."""

import pytest
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel
from qfluentwidgets import BodyLabel, LineEdit, qconfig

from app.ui import fonts, style
from app.ui.chat_widget import _MessageText


@pytest.fixture
def font_environment(qapp):
    previous_font = QFont(qapp.font())
    previous_families = list(qconfig.get(qconfig.fontFamilies))
    previous_qss = qapp.styleSheet()
    previous_theme = style._current_theme_name
    yield qapp
    qapp.setFont(previous_font)
    qconfig.set(qconfig.fontFamilies, previous_families, save=False)
    style.apply_theme(previous_theme)
    qapp.setStyleSheet(previous_qss)


def test_rendering_preferences_reach_fluent_and_rich_text(font_environment, monkeypatch, qtbot):
    app = font_environment
    family = app.font().family()
    monkeypatch.setattr(fonts, "_register_bundled_fonts", lambda: set())
    monkeypatch.setattr(fonts, "_pick_family", lambda available: family)
    assert fonts.apply_app_font() == family
    assert qconfig.get(qconfig.fontFamilies)[0] == family

    for theme in ("warm_night", "almond"):
        app.setStyleSheet(style.apply_theme(theme, content_font_size=17))
        for widget in (QLabel("中文 English"), BodyLabel("中文 English"), LineEdit(), _MessageText(False)):
            qtbot.addWidget(widget)
            widget.ensurePolished()
            font = widget.font()
            assert font.families()[0] == family
            assert font.hintingPreference() == QFont.HintingPreference.PreferVerticalHinting
            assert font.styleStrategy() & QFont.StyleStrategy.PreferAntialias
            assert font.styleStrategy() & QFont.StyleStrategy.PreferOutline
            if isinstance(widget, _MessageText):
                widget.set_text("正文 **加粗** English")
                assert widget.document().defaultFont().hintingPreference() == QFont.HintingPreference.PreferVerticalHinting
                assert font.pixelSize() == 17
                assert "font-weight:700" in widget.toHtml()
            if isinstance(widget, BodyLabel):
                assert font.pixelSize() == 14


def test_missing_preferred_family_still_smooths_system_font(font_environment, monkeypatch):
    app = font_environment
    original = QFont(app.font())
    original.setPixelSize(19)
    original.setWeight(QFont.Weight.DemiBold)
    original.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    app.setFont(original)
    monkeypatch.setattr(fonts, "_register_bundled_fonts", lambda: set())
    monkeypatch.setattr(fonts, "_pick_family", lambda available: None)
    assert fonts.apply_app_font() is None
    assert app.font().families() == original.families()
    assert app.font().pixelSize() == 19
    assert app.font().weight() == QFont.Weight.DemiBold
    assert app.font().hintingPreference() == QFont.HintingPreference.PreferVerticalHinting
    assert not app.font().styleStrategy() & QFont.StyleStrategy.NoAntialias


def test_fluent_fallbacks_are_preserved_without_saving(font_environment, monkeypatch):
    family = font_environment.font().family()
    monkeypatch.setattr(fonts, "_register_bundled_fonts", lambda: set())
    monkeypatch.setattr(fonts, "_pick_family", lambda available: family)
    qconfig.set(qconfig.fontFamilies, ["Segoe UI", "Microsoft YaHei", "PingFang SC"], save=False)
    saved = []
    monkeypatch.setattr(qconfig, "save", lambda: saved.append(True))
    fonts.apply_app_font()
    expected = list(dict.fromkeys([family, "Segoe UI", "Microsoft YaHei", "PingFang SC"]))
    assert qconfig.get(qconfig.fontFamilies) == expected
    fonts.apply_app_font()
    assert qconfig.get(qconfig.fontFamilies) == expected
    assert saved == []
