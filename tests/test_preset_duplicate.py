"""
测试预设复制功能
"""
import sys
import os
from pathlib import Path

# 设置控制台编码为 UTF-8
if sys.platform == "win32":
    os.system("chcp 65001 > nul")

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.preset_manager import PresetManager


def test_duplicate():
    """测试复制功能"""
    mgr = PresetManager()

    print("=== 测试预设复制功能 ===\n")

    # 1. 获取所有预设
    all_presets = mgr.get_all()
    print(f"当前预设数量: {len(all_presets)}")
    for p in all_presets:
        print(f"  - {p.name} (ID: {p.id}, 内置: {p.is_builtin})")

    # 2. 复制内置预设
    print("\n--- 复制内置预设「默认助手」---")
    default_preset = mgr.get("default")
    if default_preset:
        new_preset = mgr.duplicate("default", "我的助手")
        print(f"[OK] 复制成功: {new_preset.name}")
        print(f"  - ID: {new_preset.id}")
        print(f"  - 内置: {new_preset.is_builtin}")
        print(f"  - 提示词: {new_preset.system_prompt[:50]}...")

    # 3. 复制自定义预设（使用默认名称）
    print("\n--- 复制自定义预设（使用默认名称）---")
    custom_preset = mgr.duplicate(new_preset.id)
    print(f"[OK] 复制成功: {custom_preset.name}")
    print(f"  - ID: {custom_preset.id}")
    print(f"  - 内置: {custom_preset.is_builtin}")

    # 4. 显示最终列表
    print("\n--- 最终预设列表 ---")
    all_presets = mgr.get_all()
    print(f"总数: {len(all_presets)}")
    for p in all_presets:
        print(f"  - {p.name} (ID: {p.id}, 内置: {p.is_builtin})")

    # 5. 清理测试数据
    print("\n--- 清理测试数据 ---")
    mgr.delete(new_preset.id)
    mgr.delete(custom_preset.id)
    print("[OK] 清理完成")


if __name__ == "__main__":
    test_duplicate()
