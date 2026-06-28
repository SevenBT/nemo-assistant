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

from app.core.note_manager import NoteManager
from app.core.db_manager import DatabaseManager


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


def test_sticky_note_menu():
    """浮窗右键菜单源码应包含完整的文本编辑动作。"""
    # 源文件在项目根的 app/ui 下（此前误用 tests/app 相对路径导致找不到文件）
    sticky_file = _PROJECT_ROOT / "app" / "ui" / "sticky_note_window.py"
    content = sticky_file.read_text(encoding="utf-8")

    # Check for required menu items
    required_items = [
        "撤销",
        "重做",
        "剪切",
        "复制",
        "粘贴",
        "全选",
    ]

    # Check for required methods
    required_methods = [
        "undo()",
        "redo()",
        "cut()",
        "copy()",
        "paste()",
        "selectAll()",
    ]

    # Check for state checks
    required_checks = [
        "isUndoAvailable()",
        "isRedoAvailable()",
        "hasSelection()",
        "canPaste()",
        "isEmpty()",
    ]

    for item in required_items:
        assert item in content, f"缺少菜单项: {item}"

    for method in required_methods:
        assert method in content, f"缺少方法调用: {method}"

    for check in required_checks:
        assert check in content, f"缺少状态检查: {check}"


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))
