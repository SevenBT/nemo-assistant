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

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import TransparentToolButton

from app.ui import style
from app.ui.float_tooltip import FloatTooltip
from app.ui.global_click_watcher import GlobalClickWatcher
from app.ui.non_activating_popup import NonActivatingPopup
from app.ui.popup_geometry import GAP_PX as _GAP_PX
from app.ui.popup_geometry import place_below_anchor
from app.ui.text_actions import get_active_text_actions

logger = logging.getLogger(__name__)


def _build_popup_style(theme: dict) -> str:
    """根据主题生成浮标 QSS。

    紧凑无文字浮标：图标 14px，内边距 2px 起。背景用浮起面、文字用主文本色、
    hover 用强调色淡底，与应用整体主题一致。

    底色/边框仍跟随主题；浮标靠实边框从网页背景里「浮」出来，不靠颜色对比。
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

# 卡片圆角半径（px），需与 QSS 的 border-radius 保持一致。
_CARD_RADIUS_PX = 5

# 按钮图标尺寸（px）。
_ICON_PX = 14

# 鼠标移开后自动消失的延迟（ms）。
_AUTO_HIDE_MS = 2000


class TextActionPopup(NonActivatingPopup):
    """无边框、不抢焦点的划词动作条。"""

    action_chosen = pyqtSignal(str)       # 点击动作：气泡快查 / 存便签
    _hide_requested = pyqtSignal()        # 内部：从 mouse hook 线程请求关闭

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_geo: QRect | None = None
        self._cached_geo_physical: QRect | None = None
        self._tooltip = FloatTooltip()
        self._click_watcher = GlobalClickWatcher(
            geometry_provider=lambda: self._cached_geo_physical,
            on_hide_requested=self._hide_requested.emit,
            owner_name="TextActionPopup",
        )
        self._build_window()
        self._build_layout()
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.hide)
        self._hide_requested.connect(self._on_hide_requested)

    # ── 窗口设置 ────────────────────────────────────────────────────────

    def _build_window(self):
        # 窗口标志与不激活属性由 NonActivatingPopup 基类统一设置，这里只需
        # 给对象命名（供 QSS 选择器定位）。
        self.setObjectName("textActionBar")

    def _build_layout(self):
        """建外层布局；按钮行在每次 show_at 时重建（见 _rebuild_buttons）。

        结构：外壳(self) → 卡片(self._card，承载底色/边框/圆角) → 按钮行。
        外壳无边距，卡片直接铺满窗口。
        """
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("textActionCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
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

    # ── 显示/隐藏：不激活样式由基类处理，这里挂点击监听与 tooltip 清理 ──

    def showEvent(self, event):
        super().showEvent(event)  # NonActivatingPopup 负责 WS_EX_NOACTIVATE
        self._click_watcher.install()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._tooltip.cancel()
        self._click_watcher.remove()

    def _on_hide_requested(self):
        """主线程 slot：收到 hook 线程的关闭请求后执行实际 hide。"""
        self.hide()

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

        # ★ 用目标坐标查屏幕，不能用 mapToGlobal(self.rect().center())——
        # 此时弹窗尚未 move，其当前全局位置是 show 前残留的旧位置，
        # 用旧位置 screenAt 可能拿到错误的屏幕 → wrong availableGeometry
        # → 边缘修正把弹窗推到奇怪位置（表现就是「位置随机」）。
        screen = QApplication.screenAt(QPoint(x, y + _GAP_PX)) \
            or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen is not None else None
        scale = screen.devicePixelRatio() if screen is not None else 1.0

        # 边缘修正 + 物理像素几何换算下沉到 place_below_anchor。物理几何供全局
        # mouse hook 在缩放屏（125%/150%）上比对命中，否则点击按钮被判成「弹窗
        # 外」、hook 在按下瞬间就 hide，与按钮 pressed/released 抢跑（表现为
        # 「单击不触发 / 长按仍出气泡」）。
        placed = place_below_anchor(w, h, x, y, screen_geo, scale)
        self._cached_geo = placed.logical
        self._cached_geo_physical = placed.physical

        self.move(placed.logical.x(), placed.logical.y())
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
