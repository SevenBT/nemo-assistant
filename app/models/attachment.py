"""Attachment data model for file uploads in chat messages."""
import base64
import io
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Vision models downsample large images internally and bill by resolution,
# so sending the raw full-res screenshot just wastes tokens (and can exceed
# per-request limits). Cap the longest edge before encoding.
_MAX_SEND_EDGE = 1568
# Re-encode downscaled photos as JPEG (much smaller than PNG) unless the
# image has alpha, where PNG is kept to preserve transparency.
_JPEG_QUALITY = 85


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

    def is_image(self) -> bool:
        """Whether this attachment carries image pixels (for vision models)."""
        return self.file_type == "image"

    def to_data_url(self) -> Optional[str]:
        """Read the image file and return a base64 ``data:`` URL.

        Large images are downscaled to ``_MAX_SEND_EDGE`` on the longest
        edge before encoding — vision models gain nothing from extra
        resolution and bill for it. Falls back to the raw bytes if Pillow
        is unavailable or processing fails.

        Returns None if the attachment is not an image or the file is
        missing/unreadable. Built lazily at send time so session JSON
        stays small (we persist file_path, not the base64 blob).
        """
        if not self.is_image():
            return None
        path = Path(self.file_path)
        if not path.is_file():
            return None

        downscaled = self._downscaled_image_bytes(path)
        if downscaled is not None:
            data, mime = downscaled
        else:
            mime, _ = mimetypes.guess_type(path.name)
            if not mime or not mime.startswith("image/"):
                mime = "image/png"
            try:
                data = path.read_bytes()
            except OSError:
                return None

        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _downscaled_image_bytes(path: Path) -> Optional[tuple[bytes, str]]:
        """Return (bytes, mime) downscaled to the send cap, or None on failure."""
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(path) as img:
                img.load()
                longest = max(img.width, img.height)
                if longest <= _MAX_SEND_EDGE:
                    return None  # already small enough; use raw bytes

                scale = _MAX_SEND_EDGE / longest
                new_size = (
                    max(1, round(img.width * scale)),
                    max(1, round(img.height * scale)),
                )
                resized = img.resize(new_size, Image.LANCZOS)

                buf = io.BytesIO()
                has_alpha = resized.mode in ("RGBA", "LA", "P")
                if has_alpha:
                    resized.save(buf, format="PNG", optimize=True)
                    mime = "image/png"
                else:
                    resized.convert("RGB").save(
                        buf, format="JPEG", quality=_JPEG_QUALITY
                    )
                    mime = "image/jpeg"
                return buf.getvalue(), mime
        except Exception as e:
            logger.warning("图片缩放失败，回退原图 %s: %s", path, e)
            return None
