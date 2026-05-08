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
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.note_manager import NoteManager
from app.core.db_manager import DatabaseManager


def test_note_creation():
    """测试新建笔记内容为空"""
    print("测试 1: 新建笔记内容为空")
    print("-" * 50)

    # Initialize managers
    db = DatabaseManager()
    notes = NoteManager(db)

    # Create a new note with default parameters
    note = notes.create()

    print(f"笔记 ID: {note.id}")
    print(f"笔记标题: '{note.title}'")
    print(f"笔记内容: '{note.content}'")
    print(f"内容长度: {len(note.content)}")

    # Verify content is empty
    assert note.content == "", f"错误：新笔记内容不为空，实际内容为: '{note.content}'"
    assert note.title == "新笔记", f"错误：新笔记标题不正确，实际标题为: '{note.title}'"

    print("✓ 测试通过：新笔记内容为空字符串")
    print()

    # Clean up
    notes.delete(note.id)
    notes.purge(note.id)

    return True


def test_sticky_note_menu():
    """测试浮窗右键菜单代码"""
    print("测试 2: 浮窗右键菜单代码检查")
    print("-" * 50)

    # Read the sticky note window file
    sticky_file = Path(__file__).parent / "app" / "ui" / "sticky_note_window.py"
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

    print("检查菜单项...")
    for item in required_items:
        if item in content:
            print(f"  ✓ 找到菜单项: {item}")
        else:
            print(f"  ✗ 缺少菜单项: {item}")
            return False

    print("\n检查方法调用...")
    for method in required_methods:
        if method in content:
            print(f"  ✓ 找到方法: {method}")
        else:
            print(f"  ✗ 缺少方法: {method}")
            return False

    print("\n检查状态检查...")
    for check in required_checks:
        if check in content:
            print(f"  ✓ 找到状态检查: {check}")
        else:
            print(f"  ✗ 缺少状态检查: {check}")
            return False

    print("\n✓ 测试通过：浮窗右键菜单代码完整")
    print()

    return True


def main():
    print("=" * 50)
    print("PyQt6 AI 桌面助手 - 修复验证测试")
    print("=" * 50)
    print()

    try:
        # Test 1: Note creation
        if not test_note_creation():
            print("✗ 测试失败：笔记创建")
            return 1

        # Test 2: Sticky note menu
        if not test_sticky_note_menu():
            print("✗ 测试失败：浮窗右键菜单")
            return 1

        print("=" * 50)
        print("✓ 所有测试通过！")
        print("=" * 50)
        return 0

    except Exception as e:
        print(f"\n✗ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
