"""
全局热键管理器。

使用 keyboard 库注册系统级热键，回调通过 PyQt6 信号自动
从 keyboard hook 线程 marshal 回 Qt 主线程。
"""
import logging
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

try:
    import keyboard as _kb
    _KB_OK = True
except ImportError:
    _KB_OK = False

from app.core.hotkey_actions import DEFAULT_HOTKEYS, get_hotkey_actions, normalize_combo, read_hotkeys


class HotkeyManager(QObject):
    """全局热键管理器，注册/注销热键并通过信号通知 UI。"""

    screenshot_triggered    = pyqtSignal()
    new_note_triggered      = pyqtSignal()
    toggle_window_triggered = pyqtSignal()
    quick_ask_triggered     = pyqtSignal()
    selection_triggered     = pyqtSignal()
    action_triggered = pyqtSignal(str)
    paused_changed = pyqtSignal(bool)
    _requested = pyqtSignal(str, int)

    _SIGNAL_MAP = {
        "screenshot":    "screenshot_triggered",
        "new_note":      "new_note_triggered",
        "toggle_window": "toggle_window_triggered",
        "quick_ask":     "quick_ask_triggered",
        "selection":     "selection_triggered",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        # 最近一次 _register_all 中注册失败的 action 列表（供 UI 反馈）。
        self.failed_actions: list[str] = []
        self._handles = []
        self._running = False
        self._suspended: set[str] = set()
        self._paused = False
        self._generation = 0
        self._waiting_for_release = False
        self._release_timer = QTimer(self)
        self._release_timer.setInterval(25)
        self._release_timer.timeout.connect(self._resume_when_released)
        self._last_trigger: dict[str, float] = {}
        self._requested.connect(self._dispatch)

    @property
    def paused(self):
        return self._paused

    def set_paused(self, paused: bool):
        if paused == self._paused:
            return
        self._paused = paused
        self.reload()
        self.paused_changed.emit(paused)

    def suspend(self, reason: str):
        self._suspended.add(reason)
        self.reload()

    def resume(self, reason: str):
        suspended = reason in self._suspended
        self._suspended.discard(reason)
        if suspended and not self._suspended and self._running:
            # QShortcut activates on key-down. Do not let its later key-up fire
            # a global action bound to the same combination after capture closes.
            self._waiting_for_release = True
            self._release_timer.start()
            self._resume_when_released()
        else:
            self.reload()

    def _resume_when_released(self):
        if _KB_OK:
            try:
                if any(_kb.is_pressed(key) for key in ("ctrl", "alt", "shift", "win")):
                    return
            except Exception:
                logger.debug("Could not check modifier release", exc_info=True)
        self._release_timer.stop()
        self._waiting_for_release = False
        self.reload()

    # ------------------------------------------------------------------ 公开接口
    def start(self):
        """启动热键监听，注册所有已配置的热键。"""
        self._running = True
        self.reload()

    def reload(self):
        """重新注册所有热键 — 配置变更或截图结束后调用。"""
        self._unhook()
        if _KB_OK and self._running and not self._suspended and not self._waiting_for_release:
            self._register_all()

    def stop(self):
        """注销所有热键（截图模式或应用退出时调用）。"""
        self._running = False
        self._release_timer.stop()
        self._waiting_for_release = False
        self._unhook()

    # ------------------------------------------------------------------ 内部实现
    def _unhook(self):
        self._generation += 1
        for handle in self._handles:
            try:
                _kb.remove_hotkey(handle)
            except Exception:
                logger.debug("Failed to unregister owned hotkey", exc_info=True)
        self._handles.clear()

    def _register_all(self):
        hotkeys = read_hotkeys()
        self.failed_actions = []
        registered = set()
        generation = self._generation
        for action in get_hotkey_actions():
            if action.scope == "screenshot" or (self._paused and action.id != "system:pause"):
                continue
            combo = normalize_combo(hotkeys.get(action.id, ""))
            if not combo:
                continue
            callback = lambda key=action.id, epoch=generation: self._requested.emit(key, epoch)
            if combo in registered or not self._safe_add(combo, callback):
                self.failed_actions.append(action.id)
            else:
                registered.add(combo)

    def _dispatch(self, action: str, generation: int):
        if (generation != self._generation or not self._running or self._suspended
                or self._waiting_for_release
                or (self._paused and action != "system:pause")):
            return
        now = time.monotonic()
        if now - self._last_trigger.get(action, 0) < 0.25:
            return
        self._last_trigger[action] = now
        self.action_triggered.emit(action)
        if action in self._SIGNAL_MAP:
            getattr(self, self._SIGNAL_MAP[action]).emit()

    def _safe_add(self, combo: str, callback) -> bool:
        """注册单个热键，成功返回 True，失败记日志并返回 False。"""
        try:
            # keyboard uses commas to separate sequences; the comma key needs
            # its named form, whereas Qt/config use the literal character.
            backend_combo = "+".join("comma" if part == "," else part for part in combo.split("+"))
            handle = _kb.add_hotkey(backend_combo, callback, suppress=False, trigger_on_release=True)
            self._handles.append(handle)
            return True
        except Exception:
            logger.warning(
                "HotkeyManager: 注册热键 '%s' 失败", combo, exc_info=True
            )
            return False
