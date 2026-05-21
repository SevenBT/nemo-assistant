"""
Markdown 预览组件（QTextBrowser）。
GitHub 风格 CSS + wiki-link 点击拦截 + 主题适配。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy, QTextBrowser

try:
    import markdown as _markdown_lib
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False

_MARKDOWN_EXTENSIONS = [
    "extra",
    "fenced_code",
    "nl2br",
    "sane_lists",
    "toc",
]

_SIMPLE_CSS = """
body {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 14pt;
  line-height: 1.7;
  color: #24292e;
  padding: 8px 12px;
}
h1 { font-size: 22pt; font-weight: bold; }
h2 { font-size: 19pt; font-weight: bold; }
h3 { font-size: 16pt; font-weight: bold; }
h4 { font-size: 14pt; font-weight: bold; }
code { font-family: Consolas, monospace; background-color: #f6f8fa; }
pre { background-color: #f6f8fa; padding: 8px; }
blockquote { color: #6a737d; border-left: 3px solid #dfe2e5; padding-left: 10px; }
a { color: #0366d6; }
a.wikilink { background-color: #EEEDFE; color: #534AB7; }
"""

_SIMPLE_CSS_DARK = """
body {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 14pt;
  line-height: 1.7;
  color: #d4d4d4;
  padding: 8px 12px;
}
h1 { font-size: 22pt; font-weight: bold; color: #d4d4d4; }
h2 { font-size: 19pt; font-weight: bold; color: #d4d4d4; }
h3 { font-size: 16pt; font-weight: bold; color: #d4d4d4; }
h4 { font-size: 14pt; font-weight: bold; color: #d4d4d4; }
code { font-family: Consolas, monospace; background-color: #2d2d2d; }
pre { background-color: #2d2d2d; padding: 8px; }
blockquote { color: #808080; border-left: 3px solid #4a4a4a; padding-left: 10px; }
a { color: #4fc1ff; }
a.wikilink { background-color: #2D2250; color: #A78BFA; }
"""


def _render_markdown_body(text: str, base_url: str = "") -> str:
    """将 Markdown 文本渲染为 HTML body 片段。"""
    if _HAS_MARKDOWN:
        body = _markdown_lib.markdown(text, extensions=_MARKDOWN_EXTENSIONS)
    else:
        import html as _html
        body = f"<pre>{_html.escape(text)}</pre>"

    # 将相对图片路径转为绝对 file:// URL
    if base_url:
        def _abs_img(m):
            src = m.group(1)
            if src.startswith(("http://", "https://", "file://", "data:")):
                return m.group(0)
            abs_src = base_url.rstrip("/") + "/" + src.replace("\\", "/")
            return f'<img src="{abs_src}"'
        body = re.sub(r'<img src="([^"]+)"', _abs_img, body)

    # 将 [[wiki-link]] 转为可点击的 badge（跳过代码块）
    parts = re.split(r'(<code.*?>.*?</code>|<pre.*?>.*?</pre>)', body, flags=re.DOTALL)
    new_parts = []
    for p in parts:
        if p.startswith(('<code', '<pre')):
            new_parts.append(p)
        else:
            p = re.sub(
                r'\[\[([^\]]+)\]\]',
                lambda m: (
                    f'<a class="wikilink" href="assistant://wiki/{m.group(1).strip()}">'
                    f'[[{m.group(1).strip()}]]</a>'
                ),
                p,
            )
            new_parts.append(p)
    return "".join(new_parts)


def _md_to_html(text: str, base_url: str = "", dark: bool = False) -> str:
    """将 Markdown 转换为 QTextBrowser 兼容的 HTML。"""
    body = _render_markdown_body(text, base_url)
    css = _SIMPLE_CSS_DARK if dark else _SIMPLE_CSS
    base_tag = f'<base href="{base_url}">' if base_url else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
{base_tag}
<style>{css}</style>
</head><body>{body}</body></html>"""


class MarkdownPreview(QWidget):
    """Markdown 预览组件（QTextBrowser 实现）。"""

    link_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tb = QTextBrowser()
        self._tb.setObjectName("notePreviewBrowser")
        self._tb.setOpenExternalLinks(False)
        self._tb.setOpenLinks(False)
        self._tb.anchorClicked.connect(self._on_anchor_click)
        self._tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _font = QFont()
        _font.setPointSize(14)
        self._tb.setFont(_font)
        layout.addWidget(self._tb)

    def _on_anchor_click(self, url: QUrl) -> None:
        """处理链接点击。"""
        scheme = url.scheme()
        if scheme == "assistant" and url.host() == "wiki":
            self.link_clicked.emit(url.path().lstrip("/"))
        elif scheme in ("http", "https"):
            os.startfile(url.toString())

    def set_content(self, markdown_text: str, base_path: Path | None = None, dark: bool = False) -> None:
        """更新预览内容。"""
        base_url = ""
        if base_path and base_path.exists():
            base_dir = str(base_path) if base_path.is_dir() else str(base_path.parent)
            if not base_dir.endswith("/"):
                base_dir += "/"
            base_url = QUrl.fromLocalFile(base_dir).toString()

        html = _md_to_html(markdown_text, base_url, dark=dark)
        self._tb.setHtml(html)
