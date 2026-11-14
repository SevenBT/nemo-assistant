#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：验证笔记创建和浮窗右键菜单修复

测试内容：
1. 新建笔记内容为空
2. 浮窗右键菜单包含文本编辑操作
"""

import sys
import io
import tempfile
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = sys.stderr if "pytest" in sys.modules else io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

_PROJECT_ROOT = Path(__file__).parent.parent

from app.storage.note_manager import NoteManager
from app.storage.db_manager import DatabaseManager


def test_note_creation():
    """新建笔记内容应为空字符串、标题为默认值。"""
    # 使用临时数据库，避免污染真实 notes.db
    # ignore_cleanup_errors: Windows 上 SQLite 文件句柄释放有延迟，避免清理时报 PermissionError
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = DatabaseManager(Path(tmp) / "notes.db")
        notes = NoteManager(db)

        note = notes.create()

        assert note.content == "", f"新笔记内容应为空，实际: '{note.content}'"
        assert note.title == "新笔记", f"新笔记标题不正确，实际: '{note.title}'"


def test_sticky_note_menu(qtbot):
    from app.ui.components.sticky_editor import StickyEditor
    from app.i18n import t
    editor = StickyEditor()
    qtbot.addWidget(editor)
    editor.setPlainText("selected text")
    editor.selectAll()
    menu = editor.standard_edit_menu()
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
    assert all(t("edit." + key) in actions for key in ("undo", "redo", "cut", "copy", "paste", "selectAll"))
    assert actions[t("edit.copy")].isEnabled()
    assert actions[t("edit.cut")].isEnabled()
    actions[t("edit.cut")].trigger()
    assert editor.toPlainText() == ""
    editor.undo()
    assert editor.toPlainText() == "selected text"
    editor.setReadOnly(True)
    locked = editor.standard_edit_menu()
    cut = next(action for action in locked.actions() if action.text() == t("edit.cut"))
    assert not cut.isEnabled()
    menu.deleteLater()
    locked.deleteLater()


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))
