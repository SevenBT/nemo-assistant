"""
Fluent Design theme system.

Bridges app themes to qfluentwidgets' built-in theming, with a thin
custom QSS layer for app-specific elements (message bubbles, containers, etc.).
Fluent Widgets auto-style their own components — no QSS needed for them.
"""

import ctypes
import sys
from typing import Any, Dict

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme, setThemeColor

# ── Theme definitions ────────────────────────────────────────────────
# fmt: off
THEMES: Dict[str, Dict[str, Any]] = {
    "classic": {
        "name":    "经典清新",
        "mode":    Theme.LIGHT,
        "accent":  "#5B9BD5",
        "accent_light": "#D6EAFB",
        "accent_subtle": "rgba(91,155,213,0.08)",
        "user_bubble":        "#E8F4FD",
        "user_bubble_border": "#CCE5F6",
    },
    "dark": {
        "name":    "暗夜护眼",
        "mode":    Theme.DARK,
        "accent":  "#E5B876",
        "accent_light": "#3D3528",
        "accent_subtle": "rgba(229,184,118,0.10)",
        "user_bubble":        "#2D3348",
        "user_bubble_border": "#3D4358",
    },
    "mint": {
        "name":    "薄荷奶绿",
        "mode":    Theme.LIGHT,
        "accent":  "#5DAA96",
        "accent_light": "#D4F0E6",
        "accent_subtle": "rgba(93,170,150,0.08)",
        "user_bubble":        "#E3F2EC",
        "user_bubble_border": "#C8E0D6",
    },
    "latte": {
        "name":    "暖橘咖啡",
        "mode":    Theme.LIGHT,
        "accent":  "#E8896E",
        "accent_light": "#FDDDD2",
        "accent_subtle": "rgba(232,137,110,0.08)",
        "user_bubble":        "#FBE8DE",
        "user_bubble_border": "#F0D0BE",
    },
    "lavender": {
        "name":    "薰衣草紫",
        "mode":    Theme.LIGHT,
        "accent":  "#8B7EC8",
        "accent_light": "#DDD8F0",
        "accent_subtle": "rgba(139,126,200,0.08)",
        "user_bubble":        "#EBE7F5",
        "user_bubble_border": "#D5D0E2",
    },
}
# fmt: on

# ── Mode-dependent palette ───────────────────────────────────────────
_PALETTE = {
    Theme.LIGHT: {
        "bg":              "rgba(249, 250, 251, 0.88)",
        "bg_solid":        "#F9FAFB",
        "surface":         "rgba(255, 255, 255, 0.92)",
        "surface_solid":   "#FFFFFF",
        "surface_raised":  "#F3F4F6",
        "border":          "rgba(0, 0, 0, 0.06)",
        "border_solid":    "#E5E7EB",
        "text":            "#1A1D23",
        "text_secondary":  "#6B7280",
        "text_muted":      "#9CA3AF",
        "ai_bubble":       "rgba(255, 255, 255, 0.90)",
        "ai_bubble_border": "rgba(0, 0, 0, 0.06)",
        "scrollbar":       "rgba(0, 0, 0, 0.08)",
        "scrollbar_hover": "rgba(0, 0, 0, 0.18)",
        "selected":        "rgba(0, 0, 0, 0.04)",
        "hover":           "rgba(0, 0, 0, 0.03)",
        "success":         "#34D399",
        "error":           "#F87171",
        "warning":         "#FBBF24",
    },
    Theme.DARK: {
        "bg":              "rgba(26, 27, 38, 0.82)",
        "bg_solid":        "#1A1B26",
        "surface":         "rgba(36, 37, 58, 0.88)",
        "surface_solid":   "#24253A",
        "surface_raised":  "#2F3148",
        "border":          "rgba(255, 255, 255, 0.07)",
        "border_solid":    "#3A3C52",
        "text":            "#D0CCC6",
        "text_secondary":  "#9A9690",
        "text_muted":      "#605E68",
        "ai_bubble":       "rgba(36, 37, 58, 0.88)",
        "ai_bubble_border": "rgba(255, 255, 255, 0.07)",
        "scrollbar":       "rgba(255, 255, 255, 0.10)",
        "scrollbar_hover": "rgba(255, 255, 255, 0.20)",
        "selected":        "rgba(255, 255, 255, 0.06)",
        "hover":           "rgba(255, 255, 255, 0.04)",
        "success":         "#5ECB8A",
        "error":           "#F07080",
        "warning":         "#E5B876",
    },
}


