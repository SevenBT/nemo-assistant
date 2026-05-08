"""
测试预设管理 UI
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from app.core.preset_manager import PresetManager
from app.ui.preset_manager_dialog import PresetManagerDialog


def main():
    app = QApplication(sys.argv)

    # 创建预设管理器
    mgr = PresetManager()

    # 打开预设管理对话框
    dialog = PresetManagerDialog(mgr)
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
