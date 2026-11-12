"""Validate versioned, explicit evaluation cases before any execution."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator

CASE_SCHEMA = {
    "type": "object", "required": ["schema_version", "id", "revision", "status", "input", "fixtures", "expectations"],
    "properties": {
        "schema_version": {"const": 1}, "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]*$"},
        "revision": {"type": "integer", "minimum": 1}, "status": {"enum": ["draft", "reviewed"]},
        "input": {"type": "object", "required": ["mode"], "properties": {"mode": {"enum": ["snapshot", "scenario"]}}},
        "fixtures": {"type": "object"}, "expectations": {"type": "object"},
        "limits": {"type": "object", "properties": {"deadline_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600}, "max_iterations_per_step": {"type": "integer", "minimum": 1, "maximum": 100}}},
    },
}


def safe_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or chr(92) in name or ":" in name or PurePosixPath(name).is_absolute():
        raise ValueError(f"Invalid fixture path: {name!r}")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"Path escapes workspace: {name}")
    return path


def validate_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("snapshot requires nonempty messages")
    pending = set()
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content", ""), (str, type(None))):
            raise ValueError("First-release snapshots support text messages only")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Invalid message role")
        if pending and role != "tool":
            raise ValueError("Missing tool result messages")
        if role == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending:
                raise ValueError("Unmatched tool_call_id")
            pending.remove(call_id)
        for call in message.get("tool_calls", []):
            if role != "assistant" or not call.get("id") or call["id"] in pending:
                raise ValueError("Invalid or duplicate tool call")
            pending.add(call["id"])
    if pending:
        raise ValueError("Unresolved tool calls in snapshot")
    if messages[-1]["role"] not in {"user", "tool"}:
        raise ValueError("Snapshot must end with an actionable user or tool message")


def validate(case: dict, mode: str = "offline", *, allow_draft=False):
    Draft202012Validator(CASE_SCHEMA).validate(case)
    def fields(value, allowed, label):
        if not isinstance(value, dict) or set(value) - set(allowed.split()):
            raise ValueError(f"Unsupported {label} fields")
    fields(case, "schema_version id revision status title suites input fixtures expectations limits capabilities reference rubric judge_required provenance observed_tools completion_note context_complete warnings", "case")
    fields(case["input"], "mode messages steps", "input")
    fields(case["fixtures"], "tool_profile workspace_files model_script system_prompt memory clock blocked_tools", "fixtures")
    fields(case["expectations"], "tools artifacts answer execution_statuses", "expectations")
    fields(case.get("limits", {}), "deadline_seconds max_iterations_per_step", "limits")
    if not isinstance(case.get("judge_required", False), bool):
        raise ValueError("judge_required must be boolean")
    rubric = case.get("rubric", [])
    if not isinstance(rubric, list):
        raise ValueError("rubric must be a list")
    for criterion in rubric:
        fields(criterion, "id description", "rubric")
        if not all(isinstance(criterion.get(k), str) and criterion[k] for k in ("id", "description")):
            raise ValueError("Rubric requires id and description")
    if len({r["id"] for r in rubric}) != len(rubric) or (case.get("judge_required") and not rubric):
        raise ValueError("Invalid rubric or required judge without rubric")
    if case["status"] != "reviewed" and not allow_draft:
        raise ValueError(f"Draft case cannot run: {case['id']}")
    inp, fixtures, expected = case["input"], case["fixtures"], case["expectations"]
    if inp["mode"] == "snapshot":
        validate_messages(inp.get("messages"))
    else:
        steps = inp.get("steps")
        if not isinstance(steps, list) or not steps or any(not isinstance(s.get("user"), str) or not s["user"] for s in steps):
            raise ValueError("scenario requires nonempty user steps")
        ids = [s.get("id") for s in steps]
        if any(not isinstance(i, str) or not re.fullmatch(r"[a-z0-9_-]+", i) for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("scenario step ids must be unique")
    if fixtures.get("tool_profile", "none") not in {"none", "workspace-files"}:
        raise ValueError("Unsupported tool profile")
    if not isinstance(case.get("suites", ["core"]), list) or any(not isinstance(s, str) or not s for s in case.get("suites", ["core"])):
        raise ValueError("suites must contain names")
    if case.get("capabilities") and set(case["capabilities"]) - {"workspace_files"}:
        raise ValueError("Unsupported required capability")
    for name in fixtures.get("workspace_files", {}):
        safe_path(Path.cwd(), name)
    if mode == "offline" and not isinstance(fixtures.get("model_script"), list):
        raise ValueError("Offline cases require explicit model_script calls")
    if "workspace_files" in case.get("capabilities", []) and fixtures.get("tool_profile") != "workspace-files":
        raise ValueError("workspace_files capability requires its tool profile")
    if mode == "offline":
        for call in fixtures["model_script"]:
            if isinstance(call, dict):
                fields(call, "events request_contains", "model script")
                stream = call.get("events")
                if not isinstance(call.get("request_contains", []), list) or any(not isinstance(s, str) for s in call.get("request_contains", [])):
                    raise ValueError("request_contains requires strings")
            else:
                stream = call
            if not isinstance(stream, list) or any(not isinstance(e, dict) or e.get("type") not in {"text", "tool_call", "done", "error"} for e in stream):
                raise ValueError("Invalid scripted model events")
    if inp["mode"] == "scenario":
        if "messages" in inp:
            raise ValueError("scenario cannot also supply messages")
        for step in steps:
            fields(step, "id user", "scenario step")
    elif "steps" in inp:
        raise ValueError("snapshot cannot also supply steps")
    if not isinstance(fixtures.get("workspace_files", {}), dict) or any(not isinstance(v, str) for v in fixtures.get("workspace_files", {}).values()):
        raise ValueError("workspace_files must contain text values")
    if not isinstance(fixtures.get("memory", []), list) or any(not isinstance(v, str) for v in fixtures.get("memory", [])):
        raise ValueError("memory must contain strings")
    tools = expected.get("tools", {})
    fields(tools, "required forbidden no_tools order", "tools")
    if not isinstance(tools.get("no_tools", False), bool):
        raise ValueError("no_tools must be boolean")
    if tools.get("no_tools") and (tools.get("required") or tools.get("order")):
        raise ValueError("Contradictory no_tools requirement")
    if not isinstance(tools.get("required", []), list) or not isinstance(tools.get("forbidden", []), list):
        raise ValueError("required and forbidden must be lists")
    known = {"read_file", "save_file"} if fixtures.get("tool_profile") == "workspace-files" else set()
    if any(not isinstance(n, str) for n in tools.get("forbidden", []) + fixtures.get("blocked_tools", [])):
        raise ValueError("Tool names must be strings")
    valid_steps = {s["id"] for s in inp.get("steps", [{"id": "snapshot"}])}
    for rule in tools.get("required", []):
        fields(rule, "name step arguments outcome min_calls max_calls", "required tool")
        if "step" in rule and rule["step"] not in valid_steps:
            raise ValueError("Unknown required tool step")
        if not isinstance(rule.get("arguments", {}), dict):
            raise ValueError("Tool argument matcher must be an object")
        low, high = rule.get("min_calls", 1), rule.get("max_calls", 1000)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (low, high)) or low > high:
            raise ValueError("Invalid tool call count bounds")
        if rule.get("name") not in known or rule.get("outcome", "success") not in {"success", "attempted", "rejected", "error"}:
            raise ValueError("Invalid required tool rule")
    if not isinstance(tools.get("order", []), list) or not isinstance(fixtures.get("blocked_tools", []), list):
        raise ValueError("order and blocked_tools must be lists")
    for pair in tools.get("order", []):
        if not isinstance(pair, list) or len(pair) != 2 or any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(tools.get("required", [])) for i in pair) or pair[0] == pair[1]:
            raise ValueError("Tool order must reference two distinct required-rule indexes")
    for rule in expected.get("artifacts", []):
        fields(rule, "path check expected schema", "artifact")
        if rule.get("check") in {"text_equals", "text_contains"} and not isinstance(rule.get("expected"), str):
            raise ValueError("Text artifact check requires expected text")
        if rule.get("check") == "json_schema":
            Draft202012Validator.check_schema(rule["schema"])
        safe_path(Path.cwd(), rule["path"])
        if rule.get("check") not in {"exists", "absent", "text_equals", "text_contains", "json_schema"}:
            raise ValueError("Unsupported artifact check")
    if not any((tools.get("required"), tools.get("forbidden"), tools.get("no_tools") is True, expected.get("artifacts"), expected.get("answer"), case.get("rubric"))):
        raise ValueError("Case requires task acceptance criteria")
    answer = expected.get("answer", {})
    fields(answer, "contains not_contains equals schema", "answer")
    for key in ("contains", "not_contains"):
        if not isinstance(answer.get(key, []), list) or any(not isinstance(v, str) for v in answer.get(key, [])):
            raise ValueError("Answer text checks require lists of strings")
    if "equals" in answer and not isinstance(answer["equals"], str):
        raise ValueError("Answer equals requires text")
    statuses = expected.get("execution_statuses", ["completed"])
    if not isinstance(statuses, list) or not statuses or set(statuses) - {"completed", "error", "timeout"}:
        raise ValueError("Unsupported expected execution status")
    if "schema" in expected.get("answer", {}):
        Draft202012Validator.check_schema(expected["answer"]["schema"])
    return case


def load_suite(path: Path, suite: str, mode="offline") -> list[dict]:
    cases = []
    for file in sorted(path.glob("*.json")):
        if file.name.endswith(".archive.json"):
            continue
        case = json.loads(file.read_text(encoding="utf-8"))
        if suite not in case.get("suites", ["core"]):
            continue
        validate(case, mode)
        cases.append(case)
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Suite is empty or contains duplicate case ids")
    return cases
