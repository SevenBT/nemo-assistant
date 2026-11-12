"""Deterministic acceptance checks against execution evidence and artifacts."""
from __future__ import annotations

import json
from jsonschema import validate as validate_json


def _subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(v, actual[k]) for k, v in expected.items())
    return expected == actual


def evaluate(case, execution):
    checks = []
    def add(name, passed, evidence=None):
        checks.append({"id": name, "status": "pass" if passed else "fail", "evidence_ids": evidence or []})
    expected = case["expectations"]
    calls = execution.get("tool_calls", [])
    tools = expected.get("tools", {})
    matched_rules = []
    for idx, rule in enumerate(tools.get("required", [])):
        matching = [c for c in calls if c["name"] == rule["name"] and (not rule.get("step") or c["step"] == rule["step"]) and _subset(rule.get("arguments", {}), c["arguments"])]
        outcome = rule.get("outcome", "success")
        if outcome != "attempted":
            matching = [c for c in matching if (c.get("rejected") if outcome == "rejected" else c["result"].get("status") == outcome)]
        matched_rules.append(matching)
        add(f"required_tool_{idx}", rule.get("min_calls", 1) <= len(matching) <= rule.get("max_calls", float("inf")), [c["evidence_id"] for c in matching])
    for idx, (before, after) in enumerate(tools.get("order", [])):
        left, right = matched_rules[before], matched_rules[after]
        def timing(call):
            return (call.get("started_order", calls.index(call)), call.get("finished_order", calls.index(call)))
        passed = bool(left and right) and any(timing(a)[1] < timing(b)[0] for a in left for b in right)
        add(f"tool_order_{idx}", passed, [c["evidence_id"] for c in left + right])
    forbidden = tools.get("forbidden", [])
    if forbidden:
        add("forbidden_tools", not any(c["name"] in forbidden for c in calls))
    if tools.get("no_tools"):
        add("no_tools", not calls)
    for idx, rule in enumerate(expected.get("artifacts", [])):
        artifact = execution.get("artifacts", {}).get(rule["path"])
        kind = rule["check"]
        passed = artifact is not None
        if kind == "absent":
            passed = artifact is None
        elif passed and kind in {"text_equals", "text_contains"}:
            passed = artifact.get("text") == rule["expected"] if kind == "text_equals" else rule["expected"] in artifact.get("text", "")
        elif passed and kind == "json_schema":
            try:
                validate_json(json.loads(artifact["text"]), rule["schema"])
            except Exception:
                passed = False
        add(f"artifact_{idx}", passed, [f"artifact:{rule['path']}"] if artifact else [])
    answer_rule = expected.get("answer", {})
    answer = execution.get("answer", "")
    for text in answer_rule.get("contains", []):
        add(f"answer_contains_{len(checks)}", text in answer, ["answer"])
    for text in answer_rule.get("not_contains", []):
        add(f"answer_excludes_{len(checks)}", text not in answer, ["answer"])
    if "equals" in answer_rule:
        add("answer_equals", answer == answer_rule["equals"], ["answer"])
    if "schema" in answer_rule:
        try:
            validate_json(json.loads(answer), answer_rule["schema"])
            passed = True
        except Exception:
            passed = False
        add("answer_schema", passed, ["answer"])
    return checks


def verdict(execution, checks, *, judge_required=False, judge=None):
    allowed = execution.get("expected_statuses", ["completed"])
    if execution.get("execution_status") not in allowed:
        return "error"
    if any(c["status"] == "error" for c in checks):
        return "error"
    if any(c["status"] == "fail" for c in checks):
        return "fail"
    if not execution.get("evidence_complete", False):
        return "inconclusive"
    if judge_required and (not judge or judge.get("status") != "scored"):
        return "inconclusive"
    if judge_required and any(c["verdict"] != "pass" for c in judge["criteria"]):
        return "fail" if any(c["verdict"] == "fail" for c in judge["criteria"]) else "inconclusive"
    return "pass" if checks or judge_required else "inconclusive"
