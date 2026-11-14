"""Compare repeated live observations only under declared compatible conditions."""
from nemo_eval.artifacts import verify_run
from nemo_eval.reporting import make_view


def compatible_conditions(cur, base, *, change=None, allow_changes=()):
    if cur.get("schema_version") != base.get("schema_version"):
        raise ValueError("Incompatible baseline: schema_version")
    if cur["mode"] == "live" and change not in {"prompt", "application"} and not allow_changes:
        raise ValueError("Live comparison requires --change prompt or application")
    if change is not None and (change not in {"prompt", "application"} or allow_changes):
        raise ValueError("Choose one declared comparison change")
    for key in ("case_hash", "mode", "evaluator_version", "repeat", "environment_hash"):
        if cur.get(key) != base.get(key):
            raise ValueError(f"Incompatible baseline: {key}")
    for key in ("application_hash", "evaluator_hash"):
        if not cur["code"].get(key) or not base["code"].get(key):
            raise ValueError("Source fingerprints are required for comparison")
        if key == "application_hash" and change == "application":
            continue
        if cur["code"][key] != base["code"][key]:
            raise ValueError(f"Incompatible baseline: {key}")
    conditions = []
    if allow_changes:
        allowed = {"target.model", "target.api_protocol", "target.provider", "target.base_url", "target.temperature", "target.top_p", "target.max_tokens"}
        if set(allow_changes) - allowed:
            raise ValueError("Unsupported comparison change dimension")
        import copy
        configs = [copy.deepcopy(m["config"]) for m in (cur, base)]
        for dimension in allow_changes:
            section, field = dimension.split(".")
            values = [c.get(section, {}).pop(field, None) for c in configs]
            if values[0] != values[1]:
                conditions.append({"dimension": dimension, "current": values[0], "baseline": values[1]})
        if configs[0] != configs[1]:
            raise ValueError("Incompatible baseline: undeclared configuration change")
    elif cur["config_hash"] != base["config_hash"]:
        raise ValueError("Incompatible baseline: config_hash")
    if cur.get("variant_hash") != base.get("variant_hash"):
        if change not in {"prompt", "application"}:
            raise ValueError("Incompatible baseline: undeclared prompt change")
        conditions.append({"dimension": "prompt", "baseline": base.get("variant_hash"), "current": cur.get("variant_hash")})
    if change == "application" and cur["code"]["application_hash"] != base["code"]["application_hash"]:
        conditions.append({"dimension": "application", "baseline": base["code"]["application_hash"], "current": cur["code"]["application_hash"]})
    return conditions


def compare_runs(current, baseline, *, change=None, allow_changes=(), current_assessment=None, baseline_assessment=None):
    cur, base = verify_run(current), verify_run(baseline)
    conditions = compatible_conditions(cur, base, change=change, allow_changes=allow_changes)
    views = [make_view(current, current_assessment), make_view(baseline, baseline_assessment)]
    for view in views:
        if view["executed"] != view["planned"] or view["counts"]["inconclusive"]:
            raise ValueError("Cannot formally compare unexecuted tasks or missing required assessments; inspect reports")
    judges = [v.get("judge") for v in views]
    if any(judges) and (not all(judges) or judges[0]["judge_hash"] != judges[1]["judge_hash"]):
        raise ValueError("Incompatible baseline: judge_hash")
    current_cases, baseline_cases = [{c["case_id"]: c for c in v["per_case"]} for v in views]
    if current_cases.keys() != baseline_cases.keys():
        raise ValueError("Case results do not match")
    rows = []
    for case_id, c in current_cases.items():
        b = baseline_cases[case_id]
        delta = c["passed"] - b["passed"]
        rows.append({"case_id": case_id, "priority": c["priority"], "baseline": "pass" if b["stable"] else "fail",
                     "current": "pass" if c["stable"] else "fail", "baseline_passed": b["passed"], "current_passed": c["passed"],
                     "planned": c["planned"], "delta": delta, "change": "regressed" if delta < 0 else "improved" if delta > 0 else "unchanged",
                     "baseline_results": b["results"], "current_results": c["results"], "changed_conditions": conditions,
                     "baseline_run_id": base["run_id"], "current_run_id": cur["run_id"],
                     "baseline_created_at": base["created_at"], "current_created_at": cur["created_at"],
                     "baseline_statistics": views[1].get("statistics"), "current_statistics": views[0].get("statistics")})
    return rows


def markdown(rows):
    lines = ["# Evaluation comparison", "", "Observed changes only; release remains a maintainer decision.", "",
             "| Case | Priority | Baseline | Current | Change |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['case_id']} | {r['priority']} | {r['baseline_passed']}/{r['planned']} | {r['current_passed']}/{r['planned']} | {r['change']} |")
    if rows:
        lines += ["", f"Conditions: `{rows[0]['changed_conditions']}`.",
                  f"Baseline run: `{rows[0]['baseline_run_id']}` ({rows[0]['baseline_created_at']}).",
                  f"Current run: `{rows[0]['current_run_id']}` ({rows[0]['current_created_at']}).",
                  f"Baseline statistics: `{rows[0]['baseline_statistics']}`.", f"Current statistics: `{rows[0]['current_statistics']}`."]
    return "\n".join(lines) + "\n"
