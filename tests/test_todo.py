"""
测试待办功能的简单脚本。
"""
import sys
from PyQt6.QtWidgets import QApplication
from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager
from app.ui.todo_panel import TodoPanel


def main():
    app = QApplication(sys.argv)

    # 初始化数据库和笔记管理器
    db = DatabaseManager()
    note_mgr = NoteManager(db)

    # 创建待办面板
    panel = TodoPanel(note_mgr)
    panel.setWindowTitle("待办测试")
    panel.resize(800, 600)
    panel.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
