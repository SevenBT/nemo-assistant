"""
Edge-snap-to-hide manager: when the window is dragged to the top screen edge it
slides partially off-screen, leaving a bright indicator tab visible.  Hovering
over the tab slides the window out at the edge; leaving it slides back.

Clicking the tab or using tray "Show" returns the window to its original position.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    QTimer,
)
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QFrame

if TYPE_CHECKING:
    from app.ui.main_window import MainWindow


class EdgeSnapManager(QObject):
    """Per-window manager – attach one per MainWindow. Snaps to top edge only."""

    SNAP_THRESHOLD = 2        # px: snap when window top edge touches screen top (2px tolerance)
    TAB_SIZE = 9             # px: portion of window left visible when snapped
    ANIM_MS = 180            # ms: slide-in / slide-out duration
    AUTO_HIDE_MS = 200       # ms: after mouse leaves, auto-snap back

    def __init__(self, window: MainWindow):
        super().__init__(window)
        self._window = window
        self._snapped = False
        self._at_edge = False       # True when unsnapped via hover (sitting at edge)
        self._animating = False
        self._unsnapped_geo: QRect | None = None
        self._anim: QPropertyAnimation | None = None
        self._indicator: QFrame | None = None
        self._enabled = True

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)

    # ── public properties ───────────────────────────────────────────────
    @property
    def is_snapped(self) -> bool:
        return self._snapped

    @property
    def is_animating(self) -> bool:
        return self._animating

    # ── public methods ──────────────────────────────────────────────────
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self._hide_indicator()
            if self._snapped:
                self.unsnap_full()

    def check_position(self):
        """Call from ``MainWindow.moveEvent``."""
        if not self._enabled or self._snapped or self._animating:
            return

        # 只有窗口足够窄时才触发边缘吸附
        if not self._is_narrow_enough_to_snap():
            return

        # When sitting at edge after hover-unsnap, block re-snap until
        # the user actually drags the window away from the edge.
        if self._at_edge and not self._has_left_edge():
            return
        self._at_edge = False

        if self._is_at_top_edge():
            self._unsnapped_geo = self._window.geometry()
            self._snap()

    def on_enter(self):
        """Call from ``MainWindow.enterEvent``."""
        self._auto_hide_timer.stop()
        if self._snapped:
            self.unsnap()           # hover → slide out at edge

    def on_leave(self):
        """Call from ``MainWindow.leaveEvent``."""
        if not self._snapped and not self._animating and self._at_edge:
            self._auto_hide_timer.start(self.AUTO_HIDE_MS)

    def unsnap(self):
        """Hover-triggered: slide window out so it sits at the snapped edge."""
        if not self._snapped:
            return
        self._auto_hide_timer.stop()
        self._hide_indicator()
        self._snapped = False
        self._at_edge = True
        self._animating = True
        self._animate_to(self._edge_adjacent_geo())

    def unsnap_full(self):
        """Click / tray-triggered: return window to its original position."""
        if not self._snapped or self._unsnapped_geo is None:
            return
        self._auto_hide_timer.stop()
        self._hide_indicator()
        self._snapped = False
        self._at_edge = False
        self._animating = True
        self._animate_to(self._unsnapped_geo)

    def cancel_animation(self):
        """Stop any running animation and reset to normal state."""
        if not self._snapped and not self._animating:
            return  # Nothing active – don't disturb _at_edge state
        if self._anim is not None and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._hide_indicator()
        self._animating = False
        self._snapped = False
        self._at_edge = False
        self._unsnapped_geo = None
        self._auto_hide_timer.stop()

    # ── internals: geometry ─────────────────────────────────────────────
    def _is_narrow_enough_to_snap(self) -> bool:
        """检查窗口是否足够窄，可以触发边缘吸附

        只有当窗口宽度小于屏幕宽度的阈值比例时才返回 True。
        默认阈值为 40%，用户可在设置中自定义。
        """
        # 获取配置的阈值（默认 0.4 = 40%）
        threshold = self._window._config.edge_snap_width_threshold

        window_width = self._window.width()
        screen = self._window.screen()
        if screen is None:
            return True  # 无法获取屏幕信息时，允许吸附

        screen_width = screen.availableGeometry().width()
        width_ratio = window_width / screen_width

        return width_ratio < threshold

    def _is_at_top_edge(self) -> bool:
        geo = self._window.geometry()
        screen = self._window.screen()
        if screen is None:
            return False
        full = screen.geometry()
        dist_top = geo.top() - full.top()
        return dist_top <= self.SNAP_THRESHOLD

    def _snap(self):
        geo = self._window.geometry()
        screen = self._window.screen()
        work = screen.availableGeometry()
        hidden = QRect(geo)
        hidden.moveTop(work.top() - geo.height() + self.TAB_SIZE)
        self._snapped = True
        self._animate_to(hidden, on_done=self._show_indicator)

    def _edge_adjacent_geo(self) -> QRect:
        """Fully-visible geometry sitting right at the top edge."""
        geo = self._window.geometry()
        screen = self._window.screen()
        work = screen.availableGeometry()
        result = QRect(geo)
        result.moveTop(work.top())
        return result

    def _has_left_edge(self) -> bool:
        """Return True if window has been dragged away from the top edge."""
        geo = self._window.geometry()
        screen = self._window.screen()
        if screen is None:
            return True
        work = screen.availableGeometry()
        return geo.top() > work.top() + self.SNAP_THRESHOLD

    # ── internals: animation ────────────────────────────────────────────
    def _animate_to(self, target: QRect, on_done=None):
        if self._anim is not None and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._anim = QPropertyAnimation(self._window, b"geometry")
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setStartValue(self._window.geometry())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        if on_done is not None:
            self._anim.finished.connect(on_done)
        self._anim.start()

    def _on_anim_done(self):
        self._animating = False
        # If unsnapped to edge but mouse already left during animation,
        # leaveEvent was blocked by _animating — start auto-hide now.
        if self._at_edge:
            if not self._window.geometry().contains(QCursor.pos()):
                self._auto_hide_timer.start(self.AUTO_HIDE_MS)

    # ── internals: timer callbacks ──────────────────────────────────────
    def _on_auto_hide(self):
        if not self._snapped and not self._animating and self._at_edge:
            self._at_edge = False
            self._snap()

    # ── internals: indicator tab ────────────────────────────────────────
    def _ensure_indicator(self):
        if self._indicator is not None:
            return
        self._indicator = QFrame(self._window)
        self._indicator.setObjectName("snapIndicator")
        self._indicator.hide()

    def _show_indicator(self):
        if not self._snapped:
            return
        self._ensure_indicator()
        geo = self._window.geometry()
        w, h, t = geo.width(), geo.height(), self.TAB_SIZE
        self._indicator.setStyleSheet(f"""
            #snapIndicator {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #A8D8FF, stop:0.3 #6BB5F0, stop:0.7 #5BA0E8, stop:1 #4890D0);
                border-radius: 4px;
            }}
        """)
        self._indicator.setGeometry(0, h - t, w, t)
        self._indicator.raise_()
        self._indicator.show()

    def _hide_indicator(self):
        if self._indicator is not None:
            self._indicator.hide()
