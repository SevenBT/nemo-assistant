"""外观设置页 — 语言、外观模式 + 主题、内容字体、导航字体"""

from PyQt6.QtCore import Qt
from qfluentwidgets import ComboBox, FluentIcon, SegmentedWidget, SettingCard

from app.core.config import cfg
from app.i18n import t
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec
from app.ui.style import is_dark_theme, themes_by_mode


class ThemeSettingCard(SettingCard):
    """主题选择卡：上方深/浅模式切换，下方仅列出当前模式下的主题。

    参考 codex 的做法——先选外观模式（深色/浅色），主题下拉框随之
    只展示该模式的主题，避免深浅主题混在一个长列表里。
    """

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.BRUSH,
            t("settings.appearance.theme"),
            t("settings.appearance.theme.desc"),
            parent,
        )
        current = cfg.get(cfg.theme)
        self._dark = is_dark_theme(current)

        # 深/浅模式切换
        self._mode = SegmentedWidget(self)
        self._mode.addItem(
            "dark", t("settings.appearance.themeMode.dark"),
            onClick=lambda: self._on_mode_changed(True),
        )
        self._mode.addItem(
            "light", t("settings.appearance.themeMode.light"),
            onClick=lambda: self._on_mode_changed(False),
        )
        self._mode.setCurrentItem("dark" if self._dark else "light")

        # 当前模式下的主题下拉
        self._combo = ComboBox(self)
        self._populate(current)
        self._combo.currentIndexChanged.connect(self._on_theme_selected)

        self.hBoxLayout.addWidget(self._mode, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self._combo, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

        # 外部（其它入口）改了 theme 时同步 UI
        cfg.theme.valueChanged.connect(self._on_config_changed)

    def _populate(self, selected: str | None) -> None:
        """按当前模式填充主题列表，并选中 selected（若属于该模式）。"""
        self._combo.blockSignals(True)
        self._combo.clear()
        names = themes_by_mode(self._dark)
        for name in names:
            self._combo.addItem(t(f"theme.{name}"), userData=name)
        if selected in names:
            self._combo.setCurrentIndex(names.index(selected))
        else:
            self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)

    def _on_mode_changed(self, dark: bool) -> None:
        if dark == self._dark:
            return
        self._dark = dark
        # 切到该模式的第一个主题
        self._populate(None)
        self._apply_current()

    def _on_theme_selected(self, _index: int) -> None:
        self._apply_current()

    def _apply_current(self) -> None:
        name = self._combo.currentData()
        if name and name != cfg.get(cfg.theme):
            cfg.set(cfg.theme, name)

    def _on_config_changed(self, value: str) -> None:
        dark = is_dark_theme(value)
        if dark != self._dark:
            self._dark = dark
            self._mode.setCurrentItem("dark" if dark else "light")
            self._populate(value)
        elif value != self._combo.currentData():
            names = themes_by_mode(self._dark)
            if value in names:
                self._combo.blockSignals(True)
                self._combo.setCurrentIndex(names.index(value))
                self._combo.blockSignals(False)


class AppearancePage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            t("settings.appearance.group"),
            [
                CardSpec(
                    cfg.language,
                    FluentIcon.LANGUAGE,
                    t("settings.appearance.language"),
                    t("settings.appearance.language.desc"),
                    texts=["English", "中文"],
                ),
                ThemeSettingCard,
                CardSpec(
                    cfg.contentFontSize,
                    FluentIcon.FONT_SIZE,
                    t("settings.appearance.contentFont"),
                    t("settings.appearance.contentFont.desc"),
                ),
                CardSpec(
                    cfg.navigationFontSize,
                    FluentIcon.FONT,
                    t("settings.appearance.navFont"),
                    t("settings.appearance.navFont.desc"),
                ),
            ],
            parent,
        )
        # 语言切换：弹「重启后生效」提示。用标准 QMessageBox（嵌入面板内不能
        # 用 qfluentwidgets MessageBox，见 CLAUDE.md）。
        cfg.language.valueChanged.connect(self._on_language_changed)

    def _on_language_changed(self, _value):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, t("restart.title"), t("restart.language")
        )
