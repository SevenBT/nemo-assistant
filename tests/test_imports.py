"""快速冒烟测试：验证关键 UI 组件可正常导入。"""

import sys
import io
from pathlib import Path

# 设置 stdout 为 UTF-8 编码（独立运行时；pytest 下保持其捕获流）
sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_imports():
    """关键组件应能无异常导入（导入失败应让测试失败，而非被吞掉）。"""
    from app.ui.components.markdown_editor import MarkdownEditor  # noqa: F401
    from app.ui.components.horizontal_tag_bar import HorizontalTagBar  # noqa: F401
    from app.ui.notes_dialog import NotesPanel  # noqa: F401


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v"]))
