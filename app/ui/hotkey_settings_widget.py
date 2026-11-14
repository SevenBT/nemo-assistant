"""Hotkey settings tab — capture, display, and save global hotkey bindings."""
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CheckBox, SearchLineEdit, SegmentedWidget

try:
    import keyboard as _kb
    _KB_OK = True
except ImportError:
    _KB_OK = False

from app.i18n import t
from app.ui.style import set_text_role
from app.core.hotkey_actions import GROUPS, MODIFIERS, normalize_combo, scopes_overlap

# 录制只接收当前应用的 Qt 键盘事件；超时自动取消。
_CAPTURE_TIMEOUT_MS = 8000

# 全局动作和上下文动作统一要求修饰键，避免普通打字误触。
_MODIFIERS = set(MODIFIERS)


def _validate_combo(combo: str) -> str:
    """校验录入的组合键，返回错误信息；合法返回空串。"""
    if not combo:
        return t("hotkeys.err.noKey")
    parts = normalize_combo(combo).split("+")
    if not parts:
        return t("hotkeys.err.noKey")
    has_modifier = any(p in _MODIFIERS for p in parts)
    has_normal = any(p not in _MODIFIERS for p in parts)
    if not has_modifier:
        return t("hotkeys.err.needModifier")
    if not has_normal:
        return t("hotkeys.err.needNormal")
    if sum(p not in _MODIFIERS for p in parts) != 1:
        return t("hotkeys.err.needNormal")
    if normalize_combo(combo) in {"ctrl+alt+delete", "win+l"}:
        return t("hotkeys.err.reserved")
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
        self._combo_lbl.setMinimumWidth(100)
        self._combo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn = QPushButton(t("hotkeys.modify"))
        # 不写死宽度：文案随语言变化（"修改" / "Change"），加上主题 QSS 的内边距后
        # 固定宽度会裁掉文字。用最小宽度给下限——既保证文字完整，也避免录制中文案
        # 变短（"…"）时按钮缩窄抖动。
        self._btn.setMinimumWidth(self._btn.sizeHint().width())
        self._btn.clicked.connect(self._on_modify)

        layout.addWidget(self._combo_lbl, 1)
        layout.addWidget(self._btn)
        self._clear_btn = QPushButton(t("hotkeys.clear"))
        self._clear_btn.clicked.connect(self._clear_combo)
        layout.addWidget(self._clear_btn)

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
            self._hotkey_mgr.suspend("recording")
        QApplication.instance().installEventFilter(self)
        self.setFocus()
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_capture_timeout)
        self._timeout.start(_CAPTURE_TIMEOUT_MS)

    def _on_capture_timeout(self):
        self._on_captured("")

    def eventFilter(self, obj, event):
        if self._capturing and event.type() == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            if event.key() == Qt.Key.Key_Escape:
                self._on_captured("")
            elif event.key() not in (Qt.Key.Key_Control, Qt.Key.Key_Alt,
                                      Qt.Key.Key_Shift, Qt.Key.Key_Meta):
                self._on_captured(QKeySequence(event.keyCombination()).toString(
                    QKeySequence.SequenceFormat.PortableText))
            return True
        if self._capturing and event.type() == QEvent.Type.ApplicationDeactivate:
            self._on_captured("")
        return super().eventFilter(obj, event)

    def hideEvent(self, event):
        if self._capturing:
            self._on_captured("")
        super().hideEvent(event)

    def _clear_combo(self):
        if self._capturing:
            self._on_captured("")
        self.reset_combo("")
        self.combo_changed.emit(self._action, "")

    def _on_captured(self, combo: str):
        if not self._capturing:
            return
        self._capturing = False
        QApplication.instance().removeEventFilter(self)
        if hasattr(self, "_timeout"):
            self._timeout.stop()
        if self._hotkey_mgr and hasattr(self._hotkey_mgr, "resume"):
            self._hotkey_mgr.resume("recording")
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

        self._combo = normalize_combo(combo)
        self._combo_lbl.setText(_fmt(self._combo))
        self.combo_changed.emit(self._action, self._combo)
        if self._hotkey_mgr:
            self._hotkey_mgr.reload()


