"""SQLite-backed local sticky reminders scheduled without AI or tool execution."""
import logging
from datetime import datetime, timedelta, timezone
from threading import RLock

from apscheduler.triggers.cron import CronTrigger
from PyQt6.QtCore import QDateTime, QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


def local_timezone():
    # Qt resolves the full system timezone, including DST rules on Windows.
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(bytes(QDateTime.currentDateTime().timeZone().id()).decode())
    except (KeyError, ValueError):
        from tzlocal import get_localzone
        return get_localzone()


def next_occurrence(rule, after):
    if rule["repeat"] == "once":
        return None
    from zoneinfo import ZoneInfo
    zone = rule.get("timezone", "")
    try:
        tz = ZoneInfo(zone) if zone else local_timezone()
    except (KeyError, ValueError):
        tz = local_timezone()
    hour, minute = map(int, rule["time"].split(":"))
    weekdays = ",".join(str(day) for day in rule["weekdays"]) if rule["repeat"] == "weekly" else "*"
    trigger = CronTrigger(hour=hour, minute=minute, day_of_week=weekdays, timezone=tz)
    return trigger.get_next_fire_time(None, after + timedelta(seconds=1))


class StickyReminderService(QObject):
    due = pyqtSignal(object)  # Coalesced list of note ids, emitted on Qt's thread.
    changed = pyqtSignal(int)
    _check_requested = pyqtSignal()

    def __init__(self, notes, scheduler, parent=None, now=None):
        super().__init__(parent)
        self.notes = notes
        self.scheduler = scheduler
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._stopped = False
        self._job_ids = set()
        self._check_requested.connect(self.check_due)
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(30000)
        self._recovery_timer.timeout.connect(self.check_due)

    def start(self):
        self._stopped = False
        self.check_due()
        self._recovery_timer.start()

    def stop(self):
        self._stopped = True
        self._recovery_timer.stop()
        for note_id in self._job_ids.copy():
            self._cancel(note_id)

    def configure(self, note_id, when, repeat="once", weekdays=None, sound=False, enabled=True):
        if when.tzinfo is None or (enabled and when <= self._now()):
            raise ValueError("Choose a future, timezone-aware reminder time")
        if repeat not in ("once", "daily", "weekly"):
            raise ValueError("Unsupported repeat rule")
        days = sorted(set(weekdays if weekdays is not None else [when.weekday()]))
        if repeat == "weekly" and (not days or any(day not in range(7) for day in days)):
            raise ValueError("Select at least one weekday")
        zone = local_timezone()
        local = when.astimezone(zone)
        rule = {"repeat": repeat, "time": local.strftime("%H:%M"), "weekdays": days,
                "sound": bool(sound), "timezone": str(zone)}
        if repeat != "once":
            when = next_occurrence(rule, local - timedelta(seconds=1))
        with self._lock:
            self.notes.set_sticky_reminder(note_id, rule, when.isoformat(), enabled)
            self._schedule(note_id)
        self.changed.emit(note_id)

    def remove(self, note_id):
        with self._lock:
            self._cancel(note_id)
            self.notes.delete_sticky_reminder(note_id)
        self.changed.emit(note_id)

    def snooze(self, note_ids):
        with self._lock:
            for note_id in note_ids:
                record = self.notes.get_sticky_reminder(note_id)
                if record and self.notes.get(note_id):
                    self.notes.set_sticky_reminder(note_id, record["rule"], (self._now() + timedelta(minutes=10)).isoformat())
                    self._schedule(note_id)
                    self.changed.emit(note_id)

    def _cancel(self, note_id):
        self._job_ids.discard(note_id)
        if self.scheduler:
            try:
                self.scheduler._scheduler.remove_job("sticky:" + str(note_id))
            except Exception:
                pass

    def _schedule(self, note_id):
        self._cancel(note_id)
        record = self.notes.get_sticky_reminder(note_id)
        if self._stopped or not record or not record["enabled"] or not self.notes.get(note_id) or not self.scheduler:
            return
        self.scheduler._scheduler.add_job(self._check_requested.emit, trigger="date",
                                         run_date=datetime.fromisoformat(record["next_at"]),
                                         id="sticky:" + str(note_id), replace_existing=True,
                                         misfire_grace_time=None)
        self._job_ids.add(note_id)

    def check_due(self):
        if self._stopped:
            return
        now = self._now()
        due = []
        with self._lock:
            records = self.notes.get_sticky_reminders(enabled_only=True)
            enabled = {r["note_id"] for r in records}
            for note_id in self._job_ids - enabled:
                self._cancel(note_id)
            for record in records:
                try:
                    when = datetime.fromisoformat(record["next_at"])
                    if when <= now:
                        note_id = record["note_id"]
                        next_at = next_occurrence(record["rule"], now)
                        self.notes.set_sticky_reminder(note_id, record["rule"],
                                                      (next_at or when).isoformat(), enabled=next_at is not None)
                        due.append(note_id)
                        self.changed.emit(note_id)
                        self._schedule(note_id)
                    elif record["note_id"] not in self._job_ids:
                        self._schedule(record["note_id"])
                except (ValueError, KeyError, TypeError):
                    logger.exception("Invalid sticky reminder %s", record["note_id"])
        if due:
            self.due.emit(due)
