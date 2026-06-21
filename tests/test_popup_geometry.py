"""测试划词浮窗定位的纯几何函数 place_below_anchor。

不需要 QApplication：QRect 是纯值对象。验证锚点居中、四向边缘修正、
下方空间不足翻到上方，以及缩放屏下的物理像素换算。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtCore import QRect

from app.ui.popup_geometry import GAP_PX, place_below_anchor

# 一块 1920x1080、原点在 (0,0) 的虚拟屏幕。
_SCREEN = QRect(0, 0, 1920, 1080)


def test_centers_below_anchor_in_open_space():
    # Arrange: 屏幕正中的锚点，浮窗 100x40
    placed = place_below_anchor(100, 40, 960, 500, _SCREEN)

    # Act / Assert: 水平居中（x = anchor - w/2），顶边在 anchor + gap
    assert placed.logical == QRect(960 - 50, 500 + GAP_PX, 100, 40)


def test_clamps_to_right_edge():
    # 锚点贴近右边，浮窗会越过 right()，应左移贴边。
    # 注意 QRect.right() 是 left+width-1（含边界），定位逻辑用 right()-width
    # 作为左上角，故 x == right() - width。
    placed = place_below_anchor(200, 40, 1910, 500, _SCREEN)

    assert placed.logical.x() == _SCREEN.right() - 200
    assert placed.logical.width() == 200


def test_clamps_to_left_edge():
    # 锚点贴近左边，浮窗会越过 left()，应贴左边
    placed = place_below_anchor(200, 40, 5, 500, _SCREEN)

    assert placed.logical.left() == _SCREEN.left()


def test_flips_above_when_no_room_below():
    # 锚点贴近底边，下方放不下，应翻到锚点上方
    anchor_y = 1070
    placed = place_below_anchor(100, 60, 960, anchor_y, _SCREEN)

    # 翻转后顶边 = anchor_y - height - gap
    assert placed.logical.y() == anchor_y - 60 - GAP_PX


def test_clamps_to_top_after_flip():
    # 极端：翻到上方仍越界（锚点高、浮窗高），贴顶边
    placed = place_below_anchor(100, 2000, 960, 1070, _SCREEN)

    assert placed.logical.top() == _SCREEN.top()


def test_no_screen_geo_skips_edge_correction():
    # 拿不到屏幕时不做边缘修正，原样按锚点摆放
    placed = place_below_anchor(100, 40, 5, 500, None)

    assert placed.logical == QRect(5 - 50, 500 + GAP_PX, 100, 40)


def test_physical_equals_logical_at_scale_1():
    placed = place_below_anchor(100, 40, 960, 500, _SCREEN, scale=1.0)

    assert placed.physical == placed.logical


def test_physical_scales_at_150_percent():
    # 1.5 倍缩放：物理几何 = 逻辑几何 × 1.5（四舍五入）
    placed = place_below_anchor(100, 40, 960, 500, _SCREEN, scale=1.5)

    lg = placed.logical
    assert placed.physical == QRect(
        round(lg.x() * 1.5),
        round(lg.y() * 1.5),
        round(lg.width() * 1.5),
        round(lg.height() * 1.5),
    )


def test_custom_gap_applied():
    placed = place_below_anchor(100, 40, 960, 500, _SCREEN, gap=20)

    assert placed.logical.y() == 500 + 20