# ── Public API ────────────────────────────────────────────────────────

def apply_theme(theme_name: str, opacity: float = 1.0) -> str:
    """Apply Fluent theme globally and return custom QSS for app-specific elements.

    The ``opacity`` parameter is kept for backward compatibility but ignored —
    FluentWindow manages its own background; solid colors are always used.
    """
    theme = THEMES.get(theme_name, THEMES["classic"])
    setTheme(theme["mode"])
    setThemeColor(QColor(theme["accent"]))
    _apply_palette(theme)
    return _build_custom_qss(theme)


def _apply_palette(theme: dict) -> None:
    """Set QPalette so QScrollArea viewports and plain QWidgets inherit the right bg."""
    app = QApplication.instance()
    if app is None:
        return
    p = _PALETTE[theme["mode"]]
    dark = theme["mode"] == Theme.DARK
    bg_color = QColor(p["bg_solid"])
    surface_color = QColor(p["surface_solid"])
    text_color = QColor(p["text"])

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, bg_color)
    palette.setColor(QPalette.ColorRole.Base, surface_color)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(p["surface_raised"]))
    palette.setColor(QPalette.ColorRole.WindowText, text_color)
    palette.setColor(QPalette.ColorRole.Text, text_color)
    palette.setColor(QPalette.ColorRole.Button, QColor(p["surface_raised"]))
    palette.setColor(QPalette.ColorRole.ButtonText, text_color)
    app.setPalette(palette)


def get_theme(theme_name: str) -> Dict[str, Any]:
    """Return merged theme dict (theme definition + mode palette)."""
    theme = THEMES.get(theme_name, THEMES["classic"])
    palette = _PALETTE[theme["mode"]]
    return {**palette, **theme}


def enable_mica(hwnd: int, dark: bool = False) -> bool:
    """Enable Windows 11 Mica backdrop effect on *hwnd*."""
    if sys.platform != "win32":
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        v = ctypes.c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
        bd = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(bd), ctypes.sizeof(bd))
        return True
    except Exception:
        return False


# ── Internal ──────────────────────────────────────────────────────────

