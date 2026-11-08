"""Selection settings: explicit user ordering, built-ins and editable AI actions."""
from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, ComboBox, FluentIcon, LineEdit, PrimaryPushButton, PushButton,
    SettingCardGroup, StrongBodyLabel, SwitchSettingCard, TextEdit, ToggleToolButton, ToolButton,
)

from app.core.config import cfg
from app.core.selection_actions_config import BUILTIN_IDS, PRESET_IDS, normalize_selection_actions
from app.i18n import t
from app.ui.selection_icons import SELECTION_ICONS, selection_icon
from app.ui.text_actions import (
    get_all_text_actions, get_default_text_action, get_selection_actions_config,
)

_BUILTIN_PROMPTS = {"explain": "selectionExplainPrompt", "polish": "selectionPolishPrompt"}


class ActionEditor(QDialog):
    """A native dialog also works when settings are embedded in stacked panels."""

    def __init__(self, record=None, *, builtin=None, parent=None):
        super().__init__(parent)
        self._record = dict(record or {})
        self._builtin = builtin
        self._preset = get_default_text_action(self._record.get("preset", ""))
        self._icon_name = self._record.get("icon", "ROBOT")
        if self._icon_name not in SELECTION_ICONS:
            self._icon_name = "ROBOT"
        self.setWindowTitle(t("selection.actions.edit") if record or builtin else t("selection.actions.add"))
        self.resize(480, 480)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(BodyLabel(t("selection.actions.name"), self))
        name_row = QHBoxLayout()
        self._icon_btn = PushButton(self)
        self._icon_btn.setIcon(builtin.icon if builtin else selection_icon(self._icon_name))
        self._icon_btn.setText(t("selection.actions.chooseIcon"))
        self._icon_btn.setEnabled(builtin is None)
        name_row.addWidget(self._icon_btn)
        self._name = LineEdit(self)
        self._name.setMaxLength(40)
        self._name.setText(builtin.label if builtin else self._record.get("name", "") or
                           (self._preset.label if self._preset else ""))
        self._name.setEnabled(builtin is None)
        name_row.addWidget(self._name, 1)
        layout.addLayout(name_row)

        self._icon_panel = QWidget(self)
        grid = QGridLayout(self._icon_panel)
        grid.setContentsMargins(0, 0, 0, 0)
        self._icon_buttons = {}
        for index, (name, icon) in enumerate(SELECTION_ICONS.items()):
            button = ToggleToolButton(icon, self._icon_panel)
            button.setFixedSize(34, 34)
            button.setCheckable(True)
            button.setChecked(name == self._icon_name)
            button.setToolTip(t(f"selection.icon.{name}"))
            button.setAccessibleName(t(f"selection.icon.{name}"))
            button.clicked.connect(lambda _checked=False, key=name: self._select_icon(key))
            self._icon_buttons[name] = button
            grid.addWidget(button, index // 10, index % 10)
        self._icon_panel.hide()
        layout.addWidget(self._icon_panel)
        self._icon_btn.clicked.connect(lambda: self._icon_panel.setVisible(not self._icon_panel.isVisible()))

        layout.addWidget(BodyLabel(t("selection.actions.resultMode"), self))
        self._mode = ComboBox(self)
        self._mode.addItem(t("selection.actions.view"), userData="oneshot")
        self._mode.addItem(t("selection.actions.rewrite"), userData="rewrite")
        mode = builtin.mode if builtin else self._record.get("mode", "oneshot")
        self._mode.setCurrentIndex(1 if mode == "rewrite" else 0)
        self._mode.setEnabled(builtin is None)
        layout.addWidget(self._mode)

        layout.addWidget(BodyLabel(t("selection.actions.prompt"), self))
        self._prompt = TextEdit(self)
        self._prompt.setMinimumHeight(160)
        self._prompt.setPlaceholderText(t("settings.selection.promptPlaceholder"))
        if builtin:
            prompt = cfg.get(getattr(cfg, _BUILTIN_PROMPTS[builtin.key])) or builtin.default_prompt
        else:
            prompt = self._record.get("prompt", "") or (self._preset.default_prompt if self._preset else "")
        self._prompt.setPlainText(prompt)
        layout.addWidget(self._prompt, 1)
        hint = BodyLabel(t("selection.actions.promptHint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._error = BodyLabel(t("selection.actions.required"), self)
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)
        if builtin or self._preset:
            reset = PushButton(t("settings.selection.restoreDefault"), self)
            reset.clicked.connect(lambda: self._prompt.setPlainText((builtin or self._preset).default_prompt))
            layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_icon(self, name):
        self._icon_name = name
        self._icon_btn.setIcon(selection_icon(name))
        for key, button in self._icon_buttons.items():
            button.setChecked(key == name)
        self._icon_panel.hide()

    def accept(self):
        if not self._name.text().strip() or not self._prompt.toPlainText().strip():
            self._error.show()
            return
        super().accept()

    def record(self):
        return {
            **self._record,
            "id": self._record.get("id") or f"custom_{uuid.uuid4().hex}",
            "name": self._name.text().strip(), "icon": self._icon_name,
            "prompt": self._prompt.toPlainText().strip(), "mode": self._mode.currentData(),
        }


class SelectionPage(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._config = get_selection_actions_config()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        group = SettingCardGroup(t("settings.selection.group"), container)
        for icon, title, description, item in (
            (FluentIcon.QUICK_NOTE, "settings.selection.float", "settings.selection.float.desc", cfg.selectionFloatEnabled),
            (FluentIcon.ACCEPT, "settings.selection.verify", "settings.selection.verify.desc", cfg.selectionRewriteVerify),
        ):
            group.addSettingCard(SwitchSettingCard(icon, t(title), t(description), configItem=item, parent=self))
        layout.addWidget(group)
        layout.addWidget(StrongBodyLabel(t("selection.actions.manage"), container))
        hint = BodyLabel(t("selection.actions.orderHint"), container)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        add_row = QHBoxLayout()
        add = PrimaryPushButton(t("selection.actions.add"), container)
        add.clicked.connect(self._add)
        add_row.addWidget(add)
        self._templates = ComboBox(container)
        for key in PRESET_IDS:
            self._templates.addItem(get_default_text_action(key).label, userData=key)
        add_row.addWidget(self._templates, 1)
        template = PushButton(t("selection.actions.addTemplate"), container)
        template.clicked.connect(self._add_template)
        add_row.addWidget(template)
        layout.addLayout(add_row)

        self._list = QListWidget(container)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(240)
        self._list.setAccessibleName(t("selection.actions.manage"))
        self._list.currentRowChanged.connect(self._selection_changed)
        self._list.model().rowsMoved.connect(self._order_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self._list)

        controls = QHBoxLayout()
        self._placement = ComboBox(container)
        for key in ("bar", "more", "hidden"):
            self._placement.addItem(t(f"selection.actions.{key}"), userData=key)
        self._placement.currentIndexChanged.connect(self._placement_changed)
        controls.addWidget(self._placement, 1)
        self._up = ToolButton(FluentIcon.UP, container)
        self._down = ToolButton(FluentIcon.DOWN, container)
        for button, direction, key in ((self._up, -1, "up"), (self._down, 1, "down")):
            button.setToolTip(t(f"selection.actions.{key}"))
            button.setAccessibleName(t(f"selection.actions.{key}"))
            button.clicked.connect(lambda _checked=False, step=direction: self._move(step))
            controls.addWidget(button)
        self._edit_btn = PushButton(t("selection.actions.edit"), container)
        self._edit_btn.clicked.connect(self._edit)
        controls.addWidget(self._edit_btn)
        self._delete_btn = ToolButton(FluentIcon.DELETE, container)
        self._delete_btn.setToolTip(t("selection.actions.delete"))
        self._delete_btn.setAccessibleName(t("selection.actions.delete"))
        self._delete_btn.clicked.connect(self._delete)
        controls.addWidget(self._delete_btn)
        layout.insertLayout(layout.indexOf(self._list), controls)
        layout.addStretch()
        self.setWidget(container)
        self._rebuild()

    def _selected_key(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _rebuild(self, selected=None):
        self._list.blockSignals(True)
        self._list.clear()
        selected_row = 0
        for index, action in enumerate(get_all_text_actions(self._config)):
            state = self._config["buttons"][action.key]
            placement = "hidden" if not state["enabled"] else "bar" if state["pinned"] else "more"
            kind = t("selection.actions.builtin" if action.key in BUILTIN_IDS else "selection.actions.custom")
            text = f'{action.label}\n{kind} · {t(f"selection.actions.{placement}")}'
            item = QListWidgetItem(action.icon.icon(), text)
            item.setData(Qt.ItemDataRole.UserRole, action.key)
            self._list.addItem(item)
            if action.key == selected:
                selected_row = index
        self._list.blockSignals(False)
        self._list.setCurrentRow(selected_row)
        self._selection_changed()

    def _selection_changed(self, *_args):
        key = self._selected_key()
        if not key:
            return
        state = self._config["buttons"][key]
        placement = "hidden" if not state["enabled"] else "bar" if state["pinned"] else "more"
        self._placement.blockSignals(True)
        self._placement.setCurrentIndex({"bar": 0, "more": 1, "hidden": 2}[placement])
        self._placement.blockSignals(False)
        self._edit_btn.setEnabled(key not in BUILTIN_IDS or key in _BUILTIN_PROMPTS)
        self._delete_btn.setEnabled(key not in BUILTIN_IDS)
        row = self._list.currentRow()
        self._up.setEnabled(row > 0)
        self._down.setEnabled(row < self._list.count() - 1)

    def _placement_changed(self, *_args):
        key = self._selected_key()
        if not key:
            return
        placement = self._placement.currentData()
        state = self._config["buttons"][key]
        state["enabled"] = placement != "hidden"
        if placement != "hidden":
            state["pinned"] = placement == "bar"
        self.save()
        self._rebuild(key)

    def _order_changed(self, *_args):
        self._config["order"] = [self._list.item(i).data(Qt.ItemDataRole.UserRole)
                                 for i in range(self._list.count())]
        self.save()
        self._selection_changed()

    def _move(self, step):
        row = self._list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(target, item)
        self._list.setCurrentRow(target)
        self._order_changed()

    def _add(self):
        dialog = ActionEditor(parent=self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._insert(dialog.record())

    def _add_template(self):
        key = self._templates.currentData()
        preset = get_default_text_action(key)
        record = {"preset": key, "icon": "LANGUAGE" if key == "translate_inplace" else "ACCEPT",
                  "mode": preset.mode}
        dialog = ActionEditor(record, parent=self.window())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._insert(dialog.record())

    def _insert(self, record):
        key = record["id"]
        self._config["custom"].append(record)
        self._config["order"].append(key)
        self._config["buttons"][key] = {"enabled": True, "pinned": True}
        self.save()
        self._rebuild(key)

    def _edit(self):
        key = self._selected_key()
        if not key or (key in BUILTIN_IDS and key not in _BUILTIN_PROMPTS):
            return
        builtin = get_default_text_action(key) if key in BUILTIN_IDS else None
        record = next((a for a in self._config["custom"] if a["id"] == key), None)
        dialog = ActionEditor(record, builtin=builtin, parent=self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edited = dialog.record()
        if builtin:
            prompt = edited["prompt"]
            cfg.set(getattr(cfg, _BUILTIN_PROMPTS[key]), "" if prompt == builtin.default_prompt else prompt)
        else:
            record.update(edited)
        self.save()
        self._rebuild(key)

    def _delete(self):
        key = self._selected_key()
        if not key or key in BUILTIN_IDS:
            return
        answer = QMessageBox.question(self.window(), t("selection.actions.delete"), t("selection.actions.deleteConfirm"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._config["custom"] = [a for a in self._config["custom"] if a["id"] != key]
        self._config["order"].remove(key)
        self._config["buttons"].pop(key, None)
        self.save()
        self._rebuild()

    def save(self):
        self._config = normalize_selection_actions(self._config)
        cfg.set(cfg.selectionActions, self._config)
