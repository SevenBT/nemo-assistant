"""测试拖放/粘贴附件接入：文件 URL 和图片像素都解析成 Attachment，
不被输入框当作文本插入。
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

import tempfile
from app.ui.attachment_intake import attachments_from_mime
from app.ui.input_widget import InputWidget
from app.core.config import SCREENSHOTS_DIR


def test_image_file_url_becomes_image_attachment():
    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "pic.png"
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(20, 20)
        pm.fill(QColor("green"))
        pm.save(str(png), "PNG")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(png))])

        atts = attachments_from_mime(mime)
        assert len(atts) == 1, f"应解析出 1 个附件，实际 {len(atts)}"
        assert atts[0].file_type == "image"
        assert atts[0].is_image()


def test_text_file_url_becomes_text_attachment():
    with tempfile.TemporaryDirectory() as d:
        txt = Path(d) / "note.txt"
        txt.write_text("hello", encoding="utf-8")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(txt))])

        atts = attachments_from_mime(mime)
        assert len(atts) == 1
        assert atts[0].file_type == "text"
        assert "hello" in atts[0].parsed_content


def test_raw_pasted_image_is_saved_and_attached():
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))

    mime = QMimeData()
    mime.setImageData(img)

    atts = attachments_from_mime(mime)
    assert len(atts) == 1, "粘贴的图片像素应保存为附件"
    att = atts[0]
    assert att.file_type == "image"
    assert Path(att.file_path).is_file()
    assert str(SCREENSHOTS_DIR) in att.file_path
    Path(att.file_path).unlink(missing_ok=True)


def test_plain_text_is_not_attached():
    mime = QMimeData()
    mime.setText("just text")
    atts = attachments_from_mime(mime)
    assert atts == [], "纯文本不应产生附件"


def test_input_textedit_routes_files_not_text():
    """拖放图片到输入框应进入待发预览条，而非插入 URL 文本。"""
    widget = InputWidget()

    with tempfile.TemporaryDirectory() as d:
        png = Path(d) / "p.png"
        from PyQt6.QtGui import QPixmap
        pm = QPixmap(10, 10)
        pm.fill(QColor("red"))
        pm.save(str(png), "PNG")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(png))])

        edit = widget._edit
        handled = edit._try_attach(mime)
        assert handled is True, "应被识别为附件"
        assert widget.has_pending_attachments(), "图片应进入待发预览条"
        taken = widget.take_pending_attachments()
        assert len(taken) == 1 and taken[0].is_image()
        # 文本框不应被插入 URL
        assert edit.toPlainText() == "", "图片不应作为文本插入输入框"


if __name__ == "__main__":
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print("\nALL PASS")