def _build_custom_qss(theme: dict) -> str:
    p = _PALETTE[theme["mode"]]
    dark = theme["mode"] == Theme.DARK
    accent = theme["accent"]
    accent_light = theme["accent_light"]
    accent_subtle = theme["accent_subtle"]
    user_bg = theme["user_bubble"]
    user_border = theme["user_bubble_border"]

    # Always use solid backgrounds — FluentWindow manages the window chrome
    bg = p["bg_solid"]
    surface = p["surface_solid"]

    # Derived tokens
    accent_text = "#FFFFFF" if dark else "#FFFFFF"
    dialog_btn_text = "#1A1B26" if not dark else "#FFFFFF"

    return f"""
/* ═══════════════════════════════════════════════════════════════════
   Chat Area
   ═══════════════════════════════════════════════════════════════════ */
#chatArea {{
    background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Title Bar — accent bottom highlight
   ═══════════════════════════════════════════════════════════════════ */
#titleBar {{
    background: {surface};
    border-bottom: 2px solid {accent};
}}

/* SegmentedWidget selected item text color */
SegmentedWidget > QWidget[selected="true"] {{
    color: {accent};
}}
SegmentedToolWidget > QToolButton:checked,
SegmentedWidget > QWidget:checked {{
    color: {accent};
}}

/* ═══════════════════════════════════════════════════════════════════
   Session Panel — accent left stripe on selected item
   ═══════════════════════════════════════════════════════════════════ */
#sessionPanel {{
    background: {surface};
    border-right: 1px solid {p["border"]};
}}
#panelTitle {{
    font-size: 11px; font-weight: 700; color: {accent};
    text-transform: uppercase; letter-spacing: 2px;
    padding: 2px 0;
    background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Chat Scroll — thin, hover-only scrollbar
   ═══════════════════════════════════════════════════════════════════ */
#chatScroll {{
    border: none;
    background: transparent;
}}
#chatScroll QScrollBar:vertical {{
    width: 4px; background: transparent; margin: 0;
}}
#chatScroll QScrollBar::handle:vertical {{
    background: transparent; border-radius: 2px; min-height: 28px;
}}
#chatScroll QScrollBar::handle:vertical:hover {{
    background: {p["scrollbar_hover"]};
}}
#chatScroll:hover QScrollBar::handle:vertical {{
    background: {p["scrollbar"]};
}}
#chatScroll QScrollBar::add-line:vertical,
#chatScroll QScrollBar::sub-line:vertical {{ height: 0; }}
#chatScroll QScrollBar::add-page:vertical,
#chatScroll QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ═══════════════════════════════════════════════════════════════════
   Splitter — invisible handle, only shows on hover
   ═══════════════════════════════════════════════════════════════════ */
QSplitter {{ background: transparent; }}
QSplitter::handle {{
    background: transparent;
    width: 4px;
}}
QSplitter::handle:hover {{ background: {accent}; }}

/* ═══════════════════════════════════════════════════════════════════
   Message Bubbles — visual hierarchy + accent stripe on AI
   ═══════════════════════════════════════════════════════════════════ */
#userMessage {{
    background: {user_bg};
    border: 1px solid {user_border};
    border-radius: 18px; border-top-right-radius: 4px;
    margin-left: 40px;
}}
#aiMessage {{
    background: {p["ai_bubble"]};
    border: 1px solid {p["ai_bubble_border"]};
    border-left: 3px solid {accent};
    border-radius: 18px; border-top-left-radius: 4px;
    margin-right: 40px;
}}

/* Role badges — pill-shaped colored labels */
#userLabel {{
    font-size: 10px; font-weight: 700;
    color: {accent_text};
    background: {accent};
    border-radius: 9px;
    padding: 2px 10px;
    max-width: 36px;
}}
#aiLabel {{
    font-size: 10px; font-weight: 700;
    color: {"#FFFFFF" if dark else "#FFFFFF"};
    background: {p["success"]};
    border-radius: 9px;
    padding: 2px 10px;
    max-width: 30px;
}}
/* ═══════════════════════════════════════════════════════════════════
   Tool Card — status-colored left border
   ═══════════════════════════════════════════════════════════════════ */
#toolCard {{
    background: {p["surface_raised"]};
    border: 1px solid {p["border"]};
    border-left: 3px solid {p["warning"]};
    border-radius: 8px;
}}
#detailLabel {{
    font-size: 11px; color: {p["text_muted"]}; font-weight: 700;
    background: transparent;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
#detailText {{
    background: {"rgba(0,0,0,0.03)" if not dark else "rgba(255,255,255,0.04)"};
    color: {p["text_secondary"]};
    border: 1px solid {p["border_solid"]}; border-radius: 6px;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 11px;
    padding: 6px 8px;
}}

/* ═══════════════════════════════════════════════════════════════════
   File Card — hover glow
   ═══════════════════════════════════════════════════════════════════ */
#fileCard {{
    background: {p["surface_raised"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
}}
#fileCard:hover {{
    background: {accent_subtle};
    border-color: {accent};
}}
#fileName {{
    font-size: 12px; color: {p["text"]}; font-weight: 600;
    background: transparent;
}}
#fileSize {{
    font-size: 10px; color: {p["text_muted"]};
    background: transparent;
}}
#fileIcon {{
    font-size: 22px;
    background: {accent_subtle};
    border-radius: 8px;
}}

/* ═══════════════════════════════════════════════════════════════════
   Input Area — no background band, just top border separator
   ═══════════════════════════════════════════════════════════════════ */
#inputWidget {{
    background: transparent;
    border-top: 1px solid {p["border"]};
    padding: 2px 0;
}}
#inputWidget QTextEdit {{
    background: {p["surface_raised"]};
    color: {p["text"]};
    border: 2px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 13px;
}}
#inputWidget QTextEdit:focus {{
    border-color: {accent};
    background: {p["surface_solid"]};
}}

/* ═══════════════════════════════════════════════════════════════════
   Tool Status
   ═══════════════════════════════════════════════════════════════════ */
#toolStatus {{
    color: {accent}; font-size: 11px; font-weight: 500;
    padding: 3px 14px; background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Notes Panel — dark theme input overrides + color dot support
   ═══════════════════════════════════════════════════════════════════ */
#noteListPanel {{
    background: {p["surface_solid"]};
    border-radius: 10px 0 0 10px;
    border-right: 1px solid {p["border"]};
}}

/* Force dark-theme colors on notes editor widgets */
{"" if not dark else f"""
#noteListPanel QScrollBar:vertical {{
    width: 4px; background: transparent;
}}
#noteListPanel QScrollBar::handle:vertical {{
    background: {p["scrollbar"]}; border-radius: 2px;
}}
"""}

/* ═══════════════════════════════════════════════════════════════════
   Markdown rendered content in chat bubbles
   ═══════════════════════════════════════════════════════════════════ */
#userBubble, #aiBubble {{
    color: {p["text"]}; font-size: 13px; line-height: 1.65;
    background: transparent; border: none;
    selection-background-color: {accent_light};
}}
#userBubble p, #aiBubble p {{
    margin: 0 0 6px 0;
}}
#userBubble code, #aiBubble code {{
    background: {"rgba(0,0,0,0.06)" if not dark else "rgba(255,255,255,0.08)"};
    border-radius: 3px;
    padding: 1px 4px;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
}}
#userBubble pre, #aiBubble pre {{
    background: {"rgba(0,0,0,0.04)" if not dark else "rgba(255,255,255,0.06)"};
    border: 1px solid {p["border_solid"]};
    border-radius: 6px;
    padding: 8px 10px;
    margin: 4px 0;
}}
#userBubble h1, #userBubble h2, #userBubble h3,
#aiBubble h1, #aiBubble h2, #aiBubble h3 {{
    color: {p["text"]}; margin: 6px 0 4px 0;
}}
#userBubble ul, #userBubble ol,
#aiBubble ul, #aiBubble ol {{
    margin: 2px 0; padding-left: 18px;
}}
#userBubble table, #aiBubble table {{
    border-collapse: collapse; margin: 4px 0;
}}
#userBubble th, #userBubble td,
#aiBubble th, #aiBubble td {{
    border: 1px solid {p["border_solid"]}; padding: 4px 8px;
}}
#userBubble th, #aiBubble th {{
    background: {"rgba(0,0,0,0.04)" if not dark else "rgba(255,255,255,0.06)"};
    font-weight: 600;
}}

/* ═══════════════════════════════════════════════════════════════════
   Generic Overrides
   ═══════════════════════════════════════════════════════════════════ */
QLabel {{ background: transparent; }}
QWidget#attachmentsContainer {{ background: transparent; }}
QWidget#toolsContainer {{ background: transparent; }}

/* ScrollArea viewports — prevent white flash in dark theme.
   Qt QSS cannot target viewport directly; these rules cover what it can. */
QScrollArea {{ background: transparent; border: none; }}
QAbstractScrollArea {{ background: transparent; }}

/* Dialog scroll areas need solid background */
QDialog QScrollArea {{ background: {p["surface_solid"]}; }}
QDialog QAbstractScrollArea {{ background: {p["surface_solid"]}; }}

/* ═══════════════════════════════════════════════════════════════════
   Context Menu polish
   ═══════════════════════════════════════════════════════════════════ */
QMenu {{
    background: {p["surface_solid"]};
    border: 1px solid {p["border_solid"]}; border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 24px 7px 12px; border-radius: 6px;
    color: {p["text"]};
}}
QMenu::item:selected {{
    background: {accent_subtle}; color: {accent};
}}
QMenu::separator {{
    height: 1px; background: {p["border"]}; margin: 4px 8px;
}}

/* ═══════════════════════════════════════════════════════════════════
   Dialog Styling (for unconverted standard Qt widgets)
   ═══════════════════════════════════════════════════════════════════ */
QDialog {{
    background: {p["surface_solid"]};
}}
QDialog QLineEdit, QDialog QSpinBox, QDialog QDoubleSpinBox,
QDialog QTextEdit, QDialog QPlainTextEdit, QDialog QComboBox {{
    background: {p["surface_raised"]};
    color: {p["text"]};
    border: 1px solid {p["border_solid"]};
    border-radius: 8px;
    padding: 7px 12px;
}}
QDialog QLineEdit:focus, QDialog QSpinBox:focus,
QDialog QDoubleSpinBox:focus, QDialog QTextEdit:focus,
QDialog QPlainTextEdit:focus {{
    border-color: {accent};
    border-width: 2px;
}}
QDialog QTabWidget::pane {{
    border: 1px solid {p["border_solid"]};
    border-radius: 8px;
    background: {p["surface_solid"]};
    padding: 4px;
}}
QDialog QTabBar::tab {{
    background: transparent;
    color: {p["text_muted"]};
    padding: 8px 18px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
}}
QDialog QTabBar::tab:selected {{
    color: {accent};
    border-bottom: 2px solid {accent};
    font-weight: 600;
}}
QDialog QTabBar::tab:hover:!selected {{
    color: {p["text"]};
    background: {p["hover"]};
    border-radius: 6px 6px 0 0;
}}
QDialog QPushButton {{
    background: {p["surface_raised"]};
    color: {p["text"]};
    border: 1px solid {p["border_solid"]};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QDialog QPushButton:hover {{
    background: {accent_subtle};
    border-color: {accent};
    color: {accent};
}}
QDialog QPushButton:pressed {{
    background: {accent_light};
}}
QDialog QDialogButtonBox QPushButton {{
    min-width: 80px;
    background: {accent};
    color: {dialog_btn_text};
    border: none;
    font-weight: 600;
}}
QDialog QDialogButtonBox QPushButton:hover {{
    background: {accent}dd;
}}
QDialog QCheckBox {{ spacing: 8px; }}
QDialog QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 2px solid {p["border_solid"]}; border-radius: 4px;
    background: {p["surface_solid"]};
}}
QDialog QCheckBox::indicator:hover {{
    border-color: {accent};
}}
QDialog QCheckBox::indicator:checked {{
    background: {accent}; border-color: {accent};
}}
QDialog QTableWidget {{
    background: {p["surface_solid"]};
    border: 1px solid {p["border_solid"]}; border-radius: 8px;
    gridline-color: {p["surface_raised"]}; color: {p["text"]};
    alternate-background-color: {p["surface_raised"]};
}}
QDialog QTableWidget::item {{ padding: 8px 10px; }}
QDialog QTableWidget::item:selected {{
    background: {accent_subtle}; color: {p["text"]};
}}
QDialog QHeaderView::section {{
    background: {p["surface_raised"]};
    color: {p["text_secondary"]};
    padding: 8px 12px; border: none;
    border-bottom: 2px solid {p["border_solid"]};
    font-size: 12px; font-weight: 600;
}}
QDialog QGroupBox {{
    font-weight: 600;
    border: 1px solid {p["border_solid"]};
    border-radius: 8px;
    margin-top: 14px;
    padding: 18px 10px 10px;
}}
QDialog QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {accent};
}}

/* ═══════════════════════════════════════════════════════════════════
   Global Scrollbar
   ═══════════════════════════════════════════════════════════════════ */
QScrollBar:vertical {{
    width: 5px; background: transparent;
}}
QScrollBar::handle:vertical {{
    background: {p["scrollbar"]}; border-radius: 2px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p["scrollbar_hover"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# ── Legacy compatibility ─────────────────────────────────────────────
def generate_stylesheet(theme_name: str) -> str:
    """Legacy wrapper; prefer ``apply_theme`` for new code."""
    return apply_theme(theme_name)
