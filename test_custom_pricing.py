"""测试自定义定价配置"""
import json
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.cost_calculator import calculate_cost, _get_pricing_file, _load_custom_pricing


def test_pricing_file_creation():
    """测试定价文件自动创建"""
    pricing_file = _get_pricing_file()
    print(f"[TEST] Pricing file path: {pricing_file}")

    # 如果存在，显示内容
    if pricing_file.exists():
        with open(pricing_file, "r", encoding="utf-8") as f:
            pricing = json.load(f)
        print(f"[OK] Found {len(pricing)} pricing entries")

        # 显示前 3 个
        for i, (model, prices) in enumerate(list(pricing.items())[:3], 1):
            print(f"  {i}. {model}:")
            print(f"     Input:  ${prices['input_per_1m']}/M")
            print(f"     Output: ${prices['output_per_1m']}/M")
            print(f"     Cache:  ${prices.get('cache_read_per_1m', 0.0)}/M")
    else:
        print(f"[INFO] Pricing file does not exist, will be created on first use")


def test_cost_calculation():
    """测试成本计算"""
    print("\n[TEST] Cost calculation with custom pricing:")

    # 测试用例 1: Claude Sonnet 4.6（自定义定价表有）
    cost1 = calculate_cost(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1000,
        completion_tokens=500,
        cached_tokens=800,
    )
    print(f"  Claude Sonnet 4.6 (1000+500+800): ${cost1:.6f}")
    assert cost1 is not None, "Cost should not be None"

    # 测试用例 2: Ollama 本地模型（零成本）
    cost2 = calculate_cost(
        provider="ollama",
        model="qwen2.5-coder",
        prompt_tokens=5000,
        completion_tokens=2000,
    )
    print(f"  Ollama qwen2.5-coder (5000+2000): ${cost2:.6f}")
    assert cost2 == 0.0, "Local model should have zero cost"

    # 测试用例 3: 未知模型（应该返回 None）
    cost3 = calculate_cost(
        provider="custom",
        model="unknown-model",
        prompt_tokens=100,
        completion_tokens=50,
    )
    print(f"  Unknown model (100+50): {cost3}")
    assert cost3 is None, "Unknown model should return None"

    print("[OK] All cost calculations passed")


def test_user_override():
    """测试用户自定义定价覆盖"""
    print("\n[TEST] User pricing override:")

    pricing_file = _get_pricing_file()

    # 读取当前定价
    with open(pricing_file, "r", encoding="utf-8") as f:
        pricing = json.load(f)

    # 添加一个自定义模型
    pricing["custom/my-model"] = {
        "input_per_1m": 1.0,
        "output_per_1m": 2.0,
        "cache_read_per_1m": 0.1,
        "note": "测试用自定义模型"
    }

    # 写回文件
    with open(pricing_file, "w", encoding="utf-8") as f:
        json.dump(pricing, f, indent=2, ensure_ascii=False)

    print(f"[OK] Added custom/my-model to {pricing_file}")

    # 重新加载定价表
    from app.core import cost_calculator
    cost_calculator._CUSTOM_PRICING = {}
    cost_calculator._init_pricing()

    # 测试计算
    cost = calculate_cost(
        provider="custom",
        model="my-model",
        prompt_tokens=1_000_000,  # 1M tokens
        completion_tokens=500_000,  # 0.5M tokens
    )

    expected = 1.0 * 1.0 + 0.5 * 2.0  # $1.00 + $1.00 = $2.00
    print(f"  custom/my-model (1M+0.5M): ${cost:.2f} (expected: ${expected:.2f})")
    assert abs(cost - expected) < 0.01, f"Cost mismatch: {cost} != {expected}"

    print("[OK] User pricing override works")


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Custom Pricing Configuration")
    print("=" * 60)

    test_pricing_file_creation()
    test_cost_calculation()
    test_user_override()

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
