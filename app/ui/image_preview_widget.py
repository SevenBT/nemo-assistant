"""Inline image preview for chat attachments.

Renders an image attachment as a bounded thumbnail directly in the
message bubble (like web chat UIs), instead of a small file card.
Click opens the image with the system default viewer.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout
from qfluentwidgets import ToolTipPosition

from app.models.attachment import Attachment
from app.ui.title_bar import _BorderlessToolTipFilter

logger = logging.getLogger(__name__)

# Bounding box for the inline preview (logical px). Image is scaled to fit
# inside while keeping aspect ratio; never upscaled past its native size.
_MAX_W = 360
_MAX_H = 320


class ImagePreviewWidget(QFrame):
    """Show an image attachment as a bounded, clickable inline thumbnail."""

    clicked = pyqtSignal(str)  # emits file_path

    def __init__(self, attachment: Attachment, parent=None):
        super().__init__(parent)
        self._attachment = attachment
        self.setObjectName("imagePreview")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel()
        label.setObjectName("imagePreviewLabel")
        pixmap = QPixmap(self._attachment.file_path)

        if pixmap.isNull():
            # Fall back to a filename label if the image can't be loaded.
            label.setText(f"🖼️ {self._attachment.file_name}（无法预览）")
            label.setObjectName("fileName")
        else:
            scaled = pixmap.scaled(
                _MAX_W,
                _MAX_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
            label.setFixedSize(scaled.size())
            # Native Qt tooltips render all-black inside this FluentWindow theme.
            # Use qfluentwidgets' themed tooltip (borderless variant also strips
            # the Win11 DWM border) so the filename + size shows readably.
            label.setToolTip(
                f"{self._attachment.file_name} · {self._attachment.format_size()}"
            )
            label.installEventFilter(
                _BorderlessToolTipFilter(
                    label, showDelay=400, position=ToolTipPosition.TOP
                )
            )

        layout.addWidget(label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_file()
            self.clicked.emit(self._attachment.file_path)
        super().mousePressEvent(event)

    def _open_file(self):
        file_path = self._attachment.file_path
        if not Path(file_path).exists():
            logger.warning("图片不存在，无法打开: %s", file_path)
            return
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path], check=True)
            else:
                subprocess.run(["xdg-open", file_path], check=True)
        except Exception as e:
            logger.error("打开图片失败 %s: %s", file_path, e)
