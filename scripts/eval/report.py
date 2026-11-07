"""Render an evaluation run from the local trace database.

Examples:
    python -m scripts.eval.report
    python -m scripts.eval.report --run-id <run-id>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.trace_store import TraceStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "traces.db"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_id(run: dict[str, Any]) -> str:
    return run.get("eval_run_id") or run.get("run_id") or ""


def print_eval_report(
    trace_store: TraceStore,
    run_id: str | None = None,
    *,
    detail_limit: int = 20,
) -> int:
    runs = trace_store.list_eval_runs(limit=100)
    if not runs:
        print("No evaluation runs found.")
        return 1

    if run_id:
        run = next((item for item in runs if _run_id(item) == run_id), None)
        if run is None:
            print(f"Run {run_id} not found.")
            return 1
    else:
        run = runs[0]
        run_id = _run_id(run)

    results = trace_store.get_eval_results(run_id)
    averages = _as_dict(run.get("avg_scores"))

    print("=" * 80)
    print("NEMO ASSISTANT EVALUATION REPORT")
    print("=" * 80)
    print(f"Run ID: {run_id}")
    print(f"Label: {run.get('label') or '-'}")
    print(f"Model: {run.get('model') or '-'}")
    print(f"Git commit: {run.get('git_commit') or '-'}")
    print(f"Cases: {run.get('case_count', len(results))}")
    print(f"Started: {run.get('started_at') or '-'}")
    print(f"Completed: {run.get('completed_at') or '-'}")

    print("\nAverage scores")
    if averages:
        for dimension, score in sorted(averages.items()):
            print(f"  {dimension:30s} {float(score):.2f}")
    else:
        print("  -")

    baseline_run_id = run.get("baseline_eval_run_id") or run.get("baseline_run_id")
    if baseline_run_id:
        baseline = next(
            (item for item in runs if _run_id(item) == baseline_run_id),
            None,
        )
        if baseline:
            baseline_averages = _as_dict(baseline.get("avg_scores"))
            print(f"\nDelta vs baseline {baseline_run_id}")
            for dimension in sorted(set(averages) | set(baseline_averages)):
                delta = float(averages.get(dimension, 0)) - float(
                    baseline_averages.get(dimension, 0)
                )
                print(f"  {dimension:30s} {delta:+.2f}")

    judged = [result for result in results if result.get("judge_scores")]
    print(f"\nResults: {len(results)} total, {len(judged)} with judge scores")
    for index, result in enumerate(results[:detail_limit], 1):
        case_id = str(result.get("case_id") or "")[:12]
        output = result.get("actual_output") or ""
        print(f"\n{index}. Case {case_id} (output={len(output)} chars)")
        rule_scores = _as_dict(result.get("rule_scores"))
        judge_scores = _as_dict(result.get("judge_scores"))
        if rule_scores:
            print(f"   Rule: {rule_scores}")
        if judge_scores:
            print(f"   Judge: {judge_scores}")
        reasoning = (result.get("judge_reasoning") or "").replace("\n", " ")
        if reasoning:
            print(f"   Reasoning: {reasoning[:200]}")

    if len(results) > detail_limit:
        print(f"\n... {len(results) - detail_limit} more results omitted")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--run-id")
    parser.add_argument("--detail-limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return print_eval_report(
        TraceStore(args.db),
        args.run_id,
        detail_limit=args.detail_limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
