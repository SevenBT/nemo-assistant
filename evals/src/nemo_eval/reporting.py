"""Derived views of immutable task evidence and explicitly selected assessments."""
from collections import defaultdict
from statistics import median

from nemo_eval.artifacts import digest, read_json, verify_run, write_json
from nemo_eval.checks import verdict
from nemo_eval.contracts import safe_path


def aggregate(results):
    groups = defaultdict(list)
    for row in results:
        groups[row["case_id"]].append(row)
    counts = {key: sum(r["verdict"] == key for r in results)
              for key in ("pass", "fail", "error", "inconclusive", "skipped")}
    per_case = []
    for case_id, rows in groups.items():
        passed = sum(r["verdict"] == "pass" for r in rows)
        hard_passed = sum(r.get("hard_verdict", r["verdict"]) == "pass" for r in rows)
        per_case.append({"case_id": case_id, "priority": rows[0].get("priority", "normal"),
                         "category": rows[0].get("category", "uncategorized"),
                         "passed": passed, "hard_passed": hard_passed, "planned": len(rows),
                         "stable": passed == len(rows), "results": rows})
    planned = len(results)
    hard_passed = sum(p["hard_passed"] for p in per_case)
    return {"planned": planned, "executed": sum(r["execution_status"] != "not_executed" for r in results),
            "counts": counts, "task_pass_rate": counts["pass"] / planned if planned else None,
            "hard_pass_rate": hard_passed / planned if planned else None,
            "stable_cases": sum(p["stable"] for p in per_case), "case_count": len(per_case), "per_case": per_case}


def make_view(run_dir, assessment=None):
    manifest = verify_run(run_dir)
    summary = read_json(run_dir / "summary.json")
    rows = [dict(r) for r in summary["results"]]
    judged = None
    if assessment is not None:
        directory = safe_path(run_dir / "assessments", assessment)
        judged = read_json(directory / "summary.json")
        if judged.get("run_id") != manifest["run_id"] or judged.get("evidence_hash") != digest(manifest["artifact_hashes"]):
            raise ValueError("Assessment belongs to different execution evidence")
        for name, expected in judged["artifact_hashes"].items():
            if digest(safe_path(directory, name).read_text(encoding="utf-8")) != expected:
                raise ValueError("Assessment evidence changed")
        by_key = {(r["case_id"], r.get("repeat_id", 1)): r for r in judged["results"]}
        if len(by_key) != len(judged["results"]):
            raise ValueError("Duplicate assessments")
        for row in rows:
            key = row["case_id"], row.get("repeat_id", 1)
            item = by_key.get(key)
            if item is None:
                continue
            case_dir = run_dir / "cases" / row["case_id"] / str(key[1])
            case = read_json(case_dir / "input.json")
            execution = read_json(case_dir / "execution.json")
            checks = read_json(case_dir / "checks.json")
            row["verdict"] = verdict(execution, checks, judge_required=case.get("judge_required", False), judge=item)
            row["assessment"] = item
            if row["verdict"] == "pass":
                row["reason"] = "accepted"
            elif case.get("judge_required") and row.get("hard_verdict") not in {"fail", "error"}:
                row["reason"] = "required_assessment_failed" if row["verdict"] == "fail" else "required_assessment_" + item["status"]
    return {**summary, **aggregate(rows), "results": rows, "mode": manifest["mode"],
            "run_id": manifest["run_id"], "assessment_id": assessment,
            "interrupted": summary.get("interrupted", False) or bool(judged and judged.get("interrupted")),
            "judge": judged, "suite": manifest.get("suite"), "created_at": manifest.get("created_at")}


def markdown(view):
    title = "Offline execution regression" if view["mode"] == "offline" else "Live-model task evaluation"
    lines = [f"# {title}", "", f"Run: `{view['run_id']}`; suite: `{view.get('suite') or 'custom'}`.",
             f"Planned: {view['planned']}; executed: {view['executed']}; counts: {view['counts']}.",
             f"Confirmed task pass rate: {view['task_pass_rate']:.1%}; hard-check pass rate: {view['hard_pass_rate']:.1%}.",
             f"Stable cases: {view['stable_cases']}/{view['case_count']}.", ""]
    if view["mode"] == "offline":
        lines += ["Scripted model responses test execution mechanics, not real-model decision quality.", ""]
    else:
        lines += ["Small repeated samples describe observed variability; they do not prove statistical significance or release readiness.", ""]
    lines += [f"Assessment: `{view.get('assessment_id') or 'none'}`.", "",
              "| Case | Priority | Task passes | Hard passes |", "| --- | --- | --- | --- |"]
    for item in view["per_case"]:
        lines.append(f"| {item['case_id']} | {item['priority']} | {item['passed']}/{item['planned']} | {item['hard_passed']}/{item['planned']} |")
    lines += ["", "## Failures and missing assessments", ""]
    for row in view["results"]:
        if row["verdict"] != "pass":
            failed = ", ".join(c["id"] for c in row.get("checks", []) if c["status"] != "pass")
            evidence = f"cases/{row['case_id']}/{row.get('repeat_id', 1)}/execution.json"
            lines.append(f"- {row['case_id']} repeat {row.get('repeat_id', 1)}: **{row['verdict']}**; {row.get('reason', '')}; {failed}; `{evidence}`")
    lines += ["", "## Usage and cost", "", f"Target: `{view.get('cost', {}).get('target', {})}`."]
    if view.get("judge"):
        lines.append(f"Judge: `{view['judge']['cost']}`; same model source: `{view['judge']['same_model_source']}`.")
    lines.append(f"Observed execution statistics: `{view.get('statistics', {})}`.")
    lines.append("Unknown usage/cost is not zero. New runs only summarize provider-reported charges; consult the provider billing console for actual charges. Historical estimate fields, if present, are not invoices.")
    return "\n".join(lines) + "\n"


def save_report(run_dir, *, assessment=None, out=None):
    view = make_view(run_dir, assessment)
    if out is not None:
        out.mkdir(parents=True, exist_ok=False)
        write_json(out / "summary.json", view)
        (out / "report.md").write_text(markdown(view), encoding="utf-8")
    return view


def execution_statistics(executions):
    durations = [e["duration_ms"] for e in executions if "duration_ms" in e and e["execution_status"] != "not_executed"]
    calls = [c for e in executions for c in e.get("llm_calls", [])]
    usage = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        values = [c.get("usage", {}).get(field) for c in calls]
        known = [v for v in values if v is not None]
        usage[field] = {"known_total": sum(known) if known else None, "unknown_calls": len(values) - len(known)}
    return {"duration_ms": {"median": median(durations) if durations else None,
                            "min": min(durations) if durations else None, "max": max(durations) if durations else None},
            "tool_attempts": sum(len(e.get("tool_calls", [])) for e in executions),
            "tool_successes": sum((c.get("result") or {}).get("status") == "success" for e in executions for c in e.get("tool_calls", [])),
            "model_calls": sum(e.get("model_calls", 0) for e in executions), "usage": usage,
            "unobserved_model_calls": sum(max(0, e.get("model_calls", 0) - len(e.get("llm_calls", []))) for e in executions)}
