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

_ACTIONS = [
    ("screenshot",    "截图"),
    ("new_note",      "新建便签"),
    ("toggle_window", "显示/隐藏窗口"),
    ("quick_ask",     "快速提问"),
    ("selection",     "划词动作"),
]

# 录制单个快捷键的最长等待（毫秒）；超时自动取消，避免 suppress 录制卡死吞键。
_CAPTURE_TIMEOUT_MS = 8000

# 合法组合键必须包含至少一个修饰键，否则注册后会全局吞掉该普通键。
_MODIFIERS = {"ctrl", "control", "alt", "shift", "win", "windows", "cmd"}


def _validate_combo(combo: str) -> str:
    """校验录入的组合键，返回错误信息；合法返回空串。"""
    if not combo:
        return "未捕获到有效按键"
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        return "未捕获到有效按键"
    has_modifier = any(p in _MODIFIERS for p in parts)
    has_normal = any(p not in _MODIFIERS for p in parts)
    if not has_modifier:
        return "快捷键必须包含至少一个修饰键（Ctrl / Alt / Shift / Win）"
    if not has_normal:
        return "快捷键不能只有修饰键，请再按一个普通键"
    return ""


def _fmt(combo: str) -> str:
    """'ctrl+alt+a' → 'Ctrl+Alt+A'"""
    if not combo:
        return "（未设置）"

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
        if not _KB_OK:
            self.finished.emit("")
            return
        try:
            combo = _kb.read_hotkey(suppress=True)
            self.finished.emit("" if combo.lower() == "escape" else combo)
        except Exception:
            self.finished.emit("")


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

        self._btn = QPushButton("修改")
        self._btn.setFixedWidth(64)
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
        self._combo_lbl.setText("按下快捷键（Esc 取消）")
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
        self._btn.setText("修改")

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
                error = f"该快捷键已被「{conflict_label}」占用"

        if error:
            QMessageBox.warning(self, "快捷键无效", error)
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

        for action, label in _ACTIONS:
            combo = hotkeys.get(action, "")
            row = _HotkeyRow(action, combo, self._hotkey_mgr)
            row.conflict_checker = self._find_conflict
            self._rows.append(row)
            form.addRow(label + ":", row)

        layout.addLayout(form)
        layout.addStretch()

        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignRight)

        if not _KB_OK:
            warn = QLabel("⚠ keyboard 库未安装，全局快捷键不可用")
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
        """若 combo 已被其它 action 占用，返回那个 action 的中文标签；否则 None。"""
        norm = combo.strip().lower()
        labels = dict(_ACTIONS)
        for row in self._rows:
            if row.action != action and row.current_combo.strip().lower() == norm:
                return labels.get(row.action, row.action)
        return None

    def _warn_failed_registrations(self):
        """注册失败时给出可见反馈，避免用户以为已生效（静默失败）。"""
        failed = getattr(self._hotkey_mgr, "failed_actions", None)
        if not failed:
            return
        labels = dict(_ACTIONS)
        names = "、".join(labels.get(a, a) for a in failed)
        QMessageBox.warning(
            self,
            "快捷键注册失败",
            f"以下快捷键注册失败（可能被其它程序占用）：\n{names}\n\n请尝试换一组组合键。",
        )

    def _reset_defaults(self):
        from app.core.hotkey_manager import DEFAULT_HOTKEYS
        for row in self._rows:
            row.reset_combo(DEFAULT_HOTKEYS.get(row.action, ""))
