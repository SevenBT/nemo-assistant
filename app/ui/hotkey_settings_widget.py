"""Hotkey settings tab — capture, display, and save global hotkey bindings."""
import threading

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    import keyboard as _kb
    _KB_OK = True
except ImportError:
    _KB_OK = False

from app.i18n import t

# (action id, i18n key) — 标签运行时按当前语言取（语言在启动时锁定）。
_ACTIONS = [
    ("screenshot",    "hotkeys.action.screenshot"),
    ("new_note",      "hotkeys.action.newNote"),
    ("toggle_window", "hotkeys.action.toggleWindow"),
    ("quick_ask",     "hotkeys.action.quickAsk"),
    ("selection",     "hotkeys.action.selection"),
]

# 录制单个快捷键的最长等待（毫秒）；超时自动取消，避免 suppress 录制卡死吞键。
_CAPTURE_TIMEOUT_MS = 8000

# 合法组合键必须包含至少一个修饰键，否则注册后会全局吞掉该普通键。
_MODIFIERS = {"ctrl", "control", "alt", "shift", "win", "windows", "cmd"}


def _validate_combo(combo: str) -> str:
    """校验录入的组合键，返回错误信息；合法返回空串。"""
    if not combo:
        return t("hotkeys.err.noKey")
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return t("hotkeys.err.noKey")
    has_modifier = any(p in _MODIFIERS for p in parts)
    has_normal = any(p not in _MODIFIERS for p in parts)
    if not has_modifier:
        return t("hotkeys.err.needModifier")
    if not has_normal:
        return t("hotkeys.err.needNormal")
    return ""


def _fmt(combo: str) -> str:
    """'ctrl+alt+a' → 'Ctrl+Alt+A'"""
    if not combo:
        return t("hotkeys.unset")

    def _cap(part: str) -> str:
        low = part.lower()
        if low in ("ctrl", "control"):
            return "Ctrl"
        if low == "alt":
            return "Alt"
        if low == "shift":
            return "Shift"
        if low == "win":
            return "Win"
        return part.upper() if len(part) == 1 else part.capitalize()

    return "+".join(_cap(p) for p in combo.split("+"))


class _Capture(QObject):
    """Runs keyboard.read_hotkey in a background thread, signals the result.

    Emits finished("") on Escape or error; emits finished(combo) otherwise.
    """
    finished = pyqtSignal(str)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        result = ""
        if _KB_OK:
            try:
                combo = _kb.read_hotkey(suppress=True)
                result = "" if combo.lower() == "escape" else combo
            except Exception:
                result = ""
        self._safe_emit(result)

    def _safe_emit(self, result: str):
        """录制阻塞期间承载本对象的设置页可能已被销毁；emit 前确认对象仍存活。

        read_hotkey(suppress=True) 会一直阻塞到有按键，期间若对话框关闭，
        底层 C++ 对象已删除，直接 emit 会抛 RuntimeError 并使线程崩溃。
        """
        try:
            from PyQt6 import sip
            if sip.isdeleted(self):
                return
        except Exception:
            pass
        try:
            self.finished.emit(result)
        except RuntimeError:
            # 对象已在 emit 前一刻被删除，安全忽略。
            pass


