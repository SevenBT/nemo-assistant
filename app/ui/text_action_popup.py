"""划词浮标 — 选区下方弹出的一排紧凑图标按钮。

与截图工具栏（screenshot_overlay.py）共享深色圆角视觉。两种触发路径
共用同一个弹窗：
  - 划词浮标：鼠标拖选后在选区下方弹出
  - 全局热键：在当前鼠标位置弹出

★ 关键约束：弹窗绝不能抢焦点——连「点击按钮」也不能。一旦焦点被夺走，
源应用（浏览器/Word）的选区就清空了，随后的 Ctrl+C 取不到文字。

只设 WA_ShowWithoutActivating 不够（它只管 show 时不激活，不管点击）。
必须在 Windows 上给窗口加 WS_EX_NOACTIVATE 扩展样式：这样点击其上的按钮
也不会把前台焦点从源应用夺走（屏幕键盘、工具提示都靠这个）。按 CLAUDE.md
经验，此类 Win32 样式在 showEvent 里用 ctypes 设置才稳。

正因为不抢焦点，取词才能延后到「点击按钮那一刻」——弹窗本身不碰剪贴板，
只有用户真要动作时才发一次 Ctrl+C，不打扰正常的复制粘贴。

按钮按下后只发 action_chosen(key) 信号，由调用方负责取词与分发。

—— 交互规则 ——
- 显示后任意左/右键点击浮标以外区域 → 立即消失
- 点击浮标背景（非按钮区域）→ 立即消失
- 鼠标移入重置自动消失计时（2s），移出重新倒计时
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import TransparentToolButton

from app.ui import style
from app.ui.float_tooltip import FloatTooltip
from app.ui.text_actions import get_active_text_actions

logger = logging.getLogger(__name__)

try:
    import mouse as _mouse

    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False


def _build_popup_style(theme: dict) -> str:
    """根据主题生成浮标 QSS。

    紧凑无文字浮标：图标 14px，内边距 2px 起。背景用浮起面、文字用主文本色、
    hover 用强调色淡底，与应用整体主题一致。

    底色/边框仍跟随主题；浮标靠外层卡片的投影 + 实边框从网页背景里「浮」出来，
    不靠颜色对比（见 _build_layout 的卡片结构与阴影）。
    """
    return f"""
    #textActionCard {{
        background: {theme["surface_raised"]};
        border-radius: 5px;
        border: 1px solid {theme["border_solid"]};
    }}
    #textActionCard TransparentToolButton {{
        background: transparent;
        border: none;
        color: {theme["text"]};
        padding: 2px 3px;
        border-radius: 4px;
        min-width: 20px;
        min-height: 20px;
    }}
    #textActionCard TransparentToolButton:hover {{
        background: {theme["accent_subtle"]};
        color: {theme["accent"]};
    }}
