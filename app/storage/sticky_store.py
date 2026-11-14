"""Per-note desktop preferences and reminder rules, independent of note text."""
import json
from datetime import datetime


DEFAULT_STICKY_SETTINGS = {
    "version": 1, "color": "auto", "opacity": 100, "width": 280, "height": 260,
    "top": True, "collapsed": False, "locked": False, "edge": False,
    "visible": True, "font_family": "", "font_size": 13,
    "hide_completed": False,
}


def normalize_settings(saved):
    settings = dict(DEFAULT_STICKY_SETTINGS)
    if isinstance(saved, dict):
        settings.update({key: value for key, value in saved.items() if key in settings})
    for key, default in DEFAULT_STICKY_SETTINGS.items():
        if isinstance(default, bool):
            settings[key] = settings[key] if isinstance(settings[key], bool) else default
        elif isinstance(default, str) and not isinstance(settings[key], str):
            settings[key] = default
    for key, low, high in (("opacity", 70, 100), ("width", 180, 4000), ("height", 120, 4000), ("font_size", 8, 48)):
        try:
            settings[key] = max(low, min(high, int(settings[key])))
        except (TypeError, ValueError, OverflowError):
            settings[key] = DEFAULT_STICKY_SETTINGS[key]
    settings["version"] = 1
    return settings


class StickyStore:
    """Mixin sharing NoteManager's SQLite connection lifecycle."""

    def get_sticky_settings(self, note_id):
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT settings FROM sticky_settings WHERE note_id=?", (int(note_id),)).fetchone()
        try:
            saved = json.loads(row[0]) if row else {}
        except (ValueError, TypeError):
            saved = {}
        return normalize_settings(saved)

    def set_sticky_settings(self, note_id, **updates):
        note_id = int(note_id)
        settings = self.get_sticky_settings(note_id)
        settings.update({key: value for key, value in updates.items() if key in DEFAULT_STICKY_SETTINGS})
        settings = normalize_settings(settings)
        with self.db.get_connection() as conn:
            conn.execute("INSERT INTO sticky_settings(note_id,settings) SELECT id,? FROM notes WHERE id=? AND is_deleted=0 "
                         "ON CONFLICT(note_id) DO UPDATE SET settings=excluded.settings",
                         (json.dumps(settings, ensure_ascii=False), note_id))
            conn.commit()
        return settings

    def get_sticky_reminder(self, note_id):
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM sticky_reminders WHERE note_id=?", (int(note_id),)).fetchone()
        if not row:
            return None
        return {"note_id": row["note_id"], "rule": json.loads(row["rule"]),
                "next_at": row["next_at"], "enabled": bool(row["enabled"])}

    def set_sticky_reminder(self, note_id, rule, next_at, enabled=True):
        if datetime.fromisoformat(next_at).tzinfo is None:
            raise ValueError("Reminder time must include a timezone")
        with self.db.get_connection() as conn:
            conn.execute("INSERT INTO sticky_reminders(note_id,rule,next_at,enabled) "
                         "SELECT id,?,?,? FROM notes WHERE id=? AND is_deleted=0 "
                         "ON CONFLICT(note_id) DO UPDATE SET rule=excluded.rule,next_at=excluded.next_at,enabled=excluded.enabled",
                         (json.dumps(rule, ensure_ascii=False), next_at, int(enabled), int(note_id)))
            conn.commit()

    def delete_sticky_reminder(self, note_id):
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM sticky_reminders WHERE note_id=?", (int(note_id),))
            conn.commit()

    def get_sticky_reminders(self, enabled_only=False):
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT r.note_id FROM sticky_reminders r JOIN notes n ON n.id=r.note_id "
                                "WHERE n.is_deleted=0" + (" AND r.enabled=1" if enabled_only else "")).fetchall()
        return [self.get_sticky_reminder(row[0]) for row in rows]

    def get_sticky_templates(self):
        with self.db.get_connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM sticky_templates ORDER BY id")]

    def save_sticky_template(self, name, content, settings):
        # Never propagate active reminders, window position or completed state.
        appearance = {key: settings[key] for key in ("color", "opacity", "font_family", "font_size", "width", "height") if key in settings}
        with self.db.get_connection() as conn:
            cursor = conn.execute("INSERT INTO sticky_templates(name,content,settings) VALUES(?,?,?)",
                                  (name, content, json.dumps(appearance, ensure_ascii=False)))
            conn.commit()
            return cursor.lastrowid
