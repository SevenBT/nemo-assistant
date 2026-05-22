"""
Fluent Design theme system.

Bridges app themes to qfluentwidgets' built-in theming, with a thin
custom QSS layer for app-specific elements (message bubbles, containers, etc.).
Fluent Widgets auto-style their own components — no QSS needed for them.
"""

import ctypes
import sys
from typing import Any, Dict

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QDialog
from qfluentwidgets import Theme, setTheme, setThemeColor

# ── Theme definitions ────────────────────────────────────────────────
# Each theme contains identity fields + full palette.
# fmt: off
THEMES: Dict[str, Dict[str, Any]] = {
    # ─── Dark Themes ─────────────────────────────────────────────────
    "warm_night": {
        "name": "暖夜护眼",
        "mode": Theme.DARK,
        "accent": "#D4A574",
        "accent_light": "#3D3228",
        "accent_subtle": "rgba(212,165,116,0.10)",
        "user_bubble": "#302A22",
        "user_bubble_border": "#3D3528",
        "bg": "rgba(28,27,26,0.82)",
        "bg_solid": "#1C1B1A",
        "surface": "rgba(37,35,33,0.88)",
        "surface_solid": "#252321",
        "surface_raised": "#2E2C28",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#3A3835",
        "text": "#E8E0D6",
        "text_secondary": "#A09890",
        "text_muted": "#6B6560",
        "ai_bubble": "rgba(37,35,33,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#7EBF8E",
        "error": "#E07070",
        "warning": "#D4A574",
    },
    "deep_ocean": {
        "name": "深海夜空",
        "mode": Theme.DARK,
        "accent": "#7AA2F7",
        "accent_light": "#1E3A5F",
        "accent_subtle": "rgba(122,162,247,0.10)",
        "user_bubble": "#1E3048",
        "user_bubble_border": "#2A4060",
        "bg": "rgba(15,23,42,0.82)",
        "bg_solid": "#0F172A",
        "surface": "rgba(30,41,59,0.88)",
        "surface_solid": "#1E293B",
        "surface_raised": "#273548",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#334155",
        "text": "#E2E8F0",
        "text_secondary": "#94A3B8",
        "text_muted": "#64748B",
        "ai_bubble": "rgba(30,41,59,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#22C55E",
        "error": "#F87171",
        "warning": "#FBBF24",
    },
    "obsidian": {
        "name": "黑曜石",
        "mode": Theme.DARK,
        "accent": "#A0A0A0",
        "accent_light": "#2E2E2E",
        "accent_subtle": "rgba(160,160,160,0.08)",
        "user_bubble": "#242424",
        "user_bubble_border": "#333333",
        "bg": "rgba(18,18,18,0.82)",
        "bg_solid": "#121212",
        "surface": "rgba(30,30,30,0.88)",
        "surface_solid": "#1E1E1E",
        "surface_raised": "#2A2A2A",
        "border": "rgba(255,255,255,0.06)",
        "border_solid": "#333333",
        "text": "#E0E0E0",
        "text_secondary": "#9E9E9E",
        "text_muted": "#616161",
        "ai_bubble": "rgba(30,30,30,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.06)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#66BB6A",
        "error": "#EF5350",
        "warning": "#FFA726",
    },
    # ─── Light Themes ────────────────────────────────────────────────
    "morning": {
        "name": "晨光白",
        "mode": Theme.LIGHT,
        "accent": "#2563EB",
        "accent_light": "#DBEAFE",
        "accent_subtle": "rgba(37,99,235,0.08)",
        "user_bubble": "#EFF6FF",
        "user_bubble_border": "#BFDBFE",
        "bg": "rgba(248,250,252,0.88)",
        "bg_solid": "#F8FAFC",
        "surface": "rgba(255,255,255,0.92)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#F1F5F9",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#E2E8F0",
        "text": "#1E293B",
        "text_secondary": "#64748B",
        "text_muted": "#94A3B8",
        "ai_bubble": "rgba(255,255,255,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#10B981",
        "error": "#EF4444",
        "warning": "#F59E0B",
    },
    "warm_sand": {
        "name": "暖阳沙",
        "mode": Theme.LIGHT,
        "accent": "#C87941",
        "accent_light": "#FDE8D8",
        "accent_subtle": "rgba(200,121,65,0.08)",
        "user_bubble": "#FEF3E2",
        "user_bubble_border": "#FBD5A8",
        "bg": "rgba(253,251,247,0.88)",
        "bg_solid": "#FDFBF7",
        "surface": "rgba(255,253,249,0.92)",
        "surface_solid": "#FFFDF9",
        "surface_raised": "#F5F0EA",
        "border": "rgba(0,0,0,0.05)",
        "border_solid": "#E7E0D6",
        "text": "#292524",
        "text_secondary": "#78716C",
        "text_muted": "#A8A29E",
        "ai_bubble": "rgba(255,253,249,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.05)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#4ADE80",
        "error": "#F87171",
        "warning": "#FB923C",
    },
    "mint": {
        "name": "薄荷清风",
        "mode": Theme.LIGHT,
        "accent": "#0D9488",
        "accent_light": "#CCFBF1",
        "accent_subtle": "rgba(13,148,136,0.08)",
        "user_bubble": "#E6FAF5",
        "user_bubble_border": "#99F6E4",
        "bg": "rgba(248,252,251,0.88)",
        "bg_solid": "#F8FCFB",
        "surface": "rgba(255,255,255,0.92)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#ECFDF5",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#D1FAE5",
        "text": "#134E4A",
        "text_secondary": "#5F7A70",
        "text_muted": "#94ADA3",
        "ai_bubble": "rgba(255,255,255,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#10B981",
        "error": "#F87171",
        "warning": "#FBBF24",
    },
    "rose": {
        "name": "玫瑰金",
        "mode": Theme.LIGHT,
        "accent": "#E06B8A",
        "accent_light": "#FFE4E6",
        "accent_subtle": "rgba(224,107,138,0.08)",
        "user_bubble": "#FFF1F2",
        "user_bubble_border": "#FECDD3",
        "bg": "rgba(253,250,251,0.88)",
        "bg_solid": "#FDFAFB",
        "surface": "rgba(255,255,255,0.92)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#FFF1F2",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#FECDD3",
        "text": "#1C1917",
        "text_secondary": "#78716C",
        "text_muted": "#A8A29E",
        "ai_bubble": "rgba(255,255,255,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#34D399",
        "error": "#FB7185",
        "warning": "#FBBF24",
    },
    "lavender": {
        "name": "静谧紫",
        "mode": Theme.LIGHT,
        "accent": "#6366F1",
        "accent_light": "#E0E7FF",
        "accent_subtle": "rgba(99,102,241,0.08)",
        "user_bubble": "#EEF2FF",
        "user_bubble_border": "#C7D2FE",
        "bg": "rgba(250,250,253,0.88)",
        "bg_solid": "#FAFAFD",
        "surface": "rgba(255,255,255,0.92)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#EEF2FF",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#E0E7FF",
        "text": "#1E1B4B",
        "text_secondary": "#6B7280",
        "text_muted": "#9CA3AF",
        "ai_bubble": "rgba(255,255,255,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#34D399",
        "error": "#F87171",
        "warning": "#FBBF24",
    },
}
# fmt: on

