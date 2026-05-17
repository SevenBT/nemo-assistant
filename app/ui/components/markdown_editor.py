"""MarkdownEditor — QPlainTextEdit with Markdown syntax highlighting, shortcuts and context menu."""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMenu,
    QPlainTextEdit,
)


# ---------------------------------------------------------------------------
# Syntax highlighter
# ---------------------------------------------------------------------------

class _MarkdownHighlighter(QSyntaxHighlighter):
    """Applies Markdown syntax highlighting to a QTextDocument."""

    def __init__(self, document, palette=None):
        super().__init__(document)
        self._in_code_block = False
        self._build_formats(palette)

    # ── Format definitions ──────────────────────────────────────────────
    def _build_formats(self, palette=None):
        # Detect dark/light theme from palette background luminance
        dark = False
        if palette:
            bg = palette.window().color()
            dark = bg.lightness() < 128

        # Base colours
        if dark:
            muted       = QColor("#6B7280")   # grey — punctuation/symbols
            heading_col = QColor("#E5E7EB")   # near-white
            code_bg     = QColor("#1F2937")   # dark code background
            code_fg     = QColor("#F9FAFB")
            link_col    = QColor("#60A5FA")   # blue
            quote_col   = QColor("#9CA3AF")   # grey-ish
            bold_col    = QColor("#F3F4F6")
            italic_col  = QColor("#D1D5DB")
            strike_col  = QColor("#6B7280")
            hr_col      = QColor("#4B5563")
            list_col    = QColor("#60A5FA")
        else:
            muted       = QColor("#9CA3AF")
            heading_col = QColor("#111827")
            code_bg     = QColor("#F3F4F6")
            code_fg     = QColor("#1F2937")
            link_col    = QColor("#2563EB")
            quote_col   = QColor("#6B7280")
            bold_col    = QColor("#111827")
            italic_col  = QColor("#374151")
            strike_col  = QColor("#9CA3AF")
            hr_col      = QColor("#D1D5DB")
            list_col    = QColor("#6366F1")

        mono = QFont("Consolas, Courier New, monospace")

        def fmt(color=None, bold=False, italic=False, bg=None, mono_font=False, size_delta=0):
            f = QTextCharFormat()
            if color:
                f.setForeground(color)
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            if bg:
                f.setBackground(bg)
            if mono_font:
                f.setFontFamilies(["Consolas", "Courier New", "monospace"])
            if size_delta:
                f.setFontPointSize(14 + size_delta)  # base 14pt
            return f

        self._fmt = {
            # Headings — symbol muted, text bold + larger
            "h1_sym":  fmt(muted, size_delta=8),
            "h1_text": fmt(heading_col, bold=True, size_delta=8),
            "h2_sym":  fmt(muted, size_delta=5),
            "h2_text": fmt(heading_col, bold=True, size_delta=5),
            "h3_sym":  fmt(muted, size_delta=3),
            "h3_text": fmt(heading_col, bold=True, size_delta=3),
            "h4_sym":  fmt(muted, size_delta=1),
            "h4_text": fmt(heading_col, bold=True, size_delta=1),
            "h5_sym":  fmt(muted),
            "h5_text": fmt(heading_col, bold=True),
            "h6_sym":  fmt(muted),
            "h6_text": fmt(heading_col, bold=True),
            # Inline
            "bold_sym":    fmt(muted),
            "bold_text":   fmt(bold_col, bold=True),
            "italic_sym":  fmt(muted),
            "italic_text": fmt(italic_col, italic=True),
            "strike_sym":  fmt(muted),
            "strike_text": fmt(strike_col),
            "code_inline": fmt(code_fg, bg=code_bg, mono_font=True),
            "link_text":   fmt(link_col),
            "link_sym":    fmt(muted),
            "img_sym":     fmt(muted),
            # Block
            "quote_sym":   fmt(list_col),
            "quote_text":  fmt(quote_col, italic=True),
            "list_sym":    fmt(list_col),
            "hr":          fmt(hr_col),
            "code_block":  fmt(code_fg, bg=code_bg, mono_font=True),
            "code_fence":  fmt(muted, mono_font=True),
        }

    # ── Highlighter core ────────────────────────────────────────────────
    def highlightBlock(self, text: str):
        state = self.previousBlockState()

        # ── Fenced code block ──────────────────────────────────────────
        fence = re.match(r'^(`{3,}|~{3,})', text)
        if fence:
            if state == 1:
                # Closing fence
                self.setFormat(0, len(text), self._fmt["code_fence"])
                self.setCurrentBlockState(0)
            else:
                # Opening fence
                self.setFormat(0, len(text), self._fmt["code_fence"])
                self.setCurrentBlockState(1)
            return

        if state == 1:
            # Inside code block
            self.setFormat(0, len(text), self._fmt["code_block"])
            self.setCurrentBlockState(1)
            return

        self.setCurrentBlockState(0)

        # ── Headings ──────────────────────────────────────────────────
        m = re.match(r'^(#{1,6})(\s+)(.*)', text)
        if m:
            level = len(m.group(1))
            sym_end = len(m.group(1)) + len(m.group(2))
            sym_key  = f"h{level}_sym"
            text_key = f"h{level}_text"
            self.setFormat(0, sym_end, self._fmt[sym_key])
            self.setFormat(sym_end, len(text) - sym_end, self._fmt[text_key])
            return

        # ── Horizontal rule ───────────────────────────────────────────
        if re.match(r'^(\*{3,}|-{3,}|_{3,})\s*$', text):
            self.setFormat(0, len(text), self._fmt["hr"])
            return

        # ── Blockquote ────────────────────────────────────────────────
        m = re.match(r'^(>\s?)(.*)', text)
        if m:
            self.setFormat(0, len(m.group(1)), self._fmt["quote_sym"])
            self.setFormat(len(m.group(1)), len(text) - len(m.group(1)), self._fmt["quote_text"])
            self._apply_inline(text)
            return

        # ── List items ────────────────────────────────────────────────
        m = re.match(r'^(\s*)([-*+]|\d+\.)(\s)', text)
        if m:
            sym_end = len(m.group(1)) + len(m.group(2)) + len(m.group(3))
            self.setFormat(len(m.group(1)), len(m.group(2)), self._fmt["list_sym"])
            # Task list checkbox
            cb = re.match(r'^(\s*[-*+]\s)(\[[ xX]\])(\s)', text)
            if cb:
                self.setFormat(len(cb.group(1)), len(cb.group(2)), self._fmt["list_sym"])

        # ── Inline formatting ─────────────────────────────────────────
        self._apply_inline(text)

    def _apply_inline(self, text: str):
        """Apply inline Markdown formatting rules."""
        rules = [
            # Bold+italic (must come before bold/italic)
            (r'\*{3}(.+?)\*{3}',   "bold_sym", "bold_text", True),
            (r'_{3}(.+?)_{3}',     "bold_sym", "bold_text", True),
            # Bold
            (r'\*{2}(.+?)\*{2}',   "bold_sym", "bold_text", True),
            (r'_{2}(.+?)_{2}',     "bold_sym", "bold_text", True),
            # Italic
            (r'\*([^*\n]+?)\*',    "italic_sym", "italic_text", True),
            (r'_([^_\n]+?)_',      "italic_sym", "italic_text", True),
            # Strikethrough
            (r'~~(.+?)~~',         "strike_sym", "strike_text", True),
            # Inline code (no inner formatting)
            (r'`([^`\n]+?)`',      "code_inline", None, False),
            # Image (before link)
            (r'!\[([^\]]*)\]\([^)]*\)', "img_sym", "link_text", True),
            # Link
            (r'\[([^\]]+)\]\([^)]*\)',  "link_sym", "link_text", True),
        ]

        for pattern, sym_key, text_key, has_inner in rules:
            for m in re.finditer(pattern, text):
                start, end = m.start(), m.end()
                if sym_key == "code_inline" or text_key is None:
                    self.setFormat(start, end - start, self._fmt[sym_key])
                else:
                    # sym format for the whole match, then text format for inner group
                    self.setFormat(start, end - start, self._fmt[sym_key])
                    if has_inner and m.lastindex and m.lastindex >= 1:
                        inner_start = m.start(1)
                        inner_len = len(m.group(1))
                        self.setFormat(inner_start, inner_len, self._fmt[text_key])


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------