"""

# 浮标与选区之间的间距（px）。
_GAP_PX = 4

# 外壳留给投影扩散的透明边距（px）。卡片四周各留这么多空间，阴影才不被裁切。
_SHADOW_MARGIN_PX = 9
# 投影模糊半径与下沉偏移（px）。
_SHADOW_BLUR_PX = 14
_SHADOW_OFFSET_Y = 2

# 按钮图标尺寸（px）。
_ICON_PX = 14

# 鼠标移开后自动消失的延迟（ms）。
_AUTO_HIDE_MS = 2000

# Win32 扩展样式常量（用于 WS_EX_NOACTIVATE，让窗口点击不抢焦点）。
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000


class TextActionPopup(QFrame):
    """无边框、不抢焦点的划词动作条。"""

    action_chosen = pyqtSignal(str)       # 点击动作：气泡快查 / 存便签
    _hide_requested = pyqtSignal()        # 内部：从 mouse hook 线程请求关闭

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_geo: QRect | None = None
        self._cached_geo_physical: QRect | None = None
        self._mouse_hook: Callable | None = None
        self._tooltip = FloatTooltip()
        self._build_window()
        self._build_layout()
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)
        self._hide_requested.connect(self._on_hide_requested)

    # ── 窗口设置 ────────────────────────────────────────────────────────

    def _build_window(self):
        self.setObjectName("textActionBar")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _build_layout(self):
        """建外层布局；按钮行在每次 show_at 时重建（见 _rebuild_buttons）。

        结构：透明外壳(self) → 留边距 → 卡片(self._card，承载底色/边框/圆角+阴影)
        → 按钮行。外壳透明且四周留 _SHADOW_MARGIN_PX，投影才有空间扩散不被裁。
        """
        shell = QVBoxLayout(self)
        shell.setContentsMargins(
            _SHADOW_MARGIN_PX, _SHADOW_MARGIN_PX,
            _SHADOW_MARGIN_PX, _SHADOW_MARGIN_PX,
        )
        shell.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("textActionCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(_SHADOW_BLUR_PX)
        shadow.setXOffset(0)
        shadow.setYOffset(_SHADOW_OFFSET_Y)
        shadow.setColor(QColor(0, 0, 0, 110))
        self._card.setGraphicsEffect(shadow)
        shell.addWidget(self._card)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(2, 2, 2, 2)
        card_layout.setSpacing(0)

        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        card_layout.addLayout(self._row)

    def _rebuild_buttons(self) -> int:
        """按当前启用的动作重建按钮行，返回按钮数。

        每次 show_at 重建，使设置页改了显隐开关后能即时生效。
        """
        while self._row.count():
            child = self._row.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()

        actions = get_active_text_actions()
        for action in actions:
            btn = TransparentToolButton(action.icon, self)
            btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
            # 不用原生 setToolTip（不抢焦点的浮标上不触发），改用自建 tooltip：
            # 把标签记在按钮上，hover 时由 eventFilter 调度显示。
            btn._action_label = action.label
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.installEventFilter(self)
            btn.clicked.connect(
                lambda _checked=False, k=action.key: self._on_clicked(k)
            )
            self._row.addWidget(btn)
        return len(actions)

    def eventFilter(self, obj, event):
        """按钮 hover 进/出 → 调度 / 取消自建 tooltip。"""
        etype = event.type()
        if etype == QEvent.Type.Enter:
            label = getattr(obj, "_action_label", "")
            if label:
                top_left = obj.mapToGlobal(QPoint(0, 0))
                self._tooltip.schedule(label, top_left, obj.height())
        elif etype in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
            self._tooltip.cancel()
        return super().eventFilter(obj, event)

    # ── 主题适配 ────────────────────────────────────────────────────────

    def _apply_theme_style(self):
        """根据当前主题刷新浮标样式（每次显示前调用）。"""
        theme = style.get_current_theme()
        self.setStyleSheet(_build_popup_style(theme))

    # ── Win32 防激活 ────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_no_activate()
        self._install_click_watcher()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._tooltip.cancel()
        self._remove_click_watcher()

    def _apply_no_activate(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE, ex_style | _WS_EX_NOACTIVATE
            )
        except Exception:
            logger.warning(
                "WS_EX_NOACTIVATE 设置失败，弹窗点击可能抢夺焦点",
                exc_info=True,
            )

    # ── 全局点击监听（mouse hook 线程 → pyqtSignal → 主线程） ──────────

    def _on_hide_requested(self):
        """主线程 slot：收到 hook 线程的关闭请求后执行实际 hide。"""
        self.hide()

    def _install_click_watcher(self):
        """安装全局 mouse hook，监听弹窗外的点击以便立即关闭。"""
        if not _MOUSE_OK:
            return
        if self._mouse_hook is not None:
            return
        try:
            self._mouse_hook = _mouse.hook(self._on_global_event)
        except Exception:
            logger.warning("mouse hook 安装失败，点击弹窗外部将无法关闭",
                           exc_info=True)

    def _remove_click_watcher(self):
        if self._mouse_hook is None:
            return
        try:
            _mouse.unhook(self._mouse_hook)
        except Exception:
            logger.warning("mouse hook 卸载失败", exc_info=True)
            return  # 保留引用，避免下次 show 时重复安装导致泄漏
        self._mouse_hook = None

    def _on_global_event(self, event):
        """mouse hook 回调（在 hook 线程执行）。

        右键任意位置 → 立即关闭。
        左键点弹窗以外区域 → 关闭；点在弹窗内（按钮 / 背景）→ 不干涉，
        由 Qt 事件循环在主线处理：按钮 clicked → _on_clicked → hide，
        背景 mousePressEvent → hide。
        """
        event_type = getattr(event, "event_type", None)
        if event_type != "down":
            return
        button = getattr(event, "button", None)
        if button == _mouse.RIGHT:
            self._hide_requested.emit()
            return
        if button == _mouse.LEFT:
            geo = self._cached_geo_physical  # 物理像素几何，抓本地引用避免竞争
            if geo is not None:
                x, y = _mouse.get_position()
                if not geo.contains(x, y):
                    self._hide_requested.emit()

    # ── 动作处理 ──────────────────────────────────────────────────────────

    def _on_clicked(self, key: str):
        """点击动作按钮：关闭浮标并发出动作信号，由调用方取词分发。"""
        self._auto_hide.stop()
        self.hide()
        self.action_chosen.emit(key)

    def mousePressEvent(self, event):
        """点击浮标背景（非按钮区域）立即关闭；按钮有其自己的 clicked 处理。"""
        super().mousePressEvent(event)
        self.hide()

    # ── 定位 ────────────────────────────────────────────────────────────

    def show_at(self, x: int, y: int):
        """在屏幕坐标紧贴选区下方弹出。

        Args:
            x: 选区末行水平中心（UIA 路径），或鼠标 X（热键回退路径）。
            y: 选区底边（UIA 路径），或鼠标 Y（热键回退路径）。

        浮标居中对齐 x，顶边紧贴 y 下方 _GAP_PX 处。
        屏幕底边空间不足时自动翻到选区上方，左右超屏则贴边。
        """
        # 按当前显隐配置重建按钮；全部关闭则不弹。
        if self._rebuild_buttons() == 0:
            return
        self._apply_theme_style()
        self.adjustSize()
        w, h = self.width(), self.height()
        # w/h 含外壳两侧各 _SHADOW_MARGIN_PX 透明边距：水平边距对称，居中不受影响；
        # 垂直方向需减去上边距，卡片(而非外壳)顶边才落在 y + _GAP_PX 处。
        px = x - w // 2
        py = y + _GAP_PX - _SHADOW_MARGIN_PX

        # ★ 用目标坐标查屏幕，不能用 mapToGlobal(self.rect().center())——
        # 此时弹窗尚未 move，其当前全局位置是 show 前残留的旧位置，
        # 用旧位置 screenAt 可能拿到错误的屏幕 → wrong availableGeometry
        # → 边缘修正把弹窗推到奇怪位置（表现就是「位置随机」）。
        screen = QApplication.screenAt(QPoint(px + w // 2, py)) \
            or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            if px + w > geo.right():
                px = geo.right() - w
            if px < geo.left():
                px = geo.left()
            if py + h > geo.bottom():
                py = y - h - _GAP_PX + _SHADOW_MARGIN_PX  # 翻到选区上方
            if py < geo.top():
                py = geo.top()

        self._cached_geo = QRect(px, py, w, h)

        # 全局 mouse hook 拿到的是物理像素，需换算出物理坐标的几何供比对——
        # 否则在缩放屏（125%/150%）上点击按钮也会被判成「弹窗外」，hook 在按下
        # 瞬间就 hide 弹窗，与按钮 pressed/released 抢跑：表现为「单击不触发 /
        # 长按仍出气泡」。
        scale = 1.0
        try:
            if screen is not None:
                scale = screen.devicePixelRatio()
        except Exception:
            pass
        self._cached_geo_physical = QRect(
            round(px * scale), round(py * scale),
            round(w * scale), round(h * scale),
        )

        self.move(px, py)
        self.show()
        self.raise_()
        self._auto_hide.start(_AUTO_HIDE_MS)

    # ── 鼠标悬停计时 ────────────────────────────────────────────────────

    def leaveEvent(self, event):
        self._auto_hide.start(_AUTO_HIDE_MS)
        super().leaveEvent(event)

    def enterEvent(self, event):
        self._auto_hide.stop()
        super().enterEvent(event)