class HotkeySettingsWidget(QWidget):
    """Tab content widget for the "快捷键" settings tab."""

    def __init__(self, config, hotkey_mgr, parent=None):
        super().__init__(parent)
        self._config = config
        self._hotkey_mgr = hotkey_mgr
        self._rows: list[_HotkeyRow] = []
        self._current_group = "selection"
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        layout = QVBoxLayout(self)
        self._search = SearchLineEdit()
        self._search.setPlaceholderText(t("hotkeys.search"))
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)
        self._pivot = SegmentedWidget()
        for group in GROUPS:
            self._pivot.addItem(group, t(f"hotkeys.group.{group}"))
        self._pivot.setCurrentItem(self._current_group)
        self._pivot.currentItemChanged.connect(self._on_group_changed)
        layout.addWidget(self._pivot)
        self._bound_only = CheckBox(t("hotkeys.boundOnly"))
        self._bound_only.toggled.connect(self._apply_filter)
        layout.addWidget(self._bound_only)
        self._rows_widget = QWidget()
        self._form = QVBoxLayout(self._rows_widget)
        self._form.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._rows_widget)
        self.refresh_actions()
        layout.addStretch()
        footer = QHBoxLayout()
        reset_btn = QPushButton(t("hotkeys.restoreGroup"))
        reset_btn.clicked.connect(lambda: self._reset_defaults(self._current_group))
        footer.addWidget(reset_btn)
        layout.addLayout(footer)

        if not _KB_OK:
            warn = QLabel(t("hotkeys.kbMissing"))
            set_text_role(warn, "warning")
            layout.insertWidget(0, warn)

    def refresh_actions(self):
        pending = {row.action: row.current_combo for row in self._rows}
        for row in self._rows:
            if row._capturing:
                row._on_captured("")
        while self._form.count():
            item = self._form.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._rows.clear()
        self._actions = {a.id: a for a in self._config.actions}
        self._containers = {}
        hotkeys = {**self._config.hotkeys, **pending}
        for action in self._actions.values():
            container = QWidget()
            content = QHBoxLayout(container)
            content.setContentsMargins(0, 8, 0, 8)
            label = QLabel(self._label(action.id))
            label.setWordWrap(True)
            content.addWidget(label, 1)
            row = _HotkeyRow(action.id, hotkeys.get(action.id, ""), self._hotkey_mgr)
            row.conflict_checker = self._find_conflict
            row.combo_changed.connect(lambda *_: self._apply_filter())
            content.addWidget(row)
            self._rows.append(row)
            self._containers[action.id] = container
            self._form.addWidget(container)
        self._apply_filter()

    def _label(self, action_id):
        action = self._actions[action_id]
        return action.label or t(action.label_key)

    def _on_group_changed(self, group):
        self._current_group = group
        self._apply_filter()

    def _apply_filter(self, *_):
        query = self._search.text().strip().lower()
        for row in self._rows:
            action = self._actions[row.action]
            searchable = f"{self._label(row.action)} {row.current_combo} {_fmt(row.current_combo)}"
            visible = (query in searchable.lower() if query else action.group == self._current_group)
            if self._bound_only.isChecked() and not row.current_combo:
                visible = False
            self._containers[row.action].setVisible(visible)

    # ------------------------------------------------------------------ public
    def save(self):
        """Write pending changes to config and reload hotkey manager."""
        for row in self._rows:
            if row._capturing:
                row._on_captured("")
        updates = {row.action: row.current_combo for row in self._rows}
        self._config.update_hotkeys(updates)
        if self._hotkey_mgr:
            self._hotkey_mgr.reload()
            self._warn_failed_registrations()

    # ------------------------------------------------------------------ private
    def _find_conflict(self, action: str, combo: str) -> str | None:
        """若 combo 已被其它 action 占用，返回那个 action 的标签；否则 None。"""
        norm = normalize_combo(combo)
        action_scope = self._actions[action].scope
        if action_scope == "screenshot" and norm in {"ctrl+z", "ctrl+y", "ctrl+shift+z"}:
            return t("hotkeys.captureHistory")
        for row in self._rows:
            if (row.action != action and row.current_combo
                    and normalize_combo(row.current_combo) == norm
                    and scopes_overlap(action_scope, self._actions[row.action].scope)):
                return self._label(row.action)
        return None

    def _warn_failed_registrations(self):
        """注册失败时给出可见反馈，避免用户以为已生效（静默失败）。"""
        failed = getattr(self._hotkey_mgr, "failed_actions", None)
        if not failed:
            return
        names = "、".join(self._label(a) if a in self._actions else a for a in failed)
        QMessageBox.warning(
            self,
            t("hotkeys.err.registerFailedTitle"),
            t("hotkeys.err.registerFailedBody", names=names),
        )

    def _reset_defaults(self, group=None):
        targets = [row for row in self._rows
                   if group is None or self._actions[row.action].group == group]
        # Release bindings within this group together before restoring defaults,
        # so a user-swapped pair does not block its own reset.
        for row in targets:
            row.reset_combo("")
        for row in targets:
            action = self._actions[row.action]
            if action.default and self._find_conflict(action.id, action.default):
                continue
            row.reset_combo(action.default)
        self._apply_filter()
