"""
测试预设角色功能

验证：
1. PresetManager 能正确加载内置预设
2. Session 模型包含 preset_id 字段
3. SessionManager 能创建带 preset_id 的会话
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.preset_manager import PresetManager
from app.core.session_manager import SessionManager
from app.models.session import Session


def test_preset_manager():
    """测试 PresetManager"""
    print("=" * 60)
    print("测试 PresetManager")
    print("=" * 60)

    mgr = PresetManager()
    presets = mgr.get_all()

    print(f"\n✓ 加载了 {len(presets)} 个预设角色")
    for preset in presets:
        builtin_mark = "（内置）" if preset.is_builtin else "（自定义）"
        print(f"  {preset.icon} {preset.name} {builtin_mark}")
        print(f"    ID: {preset.id}")
        print(f"    Prompt: {preset.system_prompt[:50]}...")
        print()

    # 测试获取单个预设
    default_preset = mgr.get("default")
    assert default_preset is not None, "应该能获取 default 预设"
    print(f"✓ 成功获取 default 预设: {default_preset.name}")


def test_session_with_preset():
    """测试带预设的会话"""
    print("\n" + "=" * 60)
    print("测试 Session 和 SessionManager")
    print("=" * 60)

    # 测试 Session 模型
    session = Session(title="测试会话", preset_id="translator")
    print(f"\n✓ 创建会话: {session.title}")
    print(f"  preset_id: {session.preset_id}")

    # 测试序列化
    data = session.to_dict()
    assert "preset_id" in data, "to_dict 应该包含 preset_id"
    print(f"✓ to_dict 包含 preset_id: {data['preset_id']}")

    # 测试反序列化
    session2 = Session.from_dict(data)
    assert session2.preset_id == "translator", "from_dict 应该正确恢复 preset_id"
    print(f"✓ from_dict 正确恢复 preset_id: {session2.preset_id}")

    # 测试 SessionManager
    mgr = SessionManager()
    s = mgr.create(title="翻译会话", preset_id="translator")
    print(f"\n✓ SessionManager 创建会话: {s.title}")
    print(f"  preset_id: {s.preset_id}")

    # 测试更新 system_prompt
    mgr.update_system_prompt(s.id, "自定义提示词", "")
    s_updated = mgr.get(s.id)
    assert s_updated.system_prompt == "自定义提示词", "应该能更新 system_prompt"
    assert s_updated.preset_id == "", "preset_id 应该被清空"
    print(f"✓ 成功更新 system_prompt 和 preset_id")

    # 清理测试数据
    mgr.delete(s.id)
    print(f"✓ 清理测试数据")


def test_backward_compatibility():
    """测试向后兼容性"""
    print("\n" + "=" * 60)
    print("测试向后兼容性")
    print("=" * 60)

    # 模拟旧版本的会话数据（没有 preset_id）
    old_data = {
        "id": "test-old-session",
        "title": "旧会话",
        "created_at": 1234567890.0,
        "updated_at": 1234567890.0,
        "messages": [],
        "system_prompt": "旧的提示词",
        # 注意：没有 preset_id 字段
    }

    session = Session.from_dict(old_data)
    print(f"\n✓ 成功加载旧版本会话: {session.title}")
    print(f"  preset_id: '{session.preset_id}' (应该是空字符串)")
    assert session.preset_id == "", "旧会话的 preset_id 应该默认为空字符串"
    print(f"✓ 向后兼容性测试通过")


if __name__ == "__main__":
    try:
        test_preset_manager()
        test_session_with_preset()
        test_backward_compatibility()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