class _HotkeyRow(QWidget):
    """One settings row: current combo label + 修改 button."""
    combo_changed = pyqtSignal(str, str)  # (action, new_combo)

    def __init__(self, action: str, combo: str, hotkey_mgr, parent=None):
        super().__init__(parent)
        self._action = action
        self._combo = combo
        self._hotkey_mgr = hotkey_mgr
        self._capturing = False
        # 由 HotkeySettingsWidget 注入：给定组合键，返回与之冲突的其它 action 标签或 None。
        self.conflict_checker = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo_lbl = QLabel(_fmt(combo))
        self._combo_lbl.setMinimumWidth(160)
        self._combo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn = QPushButton(t("hotkeys.modify"))
        # 不写死宽度：文案随语言变化（"修改" / "Change"），加上主题 QSS 的内边距后
        # 固定宽度会裁掉文字。用最小宽度给下限——既保证文字完整，也避免录制中文案
        # 变短（"…"）时按钮缩窄抖动。
        self._btn.setMinimumWidth(self._btn.sizeHint().width())
        self._btn.clicked.connect(self._on_modify)

        layout.addWidget(self._combo_lbl, 1)
        layout.addWidget(self._btn)

    # ─────────────────────────────────────────────── public
    @property
    def action(self) -> str:
        return self._action

    @property
    def current_combo(self) -> str:
        return self._combo

    def reset_combo(self, combo: str):
        self._combo = combo
        self._combo_lbl.setText(_fmt(combo))

    # ─────────────────────────────────────────────── capture
    def _on_modify(self):
        self._btn.setEnabled(False)
        self._btn.setText("…")
        self._combo_lbl.setText(t("hotkeys.pressPrompt"))
        self._capturing = True
        if self._hotkey_mgr:
            self._hotkey_mgr.stop()
        cap = _Capture(self)
        cap.finished.connect(self._on_captured)
        cap.start()
        # 超时兜底：suppress 录制期间全局吞键，避免线程卡住导致键盘失灵。
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_capture_timeout)
        self._timeout.start(_CAPTURE_TIMEOUT_MS)

    def _on_capture_timeout(self):
        if not self._capturing:
            return
        # 模拟 Esc 让后台 read_hotkey 返回，视作取消。
        if _KB_OK:
            try:
                _kb.press_and_release("esc")
            except Exception:
                pass

    def _on_captured(self, combo: str):
        if not self._capturing:
            return
        self._capturing = False
        if hasattr(self, "_timeout"):
            self._timeout.stop()
        self._btn.setEnabled(True)
        self._btn.setText(t("hotkeys.modify"))

        if not combo:
            # 用户取消或超时：保持原值。
            self._combo_lbl.setText(_fmt(self._combo))
            if self._hotkey_mgr:
                self._hotkey_mgr.reload()
            return

        error = _validate_combo(combo)
        if not error and self.conflict_checker:
            conflict_label = self.conflict_checker(self._action, combo)
            if conflict_label:
                error = t("hotkeys.err.occupied", label=conflict_label)

        if error:
            QMessageBox.warning(self, t("hotkeys.err.invalidTitle"), error)
            self._combo_lbl.setText(_fmt(self._combo))
            if self._hotkey_mgr:
                self._hotkey_mgr.reload()
            return

        self._combo = combo
        self._combo_lbl.setText(_fmt(combo))
        self.combo_changed.emit(self._action, combo)
        if self._hotkey_mgr:
            self._hotkey_mgr.reload()


class HotkeySettingsWidget(QWidget):
    """Tab content widget for the "快捷键" settings tab."""

    def __init__(self, config, hotkey_mgr, parent=None):
        super().__init__(parent)
        self._config = config
        self._hotkey_mgr = hotkey_mgr
        self._rows: list[_HotkeyRow] = []
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        layout = QVBoxLayout(self)
        hotkeys = self._config.hotkeys
        form = QFormLayout()

        for action, label_key in _ACTIONS:
            combo = hotkeys.get(action, "")
            row = _HotkeyRow(action, combo, self._hotkey_mgr)
            row.conflict_checker = self._find_conflict
            self._rows.append(row)
            form.addRow(t(label_key) + ":", row)

        layout.addLayout(form)
        layout.addStretch()

        reset_btn = QPushButton(t("hotkeys.restoreDefault"))
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignRight)

        if not _KB_OK:
            warn = QLabel(t("hotkeys.kbMissing"))
            warn.setStyleSheet("color: orange;")
            layout.insertWidget(0, warn)

    # ------------------------------------------------------------------ public
    def save(self):
        """Write pending changes to config and reload hotkey manager."""
        updates = {row.action: row.current_combo for row in self._rows}
        self._config.update_hotkeys(updates)
        if self._hotkey_mgr:
            self._hotkey_mgr.reload()
            self._warn_failed_registrations()

    # ------------------------------------------------------------------ private
    def _find_conflict(self, action: str, combo: str) -> str | None:
        """若 combo 已被其它 action 占用，返回那个 action 的标签；否则 None。"""
        norm = combo.strip().lower()
        labels = dict(_ACTIONS)
        for row in self._rows:
            if row.action != action and row.current_combo.strip().lower() == norm:
                return t(labels.get(row.action, row.action))
        return None

    def _warn_failed_registrations(self):
        """注册失败时给出可见反馈，避免用户以为已生效（静默失败）。"""
        failed = getattr(self._hotkey_mgr, "failed_actions", None)
        if not failed:
            return
        labels = dict(_ACTIONS)
        names = "、".join(t(labels.get(a, a)) for a in failed)
        QMessageBox.warning(
            self,
            t("hotkeys.err.registerFailedTitle"),
            t("hotkeys.err.registerFailedBody", names=names),
        )

    def _reset_defaults(self):
        from app.core.hotkey_manager import DEFAULT_HOTKEYS
        for row in self._rows:
            row.reset_combo(DEFAULT_HOTKEYS.get(row.action, ""))