# Default theme key (used as fallback throughout the app)
DEFAULT_THEME = "morning"

# Track current dark mode state for the event filter
_current_dark_mode = False
# Track current text color for cursor sync (QSS doesn't propagate to cursor)
_current_text_color: str = "#E8E0D6"


class _DarkTitleBarFilter(QObject):
    """Event filter that sets DWM dark title bar on newly shown QDialogs."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(obj, QDialog)
            and sys.platform == "win32"
        ):
            try:
                hwnd = int(obj.winId())
                if hwnd:
                    dwmapi = ctypes.windll.dwmapi
                    value = ctypes.c_int(1 if _current_dark_mode else 0)
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
                    )
            except Exception:
                pass
        return False


_filter_instance: _DarkTitleBarFilter | None = None


# ── Public API ────────────────────────────────────────────────────────

def apply_theme(
    theme_name: str,
    opacity: float = 1.0,
    content_font_size: int = 15,
    editor_font_size: int = 15,
) -> str:
    """Apply Fluent theme globally and return custom QSS for app-specific elements."""
    global _current_dark_mode, _filter_instance, _current_text_color
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    dark = theme["mode"] == Theme.DARK
    _current_dark_mode = dark
    _current_text_color = theme["text"]
    setTheme(theme["mode"])
    setThemeColor(QColor(theme["accent"]))
    _apply_palette(theme)
    # Install event filter once to handle future dialogs
    app = QApplication.instance()
    if app is not None and _filter_instance is None:
        _filter_instance = _DarkTitleBarFilter(app)
        app.installEventFilter(_filter_instance)
    # Apply dark title bar to all existing top-level windows
    _apply_dark_titlebar_to_all(dark)
    return _build_custom_qss(theme, content_font_size, editor_font_size)


def _apply_dark_titlebar_to_all(dark: bool) -> None:
    """Set DWM dark title bar attribute on all top-level windows (Windows 11)."""
    if sys.platform != "win32":
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        for w in app.topLevelWidgets():
            if not w.isWindow() or w.windowHandle() is None:
                continue
            hwnd = int(w.winId())
            if hwnd:
                dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
                )
    except Exception:
        pass


def set_dark_titlebar(widget, dark: bool) -> None:
    """Set DWM dark title bar on a single widget. Call after widget.show()."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        if hwnd:
            dwmapi = ctypes.windll.dwmapi
            value = ctypes.c_int(1 if dark else 0)
            dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def _apply_palette(theme: dict) -> None:
    """Set QPalette so QScrollArea viewports and plain QWidgets inherit the right bg."""
    app = QApplication.instance()
    if app is None:
        return
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme["bg_solid"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme["surface_solid"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme["surface_raised"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme["text"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme["text_secondary"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme["surface_raised"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme["text"]))
    app.setPalette(palette)


def get_theme(theme_name: str) -> Dict[str, Any]:
    """Return full theme dict (identity + palette merged)."""
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def get_text_color() -> str:
    """Return current theme's text color hex string."""
    return _current_text_color


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

def _build_custom_qss(theme: dict, content_font_size: int = 15, editor_font_size: int = 15) -> str:
    dark = theme["mode"] == Theme.DARK
    accent = theme["accent"]
    accent_light = theme["accent_light"]
    accent_subtle = theme["accent_subtle"]
    user_bg = theme["user_bubble"]
    user_border = theme["user_bubble_border"]

    bg = theme["bg_solid"]
    surface = theme["surface_solid"]

    accent_text = "#FFFFFF"
    dialog_btn_text = "#FFFFFF" if dark else "#FFFFFF"

    code_size = max(content_font_size - 2, 10)

    return f"""
/* ═══════════════════════════════════════════════════════════════════
   Chat Area
   ═══════════════════════════════════════════════════════════════════ */
#chatArea {{
    background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Title Bar — two-row layout
   ═══════════════════════════════════════════════════════════════════ */
#titleBar {{
    background: {surface};
}}
#titleBarTop {{
    background: transparent;
}}
#titleBarNav {{
    background: transparent;
    border-top: 1px solid {theme["border"]};
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
    border-right: 1px solid {theme["border"]};
}}
#panelTitle {{
    font-size: 13px; font-weight: 700; color: {accent};
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
    background: {theme["scrollbar_hover"]};
}}
#chatScroll:hover QScrollBar::handle:vertical {{
    background: {theme["scrollbar"]};
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
   Message Bubbles — user has visible bubble, AI is frameless
   ═══════════════════════════════════════════════════════════════════ */
#userMessage {{
    background: {accent_subtle};
    border: 1.5px solid {accent};
    border-radius: 14px;
    padding: 1px 6px;
}}
#aiMessage {{
    background: transparent;
    border: none;
    border-left: 3px solid {accent};
    border-radius: 0;
    padding: 2px 6px 2px 10px;
}}

/* ═══════════════════════════════════════════════════════════════════
   Tool Summary — compact collapsed indicator
   ═══════════════════════════════════════════════════════════════════ */
#toolSummary {{
    background: {theme["surface_raised"]};
    border: 1px solid {theme["border"]};
    border-radius: 6px;
    padding: 2px 4px;
}}
#detailLabel {{
    font-size: 11px; color: {theme["text_muted"]}; font-weight: 700;
    background: transparent;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
#detailText {{
    background: {"rgba(0,0,0,0.03)" if not dark else "rgba(255,255,255,0.04)"};
    color: {theme["text_secondary"]};
    border: 1px solid {theme["border_solid"]}; border-radius: 6px;
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 11px;
    padding: 6px 8px;
}}

/* ═══════════════════════════════════════════════════════════════════
   File Card — hover glow
   ═══════════════════════════════════════════════════════════════════ */
#fileCard {{
    background: {theme["surface_raised"]};
    border: 1px solid {theme["border"]};
    border-radius: 10px;
}}
#fileCard:hover {{
    background: {accent_subtle};
    border-color: {accent};
}}
#fileName {{
    font-size: 12px; color: {theme["text"]}; font-weight: 600;
    background: transparent;
}}
#fileSize {{
    font-size: 10px; color: {theme["text_muted"]};
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
    border-top: 1px solid {theme["border"]};
    padding: 2px 0;
}}
#inputWidget QTextEdit {{
    background: {theme["surface_raised"]};
    border: 2px solid transparent;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: {editor_font_size}px;
    color: {theme["text"]};
}}
#inputWidget QTextEdit:focus {{
    border-color: {accent};
    background: {theme["surface_solid"]};
    color: {theme["text"]};
}}

/* ═══════════════════════════════════════════════════════════════════
   Tool Status
   ═══════════════════════════════════════════════════════════════════ */
#toolStatus {{
    color: {accent}; font-size: 11px; font-weight: 500;
    padding: 3px 14px; background: transparent;
}}

/* ═══════════════════════════════════════════════════════════════════
   Notes Panel
   ═══════════════════════════════════════════════════════════════════ */
#noteListPanel {{
    background: {theme["surface_solid"]};
    border-radius: 10px 0 0 10px;
    border-right: 1px solid {theme["border"]};
}}

{"" if not dark else f'''#noteListPanel QScrollBar:vertical {{
    width: 4px; background: transparent;
}}
#noteListPanel QScrollBar::handle:vertical {{
    background: {theme["scrollbar"]}; border-radius: 2px;
}}
'''}

/* ═══════════════════════════════════════════════════════════════════
   Toolbox Panel
   ═══════════════════════════════════════════════════════════════════ */
#toolListPanel {{
    background: {theme["surface_solid"]};
    border-right: 1px solid {theme["border"]};
    border-radius: 10px 0 0 10px;
}}

/* Note editor panel — transparent so side margins blend with window bg */
#noteEditorPanel {{
    background: transparent;
}}

/* Markdown editor — transparent bg, thin hover-only scrollbar at right edge */
#noteMarkdownEditor {{
    background: transparent;
    border: none;
    color: {theme["text"]};
}}
#noteMarkdownEditor QScrollBar:vertical {{
    width: 4px; background: transparent; margin: 0;
}}
#noteMarkdownEditor QScrollBar::handle:vertical {{
    background: transparent; border-radius: 2px; min-height: 28px;
}}
#noteMarkdownEditor QScrollBar::handle:vertical:hover {{
    background: {theme["scrollbar_hover"]};
}}
#noteMarkdownEditor:hover QScrollBar::handle:vertical {{
    background: {theme["scrollbar"]};
}}
#noteMarkdownEditor QScrollBar::add-line:vertical,
#noteMarkdownEditor QScrollBar::sub-line:vertical {{ height: 0; }}
#noteMarkdownEditor QScrollBar::add-page:vertical,
#noteMarkdownEditor QScrollBar::sub-page:vertical {{ background: transparent; }}

/* Markdown preview browser — same treatment */
#noteMarkdownPreview {{
    background: transparent;
}}
#notePreviewBrowser {{
    background: transparent;
    border: none;
}}
#notePreviewBrowser QScrollBar:vertical {{
    width: 4px; background: transparent; margin: 0;
}}
#notePreviewBrowser QScrollBar::handle:vertical {{
    background: transparent; border-radius: 2px; min-height: 28px;
}}
#notePreviewBrowser QScrollBar::handle:vertical:hover {{
    background: {theme["scrollbar_hover"]};
}}
#noteMarkdownPreview:hover #notePreviewBrowser QScrollBar::handle:vertical {{
    background: {theme["scrollbar"]};
}}
#notePreviewBrowser QScrollBar::add-line:vertical,
#notePreviewBrowser QScrollBar::sub-line:vertical {{ height: 0; }}
#notePreviewBrowser QScrollBar::add-page:vertical,
#notePreviewBrowser QScrollBar::sub-page:vertical {{ background: transparent; }}

/* Sticky note editor — same treatment */
#noteStickyEdit {{
    background: transparent;
    border: none;
}}
#noteStickyEdit QScrollBar:vertical {{
    width: 4px; background: transparent; margin: 0;
}}
#noteStickyEdit QScrollBar::handle:vertical {{
    background: transparent; border-radius: 2px; min-height: 28px;
}}
#noteStickyEdit QScrollBar::handle:vertical:hover {{
    background: {theme["scrollbar_hover"]};
}}
#noteStickyEdit:hover QScrollBar::handle:vertical {{
    background: {theme["scrollbar"]};
}}
#noteStickyEdit QScrollBar::add-line:vertical,
#noteStickyEdit QScrollBar::sub-line:vertical {{ height: 0; }}
#noteStickyEdit QScrollBar::add-page:vertical,
#noteStickyEdit QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ═══════════════════════════════════════════════════════════════════
   Markdown rendered content in chat bubbles
   ═══════════════════════════════════════════════════════════════════ */
#userBubble, #aiBubble {{
    color: {theme["text"]}; font-size: {content_font_size}px; line-height: 1.65;
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
    font-size: {code_size}px;
}}
#userBubble pre, #aiBubble pre {{
    background: {"rgba(0,0,0,0.04)" if not dark else "rgba(255,255,255,0.06)"};
    border: 1px solid {theme["border_solid"]};
    border-radius: 6px;
    padding: 8px 10px;
    margin: 4px 0;
}}
#userBubble h1, #userBubble h2, #userBubble h3,
#aiBubble h1, #aiBubble h2, #aiBubble h3 {{
    color: {theme["text"]}; margin: 6px 0 4px 0;
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
    border: 1px solid {theme["border_solid"]}; padding: 4px 8px;
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

QScrollArea {{ background: transparent; border: none; }}

QDialog QScrollArea {{ background: {theme["surface_solid"]}; }}
QDialog QAbstractScrollArea {{ background: {theme["surface_solid"]}; }}

/* ═══════════════════════════════════════════════════════════════════
   Dialog Styling
   ═══════════════════════════════════════════════════════════════════ */
QDialog {{
    background: {theme["surface_solid"]};
}}
QDialog QLineEdit, QDialog QSpinBox, QDialog QDoubleSpinBox,
QDialog QTextEdit, QDialog QPlainTextEdit, QDialog QComboBox {{
    background: {theme["surface_raised"]};
    color: {theme["text"]};
    border: 1px solid {theme["border_solid"]};
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
    border: 1px solid {theme["border_solid"]};
    border-radius: 8px;
    background: {theme["surface_solid"]};
    padding: 4px;
}}
QDialog QTabBar::tab {{
    background: transparent;
    color: {theme["text_muted"]};
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
    color: {theme["text"]};
    background: {theme["hover"]};
    border-radius: 6px 6px 0 0;
}}
QDialog QPushButton {{
    background: {theme["surface_raised"]};
    color: {theme["text"]};
    border: 1px solid {theme["border_solid"]};
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
    border: 2px solid {theme["border_solid"]}; border-radius: 4px;
    background: {theme["surface_solid"]};
}}
QDialog QCheckBox::indicator:hover {{
    border-color: {accent};
}}
QDialog QCheckBox::indicator:checked {{
    background: {accent}; border-color: {accent};
}}
QDialog QTableWidget {{
    background: {theme["surface_solid"]};
    border: 1px solid {theme["border_solid"]}; border-radius: 8px;
    gridline-color: {theme["surface_raised"]}; color: {theme["text"]};
    alternate-background-color: {theme["surface_raised"]};
}}
QDialog QTableWidget::item {{ padding: 8px 10px; }}
QDialog QTableWidget::item:selected {{
    background: {accent_subtle}; color: {theme["text"]};
}}
QDialog QHeaderView::section {{
    background: {theme["surface_raised"]};
    color: {theme["text_secondary"]};
    padding: 8px 12px; border: none;
    border-bottom: 2px solid {theme["border_solid"]};
    font-size: 12px; font-weight: 600;
}}
QDialog QGroupBox {{
    font-weight: 600;
    border: 1px solid {theme["border_solid"]};
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
    background: {theme["scrollbar"]}; border-radius: 2px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {theme["scrollbar_hover"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# ── Legacy compatibility ─────────────────────────────────────────────
def generate_stylesheet(theme_name: str) -> str:
    """Legacy wrapper; prefer ``apply_theme`` for new code."""
    return apply_theme(theme_name)
