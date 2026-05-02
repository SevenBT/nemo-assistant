"""
Theme system: color palettes + QSS template → runtime stylesheet generation.

Add a new theme by adding an entry to THEMES.  Each theme is a flat dict of
colour tokens; the template in _TEMPLATE references them as __TOKEN__.
"""
from typing import Dict

# ── Theme colour palettes ──────────────────────────────────────────────
# fmt: off
THEMES: Dict[str, Dict[str, str]] = {
    # ── 经典清新 ───────────────────────────────────────────────────────
    "classic": {
        "name":    "经典清新",
        "bg":      "#F0F2F5", "surface": "#FFFFFF", "surface_raised": "#F3F4F6",
        "border":  "#E5E7EB", "border_focus": "#5B9BD5",
        "accent":  "#5B9BD5", "accent_hover": "#7DB9DE", "accent_pressed": "#4A8BC5",
        "text":    "#1A1D23", "text_secondary": "#6B7280", "text_muted": "#9CA3AF",
        "text_accent": "#FFFFFF",
        "user_bubble": "#E8F4FD", "selected": "#E8F4FD",
        "success": "#34D399", "error": "#F87171", "warning": "#FBBF24",
        "scrollbar": "#D1D5DB", "scrollbar_hover": "#9CA3AF",
    },

    # ── 暗夜护眼：深邃底色 + 暖琥珀强调，减少蓝光刺激 ─────────────────
    "dark": {
        "name":    "暗夜护眼",
        "bg":      "#1A1B26", "surface": "#24253A", "surface_raised": "#2F3148",
        "border":  "#3A3C52", "border_focus": "#E5B876",
        "accent":  "#E5B876", "accent_hover": "#F0D090", "accent_pressed": "#D4A565",
        "text":    "#D0CCC6", "text_secondary": "#9A9690", "text_muted": "#605E68",
        "text_accent": "#1A1B26",
        "user_bubble": "#2D3348", "selected": "#2D3040",
        "success": "#5ECB8A", "error": "#F07080", "warning": "#E5B876",
        "scrollbar": "#3A3C52", "scrollbar_hover": "#5A5C72",
    },

    # ── 薄荷奶绿：清新薄荷绿 + 白底，干净柔和 ─────────────────────────
    "mint": {
        "name":    "薄荷奶绿",
        "bg":      "#F2F7F5", "surface": "#FFFFFF", "surface_raised": "#EDF4F1",
        "border":  "#DDE8E3", "border_focus": "#5DAA96",
        "accent":  "#5DAA96", "accent_hover": "#7BC0AE", "accent_pressed": "#4A9582",
        "text":    "#1D2A26", "text_secondary": "#5E7A70", "text_muted": "#8FA89E",
        "text_accent": "#FFFFFF",
        "user_bubble": "#E3F2EC", "selected": "#E3F2EC",
        "success": "#5DAA96", "error": "#E87878", "warning": "#E8B45A",
        "scrollbar": "#C8D9D1", "scrollbar_hover": "#96AFA3",
    },

    # ── 暖橘咖啡：奶油底色 + 珊瑚橘，温暖惬意 ─────────────────────────
    "latte": {
        "name":    "暖橘咖啡",
        "bg":      "#FDF6F0", "surface": "#FFFFFF", "surface_raised": "#F7EFE8",
        "border":  "#EBE0D5", "border_focus": "#E8896E",
        "accent":  "#E8896E", "accent_hover": "#F0A590", "accent_pressed": "#D4785E",
        "text":    "#2D221E", "text_secondary": "#7A6A60", "text_muted": "#A8988E",
        "text_accent": "#FFFFFF",
        "user_bubble": "#FBE8DE", "selected": "#FBE8DE",
        "success": "#6DBE8A", "error": "#E87878", "warning": "#E8B45A",
        "scrollbar": "#DDD0C5", "scrollbar_hover": "#B0A090",
    },

    # ── 薰衣草紫：淡紫底色 + 薰衣草紫强调，优雅沉静 ──────────────────
    "lavender": {
        "name":    "薰衣草紫",
        "bg":      "#F4F2F8", "surface": "#FFFFFF", "surface_raised": "#EFECF5",
        "border":  "#E2DFEC", "border_focus": "#8B7EC8",
        "accent":  "#8B7EC8", "accent_hover": "#A498D8", "accent_pressed": "#7A6EB5",
        "text":    "#211F2A", "text_secondary": "#6A6478", "text_muted": "#9A94A8",
        "text_accent": "#FFFFFF",
        "user_bubble": "#EBE7F5", "selected": "#EBE7F5",
        "success": "#6DBE8A", "error": "#E87878", "warning": "#E8B45A",
        "scrollbar": "#D5D0E2", "scrollbar_hover": "#A8A0B8",
    },
}
# fmt: on


