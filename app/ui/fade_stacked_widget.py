"""
页面切换淡入淡出 StackedWidget（快照交叉淡化）。

FluentWindow 默认用 PopUpAniStackedWidget（页面从下往上滑入），其
setCurrentIndex 在动画结束时会再调一次 super().setCurrentIndex 触发
relayout，导致页面归位后有明显"一跳"（滑入终点 pos 与布局位置不完全一致 /
二次 relayout）。本模块用无位移的透明度过渡替代，无位移则无跳动。

性能关键：早期实现把 QGraphicsOpacityEffect 直接挂在目标页整棵子树上做
0→1 淡入，动画 320ms 内每帧都要把该子树离屏栅格化一遍。聊天页含大量
QTextBrowser 富文本气泡时逐帧栅格化开销极大，切到聊天页明显卡顿。

改为「快照交叉淡化」：
  1. 切换前把当前（旧）页 grab 成一张静态 pixmap；
  2. 立刻切到目标页（目标页不透明、正常显示，不套任何 effect）；
  3. 用一个覆盖层 QLabel 显示旧页快照盖在切换区上，对这张 *单张位图* 做
     opacity 1→0 淡出，露出下面的新页 —— 视觉上即交叉淡化。
动画期间只栅格化一张静态 pixmap（成本恒定），新页富文本子树完全不参与逐帧
栅格化，从根上消除卡顿。旧页快照淡出、新页始终在下方完整可见，也不会有
后退方向的空窗闪烁。

用法：构造 FluentWindow 后、addSubInterface 之前，调用
    install_fade_transition(window)
把内部 stackedWidget.view 替换为本类实例。
"""

import logging

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget, QWidget

logger = logging.getLogger(__name__)

FADE_MS = 320


class FadeStackedWidget(QStackedWidget):
    """快照交叉淡化的 stacked widget，接口兼容 FluentWindow 的容器调用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # FluentWindow 容器（window/stacked_widget.py:StackedWidget）会读写这个属性，
        # 保留以兼容其 isAnimationEnabled()/setAnimationEnabled()。
        self.isAnimationEnabled = True
        self._overlay: QLabel | None = None
        self._ani: QPropertyAnimation | None = None

    def setAnimationEnabled(self, enabled: bool) -> None:
        self.isAnimationEnabled = enabled

    # FluentWindow 容器会带 duration / popOut / easingCurve 等位置参数调用，
    # 这里一律吞掉——本实现只做快照交叉淡化。
    def setCurrentWidget(self, widget: QWidget, *args, **kwargs) -> None:
        self.setCurrentIndex(self.indexOf(widget))

    def setCurrentIndex(self, index: int, *args, **kwargs) -> None:
        if index < 0 or index >= self.count() or index == self.currentIndex():
            return
        if not self.isAnimationEnabled:
            super().setCurrentIndex(index)
            return

        # 停掉进行中的动画并清掉旧覆盖层，避免叠加 / 残留。
        self._stop_running()

        # 切换前抓当前页快照：此刻旧页仍可见、几何正确，grab 一次（一次性成本，
        # 非逐帧）。拿不到旧页就退化为无动画瞬时切换。
        old = self.currentWidget()
        pixmap = old.grab() if old is not None else None

        old_geom = old.geometry() if old is not None else None
        super().setCurrentIndex(index)

        if pixmap is None or pixmap.isNull() or old_geom is None:
            return

        overlay = QLabel(self)
        overlay.setPixmap(pixmap)
        overlay.setGeometry(old_geom)
        # 快照仅用于过渡，鼠标事件穿透到下方真实新页，避免 320ms 内点击被吞。
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.show()
        overlay.raise_()

        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        ani = QPropertyAnimation(effect, b"opacity", self)
        ani.setDuration(FADE_MS)
        ani.setStartValue(1.0)
        ani.setEndValue(0.0)
        # InOutQuad：中段渐变更均匀，过渡更能被平滑感知。
        ani.setEasingCurve(QEasingCurve.Type.InOutQuad)
        ani.finished.connect(self._on_finished)
        self._overlay = overlay
        self._ani = ani
        ani.start()

    def _stop_running(self) -> None:
        if self._ani is not None:
            if self._ani.state() == QPropertyAnimation.State.Running:
                self._ani.stop()
            self._ani = None
        self._clear_overlay()

    def _on_finished(self) -> None:
        self._clear_overlay()
        self._ani = None

    def _clear_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None


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
