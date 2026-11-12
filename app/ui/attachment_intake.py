"""Shared helpers to turn dropped/pasted content into chat Attachments.

Both the message list (ChatWidget) and the input box (InputWidget) accept
drops and pastes; this module centralizes the parsing so they behave
identically. Images are saved/parsed and returned as image Attachments so
they flow through the multimodal vision channel.
"""
import logging
from collections.abc import Iterable

from PyQt6.QtCore import QMimeData
from PyQt6.QtGui import QImage

from app.core.config import SCREENSHOTS_DIR
from app.core.file_parser import FileParser, FileParseError
from app.models.attachment import Attachment

logger = logging.getLogger(__name__)


def attachments_from_paths(
    paths: Iterable[str], *, errors: list[str] | None = None
) -> list[Attachment]:
    """Use the same validation and lazy image OCR for picked and dropped files."""
    parser = FileParser()
    attachments = []
    for path in paths:
        try:
            attachments.append(parser.parse_file(path, ocr_images=False))
        except (FileParseError, OSError) as exc:
            logger.warning("解析文件失败: %s", exc)
            if errors is not None:
                errors.append(str(exc))
    return attachments


def attachments_from_mime(mime: QMimeData) -> list[Attachment]:
    """Parse a drop/paste payload into attachments.

    Handles file URLs (documents, images) and raw image data pasted from
    the clipboard (e.g. a screenshot tool that copies pixels, not a file).
    Unsupported items are skipped.
    """
    attachments: list[Attachment] = []

    if mime.hasUrls():
        attachments = attachments_from_paths(
            path for url in mime.urls() if (path := url.toLocalFile())
        )

    # Raw image bytes on the clipboard (no file path) — common for snipping
    # tools. Persist to disk so it can be referenced + sent as pixels.
    if not attachments and mime.hasImage():
        image = QImage(mime.imageData())
        if not image.isNull():
            att = _save_pasted_image(image)
            if att is not None:
                attachments.append(att)

    return attachments


_paste_counter = 0


def _save_pasted_image(image: QImage) -> Attachment | None:
    global _paste_counter
    _paste_counter += 1
    path = SCREENSHOTS_DIR / f"pasted_{id(image):x}_{_paste_counter}.png"
    if not image.save(str(path), "PNG"):
        logger.error("粘贴图片保存失败: %s", path)
        return None
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return Attachment(
        file_path=str(path),
        file_name=path.name,
        file_type="image",
        file_size=size,
    )
