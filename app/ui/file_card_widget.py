"""File card widget for displaying file attachments in chat messages."""
import logging
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QFrame,
)

from app.models.attachment import Attachment

logger = logging.getLogger(__name__)


class FileCardWidget(QFrame):
    """Display a file attachment as a compact card.

    Shows:
    - File icon or thumbnail (for images)
    - File name
    - File size

    Click to open file with system default application.
    """

    clicked = pyqtSignal(str)  # Emits file_path when clicked

    def __init__(self, attachment: Attachment, parent=None):
        super().__init__(parent)
        self._attachment = attachment
        self.setObjectName("fileCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()

    def _build(self):
        """Build the card layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Icon or thumbnail
        icon_label = self._create_icon_label()
        layout.addWidget(icon_label)

        # File info (name + size)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(self._attachment.file_name)
        name_label.setObjectName("fileName")
        name_label.setWordWrap(False)
        info_layout.addWidget(name_label)

        size_label = QLabel(self._attachment.format_size())
        size_label.setObjectName("fileSize")
        info_layout.addWidget(size_label)

        layout.addLayout(info_layout)
        layout.addStretch()

    def _create_icon_label(self) -> QLabel:
        """Create icon or thumbnail for the file.

        Returns:
            QLabel with icon or thumbnail image
        """
        label = QLabel()
        label.setFixedSize(48, 48)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self._attachment.file_type == 'image':
            # Show thumbnail for images
            pixmap = QPixmap(self._attachment.file_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                label.setPixmap(scaled)
                return label

        # Fallback: show text icon
        icon_text = self._get_icon_text()
        label.setText(icon_text)
        label.setObjectName("fileIcon")
        return label

    def _get_icon_text(self) -> str:
        """Get emoji icon for file type."""
        type_icons = {
            'text': '📄',
            'image': '🖼️',
            'pdf': '📕',
            'word': '📘',
            'excel': '📗',
        }
        return type_icons.get(self._attachment.file_type, '📎')

    def mousePressEvent(self, event):
        """Handle click to open file."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_file()
            self.clicked.emit(self._attachment.file_path)
        super().mousePressEvent(event)

    def _open_file(self):
        """Open file with system default application."""
        file_path = self._attachment.file_path
        if not Path(file_path).exists():
            logger.warning(f"文件不存在，无法打开: {file_path}")
            return

        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':  # macOS
                subprocess.run(['open', file_path], check=True)
            else:  # Linux
                subprocess.run(['xdg-open', file_path], check=True)
            logger.info(f"打开文件: {file_path}")
        except Exception as e:
            logger.error(f"打开文件失败 {file_path}: {e}")


