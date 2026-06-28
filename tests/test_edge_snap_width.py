"""测试边缘吸附宽度阈值功能"""
import sys
from pathlib import Path

# 设置 UTF-8 输出
if sys.platform == "win32":
    import io
    sys.stdout = sys.stdout if "pytest" in sys.modules else io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

import pytest

# 该测试针对已移除的旧 API（ConfigManager + edge_snap_width_threshold 0~1 比例），
# 现配置改为 cfg.edgeSnapThreshold（20~80 px 区间），语义不同，待按新 API 重写。
pytest.skip(
    "stale: ConfigManager API removed, see cfg.edgeSnapThreshold",
    allow_module_level=True,
)

from app.core.config import ConfigManager


def test_config_default():
    """测试默认配置"""
    config = ConfigManager()
    threshold = config.edge_snap_width_threshold
    print(f"✓ 默认阈值: {threshold} (期望: 0.4)")
    assert threshold == 0.4, f"默认阈值应为 0.4，实际为 {threshold}"


def test_config_update():
    """测试配置更新"""
    config = ConfigManager()

    # 更新阈值
    config.update_window_config(edge_snap_width_threshold=0.5)

    # 重新加载配置
    config2 = ConfigManager()
    threshold = config2.edge_snap_width_threshold
    print(f"✓ 更新后阈值: {threshold} (期望: 0.5)")
    assert threshold == 0.5, f"更新后阈值应为 0.5，实际为 {threshold}"

    # 恢复默认值
    config.update_window_config(edge_snap_width_threshold=0.4)


def test_width_ratio_calculation():
    """测试宽度比例计算逻辑"""
    test_cases = [
        # (窗口宽度, 屏幕宽度, 阈值, 期望结果)
        (440, 1920, 0.4, True),   # 440/1920 = 0.23 < 0.4 → 可以吸附
        (800, 1920, 0.4, False),  # 800/1920 = 0.42 > 0.4 → 不触发吸附
        (1800, 1920, 0.4, False), # 1800/1920 = 0.94 > 0.4 → 不触发吸附
        (600, 1920, 0.5, True),   # 600/1920 = 0.31 < 0.5 → 可以吸附
        (800, 1920, 0.5, True),   # 800/1920 = 0.42 < 0.5 → 可以吸附
    ]

    for window_w, screen_w, threshold, expected in test_cases:
        width_ratio = window_w / screen_w
        result = width_ratio < threshold
        status = "✓" if result == expected else "✗"
        print(f"{status} 窗口 {window_w}px / 屏幕 {screen_w}px = {width_ratio:.2f}, "
              f"阈值 {threshold:.2f} → {'可以吸附' if result else '不触发吸附'} "
              f"(期望: {'可以吸附' if expected else '不触发吸附'})")
        assert result == expected, f"测试失败: {window_w}/{screen_w} with threshold {threshold}"


if __name__ == "__main__":
    print("=" * 60)
    print("测试边缘吸附宽度阈值功能")
    print("=" * 60)

    try:
        test_config_default()
        print()
        test_config_update()
        print()
        test_width_ratio_calculation()
        print()
        print("=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"✗ 测试失败: {e}")
        print("=" * 60)
        sys.exit(1)
