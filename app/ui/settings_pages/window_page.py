"""窗口设置页 — 吸附、最小化目标、窗口尺寸"""

from qfluentwidgets import FluentIcon

from app.core.config import cfg
from app.i18n import t
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec


class WindowPage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            t("settings.window.group"),
            [
                CardSpec(
                    cfg.edgeSnap,
                    FluentIcon.PIN,
                    t("settings.window.edgeSnap"),
                    t("settings.window.edgeSnap.desc"),
                ),
                CardSpec(
                    cfg.edgeSnapThreshold,
                    FluentIcon.CONSTRACT,
                    t("settings.window.snapThreshold"),
                    t("settings.window.snapThreshold.desc"),
                ),
                CardSpec(
                    cfg.minimizeTo,
                    FluentIcon.MINIMIZE,
                    t("settings.window.minimizeTo"),
                    t("settings.window.minimizeTo.desc"),
                    texts=[t("settings.window.tray"), t("settings.window.taskbar")],
                ),
                CardSpec(
                    cfg.windowWidth,
                    FluentIcon.FULL_SCREEN,
                    t("settings.window.width"),
                    t("settings.window.width.desc"),
                ),
                CardSpec(
                    cfg.windowHeight,
                    FluentIcon.FULL_SCREEN,
                    t("settings.window.height"),
                    t("settings.window.height.desc"),
                ),
            ],
            parent,
        )
