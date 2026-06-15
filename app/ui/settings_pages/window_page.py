"""窗口设置页 — 吸附、最小化目标、窗口尺寸"""

from qfluentwidgets import FluentIcon

from app.core.config import cfg
from app.ui.settings_pages.base_auto_page import AutoSettingPage, CardSpec


class WindowPage(AutoSettingPage):
    def __init__(self, parent=None):
        super().__init__(
            "窗口",
            [
                CardSpec(
                    cfg.edgeSnap,
                    FluentIcon.PIN,
                    "顶栏吸附",
                    "窗口拖到屏幕边缘时自动吸附",
                ),
                CardSpec(
                    cfg.selectionFloatEnabled,
                    FluentIcon.QUICK_NOTE,
                    "划词浮标",
                    "在任意应用选中文字后，光标旁自动弹出动作条（解释/翻译/存便签）",
                ),
                CardSpec(
                    cfg.selectionTranslateTarget,
                    FluentIcon.LANGUAGE,
                    "划词翻译目标语言",
                    "划词翻译时默认翻译成的语言",
                    texts=["中文", "English", "日本語", "한국어", "Français",
                           "Deutsch", "Español", "Русский"],
                ),
                CardSpec(
                    cfg.edgeSnapThreshold,
                    FluentIcon.CONSTRACT,
                    "吸附宽度阈值",
                    "触发吸附的屏幕宽度百分比",
                ),
                CardSpec(
                    cfg.minimizeTo,
                    FluentIcon.MINIMIZE,
                    "最小化到",
                    "关闭窗口时最小化的目标位置",
                    texts=["系统托盘", "任务栏"],
                ),
                CardSpec(
                    cfg.windowWidth,
                    FluentIcon.FULL_SCREEN,
                    "窗口宽度",
                    "应用窗口的默认宽度",
                ),
                CardSpec(
                    cfg.windowHeight,
                    FluentIcon.FULL_SCREEN,
                    "窗口高度",
                    "应用窗口的默认高度",
                ),
                CardSpec(
                    cfg.miniWidth,
                    FluentIcon.MINIMIZE,
                    "Mini 窗口宽度",
                    "Mini 模式常驻小窗的宽度",
                ),
                CardSpec(
                    cfg.miniHeight,
                    FluentIcon.MINIMIZE,
                    "Mini 窗口高度",
                    "Mini 模式常驻小窗的高度",
                ),
                CardSpec(
                    cfg.miniFontSize,
                    FluentIcon.FONT,
                    "Mini 字体大小",
                    "Mini 模式回复区的字号",
                ),
                CardSpec(
                    cfg.miniOpacity,
                    FluentIcon.TRANSPARENT,
                    "Mini 窗口不透明度",
                    "Mini 模式整窗不透明度（百分比，越小越透）",
                ),
            ],
            parent,
        )
