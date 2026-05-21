"""编辑器设置页 — 输入/编辑区字体"""

from qfluentwidgets import FluentIcon

from app.core.config import cfg
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec


class EditorPage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            "编辑器",
            [
                CardSpec(
                    cfg.editorFontSize,
                    FluentIcon.EDIT,
                    "编辑器字体大小",
                    "聊天输入框、笔记编辑器、便利贴编辑器的字体大小",
                ),
            ],
            parent,
        )
