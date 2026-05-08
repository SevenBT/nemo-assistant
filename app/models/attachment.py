"""Attachment data model for file uploads in chat messages."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Attachment:
    """Represents a file attachment in a chat message.

    Attributes:
        file_path: Absolute path to the file
        file_name: Display name of the file
        file_type: Type category (text, image, pdf, word, excel)
        file_size: Size in bytes
        parsed_content: Extracted text content from the file
        thumbnail_path: Optional path to thumbnail image (for images)
    """
    file_path: str
    file_name: str
    file_type: str
    file_size: int
    parsed_content: str = ""
    thumbnail_path: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "parsed_content": self.parsed_content,
            "thumbnail_path": self.thumbnail_path,
        }

    @staticmethod
    def from_dict(data: dict) -> "Attachment":
        """Deserialize from dictionary."""
        return Attachment(
            file_path=data["file_path"],
            file_name=data["file_name"],
            file_type=data["file_type"],
            file_size=data["file_size"],
            parsed_content=data.get("parsed_content", ""),
            thumbnail_path=data.get("thumbnail_path"),
        )

    def format_size(self) -> str:
        """Format file size for display (e.g., '2.3 MB')."""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
