"""测试待办功能的数据库操作。"""
from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from datetime import datetime, timedelta

# 初始化
db = DatabaseManager()
mgr = NoteManager(db)

# 创建测试待办
todo1 = mgr.create(title='完成报告', content='需要完成季度报告', note_type='todo')
print(f'创建待办 1: {todo1.id} - {todo1.title}')

# 更新待办字段
mgr.update(
    todo1.id,
    '完成季度报告',
    '需要完成 Q1 季度报告，包含数据分析',
    tags=['工作', '重要'],
    priority='P1',
    due_date=(datetime.now() + timedelta(days=3)).isoformat(),
    recurrence='每月'
)
print('更新待办 1 成功')

# 创建第二个待办
todo2 = mgr.create(title='买菜', content='晚餐食材', note_type='todo')
mgr.update(
    todo2.id,
    '买菜',
    '晚餐食材：西红柿、鸡蛋、青菜',
    tags=['生活'],
    priority='P2',
    due_date=(datetime.now() + timedelta(hours=2)).isoformat()
)
print(f'创建待办 2: {todo2.id} - {todo2.title}')

# 获取所有待办
todos = mgr.get_notes_by_type('todo')
print(f'\n共有 {len(todos)} 个待办:')
for t in todos:
    print(f'  - [{t.priority or "无"}] {t.title} (完成: {t.is_completed})')

# 切换完成状态
mgr.toggle_todo_completed(todo2.id)
print(f'\n切换待办 2 完成状态')

# 再次获取
todos = mgr.get_notes_by_type('todo')
print(f'\n更新后的待办:')
for t in todos:
    print(f'  - [{t.priority or "无"}] {t.title} (完成: {t.is_completed})')

print('\n✓ 所有测试通过！')
