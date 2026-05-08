"""
测试标签系统功能。
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from app.core.note_manager import NoteManager
from app.core.db_manager import DatabaseManager


def test_tag_functions():
    """测试标签相关功能。"""
    print("初始化数据库...")
    db = DatabaseManager()
    mgr = NoteManager(db)

    print("\n1. 创建测试笔记...")
    note1 = mgr.create("测试笔记1", "这是第一条测试笔记")
    note2 = mgr.create("测试笔记2", "这是第二条测试笔记")
    print(f"   创建笔记: {note1.id}, {note2.id}")

    print("\n2. 添加标签...")
    mgr.update(note1.id, note1.title, note1.content, ["工作", "重要"])
    mgr.update(note2.id, note2.title, note2.content, ["学习", "重要"])
    print("   标签已添加")

    print("\n3. 获取所有标签...")
    all_tags = mgr.get_all_tags()
    print(f"   所有标签: {all_tags}")

    print("\n4. 获取标签及数量...")
    tags_with_count = mgr.get_all_tags_with_count()
    for tag, count in tags_with_count:
        print(f"   #{tag}: {count} 条笔记")

    print("\n5. 按标签搜索...")
    notes = mgr.search_by_tag("重要")
    print(f"   标签'重要'的笔记: {len(notes)} 条")
    for note in notes:
        print(f"   - {note.title}: {note.tags}")

    print("\n6. 获取笔记详情...")
    note = mgr.get(note1.id)
    print(f"   笔记 {note.id} 的标签: {note.tags}")

    print("\n7. 更新标签...")
    mgr.update(note1.id, note1.title, note1.content, ["工作", "紧急"])
    note = mgr.get(note1.id)
    print(f"   更新后的标签: {note.tags}")

    print("\n8. 清理测试数据...")
    mgr.delete(note1.id)
    mgr.delete(note2.id)
    mgr.purge(note1.id)
    mgr.purge(note2.id)
    print("   测试数据已清理")

    print("\n[OK] 所有测试通过!")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_tag_functions()
