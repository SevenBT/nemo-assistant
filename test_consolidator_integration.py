"""测试 Consolidator 集成 ContextManager"""
import sys
sys.path.insert(0, '/d/claudecode-projects/assistant')

from unittest.mock import MagicMock
from app.core.consolidator import Consolidator
from app.models.message import Message, MessageRole
import time

# Mock LLM Gateway 和 Memory Manager
llm_gateway = MagicMock()
memory_mgr = MagicMock()

# 测试 1: 初始化（使用真实模型名称）
print("=== Test 1: Consolidator initialization with ContextManager ===")
consolidator = Consolidator(
    llm_gateway=llm_gateway,
    memory_mgr=memory_mgr,
    model="gpt-4-turbo",
    consolidation_ratio=0.5,
)

print(f"Model: gpt-4-turbo")
print(f"Max context: {consolidator._ctx_mgr._max_context} tokens")
print(f"Usable context: {consolidator._ctx_mgr._usable_context} tokens")
print(f"Target after consolidation: {int(consolidator._ctx_mgr._usable_context * 0.5)} tokens")

# 测试 2: 小量消息（不触发压缩）
print("\n=== Test 2: Small message list (no consolidation) ===")
small_messages = [
    Message(role=MessageRole.USER, content="你好", timestamp=time.time()),
    Message(role=MessageRole.ASSISTANT, content="你好！有什么可以帮助你的吗？", timestamp=time.time()),
]

result = consolidator.maybe_consolidate(small_messages, session_id="test-session")
print(f"Input messages: {len(small_messages)}")
print(f"Output messages: {len(result)}")
print(f"Consolidation triggered: {len(result) != len(small_messages)}")

# 测试 3: 计算大量消息的 token 数
print("\n=== Test 3: Large message list token counting ===")
large_messages = []
for i in range(100):
    large_messages.append(
        Message(role=MessageRole.USER, content=f"这是第 {i} 条用户消息，包含一些内容。", timestamp=time.time())
    )
    large_messages.append(
        Message(role=MessageRole.ASSISTANT, content=f"这是第 {i} 条助手回复，包含更多的内容和细节。" * 10, timestamp=time.time())
    )

total_tokens = consolidator._ctx_mgr.count_messages_tokens(large_messages)
threshold = int(consolidator._ctx_mgr._usable_context * 0.7)

print(f"Total messages: {len(large_messages)}")
print(f"Total tokens (tiktoken): {total_tokens}")
print(f"Threshold (70%): {threshold}")
print(f"Should consolidate: {total_tokens > threshold}")

# 测试 4: 计算保留数量
print("\n=== Test 4: Calculate keep count ===")
keep_count = consolidator._ctx_mgr.calculate_keep_count(
    large_messages,
    target_ratio=0.5,
    min_keep=4,
)
print(f"Total messages: {len(large_messages)}")
print(f"Messages to keep: {keep_count}")
print(f"Messages to compress: {len(large_messages) - keep_count}")

# 测试 5: 对比旧版本的 token 估算
print("\n=== Test 5: Old vs New token estimation ===")

def old_estimate_tokens(text: str) -> int:
    """旧的启发式估算"""
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)

test_message = Message(
    role=MessageRole.ASSISTANT,
    content="这是一条包含中文和 English mixed content 的消息。包含一些技术术语如 token、context window、consolidation 等。" * 5,
    timestamp=time.time()
)

from app.core.context_manager import message_to_token_text
text = message_to_token_text(test_message)

old_count = old_estimate_tokens(text)
new_count = consolidator._ctx_mgr.count_tokens(text)
diff = abs(old_count - new_count)
diff_pct = (diff / new_count * 100) if new_count > 0 else 0

print(f"Message length: {len(text)} chars")
print(f"Old estimation: {old_count} tokens")
print(f"New (tiktoken): {new_count} tokens")
print(f"Difference: {diff} tokens ({diff_pct:.1f}%)")

print("\n[OK] All integration tests completed")
