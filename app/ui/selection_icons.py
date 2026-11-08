"""Small, stable icon palette shared by selection settings and the action bar."""
from qfluentwidgets import FluentIcon

SELECTION_ICON_NAMES = (
    "ROBOT", "DICTIONARY", "LANGUAGE", "EDIT", "ACCEPT", "DOCUMENT",
    "CODE", "CHECKBOX", "BRIGHTNESS", "CHAT", "QUICK_NOTE", "LIBRARY",
    "SEARCH", "QUESTION", "MAIL", "GLOBE", "FONT", "BRUSH", "TAG", "HEART",
)
SELECTION_ICONS = {name: FluentIcon[name] for name in SELECTION_ICON_NAMES}


def selection_icon(name: str) -> FluentIcon:
    return SELECTION_ICONS.get(name, FluentIcon.ROBOT)
