"""Quality-pipeline contracts; controlled clients are not live quality evidence."""
import copy
import json
from pathlib import Path

import pytest

from nemo_eval.artifacts import compare, digest, read_json, write_json
from nemo_eval.cli import main
from nemo_eval.contracts import validate
from nemo_eval.reporting import make_view
from nemo_eval.runner import exit_code, run
from nemo_eval.suites import Suite, select_suite
from nemo_eval.variants import resolve_variant


def live_case():
    return copy.deepcopy(select_suite("live-smoke").cases[0])


def config():
    return {"target": {"model": "controlled-target", "api_key_env": "TEST_EVAL_TARGET", "max_tokens": 100},
            "budget": {"max_model_calls": 20, "max_output_tokens": 2000}}


def execution(answer="42", **kwargs):
    return {"execution_status": "completed", "answer": answer, "tool_calls": [], "evidence_complete": True,
            "model_calls": 1, "output_reserved": 100, **kwargs}


def variant(text):
    return {"id": "test", "source": "text-file", "text": text,
            "hash": digest({"source": "text-file", "text": text})}


def test_typed_suites_and_live_tasks_cannot_consume_model_scripts():
    assert len(select_suite("offline-core").cases) == 3
    smoke, release = select_suite("live-smoke"), select_suite("live-release")
    assert (len(smoke.cases), smoke.repeat, len(release.cases), release.repeat) == (4, 1, 12, 3)
    assert {c["id"] for c in smoke.cases} <= {c["id"] for c in release.cases}
    for name, mode in (("core", "live"), ("offline-core", "live"), ("live-smoke", "offline")):
        with pytest.raises(ValueError):
            select_suite(name, mode=mode)
    for key in ("model_script", "system_prompt"):
        case = live_case()
        case["fixtures"][key] = [] if key == "model_script" else "override"
        with pytest.raises(ValueError, match="forbid"):
            validate(case, "live")


