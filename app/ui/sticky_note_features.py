"""Menus, display state and desktop interactions for a sticky window."""
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QColorDialog, QFileDialog, QInputDialog, QMenu, QMessageBox, QPushButton

from app.core.sticky_store import DEFAULT_STICKY_SETTINGS
from app.i18n import t


class StickyNoteFeatures:
    def _set_pref(self, key, value):
        self._save_position()
        self._settings[key] = value
        if self._note_mgr:
            self._settings = self._note_mgr.set_sticky_settings(self._note_id, **{key: value})
        self._apply_settings()
        self.settings_changed.emit(self._note_id)

    def _apply_settings(self):
        from app.ui.sticky_note_window import _TITLE_H, _ink_colors, _note_palette
        self._applying_settings = True
        try:
            palette = _note_palette()
            key = self._settings["color"]
            names = ("yellow", "green", "blue", "pink", "purple", "peach")
            color = palette[names.index(key)] if key in names else palette[(self._note_id or 1) % len(palette)] if key == "auto" else key
            if not QColor(color).isValid():
                color = palette[0]
            self._color = color
            ink, secondary, muted = _ink_colors(color)
            self._container._color = color
            self._container.update()
            self._title_bar.refresh_colors(color)
            self._content_edit.setStyleSheet(f"QTextEdit{{background:transparent;color:{ink};border:none;padding:8px 10px;font-size:{self._settings['font_size']}px}}")
            self._content_edit.apply_text_color("#f3f3f3" if QColor(color).lightness() < 128 else "#252525")
            self._content_edit.setReadOnly(self._settings["locked"])
            self._content_edit.hide_completed(self._settings["hide_completed"])
            was_visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._settings["top"])
            if was_visible:
                self.show()
            self.setWindowOpacity(self._settings["opacity"] / 100)
            self.setMinimumHeight(_TITLE_H if self._settings["collapsed"] else 120)
            self._content_edit.setVisible(not self._settings["collapsed"])
            self.resize(self._settings["width"], _TITLE_H if self._settings["collapsed"] else self._settings["height"])
            if not self._settings["edge"]:
                self._edge_restore()
            self.refresh_reminder()
        finally:
            self._applying_settings = False

    def refresh_reminder(self):
        reminder = self._note_mgr.get_sticky_reminder(self._note_id) if self._note_mgr else None
        active = reminder and reminder["enabled"]
        self._reminder_label.setVisible(bool(active) and not self._settings["collapsed"])
        if active:
            when = datetime.fromisoformat(reminder["next_at"]).astimezone().strftime("%m-%d %H:%M")
            self._reminder_label.setText(when)
            from app.ui.sticky_note_window import _ink_colors
            ink = _ink_colors(self._color)[0]
            self._reminder_label.setStyleSheet(f"color:{ink};background:transparent;border:none;padding:3px")

    def rename_note(self):
        if self._settings["locked"]:
            return
        if self._flush() is False:
            return
        title, ok = QInputDialog.getText(self, t("sticky.rename"), t("sticky.renamePrompt"), text=self._title)
        if ok and title.strip() and self._note_mgr:
            note = self._note_mgr.get(self._note_id)
            self._note_mgr.update(note.id, title.strip(), note.content,
                                  priority=note.priority, due_date=note.due_date, recurrence=note.recurrence)
            self._title = title.strip()
            self._title_bar.set_title(self._title)
            self.content_changed.emit(note.id, self._title, note.content)

    def hide_note(self):
        if self._flush() is False:
            return
        self._edge_restore()
        self._save_position()
        self._settings["visible"] = False
        if self._note_mgr:
            self._note_mgr.set_sticky_settings(self._note_id, visible=False)
        self.hide()
        self.settings_changed.emit(self._note_id)

    def show_note(self):
        if self._note_mgr and not self._note_mgr.get(self._note_id):
            return
        self._edge_restore()
        self._settings["visible"] = True
        if self._note_mgr:
            self._note_mgr.set_sticky_settings(self._note_id, visible=True)
        self.show()
        self.raise_()
        self.settings_changed.emit(self._note_id)

    def dispose(self):
        if self._flush() is False:
            return False
        self._disposing = True
        return self.close()

    def create_note_menu(self, editing=False):
        menu = self._content_edit.standard_edit_menu() if editing else QMenu(self)
        from app.ui.style import get_current_theme, menu_stylesheet
        menu.setStyleSheet(menu_stylesheet(get_current_theme()))
        if editing:
            menu.addSeparator()
        new = menu.addMenu(t("sticky.new"))
        new.addAction(t("sticky.empty"), lambda: self.new_requested.emit("empty"))
        new.addAction(t("sticky.fromClipboard"), lambda: self.new_requested.emit("clipboard"))
        templates = new.addMenu(t("sticky.template"))
        for key in ("today", "meeting", "shopping"):
            templates.addAction(t("sticky.template." + key), lambda checked=False, k=key: self.new_requested.emit("template:" + k))
        if self._note_mgr:
            for record in self._note_mgr.get_sticky_templates():
                templates.addAction(record["name"], lambda checked=False, key=record["id"]: self.new_requested.emit("saved:" + str(key)))
        existing = self._note_mgr.get_sticky_reminder(self._note_id) if self._note_mgr else None
        menu.addAction(t("sticky.manageReminder" if existing else "sticky.reminder"), lambda: self.reminder_requested.emit(self._note_id))
        menu.addSeparator()
        self._content_edit.add_insert_menu(menu)
        self._content_edit.add_format_menu(menu)
        appearance = menu.addMenu(t("sticky.appearance"))
        for key in ("auto", "yellow", "green", "blue", "pink", "purple", "peach"):
            action = appearance.addAction(t("sticky.color." + key), lambda checked=False, k=key: self._set_pref("color", k))
            action.setCheckable(True)
            action.setChecked(self._settings["color"] == key)
        appearance.addAction(t("sticky.color.custom"), self._choose_paper)
        opacity = appearance.addMenu(t("sticky.opacity"))
        for value in (100, 90, 80, 70):
            action = opacity.addAction(str(value) + "%", lambda checked=False, v=value: self._set_pref("opacity", v))
            action.setCheckable(True)
            action.setChecked(value == self._settings["opacity"])
        appearance.addAction(t("sticky.defaultSize"), self._default_size)
        appearance.addAction(t("sticky.resetAppearance"), self._reset_appearance)
        display = menu.addMenu(t("sticky.display"))
        for key, text in (("top", "top"), ("collapsed", "collapse"), ("locked", "lock"), ("edge", "edge"), ("hide_completed", "hideCompleted")):
            action = display.addAction(t("sticky." + text))
            action.setCheckable(True)
            action.setChecked(self._settings[key])
            action.triggered.connect(lambda checked, k=key: self._set_pref(k, checked))
        menu.addSeparator()
        menu.addAction(t("sticky.manager"), self.manager_requested.emit)
        more = menu.addMenu(t("sticky.more"))
        more.addAction(t("sticky.rename"), self.rename_note)
        more.addAction(t("sticky.menu.copyContent"), lambda: QApplication.clipboard().setText(self._content_edit.plain_text()))
        more.addAction(t("sticky.duplicate"), lambda: self._request_duplicate())
        more.addAction(t("sticky.exportTxt"), lambda: self._export(False))
        more.addAction(t("sticky.exportPng"), lambda: self._export(True))
        more.addAction(t("sticky.saveTemplate"), self._save_template)
        menu.addSeparator()
        menu.addAction(t("sticky.menu.hide"), self.hide_note)
        menu.addAction(t("sticky.trash"), self._on_delete_requested)
        return menu

    def show_note_menu(self, pos, editing=False):
        menu = self.create_note_menu(editing)
        self._menu_open = True
        self._edge_timer.stop()
        try:
            menu.exec(pos)
        finally:
            self._menu_open = False
            menu.deleteLater()

    def _show_context_menu(self, pos):
        self.show_note_menu(self._content_edit.mapToGlobal(pos), editing=True)

    def _request_duplicate(self):
        if self._flush() is not False:
            self.duplicate_requested.emit(self._note_id)

    def _choose_paper(self):
        color = QColorDialog.getColor(QColor(self._color), self)
        if color.isValid():
            self._set_pref("color", color.name())

    def _default_size(self):
        self._settings.update(width=280, height=260)
        if self._note_mgr:
            self._note_mgr.set_sticky_settings(self._note_id, width=280, height=260)
        self._apply_settings()

    def _reset_appearance(self):
        for key in ("color", "opacity", "font_family", "font_size"):
            self._settings[key] = DEFAULT_STICKY_SETTINGS[key]
        if self._note_mgr:
            self._note_mgr.set_sticky_settings(self._note_id, **self._settings)
        self._apply_settings()

    def _save_template(self):
        name, ok = QInputDialog.getText(self, t("sticky.saveTemplate"), t("sticky.templateName"))
        if ok and name.strip() and self._note_mgr:
            from app.ui.components.sticky_editor import StickyEditor
            editor = StickyEditor()
            editor.load_content(self._content_edit.toHtml())
            editor.reset_completed()
            self._note_mgr.save_sticky_template(name.strip(), editor.toHtml(), self._settings)
            editor.deleteLater()

    def _export(self, image):
        name = "".join(c if c not in '<>:"/\\|?*' else '_' for c in self._title)[:60] or "sticky"
        suffix = ".png" if image else ".txt"
        path, _ = QFileDialog.getSaveFileName(self, t("sticky.exportPng" if image else "sticky.exportTxt"), name + suffix,
                                            "PNG (*.png)" if image else "Text (*.txt)")
        if not path:
            return
        try:
            if image:
                # Render the full document, including text beyond the viewport.
                doc = self._content_edit.document().clone()
                block = doc.begin()
                while block.isValid():
                    block.setVisible(True)
                    block = block.next()
                doc.setTextWidth(max(180, self.width() - 32))
                size = doc.size()
                height = int(size.height()) + 68
                if height > 30000 or self.width() * height > 40000000:
                    raise ValueError("Image too large; export as text instead")
                output = QImage(self.width(), max(100, height), QImage.Format.Format_ARGB32)
                output.fill(QColor(self._color))
                painter = QPainter(output)
                try:
                    painter.setPen(QColor("#f3f3f3" if QColor(self._color).lightness() < 128 else "#252525"))
                    painter.drawText(QRect(16, 8, self.width() - 32, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)
                    painter.translate(16, 48)
                    from PyQt6.QtGui import QAbstractTextDocumentLayout
                    context = QAbstractTextDocumentLayout.PaintContext()
                    from PyQt6.QtGui import QPalette
                    context.palette.setColor(QPalette.ColorRole.Text, painter.pen().color())
                    doc.documentLayout().draw(painter, context)
                finally:
                    painter.end()
                    doc.deleteLater()
                if not output.save(path, "PNG"):
                    raise OSError("Image save failed")
            else:
                Path(path).write_text(self._title + "\n\n" + self._content_edit.plain_text(), encoding="utf-8")
        except (OSError, ValueError):
            QMessageBox.warning(self, t("sticky.exportFailed"), t("sticky.exportFailed"))

    def _edge_restore(self):
        if self._edge_geometry is None:
            return
        geo = self._edge_geometry
        self._edge_geometry = None
        self._edge_mutating = True
        self.setGeometry(geo)
        self._edge_mutating = False

    def _edge_hide(self):
        if (not self._settings["edge"] or not self.isVisible() or self._edge_geometry is not None
                or self._menu_open or QApplication.activePopupWidget() or QApplication.activeModalWidget()
                or self._content_edit.hasFocus() or self._resize_active or QApplication.mouseButtons()):
            return
        geo = self.geometry()
        screen = self.screen()
        if screen is None:
            return
        work = screen.availableGeometry()
        # Adjacent monitor seams are never hiding edges.
        others = [s.geometry() for s in QApplication.screens() if s is not screen]
        checks = (("top", abs(geo.top() - work.top()) <= 8, QPoint(geo.center().x(), screen.geometry().top() - 1)),
                  ("left", abs(geo.left() - work.left()) <= 8, QPoint(screen.geometry().left() - 1, geo.center().y())),
                  ("right", abs(geo.right() - work.right()) <= 8, QPoint(screen.geometry().right() + 1, geo.center().y())))
        side = next((key for key, near, point in checks if near and not any(rect.contains(point) for rect in others)), None)
        if not side:
            return
        self._edge_geometry = QRect(geo)
        self._edge_side = side
        if side == "top":
            geo.moveTop(work.top() - geo.height() + 9)
        elif side == "left":
            geo.moveLeft(work.left() - geo.width() + 9)
        else:
            geo.moveLeft(work.right() - 8)
        self._edge_mutating = True
        self.setGeometry(geo)
        self._edge_mutating = False

    def enterEvent(self, event):
        self._edge_timer.stop()
        self._edge_restore()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._edge_timer.start()
        super().leaveEvent(event)

    def hideEvent(self, event):
        if hasattr(self, "_save_timer") and not self._applying_settings:
            self._flush()
        if hasattr(self, "_edge_timer"):
            self._edge_timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_pos_timer") and not self._applying_settings and not self._edge_mutating:
            self._pos_timer.start()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and hasattr(self, "_save_timer") and not self.isActiveWindow():
            self._flush()
            self._edge_timer.start()
