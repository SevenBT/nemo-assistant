"""MarkdownEditor — QPlainTextEdit with syntax highlighting, wiki-links, and context menu."""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QKeySequence,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QImage,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMenu,
    QPlainTextEdit,
    QTextEdit,
)

from app.ui.components.markdown_highlighter import MarkdownHighlighter
from app.core.wiki_links import parse_wiki_links


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


class MarkdownEditor(QPlainTextEdit):
    """Markdown editor with syntax highlighting, wiki-links, image paste/drop."""

    wiki_link_activated = pyqtSignal(str)

    def __init__(self, images_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self._images_dir = images_dir
        self._find_replace_dialog = None
        self.setPlaceholderText("在此输入 Markdown 内容…")
        self.setAcceptDrops(True)

        # Syntax highlighter (from noteration)
        self._highlighter = MarkdownHighlighter(self.document())
        # Set initial default text color from theme
        try:
            from app.ui.style import get_text_color
            self._highlighter.set_default_text_color(get_text_color())
        except Exception:
            pass

        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._highlight_current_line()

    # ------------------------------------------------------------------ theme
    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.PaletteChange:
            self._update_highlighter_palette()
        super().changeEvent(event)

    def _update_highlighter_palette(self):
        """Update highlighter palette based on current theme."""
        try:
            from app.ui.style import _current_dark_mode, get_text_color
            dark = _current_dark_mode
            text_color = get_text_color()
        except Exception:
            bg = self.palette().window().color()
            dark = bg.lightness() < 128
            text_color = "#E8E0D6" if dark else "#1E293B"
        if dark:
            palette = {
                "heading": "#E5E7EB",
                "bold_italic": "#F3F4F6",
                "italic": "#D1D5DB",
                "link": "#60A5FA",
                "list": "#60A5FA",
                "escape": "#EF4444",
                "image": ("#FBBF24", "#3B2E00"),
                "wiki": ("#A78BFA", "#2D2250"),
                "code": ("#34D399", "#1A2E28"),
                "quote": ("#9CA3AF", "#2A2A2A"),
                "code_block": ("#9CA3AF", "#1F2937"),
            }
        else:
            palette = {
                "heading": "#1a1a2e",
                "bold_italic": "#111111",
                "italic": "#444444",
                "link": "#185FA5",
                "list": "#BA7517",
                "escape": "#c0392b",
                "image": ("#c77700", "#FFF8E1"),
                "wiki": ("#534AB7", "#EEEDFE"),
                "code": ("#1D9E75", "#F0FFF8"),
                "quote": ("#888", "#FAFAFA"),
                "code_block": ("#888", "#F5F5F5"),
            }
        self._highlighter.set_default_text_color(text_color)
        self._highlighter.set_palette(palette)

    # ------------------------------------------------------------------ public
    def set_images_dir(self, path: Path):
        self._images_dir = path

    # ------------------------------------------------------------------ current line highlight
    def _highlight_current_line(self) -> None:
        extras: list[QTextEdit.ExtraSelection] = []
        sel = QTextEdit.ExtraSelection()
        # 深浅判断从 style._current_dark_mode 读取，palette lightness 在 FluentWindow 下不可靠
        try:
            from app.ui.style import _current_dark_mode
            is_dark = _current_dark_mode
        except Exception:
            is_dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        # 用半透明叠加而非写死颜色：暗色叠淡白、浅色叠淡黑，
        # 这样当前行只在任意主题底色上微微提亮/压暗，绝不会出现突兀的黑块
        highlight = QColor(255, 255, 255, 20) if is_dark else QColor(0, 0, 0, 14)
        sel.format.setBackground(highlight)
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        extras.append(sel)
        self.setExtraSelections(extras)

    # ------------------------------------------------------------------ text color (FluentWindow fix)
    def _apply_text_color(self):
        """Force text color to follow theme (FluentWindow overrides palette).

        QPlainTextEdit 没有 setTextColor（那是 QTextEdit 的方法），用
        setCurrentCharFormat 设置新输入的前景色，再 mergeCurrentCharFormat
        让颜色应用到当前光标位置，确保不被 FluentWindow 内部样式覆盖。
        """
        try:
            from app.ui.style import get_text_color
            color = get_text_color()
        except Exception:
            color = "#000000"
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        self.setCurrentCharFormat(fmt)
        self.mergeCurrentCharFormat(fmt)
        self._highlighter.set_default_text_color(color)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._apply_text_color()

    # ------------------------------------------------------------------ mouse (wiki-link Ctrl+Click)
    def mousePressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            cursor = self.cursorForPosition(event.pos())
            pos = cursor.position()
            for link in parse_wiki_links(self.toPlainText()):
                if link.start <= pos <= link.end:
                    self.wiki_link_activated.emit(link.target)
                    return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ keyboard
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
            if key == Qt.Key.Key_QuoteLeft:
                self._wrap_selection("`", "`", "代码")
                return
            if key == Qt.Key.Key_F:
                self._open_find_replace()
                return
            if key == Qt.Key.Key_H:
                self._open_find_replace()
                return
            if key == Qt.Key.Key_Y:
                self.redo()
                return
            if key == Qt.Key.Key_V:
                # Image paste from clipboard
                clipboard = QApplication.clipboard()
                image = clipboard.image()
                if image and not image.isNull():
                    self._paste_image(image)
                    return

        if mods == (ctrl | shift):
            if key == Qt.Key.Key_V:
                self._paste_plain_text()
                return

        # Tab / Shift+Tab for list indentation, or soft-tab
        if key == Qt.Key.Key_Tab and mods == Qt.KeyboardModifier.NoModifier:
            if self._indent_list(indent=True):
                return
            # Soft-tab: insert spaces
            self.textCursor().insertText("    ")
            return
        if key == Qt.Key.Key_Backtab:
            if self._indent_list(indent=False):
                return

        super().keyPressEvent(event)

    # ------------------------------------------------------------------ paste from web (preserve newlines)
    def insertFromMimeData(self, source):
        """Override paste to preserve line breaks from clipboard content.

        Priority: plain text (reliable newlines) > HTML parsing > default.
        Web-copied markdown often has HTML where newlines are expressed via CSS
        (white-space:pre) or nested spans rather than block-level tags, so HTML
        parsing loses line breaks. The plain text representation is more reliable.
        """
        if source.hasImage():
            super().insertFromMimeData(source)
            return

        # Prefer plain text — it preserves newlines reliably
        if source.hasText():
            text = source.text()
            if text.strip():
                self.textCursor().insertText(text)
                return

        # Fallback: parse HTML if no usable plain text
        if source.hasHtml():
            html = source.html()
            import html as html_mod
            # Convert block-level elements to newlines
            text = re.sub(r'<br\s*/?>', '\n', html)
            text = re.sub(r'</(?:p|div|h[1-6]|li|tr|blockquote|pre)>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = html_mod.unescape(text)
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = text.strip()
            if text:
                self.textCursor().insertText(text)
                return

        super().insertFromMimeData(source)

    # ------------------------------------------------------------------ drag & drop (image)
    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in _IMAGE_EXTS:
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and self._images_dir:
            for url in mime.urls():
                if url.isLocalFile():
                    file_path = Path(url.toLocalFile())
                    if file_path.suffix.lower() in _IMAGE_EXTS:
                        self._drop_image_file(file_path)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # ------------------------------------------------------------------ image helpers
    def _paste_image(self, image: QImage):
        """Save clipboard image to images dir and insert markdown."""
        if not self._images_dir:
            return
        self._images_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.png"
        dest = self._images_dir / filename
        image.save(str(dest), "PNG")
        rel = f"images/{filename}"
        self.textCursor().insertText(f"![图片]({rel})")

    def _drop_image_file(self, file_path: Path):
        """Copy dropped image file to images dir and insert markdown."""
        if not self._images_dir:
            return
        self._images_dir.mkdir(parents=True, exist_ok=True)
        ext = file_path.suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = self._images_dir / filename
        shutil.copy2(str(file_path), str(dest))
        rel = f"images/{filename}"
        self.textCursor().insertText(f"![{file_path.stem}]({rel})")

    # ------------------------------------------------------------------ find/replace
    def _open_find_replace(self):
        from app.ui.components.find_replace_dialog import FindReplaceDialog
        if self._find_replace_dialog is None:
            self._find_replace_dialog = FindReplaceDialog(self)
            self._find_replace_dialog.find_next_requested.connect(self._find_next)
            self._find_replace_dialog.replace_requested.connect(self._replace)
            self._find_replace_dialog.replace_all_requested.connect(self._replace_all)
        # Pre-fill from selection
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._find_replace_dialog.set_initial_text(cursor.selectedText())
        self._find_replace_dialog.show()
        self._find_replace_dialog.raise_()

    def _find_next(self, query: str, case_sensitive: bool, whole_word: bool, use_regex: bool):
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if whole_word:
            flags |= QTextDocument.FindFlag.FindWholeWords
        if use_regex:
            from PyQt6.QtCore import QRegularExpression
            re_flags = QRegularExpression.PatternOption.NoPatternOption
            if not case_sensitive:
                re_flags |= QRegularExpression.PatternOption.CaseInsensitiveOption
            rx = QRegularExpression(query, re_flags)
            found = self.find(rx, flags)
        else:
            found = self.find(query, flags)
        # Wrap around
        if not found:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.setTextCursor(cursor)
            if use_regex:
                from PyQt6.QtCore import QRegularExpression
                re_flags = QRegularExpression.PatternOption.NoPatternOption
                if not case_sensitive:
                    re_flags |= QRegularExpression.PatternOption.CaseInsensitiveOption
                found = self.find(QRegularExpression(query, re_flags), flags)
            else:
                found = self.find(query, flags)
        return found

    def _replace(self, query: str, replacement: str, case_sensitive: bool, whole_word: bool, use_regex: bool):
        """Replace current selection if it matches, otherwise find next."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            self._find_next(query, case_sensitive, whole_word, use_regex)
            return

        selected = cursor.selectedText()
        match = False
        if use_regex:
            import re as re_mod
            re_flags = 0 if case_sensitive else re_mod.IGNORECASE
            if re_mod.fullmatch(query, selected, flags=re_flags):
                match = True
        else:
            if case_sensitive:
                match = (selected == query)
            else:
                match = (selected.lower() == query.lower())

        if match:
            cursor.insertText(replacement)
        self._find_next(query, case_sensitive, whole_word, use_regex)

    def _replace_all(self, query: str, replacement: str, case_sensitive: bool, whole_word: bool, use_regex: bool):
        """Replace all occurrences in the document."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)

        count = 0
        while self._find_next(query, case_sensitive, whole_word, use_regex):
            self.textCursor().insertText(replacement)
            count += 1
            if count > 10000:
                break

    # ------------------------------------------------------------------ context menu
    def contextMenuEvent(self, event):
        # Move cursor to right-click position if no selection
        if not self.textCursor().hasSelection():
            cursor = self.cursorForPosition(event.pos())
            self.setTextCursor(cursor)

        menu = QMenu(self)
        menu.setObjectName("markdownContextMenu")
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

        cut_act = menu.addAction("剪切")
        cut_act.setShortcut(QKeySequence.StandardKey.Cut)
        cut_act.triggered.connect(self.cut)
        copy_act = menu.addAction("复制")
        copy_act.setShortcut(QKeySequence.StandardKey.Copy)
        copy_act.triggered.connect(self.copy)
        paste_act = menu.addAction("粘贴")
        paste_act.setShortcut(QKeySequence.StandardKey.Paste)
        paste_act.triggered.connect(self.paste)
        # Detect image in clipboard and show "粘贴图片" option
        clipboard = QApplication.clipboard()
        clip_image = clipboard.image()
        if clip_image and not clip_image.isNull():
            paste_img_act = menu.addAction("粘贴图片")
            paste_img_act.triggered.connect(lambda: self._paste_image(clip_image))
        paste_plain_act = menu.addAction("以纯文本形式粘贴")
        paste_plain_act.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste_plain_act.triggered.connect(self._paste_plain_text)
        menu.addSeparator()
        select_all_act = menu.addAction("全选")
        select_all_act.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all_act.triggered.connect(self.selectAll)
        menu.addSeparator()
        menu.addAction("查找替换").triggered.connect(self._open_find_replace)

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
            pos = cursor.position()
            cursor.setPosition(pos - len(suffix) - len(placeholder))
            cursor.setPosition(pos - len(suffix), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def _clear_inline_format(self):
        """Strip common inline Markdown markers from selection."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
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
        lines = block_text.split("\u2029")
        new_lines = []
        for line in lines:
            clean = re.sub(r'^(#{1,6}\s+|[-*+]\s+(\[[ x]\]\s+)?|\d+\.\s+|>\s+)', '', line)
            new_lines.append(prefix + clean)
        cursor.insertText("\u2029".join(new_lines))

    def _set_heading(self, level: int):
        self._set_line_prefix("#" * level + " ")

    def _clear_block_prefix(self):
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
        saved_cursor = self.textCursor()
        selected = saved_cursor.selectedText()
        text, ok = QInputDialog.getText(self, "新增链接", "链接文字:", text=selected or "")
        if not ok:
            return
        url, ok2 = QInputDialog.getText(self, "新增链接", "URL:")
        if not ok2:
            return
        self.setTextCursor(saved_cursor)
        self.textCursor().insertText(f"[{text}]({url})")

    def _insert_image(self):
        if not self._images_dir:
            return
        saved_cursor = self.textCursor()
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.gif *.webp *.svg)"
        )
        if not path:
            return
        self.setTextCursor(saved_cursor)
        self._images_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(path).suffix
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = self._images_dir / filename
        shutil.copy2(path, dest)
        rel = f"images/{filename}"
        self.textCursor().insertText(f"![图片]({rel})")

    def _insert_table(self):
        self._insert_block(
            "| 列1 | 列2 | 列3 |\n| --- | --- | --- |\n| 内容 | 内容 | 内容 |"
        )

    def _insert_callout(self):
        self._insert_block("> [!NOTE]\n> 标注内容")

    def _insert_hr(self):
        self._insert_block("---")

    def _insert_code_block(self):
        # Save cursor position before dialog steals focus
        saved_cursor = self.textCursor()
        lang, ok = QInputDialog.getText(self, "代码块", "语言（如 python、js，可留空）:")
        if not ok:
            return
        self.setTextCursor(saved_cursor)
        self._insert_block(f"```{lang}\n\n```")
        cursor = self.textCursor()
        cursor.setPosition(cursor.position() - 4)
        self.setTextCursor(cursor)

    def _insert_math_block(self):
        self._insert_block("$$\n\n$$")
        cursor = self.textCursor()
        cursor.setPosition(cursor.position() - 3)
        self.setTextCursor(cursor)

    def _insert_block(self, text: str):
        """Insert block content, ensuring blank lines around it."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine, QTextCursor.MoveMode.KeepAnchor)
        before = cursor.selectedText()
        cursor = self.textCursor()
        prefix = "\n\n" if before.strip() else ""
        cursor.insertText(f"{prefix}{text}\n")

    def _paste_plain_text(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasText():
            self.textCursor().insertText(mime.text())