def test_variant_resolves_relative_text_once_and_rejects_empty(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("候选提示词", encoding="utf-8")
    path = tmp_path / "variant.toml"
    path.write_text("id='candidate'\n[prompt]\nsource='text-file'\npath='prompt.txt'\n", encoding="utf-8")
    frozen = resolve_variant(path)
    prompt.write_text("changed", encoding="utf-8")
    assert frozen["text"] == "候选提示词"
    assert resolve_variant(path)["hash"] != frozen["hash"]
    prompt.write_text("  ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        resolve_variant(path)


def test_repeats_preserve_failures_and_compare_pass_counts(tmp_path):
    case = live_case()
    for name, answers in (("old", ["42"] * 3), ("new", ["42", "wrong", "42"])):
        replies = iter(answers)
        summary = run([case], tmp_path / name, mode="live", config=config(), repeat=3,
                      variant=variant(name), executor=lambda _: execution(next(replies)))
        assert summary["planned"] == summary["executed"] == 3
        assert len(list((tmp_path / name / "cases/plain-answer").iterdir())) == 3
    rows = compare(tmp_path / "new", tmp_path / "old", change="prompt")
    assert (rows[0]["baseline_passed"], rows[0]["current_passed"], rows[0]["delta"], rows[0]["change"]) == (3, 2, -1, "regressed")
    with pytest.raises(ValueError, match="requires --change"):
        compare(tmp_path / "new", tmp_path / "old")
    case["revision"] += 1
    run([case], tmp_path / "changed", mode="live", config=config(), repeat=3,
        variant=variant("new"), executor=lambda _: execution())
    with pytest.raises(ValueError, match="case_hash"):
        compare(tmp_path / "changed", tmp_path / "old", change="prompt")


def test_budget_is_shared_across_repeats_and_unexecuted_tasks_stay_in_denominator(tmp_path):
    calls = []
    cfg = config()
    cfg["budget"] = {"max_model_calls": 1, "max_output_tokens": 100}
    def execute(_):
        calls.append(1)
        return execution()
    summary = run([live_case()], tmp_path / "limited", mode="live", config=cfg, repeat=3, executor=execute)
    assert len(calls) == 1
    assert summary["planned"] == 3 and summary["executed"] == 1
    assert summary["task_pass_rate"] == 1 / 3
    assert [r["execution_status"] for r in summary["results"]] == ["completed", "not_executed", "not_executed"]
    assert summary["budget_usage"]["model_calls"] == 1
    assert exit_code(summary) == 3


def test_worker_failure_stops_unknown_spending_and_interrupt_records_remaining_plan(tmp_path):
    calls = []
    def broken(_):
        calls.append(1)
        raise RuntimeError("worker failed after dispatch")
    summary = run([live_case()], tmp_path / "broken", mode="live", config=config(), repeat=3, executor=broken)
    assert len(calls) == 1 and summary["planned"] == 3
    assert summary["budget_usage"]["uncertain"]
    def interrupt(_):
        raise KeyboardInterrupt
    summary = run([live_case()], tmp_path / "interrupt", mode="live", config=config(), repeat=3, executor=interrupt)
    assert summary["planned"] == 3
    assert summary["results"][-1]["reason"] == "interrupted"
    assert exit_code(summary) == 130


def test_changed_raw_evidence_cannot_be_judged_or_compared(tmp_path):
    directory = tmp_path / "run"
    run([live_case()], directory, mode="live", config=config(), executor=lambda _: execution())
    path = directory / "cases/plain-answer/1/execution.json"
    data = read_json(path)
    data["answer"] = "edited"
    write_json(path, data)
    with pytest.raises(ValueError, match="evidence changed"):
        make_view(directory)


def test_source_fingerprints_reject_evaluator_and_undeclared_application_changes(tmp_path):
    for name in ("old", "new"):
        run([live_case()], tmp_path / name, mode="live", config=config(), executor=lambda _: execution())
    path = tmp_path / "new/manifest.json"
    data = read_json(path)
    assert data["code"]["application_hash"] and data["code"]["evaluator_hash"]
    data["code"]["application_hash"] = "changed"
    write_json(path, data)
    with pytest.raises(ValueError, match="application_hash"):
        compare(tmp_path / "new", tmp_path / "old", change="prompt")
    assert compare(tmp_path / "new", tmp_path / "old", change="application")
    data["code"]["evaluator_hash"] = "changed"
    write_json(path, data)
    with pytest.raises(ValueError, match="evaluator_hash"):
        compare(tmp_path / "new", tmp_path / "old", change="application")


def test_single_regression_command_creates_unique_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["regression"]) == 0
    assert main(["regression"]) == 0
    directories = list((tmp_path / "artifacts/eval/offline").iterdir())
    assert len(directories) == 2
    assert all((p / "reports/initial/report.md").is_file() for p in directories)


def test_pipeline_preflight_never_dispatches_wrong_suite_or_missing_judge(tmp_path, monkeypatch):
    import nemo_eval.cli as cli
    dispatched = []
    monkeypatch.setattr(cli, "run", lambda *a, **kw: dispatched.append(1))
    monkeypatch.setenv("TEST_EVAL_TARGET", "controlled-test-credential")
    path = tmp_path / "target.toml"
    path.write_text("[target]\nmodel='controlled'\napi_key_env='TEST_EVAL_TARGET'\n[budget]\nmax_model_calls=100\nmax_output_tokens=100000\n", encoding="utf-8")
    assert main(["regression", "--suite", "live-smoke"]) == 2
    assert main(["evaluate", "--suite", "offline-core", "--config", str(path)]) == 2
    # Explicitly direct default config lookup to an empty local config directory.
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    assert main(["evaluate", "--config", str(path), "--out", str(tmp_path / "no-run")]) == 2
    judge_path = tmp_path / "judge.toml"
    judge_path.write_text("[judge]\nmodel='controlled-judge'\napi_key_env='TEST_EVAL_JUDGE'\nmax_tokens=100\n[budget]\nmax_model_calls=1\nmax_output_tokens=100\n", encoding="utf-8")
    monkeypatch.setenv("TEST_EVAL_JUDGE", "controlled-test-credential")
    assert main(["evaluate", "--config", str(path), "--judge-config", str(judge_path), "--out", str(tmp_path / "no-run")]) == 2
    assert not dispatched and not (tmp_path / "no-run").exists()


def test_incompatible_baseline_fails_before_candidate_dispatch(tmp_path, monkeypatch):
    import nemo_eval.cli as cli
    case = live_case()
    baseline = tmp_path / "baseline"
    run([case], baseline, mode="live", config=config(), executor=lambda _: execution())
    monkeypatch.setattr(cli, "select_suite", lambda *a, **kw: Suite("controlled", "live", 1, [case]))
    dispatched = []
    monkeypatch.setattr(cli, "run", lambda *a, **kw: dispatched.append(1))
    monkeypatch.setenv("TEST_EVAL_TARGET", "controlled-test-credential")
    cfg = tmp_path / "target.toml"
    cfg.write_text("[target]\nmodel='different-model'\napi_key_env='TEST_EVAL_TARGET'\nmax_tokens=100\n[budget]\nmax_model_calls=20\nmax_output_tokens=2000\n", encoding="utf-8")
    candidate = tmp_path / "candidate"
    assert main(["evaluate", "--config", str(cfg), "--out", str(candidate), "--baseline", str(baseline), "--change", "prompt"]) == 2
    assert not dispatched and not candidate.exists()


def test_single_live_command_runs_production_tools_repeats_judge_and_comparison(tmp_path, monkeypatch):
    from nemo_eval.adapters import nemo
    import nemo_eval.cli as cli
    import nemo_eval.runner as runner
    from nemo_eval.judge import assess_run

    case = copy.deepcopy(next(c for c in select_suite("live-release").cases if c["id"] == "save-file"))
    case["rubric"] = [{"id": "honest", "description": "Answer agrees with actual tool results"}]
    case["judge_required"] = True
    monkeypatch.setattr(cli, "select_suite", lambda *a, **kw: Suite("controlled", "live", 2, [case]))
    monkeypatch.setenv("TEST_EVAL_TARGET", "controlled-test-credential")
    monkeypatch.setenv("TEST_EVAL_JUDGE", "controlled-test-credential")
    cfg = tmp_path / "target.toml"
    cfg.write_text("[target]\nmodel='controlled-target'\napi_key_env='TEST_EVAL_TARGET'\nmax_tokens=100\n[budget]\nmax_model_calls=10\nmax_output_tokens=1000\n", encoding="utf-8")
    judge_cfg = tmp_path / "judge.toml"
    judge_cfg.write_text("[judge]\nmodel='controlled-judge'\napi_key_env='TEST_EVAL_JUDGE'\nmax_tokens=100\n[budget]\nmax_model_calls=10\nmax_output_tokens=1000\n", encoding="utf-8")
    prompts, workspace_files, judge_calls = [], [], []
    def gateway(profile, logger):
        class ControlledGateway:
            def chat_stream(self, messages, **kwargs):
                logger.write({"attempt_id": str(len(prompts) + len(judge_calls)), "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
                if profile["model"] == "controlled-judge":
                    payload = json.loads(messages[1]["content"])
                    assert "step:step-1" in payload["evidence"]
                    judge_calls.append(1)
                    yield {"type": "text", "delta": json.dumps({"status": "scored", "reason": "checked", "criteria": [{"id": "honest", "verdict": "pass", "reason": "matches tool", "evidence_ids": ["artifact:result.txt"]}]})}
                else:
                    prompts.append(messages[0]["content"])
                    if any(m["role"] == "tool" for m in messages):
                        yield {"type": "text", "delta": "已保存"}
                    else:
                        yield {"type": "tool_call", "id": "save", "name": "save_file", "arguments": {"filename": "result.txt", "content": "评估成功"}}
                yield {"type": "done"}
        return ControlledGateway()
    monkeypatch.setattr(nemo, "make_live_gateway", gateway)
    def worker(case, mode, config, variant=None):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            result = nemo.execute(case, Path(directory), mode, config, variant)
            workspace_files.append(result["artifacts"]["result.txt"]["text"])
            return result
    monkeypatch.setattr(runner, "execute_worker", worker)
    old, new = tmp_path / "old", tmp_path / "new"
    common = ["evaluate", "--config", str(cfg), "--judge-config", str(judge_cfg)]
    assert main(common + ["--out", str(old)]) == 0
    prompt = tmp_path / "candidate.txt"
    prompt.write_text("候选提示词：依据实际工具结果回答。", encoding="utf-8")
    variant_path = tmp_path / "candidate.toml"
    variant_path.write_text("id='candidate'\n[prompt]\nsource='text-file'\npath='candidate.txt'\n", encoding="utf-8")
    assert main(common + ["--out", str(new), "--baseline", str(old), "--change", "prompt", "--variant", str(variant_path)]) == 0
    assert len(workspace_files) == 4 and workspace_files == ["评估成功"] * 4
    assert len(judge_calls) == 4
    assert all("智能AI助手" in p for p in prompts[:4])
    assert all("候选提示词" in p for p in prompts[4:])
    initial = read_json(new / "pipeline.json")["assessment_id"]
    assert make_view(new, initial)["counts"]["pass"] == 2
    assert (new / "comparisons/baseline/report.md").exists()
    raw_before = (new / "summary.json").read_bytes()
    assess_run(new, read_json_config(judge_cfg))
    assert (new / "summary.json").read_bytes() == raw_before
    assert read_json(new / "pipeline.json")["assessment_id"] == initial
    assert make_view(new, initial)["counts"]["pass"] == 2


def test_required_judge_never_overrides_hard_failure(tmp_path, monkeypatch):
    from nemo_eval.adapters import nemo
    from nemo_eval.judge import assess_run
    case = live_case()
    case.update(rubric=[{"id": "style", "description": "Clear answer"}], judge_required=True)
    directory = tmp_path / "failed"
    run([case], directory, mode="live", config=config(), executor=lambda _: execution("wrong"))
    class Gateway:
        def chat_stream(self, *args, **kwargs):
            yield {"type": "text", "delta": json.dumps({"status": "scored", "reason": "style", "criteria": [{"id": "style", "verdict": "pass", "reason": "clear", "evidence_ids": ["answer"]}]})}
            yield {"type": "done"}
    monkeypatch.setattr(nemo, "make_live_gateway", lambda *a: Gateway())
    rows = assess_run(directory, {"judge": {"model": "judge", "api_key_env": "TEST_JUDGE"}})
    assert make_view(directory, rows[0]["assessment_id"])["counts"]["fail"] == 1


def test_live_command_uses_real_worker_and_http_gateway_without_paid_provider(tmp_path, monkeypatch):
    """A local SSE endpoint verifies the process/wire path, not model quality."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import subprocess
    import sys
    import threading
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            chunks = [
                {"choices": [{"index": 0, "delta": {"content": "42"}, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}},
            ]
            body = ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    case = live_case()
    case["suites"] = ["wire-smoke"]
    directory = tmp_path / "cases"
    directory.mkdir()
    write_json(directory / "task.json", case)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_EVAL_TARGET", "controlled-local-credential")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    cfg = tmp_path / "target.toml"
    cfg.write_text(f"[target]\nmodel='controlled-wire'\nprovider='openai'\nbase_url='http://127.0.0.1:{server.server_port}/v1'\napi_protocol='openai_chat'\napi_key_env='TEST_EVAL_TARGET'\nmax_tokens=100\n[budget]\nmax_model_calls=2\nmax_output_tokens=200\n", encoding="utf-8")
    out = tmp_path / "wire-run"
    try:
        completed = subprocess.run([sys.executable, "-m", "nemo_eval.cli", "evaluate", "--cases", str(directory),
                                    "--suite", "wire-smoke", "--config", str(cfg), "--repeat", "2", "--out", str(out)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(requests) == 2
    assert all(r["messages"][0]["role"] == "system" and r["tools"] for r in requests)
    view = make_view(out)
    assert view["counts"]["pass"] == 2
    assert view["statistics"]["usage"]["prompt_tokens"]["known_total"] == 8
    assert (out / "reports/initial/report.md").is_file()


def read_json_config(path):
    import tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))
