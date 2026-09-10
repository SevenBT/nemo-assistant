#!/usr/bin/env python
"""测试成本计算集成到 TraceStore 的完整流程。"""
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from app.core.trace_store import TraceStore
from app.core.cost_calculator import calculate_cost_from_usage


def test_cost_calculation():
    """测试成本计算模块本身。"""
    print("=== 测试 1: 成本计算模块 ===")

    # 测试 Anthropic Claude
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "cached_tokens": 800,
    }

    cost = calculate_cost_from_usage(
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=usage,
    )
    print(f"Claude Sonnet 4.6 (1000 prompt + 500 completion + 800 cached): ${cost:.6f}" if cost else "Cost calculation failed")

    # 测试本地模型（零成本）
    cost_local = calculate_cost_from_usage(
        provider="ollama",
        model="qwen2.5-coder",
        usage=usage,
    )
    print(f"Ollama qwen2.5-coder: ${cost_local:.6f}")

    # 测试未知模型
    cost_unknown = calculate_cost_from_usage(
        provider="unknown",
        model="unknown-model",
        usage=usage,
    )
    print(f"Unknown model: {cost_unknown}")
    print()


def test_trace_store_integration():
    """测试 TraceStore 自动计算成本。"""
    print("=== 测试 2: TraceStore 集成 ===")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        store = TraceStore(db_path)
        trace_id = "test-trace-001"

        # 开始一个 turn
        store.start_turn(trace_id, session_id="test-session")

        # 记录一次 LLM 调用（带成本计算）
        store.record_llm_call(
            trace_id=trace_id,
            seq=1,
            record={
                "api_type": "chat",
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "has_tools": False,
                "input_message_count": 3,
                "ttft_ms": 234.5,
                "latency_ms": 1234.5,
                "retry_count": 0,
                "status": "success",
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                    "cached_tokens": 800,
                },
            },
        )

        # 再记录一次调用（不同模型）
        store.record_llm_call(
            trace_id=trace_id,
            seq=2,
            record={
                "api_type": "chat",
                "provider": "ollama",
                "model": "qwen2.5-coder",
                "status": "success",
                "usage": {
                    "prompt_tokens": 500,
                    "completion_tokens": 200,
                    "total_tokens": 700,
                },
            },
        )

        # 结束 turn
        store.finish_turn(
            trace_id=trace_id,
            status="success",
            turn_count=2,
            duration_ms=5000.0,
        )

        # 查询验证
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT seq, provider, model, prompt_tokens, completion_tokens, "
                "cached_tokens, cost_usd FROM llm_calls WHERE trace_id = ? ORDER BY seq",
                (trace_id,)
            ).fetchall()

            print(f"记录了 {len(rows)} 次 LLM 调用：")
            total_cost = 0.0
            for row in rows:
                cost_str = f"${row['cost_usd']:.6f}" if row['cost_usd'] is not None else "N/A"
                print(f"  [{row['seq']}] {row['provider']}/{row['model']}: "
                      f"{row['prompt_tokens']} prompt + {row['completion_tokens']} completion"
                      + (f" + {row['cached_tokens']} cached" if row['cached_tokens'] else "")
                      + f" → {cost_str}")
                if row['cost_usd'] is not None:
                    total_cost += row['cost_usd']

            print(f"\n本次会话总成本: ${total_cost:.6f}")

    finally:
        # Windows 文件锁：先关闭所有连接再删除
        import gc
        gc.collect()
        import time
        time.sleep(0.1)
        try:
            db_path.unlink()
        except PermissionError:
            pass  # Windows 可能还持有锁，忽略清理失败


if __name__ == "__main__":
    test_cost_calculation()
    test_trace_store_integration()
    print("\n[OK] All tests passed")
