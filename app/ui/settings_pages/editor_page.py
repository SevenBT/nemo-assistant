"""编辑器设置页 — 输入/编辑区字体"""

from qfluentwidgets import FluentIcon

from app.core.config import cfg
from app.i18n import t
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec


class EditorPage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            t("settings.editor.group"),
            [
                CardSpec(
                    cfg.editorFontSize,
                    FluentIcon.EDIT,
                    t("settings.editor.fontSize"),
                    t("settings.editor.fontSize.desc"),
                ),
            ],
            parent,
        )
