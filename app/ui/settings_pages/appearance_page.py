"""外观设置页 — 主题、全局字体大小"""

from qfluentwidgets import FluentIcon

from app.core.config import cfg, THEME_OPTIONS
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec
from app.ui.style import THEMES

# Build display labels for themes
_THEME_TEXTS = [THEMES[k]["name"] for k in THEME_OPTIONS]


class AppearancePage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            "外观",
            [
                CardSpec(
                    cfg.theme,
                    FluentIcon.BRUSH,
                    "主题",
                    "选择应用的颜色主题",
                    texts=_THEME_TEXTS,
                ),
                CardSpec(
                    cfg.fontSize,
                    FluentIcon.FONT_SIZE,
                    "全局字体大小",
                    "聊天、笔记列表、工具列表等所有界面的字体大小",
                ),
            ],
            parent,
        )
