"""
测试 SQLite NoteManager 的所有功能。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.note_manager import NoteManager


def test_note_manager():
    """测试笔记管理器的所有功能。"""
    nm = NoteManager()

    print("=" * 50)
    print("测试 NoteManager")
    print("=" * 50)

    # 1. 获取所有笔记
    print("\n1. 获取所有笔记")
    notes = nm.get_notes()
    print(f"   笔记数量: {len(notes)}")
    for note in notes:
        print(f"   - ID: {note.id} ({type(note.id).__name__}), 标题: {note.title}")

    # 2. 创建新笔记
    print("\n2. 创建新笔记")
    new_note = nm.create("测试笔记", "这是测试内容")
    print(f"   创建成功: ID={new_note.id}, 标题={new_note.title}")

    # 3. 获取单个笔记（测试 str 和 int 兼容性）
    print("\n3. 获取单个笔记")
    note = nm.get(new_note.id)
    print(f"   使用 int ID: {note.title if note else 'None'}")
    note = nm.get(str(new_note.id))
    print(f"   使用 str ID: {note.title if note else 'None'}")

    # 4. 更新笔记
    print("\n4. 更新笔记")
    updated = nm.update(new_note.id, "更新后的标题", "更新后的内容")
    print(f"   更新成功: {updated.title if updated else 'None'}")

    # 5. 删除笔记（移入回收站）
    print("\n5. 删除笔记")
    nm.delete(new_note.id)
    print(f"   回收站数量: {nm.trash_count()}")

    # 6. 获取回收站
    print("\n6. 获取回收站")
    trash = nm.get_trash()
    for note in trash:
        print(f"   - ID: {note.id}, 标题: {note.title}")

    # 7. 恢复笔记
    print("\n7. 恢复笔记")
    restored = nm.restore(new_note.id)
    print(f"   恢复成功: {restored}")
    print(f"   回收站数量: {nm.trash_count()}")

    # 8. 测试固定功能
    print("\n8. 测试固定功能")
    nm.pin_note(new_note.id, 100, 200)
    pinned = nm.get_pinned_notes()
    print(f"   固定笔记数量: {len(pinned)}")
    if pinned:
        print(f"   位置: ({pinned[0].pin_position_x}, {pinned[0].pin_position_y})")

    # 9. 更新固定位置
    print("\n9. 更新固定位置")
    nm.update_pin_position(new_note.id, 300, 400)
    note = nm.get(new_note.id)
    print(f"   新位置: ({note.pin_position_x}, {note.pin_position_y})")

    # 10. 取消固定
    print("\n10. 取消固定")
    nm.unpin_note(new_note.id)
    pinned = nm.get_pinned_notes()
    print(f"   固定笔记数量: {len(pinned)}")

    # 11. 永久删除
    print("\n11. 永久删除")
    nm.delete(new_note.id)
    nm.purge(new_note.id)
    print(f"   回收站数量: {nm.trash_count()}")

    # 12. 获取预览列表
    print("\n12. 获取预览列表")
    preview = nm.get_preview_list(max_preview=20)
    print(f"   预览列表数量: {len(preview)}")
    if preview:
        print(f"   第一个: {preview[0]}")

    print("\n" + "=" * 50)
    print("所有测试完成！")
    print("=" * 50)


if __name__ == "__main__":
    test_note_manager()
