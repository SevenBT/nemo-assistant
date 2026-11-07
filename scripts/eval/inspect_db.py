"""Inspect the local trace/evaluation SQLite database.

Examples:
    python -m scripts.eval.inspect_db tables
    python -m scripts.eval.inspect_db schema --table eval_results
    python -m scripts.eval.inspect_db runs
    python -m scripts.eval.inspect_db results --run-id <run-id>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "traces.db"


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def show_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    for row in rows:
        print(row["name"])


def show_schema(conn: sqlite3.Connection, table: str | None) -> None:
    if table:
        tables = [table]
    else:
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]

    for index, name in enumerate(tables):
        if index:
            print()
        print(f"[{name}]")
        for row in conn.execute(f"PRAGMA table_info({name})"):
            nullable = "" if row["notnull"] else " NULL"
            default = f" DEFAULT {row['dflt_value']}" if row["dflt_value"] is not None else ""
            print(f"  {row['name']}: {row['type']}{nullable}{default}")


def show_runs(conn: sqlite3.Connection, limit: int) -> None:
    columns = _columns(conn, "eval_runs")
    id_column = "eval_run_id" if "eval_run_id" in columns else "run_id"
    rows = conn.execute(
        f"SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()

    if not rows:
        print("No evaluation runs found.")
        return

    for row in rows:
        print(
            f"{row[id_column]} | {row['label'] or '-'} | "
            f"cases={row['case_count']} | started={row['started_at']} | "
            f"completed={row['completed_at'] or '-'}"
        )
        averages = _json_value(row["avg_scores"])
        if averages:
            print(f"  averages: {averages}")


def show_cases(conn: sqlite3.Connection, limit: int) -> None:
    rows = conn.execute(
        "SELECT case_id, title, completion_note, enabled, created_at "
        "FROM eval_cases ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("No evaluation cases found.")
        return

    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        note = row["completion_note"] or ""
        print(f"{row['case_id']} | {row['title'] or '-'} | {state} | {note}")


def show_results(conn: sqlite3.Connection, run_id: str, limit: int) -> None:
    columns = _columns(conn, "eval_results")
    run_column = "eval_run_id" if "eval_run_id" in columns else "run_id"
    id_column = "eval_result_id" if "eval_result_id" in columns else "id"
    rows = conn.execute(
        f"SELECT * FROM eval_results WHERE {run_column} = ? "
        f"ORDER BY {id_column} LIMIT ?",
        (run_id, limit),
    ).fetchall()
    if not rows:
        print(f"No results found for run {run_id}.")
        return

    for row in rows:
        output = row["actual_output"] or ""
        print(f"{row['case_id']} | trace={row['trace_id'] or '-'} | output_chars={len(output)}")
        if row["rule_scores"]:
            print(f"  rule: {_json_value(row['rule_scores'])}")
        if row["judge_scores"]:
            print(f"  judge: {_json_value(row['judge_scores'])}")
        if row["judge_reasoning"]:
            reasoning = row["judge_reasoning"].replace("\n", " ")
            print(f"  reasoning: {reasoning[:300]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("tables", help="List database tables.")

    schema = subparsers.add_parser("schema", help="Show table schemas.")
    schema.add_argument("--table", help="Show only one table.")

    runs = subparsers.add_parser("runs", help="Show recent evaluation runs.")
    runs.add_argument("--limit", type=int, default=10)

    cases = subparsers.add_parser("cases", help="Show recent evaluation cases.")
    cases.add_argument("--limit", type=int, default=20)

    results = subparsers.add_parser("results", help="Show one run's results.")
    results.add_argument("--run-id", required=True)
    results.add_argument("--limit", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with _connect(args.db) as conn:
            if args.command == "tables":
                show_tables(conn)
            elif args.command == "schema":
                show_schema(conn, args.table)
            elif args.command == "runs":
                show_runs(conn, args.limit)
            elif args.command == "cases":
                show_cases(conn, args.limit)
            elif args.command == "results":
                show_results(conn, args.run_id, args.limit)
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"inspect_db: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
