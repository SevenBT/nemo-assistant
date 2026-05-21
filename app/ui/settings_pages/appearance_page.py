"""外观设置页 — 主题、内容字体、导航字体"""

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
                    cfg.contentFontSize,
                    FluentIcon.FONT_SIZE,
                    "内容字体大小",
                    "聊天气泡中的文字大小",
                ),
                CardSpec(
                    cfg.navigationFontSize,
                    FluentIcon.FONT,
                    "导航字体大小",
                    "会话列表、工具箱、笔记列表等侧栏文字大小",
                ),
            ],
            parent,
        )
