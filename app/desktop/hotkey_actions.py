"""Shared shortcut definitions, scopes and persisted bindings."""
from __future__ import annotations

from dataclasses import dataclass

from app.desktop.selection_actions_config import normalize_selection_actions

LEGACY_ITEMS = {
    "screenshot": "hotkeyScreenshot", "new_note": "hotkeyNewNote",
    "toggle_window": "hotkeyToggleWindow", "quick_ask": "hotkeyQuickAsk",
    "selection": "hotkeySelection",
}
GROUPS = ("selection", "screenshot", "notes", "chat", "system")


@dataclass(frozen=True)
class HotkeyAction:
    id: str
    group: str
    scope: str
    label_key: str
    default: str = ""
    label: str = ""


_ACTIONS = (
    HotkeyAction("screenshot", "screenshot", "global", "hotkeys.action.screenshot", "ctrl+alt+a"),
    HotkeyAction("screenshot:ocr", "screenshot", "screenshot", "hotkeys.action.ocr", "ctrl+alt+o"),
    HotkeyAction("screenshot:pin", "screenshot", "screenshot", "hotkeys.action.pinShot", "ctrl+alt+i"),
    HotkeyAction("screenshot:copy", "screenshot", "screenshot", "hotkeys.action.copyShot", "ctrl+alt+c"),
    HotkeyAction("screenshot:vision:ask", "screenshot", "screenshot", "hotkeys.action.askShot", "ctrl+alt+v"),
    HotkeyAction("screenshot:vision:translate", "screenshot", "screenshot", "hotkeys.action.translateShot", "ctrl+alt+shift+t"),
    HotkeyAction("selection", "selection", "selection", "hotkeys.action.selection", "ctrl+alt+e"),
    HotkeyAction("selection:explain", "selection", "selection", "textaction.explain.label", "ctrl+alt+x"),
    HotkeyAction("selection:translate_inplace", "selection", "selection", "textaction.translate.label", "ctrl+alt+t"),
    HotkeyAction("selection:polish", "selection", "selection", "textaction.polish.label", "ctrl+alt+r"),
    HotkeyAction("selection:fix_grammar", "selection", "selection", "textaction.fix.label", "ctrl+alt+g"),
    HotkeyAction("selection:note", "selection", "selection", "textaction.note.label", "ctrl+alt+shift+m"),
    HotkeyAction("new_note", "notes", "global", "hotkeys.action.newNote", "ctrl+alt+n"),
    HotkeyAction("notes:new", "notes", "global", "hotkeys.action.newMarkdown", "ctrl+alt+shift+n"),
    HotkeyAction("notes:open", "notes", "global", "hotkeys.action.openNotes", "ctrl+alt+m"),
    HotkeyAction("notes:toggle", "notes", "global", "hotkeys.action.toggleNotes", "ctrl+alt+shift+h"),
    HotkeyAction("quick_ask", "chat", "global", "hotkeys.action.quickAsk", "ctrl+alt+q"),
    HotkeyAction("chat:new", "chat", "global", "hotkeys.action.newChat", "ctrl+alt+shift+c"),
    HotkeyAction("chat:copy", "chat", "global", "hotkeys.action.copyReply", "ctrl+alt+shift+y"),
    HotkeyAction("toggle_window", "system", "global", "hotkeys.action.toggleWindow", "ctrl+alt+space"),
    HotkeyAction("system:settings", "system", "global", "hotkeys.action.settings", "ctrl+alt+,"),
    HotkeyAction("system:top", "system", "global", "hotkeys.action.top", "ctrl+alt+p"),
    HotkeyAction("system:pause", "system", "global", "hotkeys.action.pause", "ctrl+alt+shift+space"),
    HotkeyAction("system:overview", "system", "global", "hotkeys.action.overview", "ctrl+alt+/"),
    HotkeyAction("system:selection_float", "system", "global", "hotkeys.action.selectionFloat", "ctrl+alt+f"),
)
DEFAULT_HOTKEYS = {action.id: action.default for action in _ACTIONS}


def get_hotkey_actions(config=None) -> tuple[HotkeyAction, ...]:
    if config is None:
        from app.config.config import cfg
        config = cfg
    selection = normalize_selection_actions(config.get(config.selectionActions))
    # Deleted custom presets must not leave executable shortcut entries behind.
    result = [a for a in _ACTIONS if not a.id.startswith("selection:")
              or a.id.split(":", 1)[1] in selection["order"]]
    known = {a.id for a in result}
    records = {r["id"]: r for r in selection["custom"]}
    for key in selection["order"]:
        action_id = f"selection:{key}"
        record = records.get(key, {})
        label = record.get("name", "")
        label_key = {
            "continue_explain": "textaction.continue.label",
            "new_continue_explain": "textaction.newContinue.label",
        }.get(key, "hotkeys.action.custom")
        if action_id not in known:
            result.append(HotkeyAction(action_id, "selection", "selection", label_key, label=label))
        elif label:
            for index, action in enumerate(result):
                if action.id == action_id:
                    result[index] = HotkeyAction(action.id, action.group, action.scope,
                                                action.label_key, action.default, label)
    return tuple(result)


def read_hotkeys(config=None) -> dict[str, str]:
    if config is None:
        from app.config.config import cfg
        config = cfg
    extra = config.get(config.hotkeyBindings)
    extra = extra if isinstance(extra, dict) else {}
    actions = get_hotkey_actions(config)
    bindings = {}
    for action in actions:
        if action.id not in LEGACY_ITEMS and action.id not in extra:
            continue
        value = (config.get(getattr(config, LEGACY_ITEMS[action.id]))
                 if action.id in LEGACY_ITEMS else extra[action.id])
        # Empty means disabled, never "fall back to the factory default".
        bindings[action.id] = value.strip() if isinstance(value, str) else ""
    # Existing user bindings take precedence over newly introduced defaults.
    scopes = {action.id: action.scope for action in actions}
    for action in actions:
        if action.id in bindings:
            continue
        conflict = any(combo and normalize_combo(combo) == normalize_combo(action.default)
                       and scopes_overlap(action.scope, scopes[key])
                       for key, combo in bindings.items())
        bindings[action.id] = "" if conflict else action.default
    return bindings


def write_hotkeys(updates: dict[str, str], config=None):
    if config is None:
        from app.config.config import cfg
        config = cfg
    bindings = read_hotkeys(config)
    bindings.update({k: v for k, v in updates.items() if k in bindings})
    for action, item in LEGACY_ITEMS.items():
        config.set(getattr(config, item), bindings[action])
    config.set(config.hotkeyBindings, {k: v for k, v in bindings.items() if k not in LEGACY_ITEMS})


_ALIASES = {"control": "ctrl", "windows": "win", "meta": "win", "cmd": "win",
            "esc": "escape", "del": "delete", "return": "enter", "comma": ",",
            "slash": "/"}
MODIFIERS = ("ctrl", "alt", "shift", "win")


def normalize_combo(combo: str) -> str:
    parts = [_ALIASES.get(p.strip().lower(), p.strip().lower())
             for p in combo.split("+") if p.strip()]
    return "+".join([p for p in MODIFIERS if p in parts]
                    + sorted(p for p in parts if p not in MODIFIERS))


def scopes_overlap(left: str, right: str) -> bool:
    # Global hooks are suspended while a screenshot overlay owns the keyboard.
    return (left == right == "screenshot") or (left != "screenshot" and right != "screenshot")
