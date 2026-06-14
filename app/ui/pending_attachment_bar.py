"""Pending attachment preview strip shown above the input box.

Displays attachments the user has dropped/pasted but not yet sent, each
as a small thumbnail (images) or chip (files) with a remove button —
mirroring the preview row in web chat UIs. The strip hugs its content
width (it is not as wide as the input box) and stays compact so the text
box does not jump when attachments appear.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app.models.attachment import Attachment

_THUMB = 52
_REMOVE = 16

_REMOVE_QSS = """
QPushButton#pendingRemove {
    background: rgba(0, 0, 0, 0.65);
    color: #FFFFFF;
    border: 1px solid rgba(255, 255, 255, 0.7);
    border-radius: 8px;
    font-size: 11px;
    font-weight: bold;
    padding: 0;
}
QPushButton#pendingRemove:hover {
    background: #C62828;
    border-color: #C62828;
}
"""


class _PendingItem(QWidget):
    """One pending attachment: thumbnail/chip + remove button overlay."""

    remove_requested = pyqtSignal(object)  # emits the Attachment

    def __init__(self, attachment: Attachment, parent=None):
        super().__init__(parent)
        self._attachment = attachment
        self.setObjectName("pendingItem")
        # Hug exactly the thumbnail; leave a sliver of top/right room so the
        # remove button can sit on the corner without being clipped.
        self.setFixedSize(_THUMB + 6, _THUMB + 6)
        self._build()

    def _build(self):
        thumb = QLabel(self)
        thumb.setObjectName("pendingThumb")
        thumb.setFixedSize(_THUMB, _THUMB)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.move(0, 6)

        if self._attachment.is_image():
            pixmap = QPixmap(self._attachment.file_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    _THUMB, _THUMB,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb.setPixmap(scaled)
            else:
                thumb.setText("🖼️")
        else:
            thumb.setText("📄")
        thumb.setToolTip(
            f"{self._attachment.file_name} · {self._attachment.format_size()}"
        )

        remove = QPushButton("✕", self)
        remove.setObjectName("pendingRemove")
        remove.setStyleSheet(_REMOVE_QSS)
        remove.setFixedSize(_REMOVE, _REMOVE)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(
            lambda: self.remove_requested.emit(self._attachment)
        )
        # Top-right corner of the item.
        remove.move(self.width() - _REMOVE, 0)
        remove.raise_()


class PendingAttachmentBar(QWidget):
    """Compact, content-width strip of pending attachments above the input."""

    changed = pyqtSignal()  # emitted whenever the pending set changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._attachments: list[Attachment] = []
        self.setObjectName("pendingBar")
        # Hug content: only as wide/tall as the items need, left-aligned.
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self.setVisible(False)

    def add(self, attachments: list[Attachment]):
        for att in attachments:
            self._attachments.append(att)
            item = _PendingItem(att)
            item.remove_requested.connect(self._on_remove)
            self._row.addWidget(item)
        self._sync_visibility()
        self.changed.emit()

    def take_all(self) -> list[Attachment]:
        """Return the pending attachments and clear the bar."""
        items = self._attachments.copy()
        self.clear()
        return items

    def clear(self):
        self._attachments.clear()
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._sync_visibility()
        self.changed.emit()

    def has_items(self) -> bool:
        return bool(self._attachments)

    def _on_remove(self, attachment: Attachment):
        for i in range(self._row.count()):
            widget = self._row.itemAt(i).widget()
            if isinstance(widget, _PendingItem) and widget._attachment is attachment:
                widget.deleteLater()
                self._row.takeAt(i)
                break
        try:
            self._attachments.remove(attachment)
        except ValueError:
            pass
        self._sync_visibility()
        self.changed.emit()

    def _sync_visibility(self):
        self.setVisible(bool(self._attachments))
