"""Read old SQLite evaluation data without initializing or modifying its schema."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from nemo_eval.artifacts import digest, write_json


def import_legacy(database: Path, out: Path):
    database = database.resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "eval_cases" not in tables:
            raise ValueError("Source database contains no legacy eval_cases")
        rows = [dict(r) for r in connection.execute("SELECT * FROM eval_cases ORDER BY case_id")]
        archive = {name: [dict(r) for r in connection.execute(f'SELECT * FROM "{name}"')] for name in ("eval_runs", "eval_results") if name in tables}
    out.mkdir(parents=True, exist_ok=True)
    imported = []
    source = digest(str(database))[:12]
    for row in rows:
        warnings = ["Acceptance criteria require maintainer review", "Historical context and fixtures not verified"]
        def parse(field, default):
            raw = row.get(field)
            if not raw:
                return default
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                warnings.append(f"Invalid/truncated {field}")
                return default
        messages = parse("api_messages", [])
        observed = parse("expected_tools", [])
        key = "legacy-" + digest([source, row["case_id"]])[:20]
        case = {"schema_version": 1, "id": key, "revision": 1, "status": "draft", "title": row.get("title"),
                "input": {"mode": "snapshot", "messages": messages}, "fixtures": {}, "expectations": {},
                "observed_tools": observed, "completion_note": row.get("completion_note"),
                "context_complete": False, "warnings": warnings,
                "provenance": {"source": "legacy_db", "source_fingerprint": source, "case_id": row["case_id"], "source_trace_id": row.get("source_trace_id")}}
        path = out / (key + ".json")
        if not path.exists():
            write_json(path, case)
        imported.append(key)
    write_json(out / "legacy-history.archive.json", {"source": source, "history": archive})
    return imported
