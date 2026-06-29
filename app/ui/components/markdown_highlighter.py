r"""
Markdown 语法高亮器。
Adapted from noteration (MIT): noteration/editor/syntax_highlighter.py
See THIRD_PARTY_NOTICES.md.

覆盖 CommonMark 基本语法：ATX/Setext 标题、粗体/斜体、代码块、
引用、列表、链接、图片、Wiki-link、水平线、转义字符等。
"""

from __future__ import annotations

import re
from PyQt6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument,
)


class MarkdownHighlighter(QSyntaxHighlighter):
    """
    Markdown syntax highlighter for QPlainTextEdit.
    Adapted from noteration (MIT). Uses block states for fenced code blocks.
    """

    _STATE_NORMAL = 0
    _STATE_CODE_FENCE = 1

    def __init__(self, document: QTextDocument, palette: dict | None = None) -> None:
        super().__init__(document)
        self._palette = palette or {}
        self._default_text_color: str | None = None
        self._default_fmt = QTextCharFormat()
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._setext_rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._code_fence_fmt = QTextCharFormat()
        self._build_rules()

    def set_palette(self, palette: dict) -> None:
        self._palette = palette
        self._build_rules()
        self.rehighlight()

    def set_default_text_color(self, color: str) -> None:
        """Set default foreground color for non-highlighted text.

        Also rebuilds rules so that formats without explicit color
        inherit this default (Qt setFormat replaces, not merges).
        """
        if color != self._default_text_color:
            self._default_text_color = color
            self._default_fmt = QTextCharFormat()
            self._default_fmt.setForeground(QColor(color))
            self._build_rules()
            self.rehighlight()

    def _make_format(
        self,
        color: str | None = None,
        bg: str | None = None,
        bold: bool = False,
        italic: bool = False,
        size_pt: float | None = None,
        underline: bool = False,
    ) -> QTextCharFormat:
        fmt = QTextCharFormat()
        # Always set foreground: explicit color > default text color > nothing
        if color:
            fmt.setForeground(QColor(color))
        elif self._default_text_color:
            fmt.setForeground(QColor(self._default_text_color))
        if bg:
            fmt.setBackground(QColor(bg))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        if size_pt:
            fmt.setFontPointSize(size_pt)
        if underline:
            fmt.setFontUnderline(True)
        return fmt

    def _build_rules(self) -> None:
        self._rules = []
        add = self._rules.append
        p = self._palette

        def get_c(key, default):
            val = p.get(key, default)
            return val if isinstance(val, str) else val[0]

        h_color = get_c("heading", "#1a1a2e")
        bi_color = get_c("bold_italic", "#111111")
        it_color = get_c("italic", "#444444")
        lnk_color = get_c("link", "#185FA5")
        lst_color = get_c("list", "#BA7517")
        esc_color = get_c("escape", "#c0392b")

        # ATX Headings
        add((re.compile(r'^# .+'), self._make_format(color=h_color, bold=True, size_pt=18)))
        add((re.compile(r'^## .+'), self._make_format(color=h_color, bold=True, size_pt=16)))
        add((re.compile(r'^### .+'), self._make_format(color=h_color, bold=True, size_pt=14)))
        add((re.compile(r'^#{4} .+'), self._make_format(color=h_color, bold=True, size_pt=13)))
        add((re.compile(r'^#{5} .+'), self._make_format(color=h_color, bold=True)))
        add((re.compile(r'^#{6} .+'), self._make_format(color=h_color, bold=True)))

        # Setext Headings
        self._setext_rules = [
            (re.compile(r'^={2,}\s*$'), self._make_format(color=h_color, bold=True)),
            (re.compile(r'^-{2,}\s*$'), self._make_format(color=h_color, bold=True)),
        ]

        # Bold + Italic
        add((re.compile(r'\*{3}[^*\n]+\*{3}'), self._make_format(bold=True, italic=True, color=bi_color)))
        add((re.compile(r'_{3}[^_\n]+_{3}'), self._make_format(bold=True, italic=True, color=bi_color)))
        add((re.compile(r'\*\*_[^_\n]+_\*\*'), self._make_format(bold=True, italic=True, color=bi_color)))
        add((re.compile(r'__\*[^*\n]+\*__'), self._make_format(bold=True, italic=True, color=bi_color)))

        # Bold
        add((re.compile(r'\*\*[^*\n]+\*\*'), self._make_format(bold=True)))
        add((re.compile(r'__[^_\n]+__'), self._make_format(bold=True)))

        # Italic
        add((re.compile(r'\*[^*\n]+\*'), self._make_format(italic=True, color=it_color)))
        add((re.compile(r'_[^_\n]+_'), self._make_format(italic=True, color=it_color)))

        # Image
        img_fg, img_bg = p.get("image", ("#c77700", "#FFF8E1"))
        add((re.compile(r'!\[[^\]]*\]\([^\)]*\)'), self._make_format(color=img_fg, bg=img_bg)))

        # Link
        add((re.compile(r'\[([^\]]+)\]\([^\)]+\)'), self._make_format(color=lnk_color, underline=True)))

        # Autolink
        add((re.compile(r'<(?:https?|ftp|mailto):[^>]+>'), self._make_format(color=lnk_color, underline=True)))
        add((re.compile(r'<[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}>'), self._make_format(color=lnk_color, underline=True)))

        # Wiki-link [[target]]
        wiki_fg, wiki_bg = p.get("wiki", ("#534AB7", "#EEEDFE"))
        add((re.compile(r'\[\[[^\]]+\]\]'), self._make_format(color=wiki_fg, bg=wiki_bg)))

        # Inline code
        code_fg, code_bg = p.get("code", ("#1D9E75", "#F0FFF8"))
        add((re.compile(r'``[^`\n]+``'), self._make_format(color=code_fg, bg=code_bg)))
        add((re.compile(r'`[^`\n]+`'), self._make_format(color=code_fg, bg=code_bg)))

        # Blockquote
        quote_fg, quote_bg = p.get("quote", ("#888", "#FAFAFA"))
        add((re.compile(r'^>>+.*'), self._make_format(color=quote_fg, italic=True, bg=quote_bg)))
        add((re.compile(r'^>.*'), self._make_format(color=quote_fg, italic=True, bg=quote_bg)))

        # List
        add((re.compile(r'^(\s*)[-*+] '), self._make_format(color=lst_color, bold=True)))
        add((re.compile(r'^(\s*)\d+[.)]\s'), self._make_format(color=lst_color, bold=True)))

        # Fenced code block format (used by highlightBlock for ``` blocks).
        # NOTE: no indented-code-block rule here — a leading Tab / 4 spaces is
        # treated as plain indentation (matching the preview, which disables
        # indented code blocks), so it must NOT get the code-block background.
        cb_fg, cb_bg = p.get("code_block", ("#888", "#F5F5F5"))
        self._code_fence_fmt = self._make_format(color=cb_fg, bg=cb_bg)

        # Horizontal rule, HTML tags, escape chars, trailing spaces, YAML separator
        add((re.compile(r'^\s*(\*{3,}|-{3,}|_{3,})\s*$'), self._make_format(color="#bbb")))
        add((re.compile(r'</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>'), self._make_format(color="#9b59b6")))
        add((re.compile(r'\\[\\`*_{}\[\]<>()+\-\.!|#]'), self._make_format(color=esc_color, bold=True)))
        add((re.compile(r'  +$'), self._make_format(bg="#D6EAF8", underline=True)))
        add((re.compile(r'^---\s*$'), self._make_format(color="#aaa")))

    # ── highlightBlock ────────────────────────────────────────────────

    def highlightBlock(self, text: str) -> None:
        prev_state = self.previousBlockState()

        # Apply default text color as baseline (syntax rules override on top)
        if self._default_text_color and text:
            self.setFormat(0, len(text), self._default_fmt)

        # Fenced code block (``` ... ```)
        stripped = text.strip()
        if stripped.startswith("```"):
            entering = prev_state != self._STATE_CODE_FENCE
            self.setFormat(0, len(text), self._code_fence_fmt)
            self.setCurrentBlockState(
                self._STATE_CODE_FENCE if entering else self._STATE_NORMAL
            )
            return

        if prev_state == self._STATE_CODE_FENCE:
            self.setFormat(0, len(text), self._code_fence_fmt)
            self.setCurrentBlockState(self._STATE_CODE_FENCE)
            return

        self.setCurrentBlockState(self._STATE_NORMAL)

        # Setext heading underline
        for pattern, fmt in self._setext_rules:
            if pattern.match(text):
                self.setFormat(0, len(text), fmt)
                return

        # Apply all inline rules
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
