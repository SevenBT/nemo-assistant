"""Shared rich-text sticky editor for desktop notes and the note library."""
import re
import uuid
import json
import html
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPalette, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat, QTextImageFormat
from PyQt6.QtWidgets import QColorDialog, QFileDialog, QFontDialog, QMenu, QMessageBox, QTextEdit

from app.config.config import NOTES_IMAGES_DIR
from app.i18n import t

_EXPLICIT_COLOR = int(QTextFormat.Property.UserProperty) + 1
_COLOR_META = "nemo-sticky-colors"


def is_sticky_html(content):
    return bool(re.search(r"<(?:!DOCTYPE|html|p|div|ul|ol|li|span|b|i|img|br|h[1-6])(?:[ >\s])", content, re.I))


class StickyEditor(QTextEdit):
    """Same document format on the desktop and in the note library."""

    editing_started = pyqtSignal()

    def __init__(self, parent=None, images_dir=None):
        super().__init__(parent)
        self.images_dir = Path(images_dir or NOTES_IMAGES_DIR)
        self.document().setBaseUrl(QUrl.fromLocalFile(str(self.images_dir.parent) + "/"))

    def load_content(self, content):
        # QTextEdit retains the insertion format when replacing an empty/plain
        # document. Never carry a previous note's strike/color into a new note.
        self.setCurrentCharFormat(QTextCharFormat())
        if is_sticky_html(content):
            self.setHtml(content)
        else:
            self.setPlainText(content)
        document = self.document()
        document.setUndoRedoEnabled(False)
        try:
            self._restore_explicit_colors(content)
            self._remove_legacy_theme_colors()
            self._remove_legacy_checklists()
        finally:
            document.setUndoRedoEnabled(True)
        if document.isEmpty():
            self.setCurrentCharFormat(QTextCharFormat())

    def _restore_explicit_colors(self, content):
        match = re.search(r'<meta\s+name="' + _COLOR_META + r'"\s+content="([^"]*)"\s*/?>', content)
        if not match:
            return
        try:
            records = json.loads(html.unescape(match.group(1)))
            if not isinstance(records, list):
                return
            for start, end, color in records:
                if not (isinstance(start, int) and isinstance(end, int) and isinstance(color, str)
                        and 0 <= start < end < self.document().characterCount() and QColor(color).isValid()):
                    continue
                cursor = QTextCursor(self.document())
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                fmt.setProperty(_EXPLICIT_COLOR, True)
                cursor.mergeCharFormat(fmt)
        except (ValueError, TypeError):
            return

    def _remove_legacy_theme_colors(self):
        from app.ui.style import THEMES
        automatic = {QColor(theme["text"]).name() for theme in THEMES.values()}
        automatic.update(("#ffffff", "#000000", "#222222", "#252525", "#f3f3f3"))
        changes = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    if (fmt.hasProperty(QTextFormat.Property.ForegroundBrush) and not fmt.property(_EXPLICIT_COLOR)
                            and fmt.foreground().color().name() in automatic):
                        fmt.clearProperty(QTextFormat.Property.ForegroundBrush)
                        changes.append((fragment.position(), fragment.length(), fmt))
                iterator += 1
            block = block.next()
        cursor = QTextCursor(self.document())
        for start, length, fmt in changes:
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)

    def toHtml(self):
        output = super().toHtml()
        colors = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().property(_EXPLICIT_COLOR):
                    colors.append([fragment.position(), fragment.position() + fragment.length(),
                                   fragment.charFormat().foreground().color().name(QColor.NameFormat.HexArgb)])
                iterator += 1
            block = block.next()
        if colors:
            metadata = html.escape(json.dumps(colors, separators=(",", ":")), quote=True)
            output = output.replace("<head>", '<head><meta name="' + _COLOR_META + '" content="' + metadata + '" />', 1)
        return output

    def apply_text_color(self, color):
        palette = self.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
            palette.setColor(group, QPalette.ColorRole.Text, QColor(color))
        self.setPalette(palette)

    def setTextColor(self, color):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setProperty(_EXPLICIT_COLOR, True)
        self.mergeCurrentCharFormat(fmt)

    def _remove_legacy_checklists(self):
        """Keep old checklist bodies as ordinary paragraphs without task state."""
        block = self.document().begin()
        while block.isValid():
            fmt = block.blockFormat()
            marker = fmt.marker()
            if marker != QTextBlockFormat.MarkerType.NoMarker:
                cursor = QTextCursor(block)
                if cursor.currentList():
                    cursor.currentList().remove(block)
                fmt.setObjectIndex(-1)
                fmt.setMarker(QTextBlockFormat.MarkerType.NoMarker)
                fmt.setIndent(0)
                fmt.setTextIndent(0)
                cursor.setBlockFormat(fmt)
                if marker == QTextBlockFormat.MarkerType.Checked:
                    char_fmt = QTextCharFormat()
                    char_fmt.setFontStrikeOut(False)
                    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cursor.mergeCharFormat(char_fmt)
                    cursor.mergeBlockCharFormat(char_fmt)
                block.setVisible(True)
            block = block.next()

    def plain_text(self):
        return self.toPlainText()

    def add_image(self, image):
        if self.isReadOnly() or image.isNull():
            return
        self.images_dir.mkdir(parents=True, exist_ok=True)
        path = self.images_dir / (uuid.uuid4().hex + ".png")
        if not image.save(str(path), "PNG"):
            raise OSError("Could not save sticky image")
        fmt = QTextImageFormat()
        fmt.setName(QUrl.fromLocalFile(str(path)).toString())
        width = min(image.width(), max(120, self.viewport().width() - 24))
        fmt.setWidth(width)
        fmt.setHeight(image.height() * width / image.width())
        self.textCursor().insertImage(fmt)

    def insertFromMimeData(self, source):
        try:
            self._insert_mime(source)
        except OSError:
            QMessageBox.warning(self, t("sticky.error"), t("sticky.imageFailed"))

    def _insert_mime(self, source):
        if self.isReadOnly():
            return
        if source.hasImage():
            self.add_image(QImage(source.imageData()))
            return
        if source.hasUrls():
            images = [QImage(url.toLocalFile()) for url in source.urls() if url.isLocalFile()]
            images = [image for image in images if not image.isNull()]
            if images:
                for image in images:
                    self.add_image(image)
                return
        if source.hasHtml():
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(source.html(), "html.parser")
            for tag in soup.find_all(["script", "iframe", "object", "link"]):
                tag.decompose()
            # Copy local image resources; never store a transient or remote URI.
            for tag in soup.find_all("img"):
                url = QUrl(tag.get("src", ""))
                path = url.toLocalFile() if url.isLocalFile() else ""
                if not path and not url.scheme():
                    candidate = Path(tag.get("src", ""))
                    if candidate.is_absolute():
                        path = str(candidate)
                    elif candidate.parts and candidate.parts[0] == "images":
                        path = str(self.images_dir.parent / candidate)
                image = QImage(path) if path else QImage()
                if image.isNull():
                    tag.decompose()
                else:
                    self.images_dir.mkdir(parents=True, exist_ok=True)
                    target = self.images_dir / (uuid.uuid4().hex + ".png")
                    if not image.save(str(target), "PNG"):
                        raise OSError("Could not save pasted image")
                    tag["src"] = QUrl.fromLocalFile(str(target)).toString()
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertHtml(str(soup))
            self._remove_legacy_checklists()
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return
        super().insertFromMimeData(source)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, t("sticky.insert.image"), "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            try:
                self.add_image(QImage(path))
            except OSError:
                QMessageBox.warning(self, t("sticky.error"), t("sticky.imageFailed"))

    def add_format_menu(self, menu):
        formats = menu.addMenu(t("sticky.format"))
        for key, prop in (("bold", "weight"), ("italic", "italic"), ("underline", "underline"), ("strike", "strike")):
            formats.addAction(t("sticky.format." + key), lambda checked=False, p=prop: self._format(p))
        formats.addAction(t("sticky.format.font"), self._choose_font)
        formats.addAction(t("sticky.format.color"), self._choose_text_color)
        for key, alignment in (("left", Qt.AlignmentFlag.AlignLeft), ("center", Qt.AlignmentFlag.AlignHCenter), ("right", Qt.AlignmentFlag.AlignRight)):
            formats.addAction(t("sticky.format." + key), lambda checked=False, a=alignment: self.setAlignment(a))
        formats.addAction(t("sticky.format.clear"), lambda: self.textCursor().setCharFormat(QTextCharFormat()))
        formats.setEnabled(not self.isReadOnly())
        return formats

    def _format(self, prop):
        current = self.currentCharFormat()
        fmt = QTextCharFormat()
        if prop == "weight":
            fmt.setFontWeight(QFont.Weight.Normal if current.fontWeight() >= QFont.Weight.Bold else QFont.Weight.Bold)
        elif prop == "italic":
            fmt.setFontItalic(not current.fontItalic())
        elif prop == "underline":
            fmt.setFontUnderline(not current.fontUnderline())
        else:
            fmt.setFontStrikeOut(not current.fontStrikeOut())
        self.mergeCurrentCharFormat(fmt)

    def _choose_font(self):
        font, ok = QFontDialog.getFont(self.currentFont(), self)
        if ok:
            self.setCurrentFont(font)

    def _choose_text_color(self):
        color = QColorDialog.getColor(self.textColor(), self)
        if color.isValid():
            self.setTextColor(color)

    def add_insert_menu(self, menu):
        from datetime import datetime
        insert = menu.addMenu(t("sticky.insert"))
        insert.addAction(t("sticky.insert.image"), self.choose_image)
        insert.addAction(t("sticky.insert.divider"), lambda: self.textCursor().insertHtml("<hr>"))
        insert.addAction(t("sticky.insert.date"), lambda: self.insertPlainText(datetime.now().strftime("%Y-%m-%d %H:%M")))
        insert.setEnabled(not self.isReadOnly())
        return insert

    def create_edit_menu(self):
        menu = self.standard_edit_menu()
        self.add_insert_menu(menu)
        self.add_format_menu(menu)
        return menu

    def standard_edit_menu(self):
        menu = QMenu(self)
        from app.ui.style import get_current_theme, menu_stylesheet
        menu.setStyleSheet(menu_stylesheet(get_current_theme()))
        selected = self.textCursor().hasSelection()
        for key, callback, enabled in (
            ("undo", self.undo, self.document().isUndoAvailable() and not self.isReadOnly()),
            ("redo", self.redo, self.document().isRedoAvailable() and not self.isReadOnly()),
            ("cut", self.cut, selected and not self.isReadOnly()),
            ("copy", self.copy, selected),
            ("paste", self.paste, self.canPaste() and not self.isReadOnly()),
            ("selectAll", self.selectAll, not self.document().isEmpty()),
        ):
            if key in ("cut", "selectAll"):
                menu.addSeparator()
            action = menu.addAction(t("edit." + key), callback)
            action.setEnabled(enabled)
        return menu

    def focusInEvent(self, event):
        self.editing_started.emit()
        super().focusInEvent(event)

    def contextMenuEvent(self, event):
        menu = self.create_edit_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()
