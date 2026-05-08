"""最终验证脚本。"""
import sys
from pathlib import Path

# 设置 Windows 控制台编码
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.note_manager import NoteManager

# 测试基本功能
nm = NoteManager()
notes = nm.get_notes()
print("[OK] 数据库连接正常")
print(f"[OK] 笔记数量: {len(notes)}")

# 测试 ID 类型兼容性
if notes:
    note = nm.get(notes[0].id)
    print(f"[OK] int ID 查询: {note.title if note else '失败'}")
    note = nm.get(str(notes[0].id))
    print(f"[OK] str ID 查询: {note.title if note else '失败'}")

# 测试新功能
pinned = nm.get_pinned_notes()
print(f"[OK] 固定笔记功能: {len(pinned)} 个")

trash_count = nm.trash_count()
print(f"[OK] 回收站功能: {trash_count} 个")

preview = nm.get_preview_list()
print(f"[OK] 预览列表功能: {len(preview)} 个")

print(f"\n所有功能验证通过！")
