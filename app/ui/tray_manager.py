from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


def _make_icon() -> QIcon:
    """Generate a clean chat-bubble icon with a sparkle (no external file)."""
    S = 64  # canvas size (HiDPI-ready)
    pix = QPixmap(S, S)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    accent = QColor("#5B9BD5")
    white = QColor("#FFFFFF")

    # ── chat bubble body ──────────────────────────────────────────────
    bubble = QRectF(6, 4, 44, 36)
    p.setBrush(accent)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(bubble, 10, 10)

    # bubble tail (bottom-right)
    tail = QPainterPath()
    tail.moveTo(42, 36)
    tail.lineTo(53, 46)
    tail.lineTo(48, 34)
    tail.closeSubpath()
    p.drawPath(tail)

    # ── 4-point sparkle inside the bubble ─────────────────────────────
    cx, cy, r = 28.0, 21.0, 7.0
    star = QPainterPath()
    star.moveTo(cx, cy - r)                      # top
    star.lineTo(cx + r * 0.35, cy - r * 0.35)    # top-right inner
    star.lineTo(cx + r, cy)                       # right
    star.lineTo(cx + r * 0.35, cy + r * 0.35)    # bottom-right inner
    star.lineTo(cx, cy + r)                       # bottom
    star.lineTo(cx - r * 0.35, cy + r * 0.35)    # bottom-left inner
    star.lineTo(cx - r, cy)                       # left
    star.lineTo(cx - r * 0.35, cy - r * 0.35)    # top-left inner
    star.closeSubpath()
    p.setBrush(white)
    p.drawPath(star)

    # ── tiny secondary sparkle (top-right outside bubble) ─────────────
    cx2, cy2, r2 = 48.0, 6.0, 4.0
    star2 = QPainterPath()
    star2.moveTo(cx2, cy2 - r2)
    star2.lineTo(cx2 + r2 * 0.35, cy2 - r2 * 0.35)
    star2.lineTo(cx2 + r2, cy2)
    star2.lineTo(cx2 + r2 * 0.35, cy2 + r2 * 0.35)
    star2.lineTo(cx2, cy2 + r2)
    star2.lineTo(cx2 - r2 * 0.35, cy2 + r2 * 0.35)
    star2.lineTo(cx2 - r2, cy2)
    star2.lineTo(cx2 - r2 * 0.35, cy2 - r2 * 0.35)
    star2.closeSubpath()
    p.drawPath(star2)

    p.end()
    return QIcon(pix)


class TrayManager(QObject):
    show_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tray = QSystemTrayIcon(parent)
        self._tray.setIcon(_make_icon())
        self._tray.setToolTip("AI Agent")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def _build_menu(self):
        self._menu = QMenu()
        menu = self._menu
        show_act = QAction("显示窗口", menu)
        show_act.triggered.connect(self.show_requested)
        menu.addAction(show_act)

        snap_act = QAction("截图", menu)
        snap_act.triggered.connect(self.screenshot_requested)
        menu.addAction(snap_act)

        menu.addSeparator()

        settings_act = QAction("设置", menu)
        settings_act.triggered.connect(self.settings_requested)
        menu.addAction(settings_act)

        menu.addSeparator()

        quit_act = QAction("退出", menu)
        quit_act.triggered.connect(self.quit_requested)
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()

    def notify(self, title: str, message: str):
        self._tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 4000
        )
