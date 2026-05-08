"""Test file parser text functionality (without OCR)."""
import tempfile
from pathlib import Path
import sys
import os

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock RapidOCR to avoid DLL issues
class MockRapidOCR:
    def __call__(self, image_path):
        return [["bbox", "Mock OCR text", 0.9]], 0.1

import app.core.file_parser as fp_module
fp_module.RapidOCR = MockRapidOCR

from app.core.file_parser import FileParser, FileParseError


def test_parse_text_file():
    """Test parsing a simple text file."""
    parser = FileParser()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("Hello, World!\n这是测试文本。")
        temp_path = f.name

    try:
        attachment = parser.parse_file(temp_path)
        assert attachment.file_type == 'text'
        assert "Hello, World!" in attachment.parsed_content
        assert "这是测试文本" in attachment.parsed_content
        print(f"✓ Text file parsed: {attachment.file_name}")
        print(f"  Size: {attachment.format_size()}")
        print(f"  Content: {attachment.parsed_content[:50]}...")
    finally:
        Path(temp_path).unlink()


def test_parse_markdown_file():
    """Test parsing a markdown file."""
    parser = FileParser()

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
        f.write("# Title\n\nThis is **markdown** content.")
        temp_path = f.name

    try:
        attachment = parser.parse_file(temp_path)
        assert attachment.file_type == 'text'
        assert "# Title" in attachment.parsed_content
        print(f"✓ Markdown file parsed: {attachment.file_name}")
    finally:
        Path(temp_path).unlink()


def test_unsupported_file():
    """Test that unsupported file types raise error."""
    parser = FileParser()

    with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
        temp_path = f.name

    try:
        try:
            parser.parse_file(temp_path)
            assert False, "Should have raised FileParseError"
        except FileParseError as e:
            assert "不支持的文件类型" in str(e)
            print(f"✓ Unsupported file correctly rejected")
    finally:
        Path(temp_path).unlink()


def test_file_size_limit():
    """Test that oversized files are rejected."""
    parser = FileParser()

    with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
        # Write 11MB of data
        f.write(b'x' * (11 * 1024 * 1024))
        temp_path = f.name

    try:
        try:
            parser.parse_file(temp_path)
            assert False, "Should have raised FileParseError"
        except FileParseError as e:
            assert "文件过大" in str(e)
            print(f"✓ Oversized file correctly rejected (11MB)")
    finally:
        Path(temp_path).unlink()


def test_nonexistent_file():
    """Test that nonexistent files raise error."""
    parser = FileParser()

    try:
        parser.parse_file("/nonexistent/file.txt")
        assert False, "Should have raised FileParseError"
    except FileParseError as e:
        assert "文件不存在" in str(e)
        print(f"✓ Nonexistent file correctly rejected")


if __name__ == '__main__':
    print("Testing FileParser (text files only)...\n")
    test_parse_text_file()
    test_parse_markdown_file()
    test_unsupported_file()
    test_file_size_limit()
    test_nonexistent_file()
    print("\n✓ All tests passed!")
