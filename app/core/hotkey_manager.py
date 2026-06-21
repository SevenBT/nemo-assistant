"""
全局热键管理器。

使用 keyboard 库注册系统级热键，回调通过 PyQt6 信号自动
从 keyboard hook 线程 marshal 回 Qt 主线程。
"""
import logging

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import keyboard as _kb
    _KB_OK = True
except ImportError:
    _KB_OK = False

DEFAULT_HOTKEYS: dict[str, str] = {
    "screenshot":    "ctrl+alt+a",
    "new_note":      "ctrl+alt+n",
    "toggle_window": "ctrl+alt+space",
    "quick_ask":     "ctrl+alt+q",
    "selection":     "ctrl+alt+e",
}

_ACTION_LABELS: dict[str, str] = {
    "screenshot":    "截图",
    "new_note":      "新建便签",
    "toggle_window": "显示/隐藏窗口",
    "quick_ask":     "快速提问",
    "selection":     "划词动作",
}


class HotkeyManager(QObject):
    """全局热键管理器，注册/注销热键并通过信号通知 UI。"""

    screenshot_triggered    = pyqtSignal()
    new_note_triggered      = pyqtSignal()
    toggle_window_triggered = pyqtSignal()
    quick_ask_triggered     = pyqtSignal()
    selection_triggered     = pyqtSignal()

    _SIGNAL_MAP = {
        "screenshot":    "screenshot_triggered",
        "new_note":      "new_note_triggered",
        "toggle_window": "toggle_window_triggered",
        "quick_ask":     "quick_ask_triggered",
        "selection":     "selection_triggered",
    }

    def __init__(self, parent=None):
        super().__init__(parent)

    # ------------------------------------------------------------------ 公开接口
    def start(self):
        """启动热键监听，注册所有已配置的热键。"""
        if _KB_OK:
            self._register_all()

    def reload(self):
        """重新注册所有热键 — 配置变更或截图结束后调用。"""
        if not _KB_OK:
            return
        self._unhook()
        self._register_all()

    def stop(self):
        """注销所有热键（截图模式或应用退出时调用）。"""
        if _KB_OK:
            self._unhook()

    # ------------------------------------------------------------------ 内部实现
    def _unhook(self):
        try:
            _kb.unhook_all_hotkeys()
        except Exception:
            pass

    def _register_all(self):
        from app.core.config import cfg
        hotkeys = {
            "screenshot": cfg.get(cfg.hotkeyScreenshot),
            "new_note": cfg.get(cfg.hotkeyNewNote),
            "toggle_window": cfg.get(cfg.hotkeyToggleWindow),
            "quick_ask": cfg.get(cfg.hotkeyQuickAsk),
            "selection": cfg.get(cfg.hotkeySelection),
        }
        for action, signal_name in self._SIGNAL_MAP.items():
            combo = hotkeys.get(action) or DEFAULT_HOTKEYS.get(action, "")
            if combo:
                self._safe_add(combo, getattr(self, signal_name).emit)

    def _safe_add(self, combo: str, callback):
        try:
            _kb.add_hotkey(combo, callback, suppress=False)
        except Exception:
            logger.warning(
                "HotkeyManager: 注册热键 '%s' 失败", combo, exc_info=True
            )
