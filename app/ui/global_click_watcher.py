"""浮窗外部点击监听 —— 划词浮标 / 结果气泡共用。

划词浮窗显示后，点击其外部区域应立即关闭。Qt 自身的焦点事件在不抢焦点
（WS_EX_NOACTIVATE）的窗口上不可靠，因此用全局 mouse hook 监听整个屏幕的
点击，命中判定交给调用方提供的「物理几何」。

★ 线程亲和性：mouse hook 回调在 hook 线程执行，不能直接操作 Qt 控件。本组件
只在 hook 线程做命中判定，要关闭时调用注入的 ``on_hide_requested`` 回调；调用方
负责把它接到一个 pyqtSignal 上 marshal 回主线程（见 TextActionPopup /
ResultBubble 的 _hide_requested 信号）。

★ 缩放屏：mouse hook 拿到的是**物理像素**坐标，调用方提供的几何也必须是物理
像素（见各浮窗的 _cached_geo_physical），否则在 125%/150% 屏上点击浮窗内部会
被误判成「外部」而误关。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QRect

logger = logging.getLogger(__name__)

try:
    import mouse as _mouse

    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False


class GlobalClickWatcher:
    """监听浮窗外部点击的全局 mouse hook 封装。

    用法：调用方在 showEvent 里 install()、hideEvent 里 remove()，并提供：
      - geometry_provider: 返回当前浮窗的**物理像素**几何（QRect | None）。
        每次点击时实时取，避免持有过期几何。
      - on_hide_requested: hook 线程中要求关闭时调用（无参）。调用方应在此把
        请求 marshal 回主线程。

    规则：右键任意位置 → 关闭；左键点在几何外 → 关闭；左键点在几何内 → 不干涉
    （交给 Qt 主循环处理按钮 clicked / 背景 mousePressEvent）。
    """

    def __init__(
        self,
        *,
        geometry_provider: Callable[[], QRect | None],
        on_hide_requested: Callable[[], None],
        owner_name: str = "Popup",
    ):
        self._geometry_provider = geometry_provider
        self._on_hide_requested = on_hide_requested
        self._owner_name = owner_name
        self._hook: Callable | None = None

    def install(self) -> None:
        """安装全局 mouse hook。重复调用安全（已装则忽略）。"""
        if not _MOUSE_OK:
            return
        if self._hook is not None:
            return
        try:
            self._hook = _mouse.hook(self._on_global_event)
        except Exception:
            logger.warning(
                "%s: mouse hook 安装失败，点击弹窗外部将无法关闭",
                self._owner_name,
                exc_info=True,
            )

    def remove(self) -> None:
        """卸载 mouse hook。卸载失败时保留引用，避免下次重复安装导致泄漏。"""
        if self._hook is None:
            return
        try:
            _mouse.unhook(self._hook)
        except Exception:
            logger.warning(
                "%s: mouse hook 卸载失败", self._owner_name, exc_info=True
            )
            return
        self._hook = None

    def _on_global_event(self, event):
        """mouse hook 回调（在 hook 线程执行）。

        右键任意位置 → 请求关闭。
        左键点浮窗以外区域 → 请求关闭；点在浮窗内 → 不干涉。
        """
        event_type = getattr(event, "event_type", None)
        if event_type != "down":
            return
        button = getattr(event, "button", None)
        if button == _mouse.RIGHT:
            self._on_hide_requested()
            return
        if button == _mouse.LEFT:
            geo = self._geometry_provider()  # 物理像素几何，本地引用避免竞争
            if geo is not None:
                x, y = _mouse.get_position()
                if not geo.contains(x, y):
                    self._on_hide_requested()
