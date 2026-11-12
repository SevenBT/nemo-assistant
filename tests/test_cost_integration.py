"""Provider charges stay separate from historical local estimates."""
import sqlite3

import pytest

from app.core.trace_store import TraceStore


def test_runtime_preserves_usage_without_loading_pricing(tmp_path, monkeypatch):
    store = TraceStore(tmp_path / "traces.db")
    store.start_trace("trace")
    for index, provider in enumerate(("anthropic", "ollama")):
        store.record_llm_call("trace", index, {
            "provider": provider, "model": "model", "status": "ok",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                      "total_tokens": 1500, "cached_tokens": 800},
            "cost_usd": 0.01, "_response_cost": 0.01, "pricing_source": "provider",
        })
    store.finish_trace("trace", status="ok")
    data = store.get_trace("trace")
    assert data["trace"]["total_tokens"] == 3000
    assert all(c["cached_tokens"] == 800 and c["cost_usd"] is None for c in data["llm_calls"])
    assert data["cost"]["reported_totals"] == {}
    assert data["cost"]["unknown_calls"] == 2
    assert not data["cost"]["complete"]


def test_provider_charges_keep_currencies_and_deduplicate_attempts(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    store.start_trace("trace")
    for index, (amount, currency) in enumerate(((0, "USD"), (0.03, "USD"), (0.2, "CNY"))):
        record = {"attempt_id": str(index), "provider_cost": {"amount": amount, "currency": currency}}
        store.record_llm_call("trace", index, record)
        store.record_llm_call("trace", index, record)
    cost = store.get_trace("trace")["cost"]
    assert cost["reported_totals"] == {"USD": 0.03, "CNY": 0.2}
    assert cost["reported_calls"] == 3 and cost["complete"]


def test_v3_migration_preserves_estimate_without_reclassifying_it(tmp_path):
    path = tmp_path / "traces.db"
    store = TraceStore(path)
    store.start_trace("trace")
    store.record_llm_call("trace", 0, {"attempt_id": "old"})
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE llm_calls SET cost_usd=0.123, pricing_source='custom_pricing', pricing_version='old'")
        for column in ("reported_cost_amount", "reported_cost_currency", "billing_url"):
            conn.execute(f"ALTER TABLE llm_calls DROP COLUMN {column}")
        conn.execute("DELETE FROM schema_version WHERE version=4")
        conn.execute("INSERT OR IGNORE INTO schema_version VALUES (3, 'old')")
    reopened = TraceStore(path)
    assert reopened.enabled
    row = reopened.get_trace("trace")["llm_calls"][0]
    assert row["cost_usd"] == 0.123 and row["pricing_version"] == "old"
    assert row["reported_cost_amount"] is None and row["billing_url"] is None
    assert reopened.get_trace("trace")["cost"]["unknown_calls"] == 1
    assert list(tmp_path.glob("traces.backup.*.db"))
    backups = len(list(tmp_path.glob("traces.backup.*.db")))
    assert TraceStore(path).enabled
    assert len(list(tmp_path.glob("traces.backup.*.db"))) == backups
