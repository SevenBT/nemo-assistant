"""测试标签 UI 组件。"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from PyQt6.QtWidgets import QApplication
from app.ui.components.tag_input import TagButton, TagInput
from app.ui.components.tag_filter_panel import TagFilterPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_tag_button_construction(qapp):
    """TagButton 子类化 qfluentwidgets 的 singledispatch 构造器不应崩溃。"""
    btn = TagButton("工作 ✕", "工作")
    assert btn.tag_name == "工作"
    assert "工作" in btn.text()


def test_tag_input_set_tags(qapp):
    """set_tags 应渲染 pill 按钮且不抛异常。"""
    tag_input = TagInput()
    tag_input.set_all_tags(["工作", "学习", "重要", "紧急", "个人"])
    tag_input.set_tags(["工作", "重要"])
    assert tag_input._tags == ["工作", "重要"]


def test_tag_input_emits_change(qapp):
    """交互式添加标签应发出 tags_changed 信号（set_tags 程序化设置刻意不发，避免回环）。"""
    tag_input = TagInput()
    received = []
    tag_input.tags_changed.connect(received.append)
    tag_input._add_tag("工作")
    assert received and received[-1] == ["工作"]


def test_tag_filter_panel_set_tags(qapp):
    """TagFilterPanel 设置带计数的标签不应崩溃。"""
    panel = TagFilterPanel()
    panel.set_tags([("工作", 5), ("学习", 3), ("重要", 8)])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
