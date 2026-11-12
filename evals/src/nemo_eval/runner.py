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
import time

from nemo_eval.artifacts import code_fingerprint, digest, write_json
from nemo_eval.checks import evaluate, verdict
from nemo_eval.contracts import validate
from nemo_eval.budget import validate_config


def execute_worker(case, mode, config, variant=None):
    with tempfile.TemporaryDirectory(prefix="nemo-eval-control-") as directory:
        control = Path(directory)
        request, response = control / "input.json", control / "output.json"
        write_json(request, {"case": case, "mode": mode, "config": config, "variant": variant})
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


def make_manifest(cases, mode, config, repeat, variant, suite):
    """Build the same compatibility conditions for preflight and execution."""
    root = Path(__file__).resolve().parents[3]
    plan = [{"case_id": c["id"], "repeat_id": n} for n in range(1, repeat + 1) for c in cases]
    return {"schema_version": 2, "run_id": uuid.uuid4().hex, "mode": mode, "complete": False,
                "created_at": datetime.now(timezone.utc).isoformat(), "case_hash": digest(cases),
                "config_hash": digest(config), "config": config, "evaluator_version": 2,
                "suite": suite, "repeat": repeat, "plan": plan, "variant": variant,
                "variant_hash": variant["hash"] if variant else None,
                "environment_hash": digest({"language": config.get("language", "zh"),
                                            "fixtures": [c["fixtures"] for c in cases],
                                            "limits": [c.get("limits", {}) for c in cases]}),
                "python": platform.python_version(), "platform": platform.platform(),
                "code": code_fingerprint(root), "selected": [c["id"] for c in cases]}


