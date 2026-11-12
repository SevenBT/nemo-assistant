"""Run every selected case to a recorded terminal state."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import signal

from nemo_eval.artifacts import code_fingerprint, digest, write_json
from nemo_eval.checks import evaluate, verdict
from nemo_eval.contracts import validate
from nemo_eval.budget import validate_config


def execute_worker(case, mode, config):
    with tempfile.TemporaryDirectory(prefix="nemo-eval-control-") as directory:
        control = Path(directory)
        request, response = control / "input.json", control / "output.json"
        write_json(request, {"case": case, "mode": mode, "config": config})
        environment = dict(os.environ, LITELLM_LOCAL_MODEL_COST_MAP="True")
        if mode == "offline":
            environment = {k: v for k, v in environment.items() if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET"))}
        with tempfile.TemporaryFile(mode="w+b") as err:
            process = subprocess.Popen([sys.executable, "-m", "nemo_eval.worker", str(request), str(response)], env=environment, stderr=err, stdout=err, start_new_session=(os.name != "nt"))
            try:
                process.wait(timeout=case.get("limits", {}).get("deadline_seconds", 30))
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return {"execution_status": "timeout", "error": "Case deadline exceeded", "evidence_complete": False}
            except BaseException:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
            if process.returncode or not response.exists():
                err.seek(0)
                return {"execution_status": "error", "error": err.read(32000).decode(errors="replace"), "evidence_complete": False}
            return json.loads(response.read_text(encoding="utf-8"))


def run(cases, out: Path, *, mode="offline", config=None, executor=None):
    config = validate_config(config or {})
    for case in cases:
        validate(case, mode)
    if mode == "live" and not config.get("target"):
        raise ValueError("Live mode requires an explicit target profile")
    out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[4]
    manifest = {"schema_version": 1, "run_id": uuid.uuid4().hex, "mode": mode, "complete": False,
                "created_at": datetime.now(timezone.utc).isoformat(), "case_hash": digest(cases),
                "config_hash": digest(config), "config": config, "evaluator_version": 1,
                "python": platform.python_version(), "platform": platform.platform(),
                "code": code_fingerprint(root), "selected": [c["id"] for c in cases]}
    write_json(out / "manifest.json", manifest)
    results = []
    spent_calls = spent_output = 0
    known_cost, unknown_calls = 0.0, 0
    costs_complete = mode == "live"
    for case in cases:
        try:
            case_config = json.loads(json.dumps(config))
            if mode == "live":
                limit = config.get("budget", {})
                case_config["budget"] = {"max_model_calls": limit.get("max_model_calls", 20) - spent_calls,
                                         "max_output_tokens": limit.get("max_output_tokens", 20480) - spent_output}
                if min(case_config["budget"].values()) <= 0:
                    raise ValueError("Run budget exhausted")
            execution = executor(case) if executor else execute_worker(case, mode, case_config)
            execution["expected_statuses"] = case["expectations"].get("execution_statuses", ["completed"])
            if mode == "live":
                # A failed worker may have consumed its entire allocation; don't
                # silently grant a fresh budget when usage is unavailable.
                spent_calls += execution.get("model_calls", case_config["budget"]["max_model_calls"])
                spent_output += execution.get("output_reserved", case_config["budget"]["max_output_tokens"])
            checks = evaluate(case, execution)
            decision = verdict(execution, checks, judge_required=case.get("judge_required", False))
        except Exception as exc:
            execution = {"execution_status": "error", "error": str(exc), "evidence_complete": False}
            checks, decision = [], "error"
        cost = execution.get("cost", {})
        costs_complete = costs_complete and cost.get("complete", False)
        known_cost += cost.get("known_cost_usd", 0)
        unknown_calls += cost.get("unknown_calls", 0)
        if mode == "live" and "cost" not in execution:
            unknown_calls += 1
        result = {"case_id": case["id"], "revision": case["revision"], "verdict": decision,
                  "execution_status": execution["execution_status"], "checks": checks}
        case_dir = out / "cases" / case["id"] / "1"
        write_json(case_dir / "input.json", case)
        write_json(case_dir / "execution.json", execution)
        write_json(case_dir / "checks.json", checks)
        results.append(result)
    counts = {key: sum(r["verdict"] == key for r in results) for key in ("pass", "fail", "error", "inconclusive", "skipped")}
    summary = {"cost": {"target": {"known_cost_usd": known_cost, "unknown_calls": unknown_calls, "complete": costs_complete and unknown_calls == 0, "applicable": mode == "live", "scope": "Explicit target model attempts; judge assessed separately"}}, "budget_usage": {"model_calls": spent_calls, "output_reserved": spent_output}, "selected": len(cases), "attempted": len(results), "finished": len(results), "counts": counts, "results": results}
    write_json(out / "summary.json", summary)
    suite = ET.Element("testsuite", name="nemo-eval", tests=str(len(results)), failures=str(counts["fail"]), errors=str(counts["error"] + counts["inconclusive"]))
    for result in results:
        node = ET.SubElement(suite, "testcase", name=result["case_id"])
        if result["verdict"] != "pass":
            ET.SubElement(node, "failure" if result["verdict"] == "fail" else "error", message=result["verdict"]).text = json.dumps(result, ensure_ascii=False)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    (out / "report.md").write_text("# Evaluation report\n\n" + "\n".join(f"- {r['case_id']}: {r['verdict']}" for r in results) + "\n", encoding="utf-8")
    manifest["complete"] = True
    manifest["artifact_hashes"] = {str(p.relative_to(out)): digest(p.read_text(encoding="utf-8")) for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"}
    write_json(out / "manifest.json", manifest)
    return summary


def exit_code(summary):
    counts = summary["counts"]
    return 3 if counts["error"] or counts["inconclusive"] or counts["skipped"] else 1 if counts["fail"] else 0
