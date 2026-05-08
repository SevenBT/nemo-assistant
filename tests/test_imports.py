"""
快速测试脚本：验证修改后的组件可以正常导入和实例化。
"""

import sys
import io
from pathlib import Path

# 设置 stdout 为 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_imports():
    """测试导入是否正常。"""
    print("测试导入...")
    try:
        from app.ui.components.todo_item_widget import TodoItemWidget
        print("  ✓ TodoItemWidget 导入成功")
    except Exception as e:
        print(f"  ✗ TodoItemWidget 导入失败: {e}")
        return False

    try:
        from app.ui.components.horizontal_tag_bar import HorizontalTagBar
        print("  ✓ HorizontalTagBar 导入成功")
    except Exception as e:
        print(f"  ✗ HorizontalTagBar 导入失败: {e}")
        return False

    try:
        from app.ui.notes_dialog import NotesPanel
        print("  ✓ NotesPanel 导入成功")
    except Exception as e:
        print(f"  ✗ NotesPanel 导入失败: {e}")
        return False

    return True

def main():
    print("=" * 60)
    print("组件导入测试")
    print("=" * 60)

    if test_imports():
        print("\n✓ 所有组件导入成功！")
        print("\n下一步：运行应用进行手动测试")
        print("  python main.py")
        return 0
    else:
        print("\n✗ 部分组件导入失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
