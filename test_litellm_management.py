"""
测试 LiteLLM 模型管理功能

运行方式：
python test_litellm_management.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from app.core.config import ConfigManager
from app.ui.settings_dialog import SettingsDialog


def main():
    app = QApplication(sys.argv)

    # 创建配置管理器
    config = ConfigManager()

    # 打开设置对话框
    dialog = SettingsDialog(config)
    dialog.exec()

    sys.exit(0)


if __name__ == "__main__":
    main()
