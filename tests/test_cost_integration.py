"""成本计算与 TraceStore 落库集成测试。"""
from __future__ import annotations

import sqlite3

import pytest

from app.core.cost_calculator import calculate_cost_from_usage
from app.core.trace_store import TraceStore


def _usage() -> dict[str, int]:
    return {
        "prompt_tokens": 1_000,
        "completion_tokens": 500,
        "cached_tokens": 800,
    }


def test_cost_calculation_for_known_and_local_models():
    anthropic_cost = calculate_cost_from_usage(
        provider="anthropic",
        model="claude-sonnet-4-6",
        usage=_usage(),
    )
    assert anthropic_cost is not None
    assert anthropic_cost > 0

    local_cost = calculate_cost_from_usage(
        provider="ollama",
        model="qwen2.5-coder",
        usage=_usage(),
    )
    assert local_cost == pytest.approx(0.0)


def test_trace_store_persists_usage_and_cost(tmp_path):
    db_path = tmp_path / "traces.db"
    store = TraceStore(db_path)
    trace_id = "test-trace-cost"

    store.start_trace(trace_id, session_id="test-session")
    store.record_llm_call(
        trace_id,
        1,
        {
            "api_type": "chat",
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "has_tools": False,
            "input_message_count": 3,
            "ttft_ms": 234.5,
            "latency_ms": 1_234.5,
            "retry_count": 0,
            "status": "success",
            "usage": {
                "prompt_tokens": 1_000,
                "completion_tokens": 500,
                "total_tokens": 1_500,
                "cached_tokens": 800,
            },
        },
    )
    store.record_llm_call(
        trace_id,
        2,
        {
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
    store.finish_trace(trace_id, status="success", turn_count=2, duration_ms=5_000)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT seq, provider, model, prompt_tokens, completion_tokens, "
            "cached_tokens, cost_usd FROM llm_calls "
            "WHERE trace_id = ? ORDER BY seq",
            (trace_id,),
        ).fetchall()

    assert len(rows) == 2
    assert rows[0]["provider"] == "anthropic"
    assert rows[0]["cost_usd"] is not None
    assert rows[0]["cost_usd"] > 0
    assert rows[1]["provider"] == "ollama"
    assert rows[1]["cost_usd"] == pytest.approx(0.0)
