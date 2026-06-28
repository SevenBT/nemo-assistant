"""测试发送前图片缩放：大图按最大边长降采样，小图保持原样。"""
import base64
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image

from app.models.attachment import Attachment
from app.models.attachment import _MAX_SEND_EDGE


def _img_attachment(path: Path) -> Attachment:
    return Attachment(
        file_path=str(path),
        file_name=path.name,
        file_type="image",
        file_size=path.stat().st_size,
    )


def _decode_data_url(url: str):
    head, b64 = url.split(",", 1)
    data = base64.b64decode(b64)
    return head, data


def test_large_image_is_downscaled():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "big.png"
        Image.new("RGB", (4000, 2000), (10, 20, 30)).save(p)
        url = _img_attachment(p).to_data_url()
        assert url is not None
        head, data = _decode_data_url(url)
        # 无 alpha 的大图应转 JPEG
        assert "image/jpeg" in head, f"大图应转 JPEG，实际 {head}"
        # 解码后最长边应被限制
        from io import BytesIO
        out = Image.open(BytesIO(data))
        assert max(out.size) == _MAX_SEND_EDGE, f"最长边应为 {_MAX_SEND_EDGE}，实际 {out.size}"


def test_small_image_kept_as_is():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "small.png"
        Image.new("RGB", (200, 100), (0, 0, 0)).save(p)
        raw = p.read_bytes()
        url = _img_attachment(p).to_data_url()
        head, data = _decode_data_url(url)
        # 小图不缩放，用原始字节（PNG）
        assert "image/png" in head
        assert data == raw, "小图应原样发送"


def test_large_image_with_alpha_stays_png():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "alpha.png"
        Image.new("RGBA", (3000, 1500), (0, 0, 0, 128)).save(p)
        url = _img_attachment(p).to_data_url()
        head, data = _decode_data_url(url)
        assert "image/png" in head, "带透明通道的图应保持 PNG"
        from io import BytesIO
        out = Image.open(BytesIO(data))
        assert max(out.size) == _MAX_SEND_EDGE


def test_non_image_returns_none():
    att = Attachment(file_path="/x.txt", file_name="x.txt", file_type="text", file_size=1)
    assert att.to_data_url() is None


def test_missing_file_returns_none():
    att = Attachment(file_path="/no/such.png", file_name="such.png", file_type="image", file_size=0)
    assert att.to_data_url() is None


if __name__ == "__main__":
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print("\nALL PASS")
