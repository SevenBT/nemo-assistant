"""
测试标签 UI 组件。
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from app.ui.components.tag_input import TagInput
from app.ui.components.tag_filter_panel import TagFilterPanel


def test_tag_input():
    """测试标签输入组件。"""
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("标签输入测试")
    window.resize(600, 200)

    layout = QVBoxLayout(window)

    # 创建标签输入组件
    tag_input = TagInput()
    tag_input.set_all_tags(["工作", "学习", "重要", "紧急", "个人"])
    tag_input.set_tags(["工作", "重要"])

    def on_tags_changed(tags):
        print(f"标签变化: {tags}")

    tag_input.tags_changed.connect(on_tags_changed)
    layout.addWidget(tag_input)

    # 创建标签过滤面板
    tag_filter = TagFilterPanel()
    tag_filter.set_tags([
        ("工作", 5),
        ("学习", 3),
        ("重要", 8),
        ("紧急", 2),
    ])

    def on_tag_selected(tag):
        print(f"选中标签: {tag if tag else '全部笔记'}")

    tag_filter.tag_selected.connect(on_tag_selected)
    layout.addWidget(tag_filter)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    test_tag_input()
