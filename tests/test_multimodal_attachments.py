"""测试多模态图片通道：图片附件 → OpenAI image_url 结构。

验证 merge_attachments_to_content 在 vision 开/关下的分流行为。
"""
import base64
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.conversation_prompt_builder import merge_attachments_to_content
from app.models.attachment import Attachment
from app.models.message import Message, MessageRole


def _make_png(tmpdir: Path) -> str:
    """Write a tiny valid PNG and return its path."""
    # 1x1 transparent PNG
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    p = tmpdir / "shot.png"
    p.write_bytes(data)
    return str(p)


def _image_attachment(path: str, ocr_text: str = "") -> Attachment:
    return Attachment(
        file_path=path,
        file_name=Path(path).name,
        file_type="image",
        file_size=Path(path).stat().st_size,
        parsed_content=ocr_text,
    )


def _text_attachment(name: str, content: str) -> Attachment:
    return Attachment(
        file_path=f"/fake/{name}",
        file_name=name,
        file_type="text",
        file_size=len(content),
        parsed_content=content,
    )


def test_image_becomes_image_url_when_vision_on():
    with tempfile.TemporaryDirectory() as d:
        png = _make_png(Path(d))
        msg = Message(
            role=MessageRole.USER,
            content="解释这张图",
            attachments=[_image_attachment(png, ocr_text="some ocr")],
        )
        out = merge_attachments_to_content([msg], vision_enabled=True)
        content = out[0]["content"]
        assert isinstance(content, list), f"vision 开时应为 list，实际 {type(content)}"
        types = [part["type"] for part in content]
        assert "image_url" in types, f"应含 image_url，实际 {types}"
        # 文字部分应是用户文字，且不重复塞 OCR
        text_parts = [p["text"] for p in content if p["type"] == "text"]
        assert any("解释这张图" in t for t in text_parts)
        assert all("some ocr" not in t for t in text_parts), "vision 开时不应重复 OCR 文字"
        # image_url 应是 data URL
        img = [p for p in content if p["type"] == "image_url"][0]
        assert img["image_url"]["url"].startswith("data:image/")


def test_image_falls_back_to_ocr_text_when_vision_off():
    with tempfile.TemporaryDirectory() as d:
        png = _make_png(Path(d))
        msg = Message(
            role=MessageRole.USER,
            content="解释这张图",
            attachments=[_image_attachment(png, ocr_text="识别出的文字")],
        )
        out = merge_attachments_to_content([msg], vision_enabled=False)
        content = out[0]["content"]
        assert isinstance(content, str), "vision 关时应为纯文本"
        assert "识别出的文字" in content
        assert "解释这张图" in content


def test_text_attachment_unchanged():
    msg = Message(
        role=MessageRole.USER,
        content="总结一下",
        attachments=[_text_attachment("a.txt", "文件正文")],
    )
    out = merge_attachments_to_content([msg], vision_enabled=True)
    content = out[0]["content"]
    assert isinstance(content, str), "纯文本附件不应触发 list content"
    assert "文件正文" in content and "总结一下" in content


def test_vision_off_lazily_ocrs_image_without_parsed_content():
    """vision 关 + 图片无预置 OCR 文字 → 降级时应懒加载 OCR（不报错、不崩）。"""
    with tempfile.TemporaryDirectory() as d:
        png = _make_png(Path(d))
        # 注意：不预置 parsed_content，模拟 intake 时未 OCR
        msg = Message(
            role=MessageRole.USER,
            content="看看",
            attachments=[_image_attachment(png, ocr_text="")],
        )
        out = merge_attachments_to_content([msg], vision_enabled=False)
        content = out[0]["content"]
        # 1x1 测试图 OCR 不出文字，但流程不应崩，用户文字应保留
        assert isinstance(content, str)
        assert "看看" in content


def test_mixed_text_and_image_vision_on():
    with tempfile.TemporaryDirectory() as d:
        png = _make_png(Path(d))
        msg = Message(
            role=MessageRole.USER,
            content="看图并结合文档",
            attachments=[
                _text_attachment("doc.txt", "文档内容"),
                _image_attachment(png),
            ],
        )
        out = merge_attachments_to_content([msg], vision_enabled=True)
        content = out[0]["content"]
        assert isinstance(content, list)
        text_parts = [p["text"] for p in content if p["type"] == "text"]
        assert any("文档内容" in t for t in text_parts), "文本附件应进 text 部分"
        assert any("看图并结合文档" in t for t in text_parts)
        assert any(p["type"] == "image_url" for p in content)


def test_missing_image_file_skips_image_url():
    msg = Message(
        role=MessageRole.USER,
        content="解释",
        attachments=[
            Attachment(
                file_path="/does/not/exist.png",
                file_name="exist.png",
                file_type="image",
                file_size=0,
                parsed_content="兜底文字",
            )
        ],
    )
    out = merge_attachments_to_content([msg], vision_enabled=True)
    content = out[0]["content"]
    # 文件不存在 → 无 image_url → 退回字符串
    assert isinstance(content, str), "取不到图片数据时应退回文本"
    assert "解释" in content


if __name__ == "__main__":
    import sys as _sys
    mod = _sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print("\nALL PASS")