def run(cases, out: Path, *, mode="offline", config=None, executor=None, repeat=1, variant=None, suite=None, progress=None):
    from nemo_eval.reporting import aggregate, execution_statistics, markdown
    from nemo_eval.variants import resolve_variant
    config = validate_config(config or {})
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 100:
        raise ValueError("repeat must be between 1 and 100")
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Cases must be nonempty with unique ids")
    for case in cases:
        validate(case, mode)
    if mode == "offline" and (config.get("target") or config.get("judge") or variant):
        raise ValueError("Offline regression rejects live profiles and prompt variants")
    if mode == "live" and not config.get("target"):
        raise ValueError("Live mode requires an explicit target profile")
    if mode == "live":
        variant = variant or resolve_variant(language=config.get("language", "zh"))
        if not executor and not os.environ.get(config["target"]["api_key_env"]):
            raise ValueError("Target api_key_env is not populated")
    manifest = make_manifest(cases, mode, config, repeat, variant, suite)
    out.mkdir(parents=True, exist_ok=False)
    plan = manifest["plan"]
    write_json(out / "manifest.json", manifest)
    results, executions = [], []
    spent_calls = spent_output = 0
    halt_reason = None
    interrupted = False
    by_id = {c["id"]: c for c in cases}
    for planned in plan:
        case = by_id[planned["case_id"]]
        started = time.perf_counter()
        case_config = json.loads(json.dumps(config))
        invoked = False
        reason = None
        try:
            if mode == "live":
                limit = config.get("budget", {})
                case_config["budget"] = {"max_model_calls": limit.get("max_model_calls", 20) - spent_calls,
                                         "max_output_tokens": limit.get("max_output_tokens", 20480) - spent_output}
                if (case_config["budget"]["max_model_calls"] <= 0 or
                        case_config["budget"]["max_output_tokens"] < config["target"].get("max_tokens", 1024)):
                    halt_reason = halt_reason or "budget_exhausted"
            if halt_reason:
                execution = {"execution_status": "not_executed", "error": halt_reason, "evidence_complete": False}
                reason = halt_reason
            else:
                invoked = True
                execution = executor(case) if executor else execute_worker(case, mode, case_config, variant)
            execution["expected_statuses"] = case["expectations"].get("execution_statuses", ["completed"])
            checks = evaluate(case, execution)
            decision = verdict(execution, checks, judge_required=case.get("judge_required", False))
        except KeyboardInterrupt:
            interrupted = True
            halt_reason = reason = "interrupted"
            execution = {"execution_status": "interrupted", "error": reason, "evidence_complete": False}
            checks, decision = [], "error"
        except Exception as exc:
            execution = {"execution_status": "error", "error": str(exc), "evidence_complete": False}
            checks, decision = [], "error"
        if mode == "live" and invoked:
            # An unresponsive worker may have spent its entire remaining allocation.
            # Retain that uncertainty and stop; never grant a fresh repeat budget.
            if "model_calls" not in execution or "output_reserved" not in execution:
                halt_reason = halt_reason or "unknown_worker_usage"
            spent_calls += execution.get("model_calls", case_config["budget"]["max_model_calls"])
            spent_output += execution.get("output_reserved", case_config["budget"]["max_output_tokens"])
        execution["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        reason = reason or ("accepted" if decision == "pass" else "acceptance_failed" if decision == "fail"
                            else "required_assessment_missing" if decision == "inconclusive" and case.get("judge_required")
                            else execution.get("error") or "missing_evidence")
        result = {**planned, "revision": case["revision"], "verdict": decision,
                  "hard_verdict": verdict(execution, checks), "reason": reason,
                  "priority": case.get("priority", "normal"), "category": case.get("category", "uncategorized"),
                  "execution_status": execution["execution_status"], "checks": checks}
        case_dir = out / "cases" / case["id"] / str(planned["repeat_id"])
        write_json(case_dir / "input.json", case)
        write_json(case_dir / "execution.json", execution)
        write_json(case_dir / "checks.json", checks)
        results.append(result)
        executions.append(execution)
        if progress:
            progress(result, len(results), len(plan))
    costs = [e.get("cost", {}) for e in executions if e["execution_status"] != "not_executed"]
    provider_amounts = {}
    for cost in costs:
        for currency, amount in cost.get("provider_reported", {}).items():
            provider_amounts[currency] = provider_amounts.get(currency, 0) + amount
    known_cost = sum(c.get("known_cost_usd", 0) for c in costs)
    unknown_calls = sum(c.get("unknown_calls", 1) for c in costs)
    aggregated = aggregate(results)
    counts = aggregated["counts"]
    summary = {**aggregated, "mode": mode, "run_id": manifest["run_id"], "suite": suite,
               "cost": {"target": {"known_cost_usd": known_cost, "estimated_cost_usd": known_cost,
                                   "provider_reported": provider_amounts, "unknown_calls": unknown_calls,
                                   "provider_unknown_calls": sum(c.get("provider_unknown_calls", 1) for c in costs),
                                   "complete": mode == "live" and all(c.get("complete", False) for c in costs) and not halt_reason,
                                   "applicable": mode == "live", "scope": "Target attempts only; configured estimates separate from provider charges"}},
               "budget_usage": {"model_calls": spent_calls, "output_reserved": spent_output, "uncertain": halt_reason == "unknown_worker_usage"},
               "selected": len(cases), "attempted": aggregated["executed"], "finished": len(results),
               "interrupted": interrupted, "statistics": execution_statistics(executions), "results": results}
    write_json(out / "summary.json", summary)
    suite = ET.Element("testsuite", name="nemo-eval", tests=str(len(results)), failures=str(counts["fail"]), errors=str(counts["error"] + counts["inconclusive"]))
    for result in results:
        node = ET.SubElement(suite, "testcase", name=f"{result['case_id']}[{result['repeat_id']}]")
        if result["verdict"] != "pass":
            ET.SubElement(node, "failure" if result["verdict"] == "fail" else "error", message=result["verdict"]).text = json.dumps(result, ensure_ascii=False)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    (out / "report.md").write_text(markdown(summary), encoding="utf-8")
    manifest["complete"] = True
    manifest["artifact_hashes"] = {p.relative_to(out).as_posix(): digest(p.read_text(encoding="utf-8")) for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"}
    write_json(out / "manifest.json", manifest)
    return summary


def exit_code(summary):
    if summary.get("interrupted"):
        return 130
    counts = summary["counts"]
    return 3 if counts["error"] or counts["inconclusive"] or counts["skipped"] else 1 if counts["fail"] else 0
