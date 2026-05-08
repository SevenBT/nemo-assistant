"""File parser for extracting content from various file types.

Supports text files, markdown, and images (with OCR).
"""
import logging
from pathlib import Path
from typing import Optional

from app.models.attachment import Attachment

logger = logging.getLogger(__name__)


class FileParseError(Exception):
    """Raised when file parsing fails."""
    pass


class FileParser:
    """Parse files and extract text content for AI context.

    Supported formats:
    - Text: .txt, .md
    - Images: .png, .jpg, .jpeg (OCR via RapidOCR)

    File size limit: 10MB per file.
    """

    SUPPORTED_TYPES = {
        '.txt': 'text',
        '.md': 'text',
        '.png': 'image',
        '.jpg': 'image',
        '.jpeg': 'image',
    }

    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self):
        self._ocr_engine: Optional[RapidOCR] = None

    @property
    def ocr_engine(self):
        """Lazy-load OCR engine on first use."""
        if self._ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr_engine = RapidOCR()
        return self._ocr_engine

    def parse_file(self, file_path: str) -> Attachment:
        """Parse a file and return an Attachment object.

        Args:
            file_path: Absolute path to the file

        Returns:
            Attachment object with parsed content

        Raises:
            FileParseError: If file doesn't exist, unsupported type, or too large
        """
        path = Path(file_path)

        # Check file exists
        if not path.exists():
            raise FileParseError(f"文件不存在: {file_path}")

        if not path.is_file():
            raise FileParseError(f"不是文件: {file_path}")

        # Check file size
        file_size = path.stat().st_size
        if file_size > self.MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            raise FileParseError(
                f"文件过大: {size_mb:.1f}MB (最大 10MB)"
            )

        # Check file type
        suffix = path.suffix.lower()
        file_type = self.SUPPORTED_TYPES.get(suffix)
        if file_type is None:
            raise FileParseError(
                f"不支持的文件类型: {suffix}\n"
                f"支持的类型: {', '.join(self.SUPPORTED_TYPES.keys())}"
            )

        # Parse content
        try:
            if file_type == 'text':
                parsed_content = self._parse_text(file_path)
            elif file_type == 'image':
                parsed_content = self._parse_image(file_path)
            else:
                raise FileParseError(f"未实现的文件类型: {file_type}")
        except Exception as e:
            logger.error(f"解析文件失败 {file_path}: {e}")
            raise FileParseError(f"解析失败: {str(e)}")

        return Attachment(
            file_path=str(path.absolute()),
            file_name=path.name,
            file_type=file_type,
            file_size=file_size,
            parsed_content=parsed_content,
        )

    @staticmethod
    def _parse_text(file_path: str) -> str:
        """Read text file content.

        Args:
            file_path: Path to text file

        Returns:
            File content as string

        Raises:
            FileParseError: If encoding detection fails
        """
        path = Path(file_path)
        # Try common encodings
        for encoding in ['utf-8', 'gbk', 'gb2312', 'utf-16']:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"成功读取文本文件 {path.name} (编码: {encoding})")
                return content
            except (UnicodeDecodeError, UnicodeError):
                continue

        raise FileParseError(
            f"无法识别文件编码，尝试了: utf-8, gbk, gb2312, utf-16"
        )

    def _parse_image(self, file_path: str) -> str:
        """Extract text from image using OCR.

        Args:
            file_path: Path to image file

        Returns:
            Extracted text content

        Raises:
            FileParseError: If OCR fails
        """
        try:
            result, elapse = self.ocr_engine(file_path)
            if result is None or len(result) == 0:
                logger.warning(f"图片 OCR 未识别到文字: {file_path}")
                return "[图片未识别到文字]"

            # result format: list of [bbox, text, confidence]
            lines = [line[1] for line in result]
            content = '\n'.join(lines)
            logger.info(
                f"成功 OCR 图片 {Path(file_path).name}, "
                f"识别 {len(lines)} 行文字, 耗时 {elapse:.2f}s"
            )
            return content

        except Exception as e:
            logger.error(f"OCR 失败 {file_path}: {e}")
            raise FileParseError(f"图片识别失败: {str(e)}")

