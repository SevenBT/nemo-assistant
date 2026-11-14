"""Reminder settings and actionable desktop cards."""
from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (QApplication, QComboBox, QDateTimeEdit, QDialog,
                            QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app.desktop.sticky_reminders import local_timezone, next_occurrence
from app.i18n import t
from qfluentwidgets import CheckBox


class StickyReminderDialog(QDialog):
    def __init__(self, service, note_id, parent=None):
        super().__init__(parent)
        self.service, self.note_id = service, note_id
        self.setWindowTitle(t("sticky.manageReminder"))
        self.setMinimumWidth(330)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("sticky.reminder.time")))
        record = service.notes.get_sticky_reminder(note_id)
        when = datetime.fromisoformat(record["next_at"]).astimezone() if record else datetime.now().astimezone() + timedelta(hours=1)
        self.time = QDateTimeEdit(QDateTime(when))
        self.time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.time.setCalendarPopup(True)
        layout.addWidget(self.time)
        layout.addWidget(QLabel(t("sticky.reminder.repeat")))
        self.repeat = QComboBox()
        for key in ("once", "daily", "weekly"):
            self.repeat.addItem(t("sticky.reminder." + key), key)
        self.repeat.setCurrentIndex(self.repeat.findData(record["rule"]["repeat"]) if record else 0)
        layout.addWidget(self.repeat)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.days = []
        weekdays = record["rule"]["weekdays"] if record else [when.weekday()]
        for i, label in enumerate(t("sticky.weekdays").split()):
            check = QPushButton(label)
            check.setObjectName("stickyWeekday")
            check.setCheckable(True)
            check.setFixedSize(34, 28)
            check.setChecked(i in weekdays)
            self.days.append(check)
            row.addWidget(check)
        layout.addLayout(row)
        from app.ui.style import contrasting_text, get_current_theme, set_text_role
        theme = get_current_theme()
        self.setStyleSheet(f"QPushButton#stickyWeekday{{padding:0}}"
                           f"QPushButton#stickyWeekday:checked{{background:{theme['accent']};color:{contrasting_text(theme['accent'])}}}")
        def update_days():
            for check in self.days:
                check.setVisible(self.repeat.currentData() == "weekly")
        self.repeat.currentIndexChanged.connect(update_days)
        update_days()
        self.sound = CheckBox(t("sticky.reminder.sound"))
        self.sound.setChecked(record["rule"].get("sound", False) if record else False)
        layout.addWidget(self.sound)
        self.enabled = CheckBox(t("sticky.reminder.enabled"))
        self.enabled.setChecked(record["enabled"] if record else True)
        layout.addWidget(self.enabled)
        self.next_label = QLabel(t("sticky.reminder.next", time=when.strftime("%Y-%m-%d %H:%M")))
        layout.addWidget(self.next_label)
        self.time.dateTimeChanged.connect(self._preview)
        self.repeat.currentIndexChanged.connect(self._preview)
        self.enabled.toggled.connect(self._preview)
        for check in self.days:
            check.toggled.connect(self._preview)
        self._preview()
        hint = QLabel(t("sticky.reminder.background"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.error = QLabel()
        set_text_role(self.error, "error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("sticky.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if record:
            remove = QPushButton(t("sticky.reminder.remove"))
            remove.clicked.connect(self.remove)
            layout.addWidget(remove)

    def _when(self):
        value = self.time.dateTime()
        date, time = value.date(), value.time()
        return datetime(date.year(), date.month(), date.day(), time.hour(), time.minute(), tzinfo=local_timezone())

    def _preview(self, *_):
        if not self.enabled.isChecked():
            self.next_label.setText(t("sticky.reminder.paused"))
            return
        when = self._when()
        repeat = self.repeat.currentData()
        weekdays = [i for i, check in enumerate(self.days) if check.isChecked()]
        if repeat == "weekly" and not weekdays:
            self.next_label.setText(t("sticky.reminder.invalid"))
            return
        if repeat != "once":
            rule = {"repeat": repeat, "time": when.strftime("%H:%M"), "weekdays": weekdays, "timezone": str(local_timezone())}
            when = next_occurrence(rule, when - timedelta(seconds=1))
        self.next_label.setText(t("sticky.reminder.next", time=when.strftime("%Y-%m-%d %H:%M")))

    def save(self):
        try:
            self.service.configure(self.note_id, self._when(), self.repeat.currentData(),
                                   [i for i, check in enumerate(self.days) if check.isChecked()],
                                   self.sound.isChecked(), self.enabled.isChecked())
        except ValueError:
            self.error.setText(t("sticky.reminder.invalid"))
            return
        self.accept()

    def remove(self):
        self.service.remove(self.note_id)
        self.accept()


class StickyReminderCard(QDialog):
    def __init__(self, service, controller, note_ids, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.note_ids = note_ids
        self.setWindowTitle(t("sticky.reminder"))
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        if len(note_ids) > 1:
            label = QLabel(t("sticky.reminder.missed", count=len(note_ids)))
            label.setWordWrap(True)
            layout.addWidget(label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMaximumHeight(300)
        contents = QWidget()
        notes_layout = QVBoxLayout(contents)
        for note_id in note_ids:
            note = service.notes.get(note_id)
            if not note:
                continue
            button = QPushButton(note.title)
            button.setToolTip(t("sticky.reminder.open"))
            button.clicked.connect(lambda checked=False, key=note_id: controller.show_note(key))
            notes_layout.addWidget(button)
        scroll.setWidget(contents)
        layout.addWidget(scroll)
        actions = QHBoxLayout()
        snooze = QPushButton(t("sticky.reminder.snooze"))
        snooze.clicked.connect(lambda: (service.snooze(note_ids), self.close()))
        actions.addWidget(snooze)
        dismiss = QPushButton(t("sticky.reminder.dismiss"))
        dismiss.clicked.connect(self.close)
        actions.addWidget(dismiss)
        layout.addLayout(actions)
        records = [service.notes.get_sticky_reminder(key) for key in note_ids]
        if any(record and record["rule"].get("sound") for record in records):
            QApplication.beep()
