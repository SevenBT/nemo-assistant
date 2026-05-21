"""
Base class for auto-generated settings pages.

Inspects ConfigItem validator types and creates the appropriate
qfluentwidgets SettingCard for each item.
"""

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QScrollArea
from PyQt6.QtCore import Qt
from qfluentwidgets import (
    BoolValidator,
    ConfigItem,
    FluentIcon,
    OptionsConfigItem,
    RangeConfigItem,
    RangeSettingCard,
    ComboBoxSettingCard,
    SwitchSettingCard,
    SettingCardGroup,
)


class CardSpec:
    """Specification for a single setting card."""

    def __init__(
        self,
        item: ConfigItem,
        icon: FluentIcon,
        title: str,
        content: str = "",
        texts: list[str] | None = None,
    ):
        self.item = item
        self.icon = icon
        self.title = title
        self.content = content
        self.texts = texts  # display labels for OptionsConfigItem


class AutoSettingPage(QScrollArea):
    """
    A settings page that auto-generates SettingCards from CardSpec list.

    Usage:
        page = AutoSettingPage("外观", [
            CardSpec(cfg.theme, FluentIcon.BRUSH, "主题", texts=["暖夜", ...]),
            CardSpec(cfg.contentFontSize, FluentIcon.FONT_SIZE, "内容字体大小"),
        ])
    """

    def __init__(self, title: str, specs: list[CardSpec], parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        group = SettingCardGroup(title, container)

        for spec in specs:
            card = self._create_card(spec)
            if card:
                group.addSettingCard(card)

        layout.addWidget(group)
        self.setWidget(container)

    def _create_card(self, spec: CardSpec) -> QWidget | None:
        """Create the appropriate card based on config item type."""
        item = spec.item

        if isinstance(item, RangeConfigItem):
            return RangeSettingCard(
                item, spec.icon, spec.title, spec.content, parent=self
            )
        elif isinstance(item, OptionsConfigItem):
            return ComboBoxSettingCard(
                item, spec.icon, spec.title, spec.content,
                texts=spec.texts or [],
                parent=self,
            )
        elif isinstance(item.validator, BoolValidator):
            return SwitchSettingCard(
                spec.icon, spec.title, spec.content,
                configItem=item, parent=self,
            )
        return None
