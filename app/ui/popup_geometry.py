"""划词浮窗定位 —— 紧贴选区下方摆放，含边缘修正与物理像素换算。

划词浮标与结果气泡都「锚定在选区下方居中」，且都要：
  - 屏幕边缘修正：左右越界贴边，下方空间不足则翻到选区上方；
  - 物理像素几何：全局 mouse hook 拿到的是物理像素坐标，需按屏幕缩放比
    （devicePixelRatio）换算出物理几何供命中判定，否则缩放屏上误判内外。

把这套纯几何计算抽成无副作用的函数，便于单测（给定屏幕几何 + 缩放比，
验证贴边 / 翻转 / 物理换算），调用方只负责查屏幕与实际 move()。
"""
from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRect

# 浮窗与选区之间的间距（px）。划词浮标 / 结果气泡 / tooltip 共用。
GAP_PX = 4


class PlacedGeometry(NamedTuple):
    """定位结果：逻辑像素几何（供 Qt move/resize）+ 物理像素几何（供 hook 比对）。"""

    logical: QRect
    physical: QRect


def place_below_anchor(
    width: int,
    height: int,
    anchor_x: int,
    anchor_y: int,
    screen_geo: QRect | None,
    scale: float = 1.0,
    gap: int = GAP_PX,
) -> PlacedGeometry:
    """把 width×height 的浮窗摆到锚点下方居中，返回逻辑 + 物理几何。

    Args:
        width, height: 浮窗逻辑尺寸（px）。
        anchor_x: 选区水平中心（逻辑像素），浮窗据此水平居中。
        anchor_y: 选区底边（逻辑像素），浮窗顶边落在其下方 gap 处。
        screen_geo: 目标屏幕的 availableGeometry（逻辑像素）。None 表示不做
            边缘修正（拿不到屏幕时的退化路径）。
        scale: 屏幕缩放比（devicePixelRatio），用于换算物理几何。
        gap: 浮窗与选区之间的间距。

    Returns:
        PlacedGeometry(logical, physical)。

    边缘修正规则：
        - 右越界 → 左移贴右边；左越界 → 贴左边；
        - 下方放不下 → 翻到锚点上方（顶边 = anchor_y - height - gap）；
        - 上方仍越界 → 贴顶边。
    """
    px = anchor_x - width // 2
    py = anchor_y + gap

    if screen_geo is not None:
        if px + width > screen_geo.right():
            px = screen_geo.right() - width
        if px < screen_geo.left():
            px = screen_geo.left()
        if py + height > screen_geo.bottom():
            py = anchor_y - height - gap  # 翻到选区上方
        if py < screen_geo.top():
            py = screen_geo.top()

    logical = QRect(px, py, width, height)
    physical = QRect(
        round(px * scale),
        round(py * scale),
        round(width * scale),
        round(height * scale),
    )
    return PlacedGeometry(logical=logical, physical=physical)
