"""
页面切换淡入淡出 StackedWidget。

FluentWindow 默认用 PopUpAniStackedWidget（页面从下往上滑入），其
setCurrentIndex 在动画结束时会再调一次 super().setCurrentIndex 触发
relayout，导致页面归位后有明显"一跳"（滑入终点 pos 与布局位置不完全一致 /
二次 relayout）。

本模块用纯透明度渐变替代位移动画：无位移则无跳动。每次切换统一为
「立即切到目标页 + 该页透明度 0→1 淡入」，不做旧页淡出，避免后退方向的
空窗闪烁，也不依赖动画索引一一对应。

用法：构造 FluentWindow 后、addSubInterface 之前，调用
    install_fade_transition(window)
把内部 stackedWidget.view 替换为本类实例。
"""

import logging

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

logger = logging.getLogger(__name__)

FADE_MS = 320


class FadeStackedWidget(QStackedWidget):
    """透明度淡入淡出的 stacked widget，接口兼容 FluentWindow 的容器调用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # FluentWindow 容器（window/stacked_widget.py:StackedWidget）会读写这个属性，
        # 保留以兼容其 isAnimationEnabled()/setAnimationEnabled()。
        self.isAnimationEnabled = True
        self._effect: QGraphicsOpacityEffect | None = None
        self._ani: QPropertyAnimation | None = None

    def setAnimationEnabled(self, enabled: bool) -> None:
        self.isAnimationEnabled = enabled

    # FluentWindow 容器会带 duration / popOut / easingCurve 等位置参数调用，
    # 这里一律吞掉——本实现只做淡入。
    def setCurrentWidget(self, widget: QWidget, *args, **kwargs) -> None:
        self.setCurrentIndex(self.indexOf(widget))

    def setCurrentIndex(self, index: int, *args, **kwargs) -> None:
        if index < 0 or index >= self.count() or index == self.currentIndex():
            return
        if not self.isAnimationEnabled:
            super().setCurrentIndex(index)
            return

        # 停掉进行中的动画并清掉旧 effect，避免叠加 / 残留半透明。
        self._stop_running()

        super().setCurrentIndex(index)
        widget = self.widget(index)

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        ani = QPropertyAnimation(effect, b"opacity", self)
        ani.setDuration(FADE_MS)
        ani.setStartValue(0.0)
        ani.setEndValue(1.0)
        # InOutQuad：中段渐变更均匀，比 OutCubic（起步猛冲到位）更能被感知到淡入。
        ani.setEasingCurve(QEasingCurve.Type.InOutQuad)
        ani.finished.connect(self._on_finished)
        self._effect = effect
        self._ani = ani
        ani.start()

    def _stop_running(self) -> None:
        if self._ani is not None:
            if self._ani.state() == QPropertyAnimation.State.Running:
                self._ani.stop()
            self._ani = None
        self._clear_effect()

    def _on_finished(self) -> None:
        # 动画结束移除 effect：QGraphicsOpacityEffect 常驻会拖累重绘性能，
        # 且可能影响子控件的裁剪/透明表现。
        self._clear_effect()
        self._ani = None

    def _clear_effect(self) -> None:
        if self._effect is not None:
            w = self._effect.parent()
            if isinstance(w, QWidget):
                w.setGraphicsEffect(None)
            self._effect = None


def install_fade_transition(window) -> bool:
    """把 FluentWindow 内部 stackedWidget.view 替换为 FadeStackedWidget。

    必须在 addSubInterface 之前调用（否则页面已加进旧 view）。
    返回是否替换成功；结构不符合预期时返回 False，保留原动画（不致命）。
    """
    container = getattr(window, "stackedWidget", None)
    old_view = getattr(container, "view", None)
    if container is None or old_view is None:
        logger.warning("未找到 stackedWidget.view，跳过淡入淡出替换")
        return False
    if old_view.count() > 0:
        logger.warning("stackedWidget 已有页面，淡入淡出须在 addSubInterface 前安装")
        return False

    new_view = FadeStackedWidget(container)
    # 断开旧 view 的 currentChanged→容器 转发，改接新 view。
    try:
        old_view.currentChanged.disconnect(container.currentChanged)
    except (TypeError, RuntimeError):
        pass
    container.hBoxLayout.replaceWidget(old_view, new_view)
    old_view.setParent(None)
    old_view.deleteLater()
    container.view = new_view
    new_view.currentChanged.connect(container.currentChanged)
    return True
