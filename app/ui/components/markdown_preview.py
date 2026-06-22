"""
Markdown 预览组件（QTextBrowser）。
GitHub 风格 CSS + wiki-link 点击拦截 + 主题适配。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QTextBlockFormat, QTextCursor
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


def _build_markdown():
    """Markdown instance with indented code blocks disabled.

    A leading Tab / 4 spaces is normally parsed as an indented code block, so
    users indenting a paragraph saw it rendered as code. Deregister the 'code'
    block processor: indentation becomes a normal paragraph again. Fenced code
    (``` ) still works via the fenced_code extension, and list nesting (handled
    by the list processors, not 'code') is unaffected.
    """
    if not _HAS_MARKDOWN:
        return None
    md = _markdown_lib.Markdown(extensions=_MARKDOWN_EXTENSIONS)
    if "code" in md.parser.blockprocessors:
        md.parser.blockprocessors.deregister("code")
    return md


_MD = _build_markdown()

_SIMPLE_CSS = """
body {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 14pt;
  line-height: 1.4;
  color: #24292e;
  padding: 8px 12px;
}
p { margin-top: 2px; margin-bottom: 2px; }
ul, ol { margin-top: 2px; margin-bottom: 2px; }
li { margin-top: 0px; margin-bottom: 0px; }
h1 { font-size: 22pt; font-weight: bold; margin-top: 8px; margin-bottom: 4px; }
h2 { font-size: 19pt; font-weight: bold; margin-top: 8px; margin-bottom: 4px; }
h3 { font-size: 16pt; font-weight: bold; margin-top: 6px; margin-bottom: 3px; }
h4 { font-size: 14pt; font-weight: bold; margin-top: 6px; margin-bottom: 3px; }
code { font-family: Consolas, monospace; background-color: #f6f8fa; }
pre { background-color: #f6f8fa; padding: 8px; }
blockquote { color: #6a737d; border-left: 3px solid #dfe2e5; padding-left: 10px; margin-top: 2px; margin-bottom: 2px; }
a { color: #0366d6; }
a.wikilink { background-color: #EEEDFE; color: #534AB7; }
"""

_SIMPLE_CSS_DARK = """
body {
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 14pt;
  line-height: 1.4;
  color: #d4d4d4;
  padding: 8px 12px;
}
p { margin-top: 2px; margin-bottom: 2px; }
ul, ol { margin-top: 2px; margin-bottom: 2px; }
li { margin-top: 0px; margin-bottom: 0px; }
h1 { font-size: 22pt; font-weight: bold; color: #d4d4d4; margin-top: 8px; margin-bottom: 4px; }
h2 { font-size: 19pt; font-weight: bold; color: #d4d4d4; margin-top: 8px; margin-bottom: 4px; }
h3 { font-size: 16pt; font-weight: bold; color: #d4d4d4; margin-top: 6px; margin-bottom: 3px; }
h4 { font-size: 14pt; font-weight: bold; color: #d4d4d4; margin-top: 6px; margin-bottom: 3px; }
code { font-family: Consolas, monospace; background-color: #2d2d2d; }
pre { background-color: #2d2d2d; padding: 8px; }
blockquote { color: #808080; border-left: 3px solid #4a4a4a; padding-left: 10px; margin-top: 2px; margin-bottom: 2px; }
a { color: #4fc1ff; }
a.wikilink { background-color: #2D2250; color: #A78BFA; }
"""


_LIST_OR_QUOTE = re.compile(r"^[ \t]*([-*+]\s|\d+\.\s|>)")


def _preserve_indent(text: str) -> str:
    """Convert leading indentation to ``&nbsp;`` so it survives HTML rendering.

    With indented code blocks disabled, an indented paragraph renders as a normal
    paragraph — but HTML collapses its leading whitespace, so the indent vanished
    in the preview. Replace each leading space with ``&nbsp;`` (tab → 4) to keep
    it. List / blockquote lines are left untouched: their leading spaces drive
    nesting, and fenced code blocks keep their literal indentation.
    """
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or _LIST_OR_QUOTE.match(line):
            out.append(line)
            continue
        m = re.match(r"^([ \t]+)", line)
        if m:
            ws = m.group(1).replace("\t", "    ")
            line = "&nbsp;" * len(ws) + line[len(m.group(1)):]
        out.append(line)
    return "\n".join(out)


def _render_markdown_body(text: str, base_url: str = "") -> str:
    """将 Markdown 文本渲染为 HTML body 片段。"""
    if _HAS_MARKDOWN:
        _MD.reset()
        body = _MD.convert(_preserve_indent(text))
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
        self._tighten_spacing()

    def _tighten_spacing(self) -> None:
        """Force tight line/paragraph spacing on every block.

        Qt's rich-text engine ignores CSS ``line-height`` and only loosely
        honors block margins, so set it directly via QTextBlockFormat: a single
        line height (100%, ProportionalHeight) plus small top/bottom margins.
        """
        doc = self._tb.document()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            cursor.setPosition(block.position())
            fmt = block.blockFormat()
            fmt.setLineHeight(100, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setTopMargin(2)
            fmt.setBottomMargin(2)
            cursor.setBlockFormat(fmt)
            block = block.next()
        cursor.endEditBlock()
