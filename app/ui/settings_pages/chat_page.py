"""聊天设置页"""

from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec


class ChatPage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            "聊天",
            [],
            parent,
        )
