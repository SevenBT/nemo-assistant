import json
import sqlite3

from app.observability.trace_store import TraceStore
from app.observability.diagnostics import build_diagnostic, redact


def test_fresh_runtime_database_has_no_evaluation_tables(tmp_path):
    store = TraceStore(tmp_path / "runtime.db")
    assert store.enabled
    with sqlite3.connect(tmp_path / "runtime.db") as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "iteration_records" in tables
    assert not any(t.startswith("eval_") for t in tables)
    store.start_trace("trace")
    store.record_iteration("trace", turn=0, answer="answer", tool_count=0, error_count=0, had_error=False)
    store.finish_trace("trace", status="ok")
    assert store.get_trace("trace")["iterations"][0]["answer"] == "answer"


def test_v1_and_v2_iteration_migration_preserves_legacy_tables(tmp_path):
    for version in (1, 2):
        path = tmp_path / f"v{version}.db"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            connection.execute("INSERT INTO schema_version VALUES (?, '2026-11-09')", (version,))
            ident, turn = ("id", "turn") if version == 1 else ("eval_sample_id", "turn_index")
            connection.execute(f"CREATE TABLE eval_samples ({ident} INTEGER PRIMARY KEY, trace_id TEXT, {turn} INTEGER, answer TEXT, tool_count INTEGER, error_count INTEGER, had_error INTEGER, created_at TEXT, scores TEXT)")
            connection.execute("INSERT INTO eval_samples VALUES (1, 'trace', 0, 'old answer', 0, 0, 0, '2026-11-09', '{}')")
        store = TraceStore(path)
        assert store.enabled
        assert TraceStore(path).enabled
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM iteration_records").fetchone()[0] == 1
            assert connection.execute("SELECT answer FROM eval_samples").fetchone()[0] == "old answer"
            assert "scores" not in {r[1] for r in connection.execute("PRAGMA table_info(iteration_records)")}
        assert list(tmp_path.glob(f"v{version}.backup.*.db"))
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM iteration_records")
        assert TraceStore(path).enabled
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM iteration_records").fetchone()[0] == 0


def test_attempt_id_deduplicates_usage_and_unknown_cost_is_not_zero(tmp_path):
    store = TraceStore(tmp_path / "runtime.db")
    store.start_trace("trace")
    record = {"attempt_id": "attempt", "model": "unknown", "usage": {"total_tokens": 7}, "status": "ok"}
    store.record_llm_call("trace", 0, record)
    store.record_llm_call("trace", 0, record)
    data = store.get_trace("trace")
    assert len(data["llm_calls"]) == 1
    assert data["cost"]["unknown_calls"] == 1 and not data["cost"]["complete"]


def test_diagnostic_omits_private_bodies_and_recursively_redacts():
    secret = "CANARY_PRIVATE_BODY"
    data = {"trace": {"status": "ok", "total_tokens": 42, "session_id": secret, "error": secret},
            "tool_calls": [{"name": "read_file", "status": "success", "arguments": {"path": secret}, "result": secret}],
            "iterations": [{"answer": secret}]}
    diagnostic = build_diagnostic(data)
    assert secret not in json.dumps(diagnostic)
    assert diagnostic["replayable"] is False
    assert diagnostic["trace"]["total_tokens"] == 42
    assert "CANARY_SECRET" not in json.dumps(redact({"nested": [{"api_key": "CANARY_SECRET"}], "error": "Bearer CANARY_SECRET"}))


def test_diagnostic_distinguishes_reported_charge_from_legacy_estimates():
    diagnostic = build_diagnostic({"llm_calls": [{"cost_usd": 42, "pricing_source": "custom_pricing",
        "reported_cost_amount": 0.01, "reported_cost_currency": "USD", "total_tokens": 10}]})
    call = diagnostic["llm_calls"][0]
    assert call["reported_cost_amount"] == 0.01 and call["reported_cost_currency"] == "USD"
    assert "cost_usd" not in call and "pricing_source" not in call


def test_migration_failure_rolls_back_schema_changes(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
        connection.execute("INSERT INTO schema_version VALUES (2, 'old')")
    def fail(*args):
        raise RuntimeError("simulated migration failure")
    monkeypatch.setattr(TraceStore, "_set_schema_version", fail)
    assert not TraceStore(path).enabled
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 2
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'iteration_records'").fetchone() is None
