"""测试 ContextManager 的 token 计数功能"""
import sys
sys.path.insert(0, '/d/claudecode-projects/assistant')

from app.core.context_manager import (
    ContextManager,
    count_tokens,
    get_context_window_for_model,
)

# 测试 1: 基础 token 计数
print("=== Test 1: Basic token counting ===")
text_en = "Hello, world! This is a test."
text_cn = "你好世界！这是一个测试。"
text_mixed = "混合文本 mixed text 123"

print(f"English text: '{text_en}'")
print(f"  Tokens (gpt-4): {count_tokens(text_en, 'gpt-4')}")
print(f"  Tokens (claude-4): {count_tokens(text_cn, 'claude-4')}")

print(f"\nChinese text: '{text_cn}'")
print(f"  Tokens (gpt-4): {count_tokens(text_cn, 'gpt-4')}")

print(f"\nMixed text: '{text_mixed}'")
print(f"  Tokens (gpt-4): {count_tokens(text_mixed, 'gpt-4')}")

# 测试 2: 上下文窗口大小
print("\n=== Test 2: Context window sizes ===")
models = [
    "gpt-4-turbo",
    "gpt-4o",
    "claude-3.5-sonnet",
    "claude-4-opus",
    "deepseek-v4",
    "unknown-model"
]

for model in models:
    window = get_context_window_for_model(model)
    print(f"{model:25s} -> {window:7d} tokens")

# 测试 3: ContextManager 初始化
print("\n=== Test 3: ContextManager initialization ===")
ctx_mgr = ContextManager(model="gpt-4-turbo", reserve_ratio=0.2)
print(f"Model: gpt-4-turbo")
print(f"Max context: {ctx_mgr._max_context} tokens")
print(f"Usable context: {ctx_mgr._usable_context} tokens")
print(f"Reserved for completion: {ctx_mgr._max_context - ctx_mgr._usable_context} tokens")

# 测试 4: 与旧的启发式估算对比
print("\n=== Test 4: Tiktoken vs heuristic comparison ===")

def old_estimate(text: str) -> int:
    """旧的字符启发式估算"""
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)

test_texts = [
    "This is a simple English sentence.",
    "这是一个简单的中文句子。",
    "JSON payload: {\"key\": \"value\", \"nested\": {\"data\": [1, 2, 3]}}",
    "Long code snippet: def calculate(x, y): return x * y + sum([i for i in range(100)])"
]

for text in test_texts:
    tiktoken_count = count_tokens(text, "gpt-4")
    heuristic_count = old_estimate(text)
    diff = abs(tiktoken_count - heuristic_count)
    diff_pct = (diff / tiktoken_count * 100) if tiktoken_count > 0 else 0

    print(f"\nText: {text[:50]}...")
    print(f"  Tiktoken: {tiktoken_count}")
    print(f"  Heuristic: {heuristic_count}")
    print(f"  Difference: {diff} ({diff_pct:.1f}%)")

print("\n[OK] All tests completed")
