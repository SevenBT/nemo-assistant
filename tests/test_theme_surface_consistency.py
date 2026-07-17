import re

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from app.ui.style import THEMES, _build_custom_qss
from app.ui.toolbox_panel import ToolboxPanel


_app = QApplication.instance() or QApplication([])


class _EmptyRegistry:
    def get_all(self) -> list:
        return []


CANVAS_SELECTORS = (
    "#chatInterface",
    "#notesInterface",
    "#toolboxInterface",
    "#chatArea",
    "#noteEditorPanel",
    "#toolDetailPanel",
    "#sessionPanel",
    "#noteListPanel",
    "#toolListPanel",
)
LIST_SELECTORS = ("#sessionList", "#noteList", "#toolList")


def _background_for(qss: str, selector: str) -> str | None:
    qss = re.sub(r"/\*.*?\*/", "", qss, flags=re.DOTALL)
    background = None
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", qss):
        if selector not in (part.strip() for part in selectors.split(",")):
            continue
        for match in re.finditer(
            r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)", declarations
        ):
            background = match.group(1).strip()
    return background


@pytest.mark.parametrize("theme", THEMES.values(), ids=THEMES.keys())
def test_primary_tab_surfaces_share_theme_canvas_color(theme: dict) -> None:
    qss = _build_custom_qss(theme)

    assert {
        selector: _background_for(qss, selector)
        for selector in CANVAS_SELECTORS
    } == {selector: theme["surface_solid"] for selector in CANVAS_SELECTORS}


@pytest.mark.parametrize("theme", THEMES.values(), ids=THEMES.keys())
def test_primary_tab_lists_inherit_their_canvas_color(theme: dict) -> None:
    qss = _build_custom_qss(theme)

    assert {
        selector: _background_for(qss, selector)
        for selector in LIST_SELECTORS
    } == {selector: "transparent" for selector in LIST_SELECTORS}


def test_tool_detail_panel_is_bound_to_canvas_selector() -> None:
    panel = ToolboxPanel(_EmptyRegistry())

    assert panel.findChild(QWidget, "toolDetailPanel") is not None