class MarkdownEditor(QPlainTextEdit):
    """Plain-text Markdown editor with syntax highlighting, keyboard shortcuts and context menu."""

    def __init__(self, images_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self._images_dir = images_dir
        self.setPlaceholderText("在此输入 Markdown 内容…")
        self._highlighter = _MarkdownHighlighter(self.document(), self.palette())

    def changeEvent(self, event):
        """Re-build highlighter formats when palette changes (theme switch)."""
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.PaletteChange:
            self._highlighter._build_formats(self.palette())
            self._highlighter.rehighlight()
        super().changeEvent(event)

    # ------------------------------------------------------------------ public
    def set_images_dir(self, path: Path):
        self._images_dir = path

    def _apply_text_color(self):
        """Force text color to follow theme (FluentWindow overrides palette)."""
        try:
            from app.ui.style import get_text_color
            color = get_text_color()
        except Exception:
            color = "#000000"
        from PyQt6.QtGui import QColor, QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.textCursor()
        self.setCurrentCharFormat(fmt)
        # Also set via viewport stylesheet for the base text color
        self.viewport().setStyleSheet(f"color: {color}; background: transparent;")

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._apply_text_color()
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier

        if mods == ctrl:
            if key == Qt.Key.Key_B:
                self._wrap_selection("**", "**", "加粗文字")
                return
            if key == Qt.Key.Key_I:
                self._wrap_selection("*", "*", "斜体文字")
                return
            if key == Qt.Key.Key_K:
                self._insert_link()
                return
            if key == Qt.Key.Key_QuoteLeft:  # Ctrl+`
                self._wrap_selection("`", "`", "代码")
                return

        if mods == (ctrl | shift):
            if key == Qt.Key.Key_V:
                self._paste_plain_text()
                return

        # Tab / Shift+Tab for list indentation
        if key == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
            if self._indent_list(indent=True):
                return
        if key == Qt.Key.Key_Backtab:
            if self._indent_list(indent=False):
                return

        super().keyPressEvent(event)

    # ------------------------------------------------------------------ context menu
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setObjectName("markdownContextMenu")
        # Theme-aware menu colors
        try:
            from app.ui.style import get_text_color, _current_dark_mode
            text_color = get_text_color()
            bg_color = "#2D2D2D" if _current_dark_mode else "#FFFFFF"
            hover_bg = "#3D3D3D" if _current_dark_mode else "#F3F4F6"
        except Exception:
            text_color, bg_color, hover_bg = "#000000", "#FFFFFF", "#F3F4F6"
        menu.setStyleSheet(
            f"QMenu {{ color: {text_color}; background: {bg_color}; border: 1px solid rgba(128,128,128,0.3); }}"
            f"QMenu::item:selected {{ background: {hover_bg}; }}"
        )

        # Link
        menu.addAction("新增链接").triggered.connect(self._insert_link)
        menu.addSeparator()

        # Text format submenu
        fmt_menu = menu.addMenu("文本格式")
        fmt_menu.addAction("加粗").triggered.connect(lambda: self._wrap_selection("**", "**", "加粗文字"))
        fmt_menu.addAction("倾斜").triggered.connect(lambda: self._wrap_selection("*", "*", "斜体文字"))
        fmt_menu.addAction("删除线").triggered.connect(lambda: self._wrap_selection("~~", "~~", "删除线文字"))
        fmt_menu.addAction("高亮").triggered.connect(lambda: self._wrap_selection("==", "==", "高亮文字"))
        fmt_menu.addAction("代码").triggered.connect(lambda: self._wrap_selection("`", "`", "代码"))
        fmt_menu.addAction("数学").triggered.connect(lambda: self._wrap_selection("$", "$", "公式"))
        fmt_menu.addAction("注释").triggered.connect(lambda: self._wrap_selection("<!-- ", " -->", "注释"))
        fmt_menu.addSeparator()
        fmt_menu.addAction("清除格式").triggered.connect(self._clear_inline_format)

        # Paragraph submenu
        para_menu = menu.addMenu("段落设置")
        para_menu.addAction("无序列表").triggered.connect(lambda: self._set_line_prefix("- "))
        para_menu.addAction("有序列表").triggered.connect(lambda: self._set_line_prefix("1. "))
        para_menu.addAction("任务列表").triggered.connect(lambda: self._set_line_prefix("- [ ] "))
        para_menu.addSeparator()
        para_menu.addAction("H1 一级标题").triggered.connect(lambda: self._set_heading(1))
        para_menu.addAction("H2 二级标题").triggered.connect(lambda: self._set_heading(2))
        para_menu.addAction("H3 三级标题").triggered.connect(lambda: self._set_heading(3))
        para_menu.addAction("H4 四级标题").triggered.connect(lambda: self._set_heading(4))
        para_menu.addAction("H5 五级标题").triggered.connect(lambda: self._set_heading(5))
        para_menu.addAction("H6 六级标题").triggered.connect(lambda: self._set_heading(6))
        para_menu.addAction("正文").triggered.connect(self._clear_block_prefix)
        para_menu.addAction("引用").triggered.connect(lambda: self._set_line_prefix("> "))

        # Insert submenu
        ins_menu = menu.addMenu("插入")
        ins_menu.addAction("图片").triggered.connect(self._insert_image)
        ins_menu.addAction("表格").triggered.connect(self._insert_table)
        ins_menu.addAction("标注").triggered.connect(self._insert_callout)
        ins_menu.addAction("分隔线").triggered.connect(self._insert_hr)
        ins_menu.addAction("代码块").triggered.connect(self._insert_code_block)
        ins_menu.addAction("数学块").triggered.connect(self._insert_math_block)

        menu.addSeparator()

        # Clipboard
        cut_act = menu.addAction("剪切")
        cut_act.setShortcut(QKeySequence.StandardKey.Cut)
        cut_act.triggered.connect(self.cut)

        copy_act = menu.addAction("复制")
        copy_act.setShortcut(QKeySequence.StandardKey.Copy)
        copy_act.triggered.connect(self.copy)

        paste_act = menu.addAction("粘贴")
        paste_act.setShortcut(QKeySequence.StandardKey.Paste)
        paste_act.triggered.connect(self.paste)

        paste_plain_act = menu.addAction("以纯文本形式粘贴")
        paste_plain_act.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_plain_act.triggered.connect(self._paste_plain_text)

        menu.addSeparator()

        select_all_act = menu.addAction("全选")
        select_all_act.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_act.triggered.connect(self.selectAll)

        # Enable/disable clipboard actions based on state
        has_selection = self.textCursor().hasSelection()
        cut_act.setEnabled(has_selection)
        copy_act.setEnabled(has_selection)
        clipboard_text = QApplication.clipboard().text()
        paste_act.setEnabled(bool(clipboard_text))
        paste_plain_act.setEnabled(bool(clipboard_text))

        menu.exec(event.globalPos())

    # ------------------------------------------------------------------ inline helpers
    def _wrap_selection(self, prefix: str, suffix: str, placeholder: str = ""):
        cursor = self.textCursor()
        selected = cursor.selectedText()
        text = selected if selected else placeholder
        cursor.insertText(f"{prefix}{text}{suffix}")
        if not selected and placeholder:
            # Select the placeholder so user can type over it
            pos = cursor.position()
            cursor.setPosition(pos - len(suffix) - len(placeholder))
            cursor.setPosition(pos - len(suffix), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def _clear_inline_format(self):
        """Strip common inline Markdown markers from selection."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        import re
        text = cursor.selectedText()
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        text = re.sub(r'==(.+?)==', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'\$(.+?)\$', r'\1', text)
        text = re.sub(r'<!--\s*(.+?)\s*-->', r'\1', text)
        cursor.insertText(text)

    # ------------------------------------------------------------------ block helpers
    def _current_line_text(self) -> str:
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        return cursor.selectedText()

    def _set_line_prefix(self, prefix: str):
        """Add prefix to every selected line (or current line if no selection)."""
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        block_start = cursor.position()

        cursor.setPosition(end)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        block_end = cursor.position()

        cursor.setPosition(block_start)
        cursor.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
        block_text = cursor.selectedText()

        import re
        # \u2029 is Qt's paragraph separator in selectedText()
        lines = block_text.split("\u2029")
        new_lines = []
        for line in lines:
            # Remove existing list/heading prefixes before adding new one
            clean = re.sub(r'^(#{1,6}\s+|[-*+]\s+(\[[ x]\]\s+)?|\d+\.\s+|>\s+)', '', line)
            new_lines.append(prefix + clean)

        cursor.insertText("\u2029".join(new_lines))

    def _set_heading(self, level: int):
        self._set_line_prefix("#" * level + " ")

    def _clear_block_prefix(self):
        """Remove heading/list/quote prefix from selected lines."""
        import re
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)

        block_text = cursor.selectedText()
        lines = block_text.split("\u2029")
        new_lines = [re.sub(r'^(#{1,6}\s+|[-*+]\s+(\[[ x]\]\s+)?|\d+\.\s+|>\s+)', '', l) for l in lines]
        cursor.insertText("\u2029".join(new_lines))

    def _indent_list(self, indent: bool) -> bool:
        """Indent/unindent list item. Returns True if handled."""
        import re
        line = self._current_line_text()
        if not re.match(r'^(\s*)([-*+]|\d+\.)\s', line):
            return False
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        if indent:
            cursor.insertText("    " + text)
        else:
            if text.startswith("    "):
                cursor.insertText(text[4:])
            elif text.startswith("  "):
                cursor.insertText(text[2:])
        return True

    # ------------------------------------------------------------------ insert helpers
    def _insert_link(self):
        selected = self.textCursor().selectedText()
        text, ok = QInputDialog.getText(self, "新增链接", "链接文字:", text=selected or "")
        if not ok:
            return
        url, ok2 = QInputDialog.getText(self, "新增链接", "URL:")
        if not ok2:
            return
        self.textCursor().insertText(f"[{text}]({url})")

    def _insert_image(self):
        if not self._images_dir:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.gif *.webp *.svg)"
        )
        if not path:
            return
        self._images_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(path).suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = self._images_dir / filename
        shutil.copy2(path, dest)
        rel = f"images/{filename}"
        self.textCursor().insertText(f"![图片]({rel})")

    def _insert_table(self):
        table = (
            "| 列1 | 列2 | 列3 |\n"
            "| --- | --- | --- |\n"
            "| 内容 | 内容 | 内容 |"
        )
        self._insert_block(table)

    def _insert_callout(self):
        self._insert_block("> [!NOTE]\n> 标注内容")

    def _insert_hr(self):
        self._insert_block("---")

    def _insert_code_block(self):
        lang, ok = QInputDialog.getText(self, "代码块", "语言（如 python、js，可留空）:")
        if not ok:
            return
        self._insert_block(f"```{lang}\n\n```")
        # Move cursor inside the block
        cursor = self.textCursor()
        pos = cursor.position()
        cursor.setPosition(pos - 4)  # before closing ```
        self.setTextCursor(cursor)

    def _insert_math_block(self):
        self._insert_block("$$\n\n$$")
        cursor = self.textCursor()
        pos = cursor.position()
        cursor.setPosition(pos - 3)
        self.setTextCursor(cursor)

    def _insert_block(self, text: str):
        """Insert block content, ensuring blank lines around it."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
        line = cursor.selectedText()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        prefix = "\n\n" if line.strip() else "\n"
        cursor.insertText(f"{prefix}{text}\n\n")

    def _paste_plain_text(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasText():
            self.textCursor().insertText(mime.text())
