"""
快速测试待办功能的启动脚本。

创建一些测试数据并启动主窗口。
"""
import sys
from datetime import datetime, timedelta
from PyQt6.QtWidgets import QApplication

from app.core.config import ConfigManager
from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from app.core.scheduler import Scheduler
from app.ui.main_window import MainWindow


def create_test_todos(mgr: NoteManager):
    """创建测试待办数据。"""
    # 待办 1：高优先级，3天后到期
    todo1 = mgr.create(title='完成季度报告', content='需要完成 Q1 季度报告，包含数据分析', note_type='todo')
    mgr.update(
        todo1.id,
        '完成季度报告',
        '需要完成 Q1 季度报告，包含数据分析和图表',
        tags=['工作', '重要'],
        priority='P1',
        due_date=(datetime.now() + timedelta(days=3)).isoformat(),
        recurrence='每月'
    )

    # 待办 2：中优先级，2小时后到期
    todo2 = mgr.create(title='买菜', content='晚餐食材', note_type='todo')
    mgr.update(
        todo2.id,
        '买菜',
        '晚餐食材：西红柿、鸡蛋、青菜',
        tags=['生活'],
        priority='P2',
        due_date=(datetime.now() + timedelta(hours=2)).isoformat()
    )

    # 待办 3：低优先级，无截止日期
    todo3 = mgr.create(title='学习 Python', content='', note_type='todo')
    mgr.update(
        todo3.id,
        '学习 Python',
        '学习 Python 高级特性：装饰器、生成器、异步编程',
        tags=['学习'],
        priority='P3'
    )

    # 待办 4：已过期
    todo4 = mgr.create(title='回复邮件', content='', note_type='todo')
    mgr.update(
        todo4.id,
        '回复邮件',
        '回复客户的项目咨询邮件',
        tags=['工作'],
        priority='P1',
        due_date=(datetime.now() - timedelta(hours=1)).isoformat()
    )

    print(f'创建了 4 个测试待办')


def main():
    app = QApplication(sys.argv)

    # 初始化
    config = ConfigManager()
    db = DatabaseManager()
    note_mgr = NoteManager(db)
    scheduler = Scheduler()

    # 创建测试数据（仅在首次运行时）
    todos = note_mgr.get_notes_by_type('todo')
    if len(todos) == 0:
        print('首次运行，创建测试数据...')
        create_test_todos(note_mgr)

    # 启动主窗口
    window = MainWindow(config, note_mgr, scheduler)
    window.show()

    # 切换到待办页面
    window._switch_view(2)  # index 2 = 待办

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