# ── QSS template ───────────────────────────────────────────────────────
# Token format: __TOKEN__  (double-underscore to avoid CSS conflicts)

_TEMPLATE = r"""
/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: __TEXT__;
    background: transparent;
}

/* ── Transparent containers ──────────────────────────────────────── */
QStackedWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ── Main container ───────────────────────────────────────────────── */
#mainWindow {
    background: __BG__;
    border: 1px solid __BORDER__;
    border-radius: 12px;
}
#chatArea { background: __BG__; }

/* ── Title bar ────────────────────────────────────────────────────── */
#titleBar {
    background: __SURFACE__;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    border-bottom: 1px solid __BORDER__;
}
#titleLabel {
    font-size: 14px; font-weight: 600;
    color: __TEXT__;
}

/* ── Session panel ────────────────────────────────────────────────── */
#sessionPanel {
    background: __SURFACE__;
    border-right: 1px solid __BORDER__;
}
#panelTitle {
    font-size: 12px; font-weight: 600; color: __TEXT_MUTED__;
    text-transform: uppercase; letter-spacing: 1px;
}
#sessionList { background: transparent; border: none; outline: none; }
#sessionList::item {
    padding: 7px 8px; border-radius: 6px;
    color: __TEXT_SECONDARY__; font-size: 12px;
}
#sessionList::item:selected { background: __SELECTED__; color: __TEXT__; }
#sessionList::item:hover:!selected { background: __SURFACE_RAISED__; }

/* ── Chat scroll area ─────────────────────────────────────────────── */
#chatScroll { border: none; background: __BG__; }
#chatScroll QScrollBar:vertical {
    width: 4px; background: transparent;
}
#chatScroll QScrollBar::handle:vertical {
    background: __SCROLLBAR__; border-radius: 2px; min-height: 20px;
}
#chatScroll QScrollBar::handle:vertical:hover { background: __SCROLLBAR_HOVER__; }

/* ── Message bubbles ──────────────────────────────────────────────── */
#userMessage {
    background: __USER_BUBBLE__;
    border-radius: 14px; border-top-right-radius: 4px;
    margin-left: 40px;
}
#aiMessage {
    background: __SURFACE__;
    border: 1px solid __BORDER__;
    border-radius: 14px; border-top-left-radius: 4px;
    margin-right: 40px;
}
#userLabel { font-size: 11px; font-weight: 600; color: __ACCENT__; }
#aiLabel   { font-size: 11px; font-weight: 600; color: __SUCCESS__; }
#userBubble, #aiBubble {
    color: __TEXT__; font-size: 13px; line-height: 1.6;
    background: transparent; border: none;
}

/* ── Tool card ────────────────────────────────────────────────────── */
#toolCard {
    background: __SURFACE_RAISED__;
    border: 1px solid __BORDER__;
    border-radius: 8px; margin-top: 4px;
}
#detailLabel { font-size: 11px; color: __TEXT_MUTED__; font-weight: 600; }
#detailText {
    background: __SURFACE_RAISED__; color: __TEXT_SECONDARY__;
    border: 1px solid __BORDER__; border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", monospace; font-size: 11px;
}

/* ── Input area ───────────────────────────────────────────────────── */
#inputWidget {
    background: __SURFACE__;
    border-top: 1px solid __BORDER__;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
}
#inputEdit {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 10px;
    padding: 8px 12px; font-size: 13px;
}
#inputEdit:focus { border-color: __BORDER_FOCUS__; background: __SURFACE__; }

/* ── Buttons ──────────────────────────────────────────────────────── */
#sendBtn {
    background: __ACCENT__; color: __TEXT_ACCENT__;
    border: none; border-radius: 10px;
    font-weight: 600; font-size: 13px; padding: 6px 12px;
}
#sendBtn:hover  { background: __ACCENT_HOVER__; }
#sendBtn:pressed{ background: __ACCENT_PRESSED__; }
#sendBtn:disabled { background: __SCROLLBAR__; color: __TEXT_MUTED__; }

#iconBtn {
    background: transparent; color: __TEXT_SECONDARY__;
    border: none; border-radius: 6px;
    font-size: 12px; font-weight: 500; padding: 0 4px;
}
#iconBtn:hover  { background: __SURFACE_RAISED__; color: __TEXT__; }
#iconBtn:pressed{ background: __BORDER__; }

#closeBtn {
    background: transparent; color: __TEXT_MUTED__;
    border: none; border-radius: 6px;
    font-size: 14px; font-weight: 600; padding: 0 4px;
}
#closeBtn:hover { background: __ERROR__; color: #FFFFFF; }

/* ── New session button ───────────────────────────────────────────── */
#newSessionBtn {
    background: __SURFACE_RAISED__; color: __ACCENT__;
    border: none; border-radius: 6px;
    font-size: 11px; font-weight: 600; padding: 0 8px;
}
#newSessionBtn:hover  { background: __BORDER__; color: __ACCENT_PRESSED__; }
#newSessionBtn:pressed{ background: __SCROLLBAR__; }

/* ── Toggle button (tool card) ────────────────────────────────────── */
#toggleBtn {
    background: __SURFACE_RAISED__; color: __ACCENT__;
    border: none; border-radius: 4px;
    font-size: 11px; padding: 2px 8px;
}
#toggleBtn:hover { background: __BORDER__; }

/* ── Dialogs ──────────────────────────────────────────────────────── */
QDialog { background: __SURFACE__; }
QLabel { background: transparent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QComboBox {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 8px;
    padding: 6px 10px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: __BORDER_FOCUS__; background: __SURFACE__;
}
QTabWidget::pane {
    border: 1px solid __BORDER__; border-radius: 8px;
    background: __SURFACE__;
}
QTabBar::tab {
    background: __SURFACE_RAISED__; color: __TEXT_MUTED__;
    padding: 6px 16px; border-radius: 8px 8px 0 0;
}
QTabBar::tab:selected { background: __SURFACE__; color: __TEXT__; }
QPushButton {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: none; border-radius: 8px; padding: 6px 14px;
}
QPushButton:hover  { background: __BORDER__; }
QPushButton:pressed{ background: __SCROLLBAR__; }
QDialogButtonBox QPushButton {
    min-width: 70px;
    background: __ACCENT__; color: __TEXT_ACCENT__;
}
QDialogButtonBox QPushButton:hover { background: __ACCENT_HOVER__; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid __SCROLLBAR__; border-radius: 4px;
    background: __SURFACE__;
}
QCheckBox::indicator:checked { background: __ACCENT__; border-color: __ACCENT__; }
QTableWidget {
    background: __SURFACE__;
    border: 1px solid __BORDER__; border-radius: 8px;
    gridline-color: __SURFACE_RAISED__; color: __TEXT__;
}
QTableWidget::item { padding: 6px 8px; }
QTableWidget::item:selected { background: __SELECTED__; color: __TEXT__; }
QHeaderView::section {
    background: __SURFACE_RAISED__; color: __TEXT_SECONDARY__;
    padding: 8px 10px; border: none;
    border-bottom: 1px solid __BORDER__;
    font-size: 12px; font-weight: 600;
}
QScrollBar:vertical { width: 6px; background: transparent; }
QScrollBar::handle:vertical {
    background: __SCROLLBAR__; border-radius: 3px; min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: __SCROLLBAR_HOVER__; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Typing indicator ─────────────────────────────────────────────── */
#typingLabel { color: __TEXT_MUTED__; font-size: 12px; font-style: italic; }

/* ── Tray / context menu ──────────────────────────────────────────── */
QMenu {
    background: __SURFACE__;
    border: 1px solid __BORDER__; border-radius: 10px;
    padding: 6px 4px; color: __TEXT__;
}
QMenu::item {
    padding: 7px 28px 7px 14px; border-radius: 6px;
    color: __TEXT__; background: transparent;
}
QMenu::item:selected { background: __SURFACE_RAISED__; color: __TEXT__; }
QMenu::item:disabled { color: __SCROLLBAR__; }
QMenu::separator {
    height: 1px; background: __BORDER__; margin: 4px 10px;
}

/* ── Notes panel ──────────────────────────────────────────────────── */
#noteListPanel { background: __SURFACE__; border-radius: 8px 0 0 8px; }
#noteList { background: transparent; border: none; outline: none; }
#noteList::item {
    padding: 8px 10px; border-radius: 6px;
    color: __TEXT_SECONDARY__; font-size: 12px; line-height: 1.4;
}
#noteList::item:selected { background: __SELECTED__; color: __TEXT__; }
#noteList::item:hover:!selected { background: __SURFACE_RAISED__; }
#noteTitleEdit {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 8px;
    padding: 8px 12px; font-size: 14px; font-weight: 600;
}
#noteTitleEdit:focus { border-color: __BORDER_FOCUS__; background: __SURFACE__; }
#noteContentEdit {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 8px;
    padding: 8px 12px; font-size: 13px;
}
#noteContentEdit:focus { border-color: __BORDER_FOCUS__; background: __SURFACE__; }
#noteToolBtn {
    background: __SURFACE_RAISED__; color: __TEXT__;
    border: none; border-radius: 8px;
    padding: 5px 14px; font-size: 12px;
}
#noteToolBtn:hover  { background: __BORDER__; color: __TEXT__; }
#noteToolBtn:pressed{ background: __SCROLLBAR__; }

/* ── View-switcher buttons ────────────────────────────────────────── */
#viewBtn {
    background: transparent; color: __TEXT_SECONDARY__;
    border: none; border-radius: 6px;
    font-size: 12px; font-weight: 500;
}
#viewBtn:hover   { background: __SURFACE_RAISED__; color: __TEXT__; }
#viewBtn:checked { background: __SELECTED__; color: __ACCENT__; font-weight: 600; }
#viewBtn:checked:hover { background: __USER_BUBBLE__; color: __ACCENT_PRESSED__; }

#noteStatusLabel { color: __SUCCESS__; font-size: 11px; padding: 0 6px; }

/* ── Size grip (unused) ───────────────────────────────────────────── */
#sizeGrip { background: transparent; width: 14px; height: 14px; }
"""


# ── Public API ─────────────────────────────────────────────────────────

def generate_stylesheet(theme_name: str) -> str:
    """Fill the QSS template with a theme's colour tokens."""
    colors = THEMES.get(theme_name, THEMES["classic"])
    css = _TEMPLATE
    for key, val in colors.items():
        if key == "name":
            continue
        css = css.replace(f"__{key.upper()}__", val)
    return css


# Default – kept for backward compat (used at import time by main.py)
STYLESHEET = generate_stylesheet("classic")
