"""
Fluent Design 主题系统。

将应用主题桥接到 qfluentwidgets 内置主题，并提供一层自定义 QSS
用于应用特有元素（消息气泡、容器等）。Fluent 组件自身由库自动样式化。
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
    "almond": {
        "name": "杏仁奶咖",
        "mode": Theme.LIGHT,
        "accent": "#B07D56",
        "accent_light": "#EBDDCE",
        "accent_subtle": "rgba(176,125,86,0.09)",
        "user_bubble": "#F3E7D8",
        "user_bubble_border": "#E2CDB4",
        "bg": "rgba(244,237,228,0.90)",
        "bg_solid": "#F4EDE4",
        "surface": "rgba(250,244,236,0.93)",
        "surface_solid": "#FAF4EC",
        "surface_raised": "#EDE2D4",
        "border": "rgba(90,60,30,0.08)",
        "border_solid": "#DECBB4",
        "text": "#4A3F35",
        "text_secondary": "#7A6A58",
        "text_muted": "#A8967F",
        "ai_bubble": "rgba(250,244,236,0.92)",
        "ai_bubble_border": "rgba(90,60,30,0.08)",
        "scrollbar": "rgba(74,63,53,0.12)",
        "scrollbar_hover": "rgba(74,63,53,0.24)",
        "selected": "rgba(74,63,53,0.05)",
        "hover": "rgba(74,63,53,0.04)",
        "success": "#5C8A4E",
        "error": "#C25B4E",
        "warning": "#C4912F",
    },
    "misty": {
        "name": "雾屿青岚",
        "mode": Theme.LIGHT,
        "accent": "#4F7C8C",
        "accent_light": "#D5E3E7",
        "accent_subtle": "rgba(79,124,140,0.09)",
        "user_bubble": "#DCE8EB",
        "user_bubble_border": "#C2D5DA",
        "bg": "rgba(229,235,237,0.90)",
        "bg_solid": "#E5EBED",
        "surface": "rgba(240,245,246,0.93)",
        "surface_solid": "#F0F5F6",
        "surface_raised": "#DEE7E9",
        "border": "rgba(30,55,65,0.08)",
        "border_solid": "#C7D5D8",
        "text": "#33454C",
        "text_secondary": "#5E737B",
        "text_muted": "#90A4AB",
        "ai_bubble": "rgba(240,245,246,0.92)",
        "ai_bubble_border": "rgba(30,55,65,0.08)",
        "scrollbar": "rgba(51,69,76,0.12)",
        "scrollbar_hover": "rgba(51,69,76,0.24)",
        "selected": "rgba(51,69,76,0.05)",
        "hover": "rgba(51,69,76,0.04)",
        "success": "#4F8A6B",
        "error": "#C25F5A",
        "warning": "#C68A3E",
    },
    "sage": {
        "name": "鼠尾草绿",
        "mode": Theme.LIGHT,
        "accent": "#5E7A52",
        "accent_light": "#DAE5D2",
        "accent_subtle": "rgba(94,122,82,0.09)",
        "user_bubble": "#E2EAD9",
        "user_bubble_border": "#CBD8BE",
        "bg": "rgba(233,237,228,0.90)",
        "bg_solid": "#E9EDE4",
        "surface": "rgba(243,246,238,0.93)",
        "surface_solid": "#F3F6EE",
        "surface_raised": "#E2E8D8",
        "border": "rgba(40,60,30,0.08)",
        "border_solid": "#CCD8BF",
        "text": "#3C4636",
        "text_secondary": "#67735C",
        "text_muted": "#9AA68C",
        "ai_bubble": "rgba(243,246,238,0.92)",
        "ai_bubble_border": "rgba(40,60,30,0.08)",
        "scrollbar": "rgba(60,70,54,0.12)",
        "scrollbar_hover": "rgba(60,70,54,0.24)",
        "selected": "rgba(60,70,54,0.05)",
        "hover": "rgba(60,70,54,0.04)",
        "success": "#5C8A4E",
        "error": "#BD5B50",
        "warning": "#C18A33",
    },
    # ─── Morandi Palettes ────────────────────────────────────────────
    "morandi_clay": {
        "name": "莫兰迪·陶土",
        "mode": Theme.LIGHT,
        "accent": "#A4756B",
        "accent_light": "#E6D6D0",
        "accent_subtle": "rgba(164,117,107,0.09)",
        "user_bubble": "#EADFD9",
        "user_bubble_border": "#D9C7BF",
        "bg": "rgba(237,230,225,0.90)",
        "bg_solid": "#EDE6E1",
        "surface": "rgba(246,240,236,0.93)",
        "surface_solid": "#F6F0EC",
        "surface_raised": "#E7DCD5",
        "border": "rgba(80,55,45,0.08)",
        "border_solid": "#DACBC2",
        "text": "#4D423D",
        "text_secondary": "#7C6E67",
        "text_muted": "#A99B92",
        "ai_bubble": "rgba(246,240,236,0.92)",
        "ai_bubble_border": "rgba(80,55,45,0.08)",
        "scrollbar": "rgba(77,66,61,0.12)",
        "scrollbar_hover": "rgba(77,66,61,0.24)",
        "selected": "rgba(77,66,61,0.05)",
        "hover": "rgba(77,66,61,0.04)",
        "success": "#7E9277",
        "error": "#B5726B",
        "warning": "#C0995E",
    },
    "morandi_haze": {
        "name": "莫兰迪·雾霭蓝",
        "mode": Theme.LIGHT,
        "accent": "#7E909B",
        "accent_light": "#DCE3E8",
        "accent_subtle": "rgba(126,144,155,0.09)",
        "user_bubble": "#E2E8EC",
        "user_bubble_border": "#CBD5DC",
        "bg": "rgba(233,237,240,0.90)",
        "bg_solid": "#E9EDF0",
        "surface": "rgba(243,246,248,0.93)",
        "surface_solid": "#F3F6F8",
        "surface_raised": "#E0E6EA",
        "border": "rgba(45,60,70,0.08)",
        "border_solid": "#CDD8DE",
        "text": "#3E484E",
        "text_secondary": "#6B777E",
        "text_muted": "#9AA5AB",
        "ai_bubble": "rgba(243,246,248,0.92)",
        "ai_bubble_border": "rgba(45,60,70,0.08)",
        "scrollbar": "rgba(62,72,78,0.12)",
        "scrollbar_hover": "rgba(62,72,78,0.24)",
        "selected": "rgba(62,72,78,0.05)",
        "hover": "rgba(62,72,78,0.04)",
        "success": "#7E9277",
        "error": "#B5726B",
        "warning": "#C0995E",
    },
    "morandi_olive": {
        "name": "莫兰迪·豆绿",
        "mode": Theme.LIGHT,
        "accent": "#8A9275",
        "accent_light": "#DEE2D2",
        "accent_subtle": "rgba(138,146,117,0.09)",
        "user_bubble": "#E4E7D9",
        "user_bubble_border": "#CFD4BF",
        "bg": "rgba(235,237,228,0.90)",
        "bg_solid": "#EBEDE4",
        "surface": "rgba(244,246,238,0.93)",
        "surface_solid": "#F4F6EE",
        "surface_raised": "#E3E6D8",
        "border": "rgba(60,65,45,0.08)",
        "border_solid": "#D2D7C2",
        "text": "#454A3C",
        "text_secondary": "#717764",
        "text_muted": "#A2A795",
        "ai_bubble": "rgba(244,246,238,0.92)",
        "ai_bubble_border": "rgba(60,65,45,0.08)",
        "scrollbar": "rgba(69,74,60,0.12)",
        "scrollbar_hover": "rgba(69,74,60,0.24)",
        "selected": "rgba(69,74,60,0.05)",
        "hover": "rgba(69,74,60,0.04)",
        "success": "#7E9277",
        "error": "#B5726B",
        "warning": "#C0995E",
    },
    "morandi_lilac": {
        "name": "莫兰迪·藕荷",
        "mode": Theme.LIGHT,
        "accent": "#9B8A9E",
        "accent_light": "#E4DCE5",
        "accent_subtle": "rgba(155,138,158,0.09)",
        "user_bubble": "#E8E1E9",
        "user_bubble_border": "#D6CAD7",
        "bg": "rgba(237,232,238,0.90)",
        "bg_solid": "#EDE8EE",
        "surface": "rgba(246,242,247,0.93)",
        "surface_solid": "#F6F2F7",
        "surface_raised": "#E6DEE7",
        "border": "rgba(65,50,68,0.08)",
        "border_solid": "#DACEDB",
        "text": "#473F49",
        "text_secondary": "#766E78",
        "text_muted": "#A69EA8",
        "ai_bubble": "rgba(246,242,247,0.92)",
        "ai_bubble_border": "rgba(65,50,68,0.08)",
        "scrollbar": "rgba(71,63,73,0.12)",
        "scrollbar_hover": "rgba(71,63,73,0.24)",
        "selected": "rgba(71,63,73,0.05)",
        "hover": "rgba(71,63,73,0.04)",
        "success": "#7E9277",
        "error": "#B5726B",
        "warning": "#C0995E",
    },
    # ─── Curated Community Palettes (Dark) ───────────────────────────
    "mocha": {
        "name": "摩卡",
        "mode": Theme.DARK,
        "accent": "#CBA6F7",
        "accent_light": "#3A2E50",
        "accent_subtle": "rgba(203,166,247,0.10)",
        "user_bubble": "#45475A",
        "user_bubble_border": "#585B70",
        "bg": "rgba(30,30,46,0.82)",
        "bg_solid": "#1E1E2E",
        "surface": "rgba(49,50,68,0.88)",
        "surface_solid": "#313244",
        "surface_raised": "#45475A",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#45475A",
        "text": "#CDD6F4",
        "text_secondary": "#A6ADC8",
        "text_muted": "#7F849C",
        "ai_bubble": "rgba(49,50,68,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#A6E3A1",
        "error": "#F38BA8",
        "warning": "#F9E2AF",
    },
    "rose_pine": {
        "name": "玫瑰松",
        "mode": Theme.DARK,
        "accent": "#C4A7E7",
        "accent_light": "#2E2A45",
        "accent_subtle": "rgba(196,167,231,0.10)",
        "user_bubble": "#403D52",
        "user_bubble_border": "#524F67",
        "bg": "rgba(25,23,36,0.82)",
        "bg_solid": "#191724",
        "surface": "rgba(31,29,46,0.88)",
        "surface_solid": "#1F1D2E",
        "surface_raised": "#26233A",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#403D52",
        "text": "#E0DEF4",
        "text_secondary": "#908CAA",
        "text_muted": "#6E6A86",
        "ai_bubble": "rgba(31,29,46,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#9CCFD8",
        "error": "#EB6F92",
        "warning": "#F6C177",
    },
    "nord": {
        "name": "北欧极夜",
        "mode": Theme.DARK,
        "accent": "#88C0D0",
        "accent_light": "#2F4A52",
        "accent_subtle": "rgba(136,192,208,0.10)",
        "user_bubble": "#434C5E",
        "user_bubble_border": "#4C566A",
        "bg": "rgba(46,52,64,0.82)",
        "bg_solid": "#2E3440",
        "surface": "rgba(59,66,82,0.88)",
        "surface_solid": "#3B4252",
        "surface_raised": "#434C5E",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#4C566A",
        "text": "#ECEFF4",
        "text_secondary": "#AEB6C4",
        "text_muted": "#7B8494",
        "ai_bubble": "rgba(59,66,82,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#A3BE8C",
        "error": "#BF616A",
        "warning": "#EBCB8B",
    },
    "everforest": {
        "name": "林间暮色",
        "mode": Theme.DARK,
        "accent": "#A7C080",
        "accent_light": "#3A4A3A",
        "accent_subtle": "rgba(167,192,128,0.10)",
        "user_bubble": "#475258",
        "user_bubble_border": "#4F585E",
        "bg": "rgba(45,53,59,0.82)",
        "bg_solid": "#2D353B",
        "surface": "rgba(52,63,68,0.88)",
        "surface_solid": "#343F44",
        "surface_raised": "#3D484D",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#4F585E",
        "text": "#D3C6AA",
        "text_secondary": "#9DA9A0",
        "text_muted": "#859289",
        "ai_bubble": "rgba(52,63,68,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#83C092",
        "error": "#E67E80",
        "warning": "#DBBC7F",
    },
    "everforest_bright": {
        "name": "林间晨光",
        "mode": Theme.DARK,
        "accent": "#B7CE8F",
        "accent_light": "#45543E",
        "accent_subtle": "rgba(183,206,143,0.12)",
        "user_bubble": "#54606A",
        "user_bubble_border": "#616D77",
        "bg": "rgba(56,65,74,0.84)",
        "bg_solid": "#38414A",
        "surface": "rgba(66,77,86,0.90)",
        "surface_solid": "#424D56",
        "surface_raised": "#4D5962",
        "border": "rgba(255,255,255,0.08)",
        "border_solid": "#5C6872",
        "text": "#E6DCC6",
        "text_secondary": "#B4BEB4",
        "text_muted": "#96A198",
        "ai_bubble": "rgba(66,77,86,0.90)",
        "ai_bubble_border": "rgba(255,255,255,0.08)",
        "scrollbar": "rgba(255,255,255,0.12)",
        "scrollbar_hover": "rgba(255,255,255,0.22)",
        "selected": "rgba(255,255,255,0.07)",
        "hover": "rgba(255,255,255,0.05)",
        "success": "#8FCF9E",
        "error": "#E88A8C",
        "warning": "#E0C489",
    },
    "solarized": {
        "name": "深海靛青",
        "mode": Theme.DARK,
        "accent": "#268BD2",
        "accent_light": "#13415A",
        "accent_subtle": "rgba(38,139,210,0.10)",
        "user_bubble": "#0B3D4D",
        "user_bubble_border": "#1A4E5E",
        "bg": "rgba(0,43,54,0.84)",
        "bg_solid": "#002B36",
        "surface": "rgba(7,54,66,0.89)",
        "surface_solid": "#073642",
        "surface_raised": "#0E4B5A",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#0E4B5A",
        "text": "#93A1A1",
        "text_secondary": "#839496",
        "text_muted": "#586E75",
        "ai_bubble": "rgba(7,54,66,0.89)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#859900",
        "error": "#DC322F",
        "warning": "#B58900",
    },
    "gruvbox": {
        "name": "复古琥珀",
        "mode": Theme.DARK,
        "accent": "#FE8019",
        "accent_light": "#5A3D24",
        "accent_subtle": "rgba(254,128,25,0.10)",
        "user_bubble": "#3D3528",
        "user_bubble_border": "#504333",
        "bg": "rgba(40,40,40,0.82)",
        "bg_solid": "#282828",
        "surface": "rgba(60,56,54,0.88)",
        "surface_solid": "#3C3836",
        "surface_raised": "#504945",
        "border": "rgba(255,255,255,0.07)",
        "border_solid": "#504945",
        "text": "#EBDBB2",
        "text_secondary": "#A89984",
        "text_muted": "#7C6F64",
        "ai_bubble": "rgba(60,56,54,0.88)",
        "ai_bubble_border": "rgba(255,255,255,0.07)",
        "scrollbar": "rgba(255,255,255,0.10)",
        "scrollbar_hover": "rgba(255,255,255,0.20)",
        "selected": "rgba(255,255,255,0.06)",
        "hover": "rgba(255,255,255,0.04)",
        "success": "#B8BB26",
        "error": "#FB4934",
        "warning": "#FABD2F",
    },
    # ─── Curated Community Palettes (Light) ──────────────────────────
    "latte": {
        "name": "拿铁",
        "mode": Theme.LIGHT,
        "accent": "#8839EF",
        "accent_light": "#E5D8FA",
        "accent_subtle": "rgba(136,57,239,0.08)",
        "user_bubble": "#DCE0E8",
        "user_bubble_border": "#BCC0CC",
        "bg": "rgba(239,241,245,0.88)",
        "bg_solid": "#EFF1F5",
        "surface": "rgba(255,255,255,0.92)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#E6E9EF",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#CCD0DA",
        "text": "#4C4F69",
        "text_secondary": "#6C6F85",
        "text_muted": "#8C8FA1",
        "ai_bubble": "rgba(255,255,255,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#40A02B",
        "error": "#D20F39",
        "warning": "#DF8E1D",
    },
    "rose_pine_dawn": {
        "name": "玫瑰晨曦",
        "mode": Theme.LIGHT,
        "accent": "#907AA9",
        "accent_light": "#E8DEF0",
        "accent_subtle": "rgba(144,122,169,0.08)",
        "user_bubble": "#EFE5DD",
        "user_bubble_border": "#DFDAD9",
        "bg": "rgba(250,244,237,0.88)",
        "bg_solid": "#FAF4ED",
        "surface": "rgba(255,250,243,0.92)",
        "surface_solid": "#FFFAF3",
        "surface_raised": "#F2E9E1",
        "border": "rgba(0,0,0,0.05)",
        "border_solid": "#DFDAD9",
        "text": "#575279",
        "text_secondary": "#797593",
        "text_muted": "#9893A5",
        "ai_bubble": "rgba(255,250,243,0.90)",
        "ai_bubble_border": "rgba(0,0,0,0.05)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#56949F",
        "error": "#B4637A",
        "warning": "#EA9D34",
    },
    "solarized_light": {
        "name": "晨曦米黄",
        "mode": Theme.LIGHT,
        "accent": "#268BD2",
        "accent_light": "#D8E5DF",
        "accent_subtle": "rgba(38,139,210,0.09)",
        "user_bubble": "#EEE3C6",
        "user_bubble_border": "#DDD3B5",
        "bg": "rgba(253,246,227,0.90)",
        "bg_solid": "#FDF6E3",
        "surface": "rgba(255,251,239,0.93)",
        "surface_solid": "#FFFBEF",
        "surface_raised": "#EEE8D5",
        "border": "rgba(40,60,65,0.08)",
        "border_solid": "#DDD6C1",
        "text": "#586E75",
        "text_secondary": "#657B83",
        "text_muted": "#93A1A1",
        "ai_bubble": "rgba(255,251,239,0.92)",
        "ai_bubble_border": "rgba(40,60,65,0.08)",
        "scrollbar": "rgba(88,110,117,0.12)",
        "scrollbar_hover": "rgba(88,110,117,0.24)",
        "selected": "rgba(88,110,117,0.05)",
        "hover": "rgba(88,110,117,0.04)",
        "success": "#859900",
        "error": "#DC322F",
        "warning": "#B58900",
    },
    "gruvbox_light": {
        "name": "暖砂浅褐",
        "mode": Theme.LIGHT,
        "accent": "#D65D0E",
        "accent_light": "#EADBB5",
        "accent_subtle": "rgba(214,93,14,0.09)",
        "user_bubble": "#EFE0B8",
        "user_bubble_border": "#E0CFA3",
        "bg": "rgba(251,241,199,0.90)",
        "bg_solid": "#FBF1C7",
        "surface": "rgba(249,245,215,0.93)",
        "surface_solid": "#F9F5D7",
        "surface_raised": "#EBDBB2",
        "border": "rgba(80,60,40,0.08)",
        "border_solid": "#E0D2A8",
        "text": "#3C3836",
        "text_secondary": "#665C54",
        "text_muted": "#928374",
        "ai_bubble": "rgba(249,245,215,0.92)",
        "ai_bubble_border": "rgba(80,60,40,0.08)",
        "scrollbar": "rgba(60,56,54,0.12)",
        "scrollbar_hover": "rgba(60,56,54,0.24)",
        "selected": "rgba(60,56,54,0.05)",
        "hover": "rgba(60,56,54,0.04)",
        "success": "#79740E",
        "error": "#9D0006",
        "warning": "#B57614",
    },
    # ─── Plain White Themes ──────────────────────────────────────────
    "cloud_white": {
        "name": "云白",
        "mode": Theme.LIGHT,
        "accent": "#22272E",
        "accent_light": "#E2E5EA",
        "accent_subtle": "rgba(34,39,46,0.07)",
        "user_bubble": "#EEF2F7",
        "user_bubble_border": "#D6DEE8",
        "bg": "rgba(255,255,255,0.92)",
        "bg_solid": "#FFFFFF",
        "surface": "rgba(250,251,252,0.94)",
        "surface_solid": "#FAFBFC",
        "surface_raised": "#F0F2F5",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#E1E5EA",
        "text": "#1F2933",
        "text_secondary": "#52606D",
        "text_muted": "#9AA5B1",
        "ai_bubble": "rgba(250,251,252,0.92)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#2E7D32",
        "error": "#D32F2F",
        "warning": "#ED9B00",
    },
    "ivory_paper": {
        "name": "象牙白",
        "mode": Theme.LIGHT,
        "accent": "#6E655B",
        "accent_light": "#E9E2D8",
        "accent_subtle": "rgba(110,101,91,0.08)",
        "user_bubble": "#F5EFE8",
        "user_bubble_border": "#E6DACC",
        "bg": "rgba(253,251,248,0.92)",
        "bg_solid": "#FDFBF8",
        "surface": "rgba(255,254,252,0.94)",
        "surface_solid": "#FFFEFC",
        "surface_raised": "#F4EEE6",
        "border": "rgba(60,45,30,0.06)",
        "border_solid": "#E8DECF",
        "text": "#3A342E",
        "text_secondary": "#6E655B",
        "text_muted": "#A69C8F",
        "ai_bubble": "rgba(255,254,252,0.92)",
        "ai_bubble_border": "rgba(60,45,30,0.06)",
        "scrollbar": "rgba(58,52,46,0.10)",
        "scrollbar_hover": "rgba(58,52,46,0.22)",
        "selected": "rgba(58,52,46,0.04)",
        "hover": "rgba(58,52,46,0.03)",
        "success": "#4F8A4F",
        "error": "#C0564E",
        "warning": "#C4912F",
    },
    "snow_white": {
        "name": "雪白",
        "mode": Theme.LIGHT,
        "accent": "#4B5563",
        "accent_light": "#E2E5EA",
        "accent_subtle": "rgba(75,85,99,0.08)",
        "user_bubble": "#EDEFF2",
        "user_bubble_border": "#DADEE3",
        "bg": "rgba(255,255,255,0.92)",
        "bg_solid": "#FFFFFF",
        "surface": "rgba(248,249,250,0.94)",
        "surface_solid": "#F8F9FA",
        "surface_raised": "#EDEFF1",
        "border": "rgba(0,0,0,0.06)",
        "border_solid": "#DEE1E5",
        "text": "#2B2F36",
        "text_secondary": "#5B626B",
        "text_muted": "#98A0A8",
        "ai_bubble": "rgba(248,249,250,0.92)",
        "ai_bubble_border": "rgba(0,0,0,0.06)",
        "scrollbar": "rgba(0,0,0,0.08)",
        "scrollbar_hover": "rgba(0,0,0,0.18)",
        "selected": "rgba(0,0,0,0.04)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#2E7D46",
        "error": "#C43D3D",
        "warning": "#C7891F",
    },
    "pure_white": {
        "name": "纯白",
        "mode": Theme.LIGHT,
        "accent": "#000000",
        "accent_light": "#E6E6E6",
        "accent_subtle": "rgba(0,0,0,0.06)",
        "user_bubble": "#F2F2F2",
        "user_bubble_border": "#E0E0E0",
        "bg": "rgba(255,255,255,0.94)",
        "bg_solid": "#FFFFFF",
        "surface": "rgba(255,255,255,0.96)",
        "surface_solid": "#FFFFFF",
        "surface_raised": "#F5F5F5",
        "border": "rgba(0,0,0,0.07)",
        "border_solid": "#E4E4E4",
        "text": "#1A1A1A",
        "text_secondary": "#555555",
        "text_muted": "#999999",
        "ai_bubble": "rgba(255,255,255,0.94)",
        "ai_bubble_border": "rgba(0,0,0,0.07)",
        "scrollbar": "rgba(0,0,0,0.09)",
        "scrollbar_hover": "rgba(0,0,0,0.20)",
        "selected": "rgba(0,0,0,0.05)",
        "hover": "rgba(0,0,0,0.03)",
        "success": "#2E7D32",
        "error": "#D32F2F",
        "warning": "#C7891F",
    },
    # ─── Warm White Themes ───────────────────────────────────────────
    "warm_linen": {
        "name": "暖亚麻",
        "mode": Theme.LIGHT,
        "accent": "#9A6B45",
        "accent_light": "#EDDDCB",
        "accent_subtle": "rgba(154,107,69,0.09)",
        "user_bubble": "#F6E9DA",
        "user_bubble_border": "#EBD6BF",
        "bg": "rgba(253,249,243,0.92)",
        "bg_solid": "#FDF9F3",
        "surface": "rgba(255,252,247,0.94)",
        "surface_solid": "#FFFCF7",
        "surface_raised": "#F5EBDD",
        "border": "rgba(90,60,30,0.07)",
        "border_solid": "#EBDDCB",
        "text": "#3B322A",
        "text_secondary": "#6F6255",
        "text_muted": "#A99A88",
        "ai_bubble": "rgba(255,252,247,0.92)",
        "ai_bubble_border": "rgba(90,60,30,0.07)",
        "scrollbar": "rgba(90,60,30,0.10)",
        "scrollbar_hover": "rgba(90,60,30,0.22)",
        "selected": "rgba(90,60,30,0.05)",
        "hover": "rgba(90,60,30,0.03)",
        "success": "#5A8A3C",
        "error": "#C0564E",
        "warning": "#C4912F",
    },
    "warm_almond": {
        "name": "暖杏白",
        "mode": Theme.LIGHT,
        "accent": "#C08A5E",
        "accent_light": "#F0DEC9",
        "accent_subtle": "rgba(192,138,94,0.10)",
        "user_bubble": "#FBEEDD",
        "user_bubble_border": "#F2DEC5",
        "bg": "rgba(255,251,245,0.92)",
        "bg_solid": "#FFFBF5",
        "surface": "rgba(255,253,249,0.94)",
        "surface_solid": "#FFFDF9",
        "surface_raised": "#F9EFE2",
        "border": "rgba(120,80,40,0.06)",
        "border_solid": "#F0E1CF",
        "text": "#4A3B2E",
        "text_secondary": "#7A6653",
        "text_muted": "#B4A28C",
        "ai_bubble": "rgba(255,253,249,0.92)",
        "ai_bubble_border": "rgba(120,80,40,0.06)",
        "scrollbar": "rgba(120,80,40,0.10)",
        "scrollbar_hover": "rgba(120,80,40,0.22)",
        "selected": "rgba(120,80,40,0.05)",
        "hover": "rgba(120,80,40,0.03)",
        "success": "#5E8F49",
        "error": "#C85A4C",
        "warning": "#CE9A34",
    },
}
# fmt: on

# 默认主题（应用各处的 fallback）
DEFAULT_THEME = "almond"

# 当前深色模式状态，供事件过滤器使用
_current_dark_mode = False
# 当前文本颜色，用于光标同步（QSS 不会传播到光标）
_current_text_color: str = "#E8E0D6"
# 当前主题强调色，用于按 accent 亮度推算前景色（如发送按钮图标）
_current_accent: str = "#D4A574"
# 当前主题表面色，用于把强调色混淡（发送按钮背景）
_current_surface: str = "#2A2724"
# 当前主题窗口底色，用于保证按钮与大背景有足够对比
_current_bg: str = "#221F1C"


class _DarkTitleBarFilter(QObject):
    """事件过滤器：对新显示的 QDialog 设置 DWM 深色标题栏。"""

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


# ── 公开 API ────────────────────────────────────────────────────────

def apply_theme(
    theme_name: str,
    opacity: float = 1.0,
    content_font_size: int = 15,
    editor_font_size: int = 15,
) -> str:
    """应用 Fluent 主题并返回应用特有元素的自定义 QSS。"""
    global _current_dark_mode, _filter_instance, _current_text_color, _current_accent, _current_surface, _current_bg
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])
    dark = theme["mode"] == Theme.DARK
    _current_dark_mode = dark
    _current_text_color = theme["text"]
    _current_accent = theme["accent"]
    _current_surface = theme["surface_solid"]
    _current_bg = theme["bg_solid"]
    setTheme(theme["mode"])
    setThemeColor(QColor(theme["accent"]))
    _apply_palette(theme)
    # 安装事件过滤器，处理后续弹出的对话框
    app = QApplication.instance()
    if app is not None and _filter_instance is None:
        _filter_instance = _DarkTitleBarFilter(app)
        app.installEventFilter(_filter_instance)
    # 对所有已存在的顶层窗口应用深色标题栏
    _apply_dark_titlebar_to_all(dark)
    return _build_custom_qss(theme, content_font_size, editor_font_size)


def _apply_dark_titlebar_to_all(dark: bool) -> None:
    """对所有顶层窗口设置 DWM 深色标题栏属性（Windows 11）。"""
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
    """对单个窗口设置 DWM 深色标题栏，需在 widget.show() 之后调用。"""
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
    """设置 QPalette，使 QScrollArea 视口和普通 QWidget 继承正确的背景色。"""
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
    """返回完整的主题字典（身份信息 + 调色板合并）。"""
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def is_dark_theme(theme_name: str) -> bool:
    """指定主题是否为深色模式。"""
    return get_theme(theme_name)["mode"] == Theme.DARK


def themes_by_mode(dark: bool) -> list[str]:
    """按深/浅模式返回主题 id 列表（保持 THEMES 声明顺序）。"""
    return [
        name for name, theme in THEMES.items()
        if (theme["mode"] == Theme.DARK) == dark
    ]


def get_current_theme() -> Dict[str, Any]:
    """返回当前激活主题的字典。

    供独立浮窗/卡片在构建或显示时就地取色，避免各处重复
    ``cfg.get(cfg.theme)`` + ``get_theme()`` 的样板。配置在函数内惰性导入，
    规避 style ←→ config 的循环依赖。
    """
    try:
        from app.core.config import cfg

        return get_theme(cfg.get(cfg.theme))
    except Exception:
        return THEMES[DEFAULT_THEME]



def get_text_color() -> str:
    """返回当前主题的文本颜色十六进制字符串。"""
    return _current_text_color


_BTN_BLEND = 0.4          # 常态：往 surface 混多少（黯淡强度）
_BTN_MIN_CONTRAST = 2.4   # 按钮与窗口背景的最低对比度（保证能区分）


def _resolve_btn_blend() -> float:
    """决定按钮背景往 surface 混的比例。

    暗色主题混淡＝压暗，越混与背景差异越小；浅色主题混淡＝提亮，同样越混
    越贴近浅背景。故从目标比例起，若混出的底色与窗口背景对比低于阈值，
    逐步回退（少混、更接近纯 accent）直到拉开差距。
    """
    bg_lum = _relative_luminance(QColor(_current_bg))
    t = _BTN_BLEND
    while t > 0.0:
        cand = _blend(_current_accent, _current_surface, t)
        if _contrast_ratio(_relative_luminance(QColor(cand)), bg_lum) >= _BTN_MIN_CONTRAST:
            return t
        t -= 0.05
    return 0.0


def get_accent_button_bg() -> str:
    """发送按钮背景色：把强调色往主题表面色混淡。

    满饱和的 accent 作按钮底色太跳、与主题不协调。往 surface 混降低饱和/
    亮度让它黯淡，但通过 _resolve_btn_blend 钳制，保证与大背景仍有足够
    对比、不会糊进去。返回混合后的十六进制。
    """
    return _blend(_current_accent, _current_surface, _resolve_btn_blend())


def get_accent_button_bg_hover() -> str:
    """按钮 hover 态：比常态往 accent 拉回一点（更鲜明）。"""
    t = max(0.0, _resolve_btn_blend() - 0.12)
    return _blend(_current_accent, _current_surface, t)


def get_accent_button_bg_pressed() -> str:
    """按钮 pressed 态：比常态往 surface 多混一点（更暗沉）。"""
    t = min(1.0, _resolve_btn_blend() + 0.12)
    return _blend(_current_accent, _current_surface, t)


def get_accent_text_color() -> str:
    """返回叠在（已混淡的）按钮背景上的前景色（黑或白），取对比度更高者。

    qfluentwidgets 的 PrimaryPushButton 默认在 accent 底上画白色图标/文字，
    浅色强调色（如 Everforest 的 #A7C080）白色对比度过低，发送箭头糊成一片。
    按钮实际底色是 get_accent_button_bg()（混淡后），据此择优黑/白前景。
    """
    bg_lum = _relative_luminance(QColor(get_accent_button_bg()))
    white_ratio = _contrast_ratio(bg_lum, 1.0)
    dark_ratio = _contrast_ratio(bg_lum, _relative_luminance(QColor("#1A1A1A")))
    return "#1A1A1A" if dark_ratio > white_ratio else "#FFFFFF"


def _blend(fg: str, bg: str, t: float) -> str:
    """按比例 t 把 fg 混向 bg（t=0 全 fg，t=1 全 bg），返回十六进制。"""
    c1, c2 = QColor(fg), QColor(bg)
    r = round(c1.red() * (1 - t) + c2.red() * t)
    g = round(c1.green() * (1 - t) + c2.green() * t)
    b = round(c1.blue() * (1 - t) + c2.blue() * t)
    return "#%02X%02X%02X" % (r, g, b)


def _relative_luminance(color: QColor) -> float:
    """WCAG 相对亮度。"""
    def _linear(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * _linear(color.red())
        + 0.7152 * _linear(color.green())
        + 0.0722 * _linear(color.blue())
    )


def _contrast_ratio(lum1: float, lum2: float) -> float:
    """两个相对亮度之间的 WCAG 对比度（1:1 ~ 21:1）。"""
    hi, lo = max(lum1, lum2), min(lum1, lum2)
    return (hi + 0.05) / (lo + 0.05)


def enable_mica(hwnd: int, dark: bool = False) -> bool:
    """为指定窗口句柄启用 Windows 11 Mica 背景效果。"""
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


# ── 内部实现 ─────────────────────────────────────────────────────────

def _build_custom_qss(theme: dict, content_font_size: int = 15, editor_font_size: int = 15) -> str:
    dark = theme["mode"] == Theme.DARK
    accent = theme["accent"]
    accent_light = theme["accent_light"]
    accent_subtle = theme["accent_subtle"]

    bg = theme["bg_solid"]
    surface = theme["surface_solid"]

    user_bg = theme["user_bubble"]

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
   Message Bubbles — user has filled (borderless) bubble, AI is frameless
   ═══════════════════════════════════════════════════════════════════ */
#userMessage {{
    background: {user_bg};
    border: none;
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


# ── 兼容旧接口 ─────────────────────────────────────────────────────────
def generate_stylesheet(theme_name: str) -> str:
    """旧接口兼容；新代码请使用 ``apply_theme``。"""
    return apply_theme(theme_name)
