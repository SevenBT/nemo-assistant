"""测试截图识图分支：截图 → 图片附件 + 预填提示词。

不依赖 Qt 事件循环：用最小的 QApplication + 真实 QPixmap 验证
ScreenshotController._on_done 在 vision:* 动作下的行为。
"""
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QPoint

_app = QApplication.instance() or QApplication(sys.argv)

from app.ui.screenshot_controller import ScreenshotController
from app.core.config import SCREENSHOTS_DIR


def _make_pixmap() -> QPixmap:
    pm = QPixmap(10, 10)
    pm.fill(QColor("red"))
    return pm


def _make_controller():
    calls = []  # list[(attachments, vision_action)]
    window = QWidget()
    ctrl = ScreenshotController(
        window,
        vision_callback=lambda atts, va: calls.append((atts, va)),
    )
    return ctrl, calls


def test_vision_action_attaches_image_and_passes_action():
    ctrl, calls = _make_controller()
    pm = _make_pixmap()

    ctrl._on_done(pm, "vision:explain", "", QPoint(0, 0))

    assert len(calls) == 1, "应触发一次识图回调"
    atts, va = calls[0]
    assert len(atts) == 1
    att = atts[0]
    assert att.file_type == "image", "应是图片类型附件"
    assert Path(att.file_path).is_file(), "PNG 应已落盘"
    assert str(SCREENSHOTS_DIR) in att.file_path, "应存进 screenshots 目录"
    assert att.parsed_content == "", "识图不应跑 OCR 填 parsed_content"

    assert va.key == "explain", "应传递对应的识图动作"
    assert va.prompt == "请解释这张图片的内容。", f"提示词错误: {va.prompt}"
    assert va.auto_send is True, "解释动作应自动发送"
    assert va.session_title, "应带会话标题"

    # 清理落盘文件
    Path(att.file_path).unlink(missing_ok=True)


def test_vision_ask_is_not_auto_send():
    ctrl, calls = _make_controller()
    pm = _make_pixmap()

    ctrl._on_done(pm, "vision:ask", "", QPoint(0, 0))

    assert len(calls) == 1
    atts, va = calls[0]
    assert va.key == "ask"
    assert va.prompt == "", "通用问AI 提示词应为空"
    assert va.auto_send is False, "通用问AI 不应自动发送"
    Path(atts[0].file_path).unlink(missing_ok=True)


def test_ocr_action_does_not_attach():
    ctrl, calls = _make_controller()
    pm = _make_pixmap()

    # OCR 路径只复制剪贴板，不走识图回调
    ctrl._on_done(pm, "ocr", "识别的文字", QPoint(0, 0))

    assert calls == [], "OCR 不应触发识图回调"


def test_cancel_does_nothing():
    ctrl, calls = _make_controller()
    ctrl._on_done(QPixmap(), "cancel", "", QPoint(0, 0))
    assert calls == []


def test_vision_without_callbacks_is_safe():
    window = QWidget()
    ctrl = ScreenshotController(window)  # no callbacks
    pm = _make_pixmap()
    # 不应抛异常
    ctrl._on_done(pm, "vision:explain", "", QPoint(0, 0))


if __name__ == "__main__":
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print("\nALL PASS")
