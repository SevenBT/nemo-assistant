"""Screenshot workflow controller for the main window."""

import logging
from io import BytesIO

from PyQt6.QtCore import QObject, QPoint, QTimer, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QApplication, QFileDialog, QWidget

from app.core.config import SCREENSHOTS_DIR
from app.core.ocr_engine import OcrEngineService
from app.i18n import t
from app.models.attachment import Attachment
from app.ui.pin_window import PinWindow
from app.ui.screenshot_overlay import ScreenshotOverlay
from app.ui.vision_actions import get_vision_action

logger = logging.getLogger(__name__)


class ScreenshotController(QObject):
    """Owns screenshot overlay state and post-capture actions.

    Two independent post-capture paths:
    - OCR ("识字") and pin/copy/save are handled in-place.
    - Vision ("识图", action ``vision:<key>``) saves the shot as a PNG,
      wraps it as an image Attachment, and hands it to the chat via
      ``vision_callback(attachments, vision_action)``. The chat opens a
      fresh session per shot so questions never pollute an existing
      conversation. It does NOT run OCR — vision sends pixels, OCR
      extracts text.
    """

    def __init__(
        self,
        window: QWidget,
        *,
        vision_callback=None,
        ocr_engine_service: OcrEngineService | None = None,
    ):
        super().__init__(window)
        self._window = window
        self._vision_callback = vision_callback
        self._ocr_engine_service = ocr_engine_service
        self._overlay: ScreenshotOverlay | None = None
        self._pin_windows: list[PinWindow] = []
        self._shot_counter = 0

    def set_chat_callbacks(self, *, vision_callback):
        """Wire the chat hook after the session controller exists."""
        self._vision_callback = vision_callback

    def start(self):
        if self._overlay is not None:
            return
        self._window.hide()
        QTimer.singleShot(200, self._show_overlay)

    def _show_overlay(self):
        self._overlay = ScreenshotOverlay(
            ocr_engine_service=self._ocr_engine_service,
        )
        self._overlay.captured.connect(self._on_done)
        self._overlay.show()
        self._overlay.activateWindow()

    def _on_done(self, pixmap: QPixmap, action: str, ocr_text: str, pos: QPoint):
        self._overlay = None
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

        if action == "cancel":
            return
        if action == "ocr":
            if ocr_text:
                QApplication.clipboard().setText(ocr_text)
            return
        if action.startswith("vision:"):
            if not pixmap.isNull():
                self._send_to_ai(pixmap, action)
            return
        if pixmap.isNull():
            return

        if action == "pin":
            self._pin_screenshot(pixmap, pos)
        elif action == "copy":
            QApplication.clipboard().setPixmap(pixmap)
        elif action == "save":
            self._save_screenshot(pixmap)

    # ── Vision (识图) ──────────────────────────────────────────────────

    def _send_to_ai(self, pixmap: QPixmap, action: str):
        """Persist the shot and hand it to chat, which opens a fresh session."""
        if self._vision_callback is None:
            logger.warning("识图：未配置 vision_callback，无法发送截图给 AI")
            return

        key = action.split(":", 1)[1] if ":" in action else "ask"
        vision_action = get_vision_action(key)
        if vision_action is None:
            logger.warning("识图：未知动作 %s", action)
            return

        attachment = self._save_as_attachment(pixmap)
        if attachment is None:
            return

        self._vision_callback([attachment], vision_action)

    @staticmethod
    def _strip_metadata(image: QImage) -> bytes:
        """Remove all metadata from QImage and return clean PNG bytes.

        Returns raw PNG bytes without any metadata (DPI, ICC profile, etc.).
        Falls back to original QImage.save() if PIL is unavailable.
        """
        try:
            from PIL import Image
            from io import BytesIO

            # Convert QImage to PIL Image (pure pixel data)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            buffer.close()

            pil_image = Image.open(BytesIO(buffer.data()))

            # Save without metadata
            output = BytesIO()
            pil_image.save(
                output,
                format="PNG",
                optimize=False,  # Don't add optimization metadata
                dpi=None,  # Explicitly remove DPI
            )
            return output.getvalue()

        except ImportError:
            logger.warning("元数据清除：PIL 未安装，使用原始保存（可能含元数据）")
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            buffer.close()
            return buffer.data().data()
        except Exception as e:
            logger.warning("元数据清除：处理失败 %s，使用原始保存", e)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            buffer.close()
            return buffer.data().data()

    def _save_as_attachment(self, pixmap: QPixmap) -> Attachment | None:
        """Save pixmap as PNG under SCREENSHOTS_DIR and wrap as image Attachment.

        Strips all metadata (DPI, ICC profile, etc.) to ensure AI receives pure pixel data.
        """
        self._shot_counter += 1
        # Monotonic counter (not time) keeps naming stable without Date.now.
        path = SCREENSHOTS_DIR / f"shot_{id(pixmap):x}_{self._shot_counter}.png"

        # Convert to QImage and strip metadata, get clean PNG bytes
        image = pixmap.toImage()
        clean_png_bytes = self._strip_metadata(image)

        # Write clean PNG bytes to file
        try:
            with open(path, "wb") as f:
                f.write(clean_png_bytes)
        except OSError as e:
            logger.error("识图：截图保存失败 %s: %s", path, e)
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

    # ── Pin / Save ─────────────────────────────────────────────────────

    def _pin_screenshot(self, pixmap: QPixmap, pos: QPoint):
        win = PinWindow(pixmap, pos=pos)
        win.show()
        self._pin_windows.append(win)
        win.closed.connect(
            lambda w=win: self._pin_windows.remove(w)
            if w in self._pin_windows
            else None
        )

    def _save_screenshot(self, pixmap: QPixmap):
        path, _ = QFileDialog.getSaveFileName(
            self._window,
            t("screenshot.saveDialogTitle"),
            "screenshot.png",
            "PNG (*.png)",
        )
        if path:
            pixmap.save(path, "PNG")
