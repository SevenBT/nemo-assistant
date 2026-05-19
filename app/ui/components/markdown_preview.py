"""
Markdown 预览组件（QWebEngineView）。
移植自 noteration/ui/editor_tab.py 的 MarkdownPreview。
GitHub 风格 CSS + wiki-link 点击拦截 + 主题适配。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

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

_PREVIEW_CSS = """
:root {
  --bg:      #ffffff;
  --text:    #24292e;
  --muted:   #6a737d;
  --border:  #e1e4e8;
  --code-bg: #f6f8fa;
  --link:    #0366d6;
  --bq-border: #dfe2e5;
  --bq-bg:   #f9f9f9;
  --wiki-bg: #EEEDFE;
  --wiki-fg: #534AB7;
}
* { box-sizing: border-box; }
html { font-size: 16px; background: var(--bg); }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
               Helvetica, Arial, sans-serif;
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text);
  background: var(--bg);
  max-width: 780px;
  margin: 0 auto;
  padding: 2rem 2.5rem 4rem;
}
h1,h2,h3,h4,h5,h6 { font-weight: 600; line-height: 1.25; margin-top: 1.5em; margin-bottom: .5em; }
h1 { font-size: 2em; border-bottom: 1px solid var(--border); padding-bottom:.3em; }
h2 { font-size: 1.5em; border-bottom: 1px solid var(--border); padding-bottom:.3em; }
h3 { font-size: 1.25em; }
h4 { font-size: 1em; }
h5 { font-size: .875em; }
h6 { font-size: .85em; color: var(--muted); }
p { margin: 0 0 1em; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
strong { font-weight: 600; }
blockquote {
  margin: 1em 0; padding: .5em 1em; color: var(--muted);
  background: var(--bq-bg); border-left: .25em solid var(--bq-border);
  border-radius: 0 4px 4px 0;
}
blockquote p { margin: 0; }
ul, ol { padding-left: 2em; margin: 0 0 1em; }
li + li { margin-top: .25em; }
code {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: .9em; background: var(--code-bg); padding: .1em .35em;
  border-radius: 3px; border: 1px solid var(--border);
}
pre {
  background: var(--code-bg); border: 1px solid var(--border);
  border-radius: 6px; padding: 1em 1.25em; overflow-x: auto;
  line-height: 1.5; margin: 0 0 1em;
}
pre code { background: transparent; border: none; padding: 0; font-size: .875em; }
hr { border: none; border-top: 2px solid var(--border); margin: 1.5em 0; }
table { border-collapse: collapse; width: 100%; margin: 0 0 1em; font-size: .9em; }
th, td { border: 1px solid var(--border); padding: .5em .75em; text-align: left; }
th { background: var(--code-bg); font-weight: 600; }
tr:nth-child(even) { background: var(--bq-bg); }
img { max-width: 100%; height: auto; border-radius: 4px; }
a.wikilink {
  background: var(--wiki-bg); color: var(--wiki-fg);
  padding: .05em .35em; border-radius: 3px; font-size: .9em;
  text-decoration: none; border: 1px solid var(--border); cursor: pointer;
}
a.wikilink:hover { opacity: 0.8; }
"""


def _get_css_vars(dark: bool) -> str:
    """根据主题生成 CSS 变量覆盖。"""
    if dark:
        return """
        :root {
          --bg:      #1e1e1e;
          --text:    #d4d4d4;
          --muted:   #808080;
          --border:  #3e3e3e;
          --code-bg: #2d2d2d;
          --link:    #4fc1ff;
          --bq-border: #4a4a4a;
          --bq-bg:   #252525;
          --wiki-bg: #2D2250;
          --wiki-fg: #A78BFA;
        }
        """
    return ""


def _md_to_html(text: str, base_url: str = "", dark: bool = False) -> str:
    """将 Markdown 转换为自包含 HTML 文档。"""
    if _HAS_MARKDOWN:
        body = _markdown_lib.markdown(text, extensions=_MARKDOWN_EXTENSIONS)
    else:
        import html as _html
        body = f"<pre>{_html.escape(text)}</pre>"

    # 将相对图片路径转为绝对 file:// URL（QWebEngineView setHtml 安全策略需要）
    if base_url:
        def _abs_img(m):
            src = m.group(1)
            if src.startswith(("http://", "https://", "file://", "data:")):
                return m.group(0)
            # base_url is like "file:///D:/path/to/notes/"
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
    body = "".join(new_parts)

    css_vars = _get_css_vars(dark)
    base_tag = f'<base href="{base_url}">' if base_url else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
{base_tag}
<style>{_PREVIEW_CSS}{css_vars}</style>
</head><body>{body}</body></html>"""


# ---------------------------------------------------------------------------
# WebEngine Page (intercepts wiki-link clicks)
# ---------------------------------------------------------------------------

if _HAS_WEBENGINE:
    class _AssistantPage(QWebEnginePage):
        """拦截导航请求，处理 wiki-link 和外部 URL。"""
        link_clicked = pyqtSignal(str)

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                return True
            scheme = url.scheme()
            if scheme == "assistant":
                if url.host() == "wiki":
                    target = url.path().lstrip("/")
                    self.link_clicked.emit(target)
                return False
            if scheme in ("http", "https", "ftp"):
                os.startfile(url.toString())
                return False
            return False


# ---------------------------------------------------------------------------
# MarkdownPreview
# ---------------------------------------------------------------------------

class MarkdownPreview(QWidget):
    """
    Markdown 预览组件。
    优先使用 QWebEngineView（GitHub 风格渲染），不可用时降级到 QTextBrowser。
    """

    link_clicked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if _HAS_WEBENGINE:
            self._view = QWebEngineView()
            self._page = _AssistantPage(self)
            self._page.link_clicked.connect(self.link_clicked)
            self._view.setPage(self._page)
            self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(self._view)
            self._use_webengine = True
        else:
            from PyQt6.QtWidgets import QTextBrowser
            self._tb = QTextBrowser()
            self._tb.setOpenExternalLinks(False)
            self._tb.setOpenLinks(False)
            self._tb.anchorClicked.connect(self._on_anchor_click)
            self._tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(self._tb)
            self._use_webengine = False

    def _on_anchor_click(self, url: QUrl) -> None:
        """QTextBrowser 降级模式下处理链接点击。"""
        scheme = url.scheme()
        if scheme == "assistant" and url.host() == "wiki":
            self.link_clicked.emit(url.path().lstrip("/"))
        elif scheme in ("http", "https"):
            os.startfile(url.toString())

    def set_content(self, markdown_text: str, base_path: Path | None = None, dark: bool = False) -> None:
        """更新预览内容。"""
        base_url = QUrl()
        if base_path and base_path.exists():
            base_dir = str(base_path) if base_path.is_dir() else str(base_path.parent)
            if not base_dir.endswith("/"):
                base_dir += "/"
            base_url = QUrl.fromLocalFile(base_dir)

        html = _md_to_html(markdown_text, base_url.toString(), dark=dark)

        if self._use_webengine:
            self._page.setHtml(html, base_url)
        else:
            self._tb.setHtml(html)
