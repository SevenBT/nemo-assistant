"""Persisted selection button definitions, independent of Qt and the UI registry."""
from __future__ import annotations

BUILTIN_IDS = ("explain", "continue_explain", "new_continue_explain", "polish", "note")
PRESET_IDS = ("translate_inplace", "fix_grammar")
DEFAULT_ORDER = (*BUILTIN_IDS[:-1], *PRESET_IDS, "note")


def default_selection_actions(legacy: dict | None = None) -> dict:
    """Seed editable presets once, retaining legacy prompts and visibility."""
    legacy = legacy or {}
    custom = []
    for key, prompt_key in zip(PRESET_IDS, ("TranslatePrompt", "FixGrammarPrompt")):
        custom.append({
            "id": key, "preset": key, "name": "", "icon":
            "LANGUAGE" if key == "translate_inplace" else "ACCEPT",
            "prompt": legacy.get(prompt_key, "") or "", "mode": "rewrite",
        })
    enabled = {
        "explain": legacy.get("ExplainEnabled", True),
        "continue_explain": legacy.get("ContinueExplainEnabled", True),
        "new_continue_explain": legacy.get("ContinueExplainEnabled", True),
        "polish": legacy.get("RewriteEnabled", True),
        "translate_inplace": legacy.get("RewriteEnabled", True),
        "fix_grammar": legacy.get("RewriteEnabled", True),
        "note": legacy.get("NoteEnabled", True),
    }
    return {
        "version": 1, "custom": custom, "order": list(DEFAULT_ORDER),
        "buttons": {key: {"enabled": bool(value), "pinned": True}
                    for key, value in enabled.items()},
    }


def normalize_selection_actions(value: object) -> dict:
    """Return a fresh validated value; never regenerate explicitly deleted presets."""
    if not isinstance(value, dict) or not value:
        return default_selection_actions()
    custom = []
    seen = set(BUILTIN_IDS)
    records = value.get("custom", [])
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        key = record.get("id")
        if not isinstance(key, str) or not key.strip() or key in seen:
            continue
        preset = record.get("preset", "")
        preset = preset if preset in PRESET_IDS else ""
        prompt = record.get("prompt", "")
        prompt = prompt.strip() if isinstance(prompt, str) else ""
        name = record.get("name", "")
        name = name.strip() if isinstance(name, str) else ""
        if not preset and (not prompt or not name):
            continue
        seen.add(key)
        icon = record.get("icon", "ROBOT")
        custom.append({
            "id": key, "preset": preset, "name": name, "prompt": prompt,
            "icon": icon if isinstance(icon, str) else "ROBOT",
            "mode": "rewrite" if record.get("mode") == "rewrite" else "oneshot",
        })
    order = []
    stored_order = value.get("order", [])
    for key in stored_order if isinstance(stored_order, list) else []:
        if isinstance(key, str) and key in seen and key not in order:
            order.append(key)
    # Missing buttons append deterministically; existing user positions never move.
    order.extend(key for key in (*BUILTIN_IDS, *(a["id"] for a in custom))
                 if key not in order)
    buttons = value.get("buttons", {})
    buttons = buttons if isinstance(buttons, dict) else {}
    states = {}
    for key in order:
        state = buttons.get(key, {})
        state = state if isinstance(state, dict) else {}
        states[key] = {"enabled": state.get("enabled", True) is not False,
                       "pinned": state.get("pinned", True) is not False}
    return {"version": 1, "custom": custom, "order": order, "buttons": states}
