"""Hotkey settings tab — capture, display, and save global hotkey bindings."""
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
        self._combo_lbl.setText("按 Esc 取消")
        if self._hotkey_mgr:
            self._hotkey_mgr.stop()
        cap = _Capture(self)
        cap.finished.connect(self._on_captured)
        cap.start()

    def _on_captured(self, combo: str):
        self._btn.setEnabled(True)
        self._btn.setText("修改")
        if combo:
            self._combo = combo
            self._combo_lbl.setText(_fmt(combo))
            self.combo_changed.emit(self._action, combo)
        else:
            self._combo_lbl.setText(_fmt(self._combo))
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

    # ------------------------------------------------------------------ private
    def _reset_defaults(self):
        from app.core.hotkey_manager import DEFAULT_HOTKEYS
        for row in self._rows:
            row.reset_combo(DEFAULT_HOTKEYS.get(row.action, ""))
