"""
测试预设编辑功能
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.preset_manager import PresetManager


def test_builtin_edit():
    """测试内置预设编辑功能"""
    mgr = PresetManager()

    print("=== 测试 1: 获取内置预设 ===")
    default_preset = mgr.get("default")
    if default_preset:
        print(f"[OK] 找到内置预设: {default_preset.name}")
        print(f"  原始提示词: {default_preset.system_prompt[:50]}...")
    else:
        print("[FAIL] 未找到内置预设")
        return

    print("\n=== 测试 2: 检查是否被修改 ===")
    is_modified = mgr.is_modified("default")
    print(f"  是否被修改: {is_modified}")

    print("\n=== 测试 3: 修改内置预设 ===")
    original_prompt = default_preset.system_prompt
    default_preset.system_prompt = "这是修改后的提示词"
    try:
        mgr.update(default_preset)
        print("[OK] 修改成功")
    except ValueError as e:
        print(f"[FAIL] 修改失败: {e}")
        return

    print("\n=== 测试 4: 验证修改 ===")
    modified_preset = mgr.get("default")
    if modified_preset and modified_preset.system_prompt == "这是修改后的提示词":
        print("[OK] 修改已保存")
    else:
        print("[FAIL] 修改未保存")

    print("\n=== 测试 5: 检查修改状态 ===")
    is_modified = mgr.is_modified("default")
    print(f"  是否被修改: {is_modified}")
    if is_modified:
        print("[OK] 正确检测到修改")
    else:
        print("[FAIL] 未检测到修改")

    print("\n=== 测试 6: 恢复默认 ===")
    try:
        mgr.restore_builtin("default")
        print("[OK] 恢复成功")
    except Exception as e:
        print(f"[FAIL] 恢复失败: {e}")
        return

    print("\n=== 测试 7: 验证恢复 ===")
    restored_preset = mgr.get("default")
    if restored_preset and restored_preset.system_prompt == original_prompt:
        print("[OK] 已恢复到原始状态")
    else:
        print("[FAIL] 恢复失败")

    print("\n=== 测试 8: 检查恢复后的修改状态 ===")
    is_modified = mgr.is_modified("default")
    print(f"  是否被修改: {is_modified}")
    if not is_modified:
        print("[OK] 修改状态已清除")
    else:
        print("[FAIL] 修改状态未清除")

    print("\n=== 测试 9: 尝试删除内置预设 ===")
    try:
        mgr.delete("default")
        print("[FAIL] 不应该允许删除内置预设")
    except ValueError as e:
        print(f"[OK] 正确阻止删除: {e}")

    print("\n=== 测试 10: 尝试恢复非内置预设 ===")
    try:
        mgr.restore_builtin("non_existent")
        print("[FAIL] 不应该允许恢复非内置预设")
    except ValueError as e:
        print(f"[OK] 正确阻止恢复: {e}")

    print("\n=== 所有测试完成 ===")


if __name__ == "__main__":
    test_builtin_edit()
