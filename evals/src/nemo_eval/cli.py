"""Single-command offline regression and live evaluation pipelines."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid

from nemo_eval.artifacts import compare, read_json, write_json, verify_run
from nemo_eval.budget import validate_config
from nemo_eval.runner import exit_code, run
from nemo_eval.suites import ROOT, select_suite


def read_config(path):
    if not path.is_file():
        raise ValueError(f"Configuration not found: {path}. Copy the corresponding .example.toml and set its model/key environment variable first.")
    return validate_config(tomllib.loads(path.read_text(encoding="utf-8")))


def preflight_profile(config, name):
    validate_config(config)
    profile = config.get(name)
    if not profile or not os.environ.get(profile["api_key_env"]):
        raise ValueError(f"{name}: configure model and populate api_key_env before running")
    if set(config.get("budget", {})) != {"max_model_calls", "max_output_tokens"}:
        raise ValueError(f"{name}: explicit max_model_calls and max_output_tokens budgets required")
    if config["budget"]["max_output_tokens"] < profile.get("max_tokens", 1024):
        raise ValueError(f"{name}: output budget cannot cover one request")
    if profile["model"].startswith("REPLACE_"):
        raise ValueError(f"{name}: replace the example model id")


def new_output(mode):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("artifacts/eval") / mode / f"{stamp}-{uuid.uuid4().hex[:8]}"


def initial_assessment(run_dir):
    pointer = run_dir / "pipeline.json"
    return read_json(pointer).get("assessment_id") if pointer.is_file() else None


def save_comparison(rows, out):
    from nemo_eval.comparison import markdown
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "comparison.json", rows)
    (out / "report.md").write_text(markdown(rows), encoding="utf-8")


def pipeline(args):
    from nemo_eval.reporting import save_report
    from nemo_eval.variants import resolve_variant
    live = args.command == "evaluate"
    mode = "live" if live else "offline"
    suite = select_suite(args.suite, mode=mode, cases_dir=args.cases)
    repeat = args.repeat if args.repeat is not None else suite.repeat
    config, judge_config, variant = {}, None, None
    if live:
        config = read_config(args.config or ROOT / "configs/live.toml")
        if config.get("judge"):
            judge_config = {"judge": config.pop("judge"), "budget": dict(config.get("budget", {}))}
        preflight_profile(config, "target")
        variant = resolve_variant(args.variant, language=config.get("language", "zh"))
        needs_judge = any(c.get("judge_required") for c in suite.cases)
        judge_path = args.judge_config or ROOT / "configs/judge.toml"
        if args.judge_config or (any(c.get("rubric") for c in suite.cases) and judge_path.is_file()):
            judge_config = read_config(judge_path)
        if needs_judge and judge_config is None:
            raise ValueError("This suite requires Judge assessment. Configure evals/configs/judge.toml or --judge-config before any paid target calls. Use live-smoke for tasks needing no Judge.")
        if judge_config:
            preflight_profile(judge_config, "judge")
        if args.baseline and not args.change:
            raise ValueError("--baseline requires --change prompt or application")
    out = args.out or new_output(mode)
    if out.exists():
        raise ValueError("Output directory must be new")
    if isinstance(repeat, bool) or not 1 <= repeat <= 100:
        raise ValueError("repeat must be between 1 and 100")
    if judge_config:
        required_calls = sum(bool(c.get("judge_required")) for c in suite.cases) * repeat
        required_output = required_calls * judge_config["judge"].get("max_tokens", 1024)
        if (judge_config["budget"]["max_model_calls"] < required_calls or
                judge_config["budget"]["max_output_tokens"] < required_output):
            raise ValueError("Judge budget cannot cover required assessments; increase it or reduce --repeat before target calls")
    baseline_assessment = None
    if live and args.baseline:
        from nemo_eval.reporting import make_view
        from nemo_eval.comparison import compatible_conditions
        from nemo_eval.runner import make_manifest
        baseline_assessment = args.baseline_assessment or initial_assessment(args.baseline)
        baseline_view = make_view(args.baseline, baseline_assessment)
        compatible_conditions(make_manifest(suite.cases, mode, config, repeat, variant, suite.name),
                              verify_run(args.baseline), change=args.change)
        if baseline_view["executed"] != baseline_view["planned"] or baseline_view["counts"]["inconclusive"]:
            raise ValueError("Baseline has unexecuted tasks or missing required assessments")
        expects_judge = bool(judge_config and any(c.get("rubric") for c in suite.cases))
        if bool(baseline_view["judge"]) != expects_judge:
            raise ValueError("Baseline and candidate must select compatible Judge assessments")
        if baseline_view["judge"]:
            from nemo_eval.judge import profile_hash
            if judge_config is None or baseline_view["judge"]["judge_hash"] != profile_hash(judge_config["judge"]):
                raise ValueError("Incompatible baseline: judge_hash")
    print(f"{'Live-model evaluation' if live else 'Offline regression'}: {suite.name}, {len(suite.cases)} cases x {repeat} repeats = {len(suite.cases) * repeat} tasks", flush=True)
    if live:
        print(f"Target budget: {config['budget']}; Judge budget: {judge_config['budget'] if judge_config else 'not required'}. Not an input-token or dollar ceiling.", flush=True)
    print(f"Output: {out.resolve()}", flush=True)
    def progress(result, finished, total):
        print(f"[{finished}/{total}] {result['case_id']} repeat {result['repeat_id']}: {result['verdict']}", flush=True)
    summary = run(suite.cases, out, mode=mode, config=config, repeat=repeat, variant=variant, suite=suite.name, progress=progress)
    assessment_id = None
    if live and judge_config and any(c.get("rubric") for c in suite.cases) and not summary.get("interrupted"):
        from nemo_eval.judge import assess_run
        print("Assessing recorded task evidence with Judge...", flush=True)
        assessments = assess_run(out, judge_config)
        if assessments:
            assessment_id = assessments[0]["assessment_id"]
    report_dir = out / "reports" / "initial"
    view = save_report(out, assessment=assessment_id, out=report_dir)
    # Freeze this pipeline's assessment; subsequent rejudging never updates it.
    write_json(out / "pipeline.json", {"run_id": summary["run_id"], "assessment_id": assessment_id,
                                      "report": "reports/initial/report.md"})
    print(f"Report: {(report_dir / 'report.md').resolve()}", flush=True)
    code = exit_code(view)
    if live and args.baseline and code not in {3, 130}:
        rows = compare(out, args.baseline, change=args.change, current_assessment=assessment_id,
                       baseline_assessment=baseline_assessment)
        compare_dir = out / "comparisons" / "baseline"
        save_comparison(rows, compare_dir)
        print(f"Comparison: {(compare_dir / 'report.md').resolve()}", flush=True)
        if any(r["delta"] < 0 for r in rows):
            code = 1
    print(json.dumps({"counts": view["counts"], "stable_cases": view["stable_cases"], "planned": view["planned"],
                      "executed": view["executed"], "assessment_id": assessment_id}, ensure_ascii=False, indent=2))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nemo-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, default in (("regression", "offline-core"), ("evaluate", "live-release")):
        sub = commands.add_parser(name)
        sub.add_argument("--suite", default=default)
        sub.add_argument("--cases", type=Path)
        sub.add_argument("--repeat", type=int)
        sub.add_argument("--out", type=Path)
        if name == "evaluate":
            sub.add_argument("--config", type=Path)
            sub.add_argument("--judge-config", type=Path)
            sub.add_argument("--variant", type=Path)
            sub.add_argument("--baseline", type=Path)
            sub.add_argument("--baseline-assessment")
            sub.add_argument("--change", choices=["prompt", "application"])
    for name in ("validate", "run"):
        sub = commands.add_parser(name)
        sub.add_argument("--cases", type=Path)
        sub.add_argument("--suite", default="core")
        sub.add_argument("--mode", choices=["offline", "live"])
        if name == "run":
            sub.add_argument("--out", type=Path, required=True)
            sub.add_argument("--config", type=Path)
    sub = commands.add_parser("judge")
    sub.add_argument("--run", type=Path, required=True)
    sub.add_argument("--config", type=Path, required=True)
    sub = commands.add_parser("report")
    sub.add_argument("--run", type=Path, required=True)
    sub.add_argument("--assessment")
    sub.add_argument("--out", type=Path)
    sub = commands.add_parser("compare")
    sub.add_argument("--current", type=Path, required=True)
    sub.add_argument("--baseline", type=Path, required=True)
    sub.add_argument("--change", choices=["prompt", "application"])
    sub.add_argument("--current-assessment")
    sub.add_argument("--baseline-assessment")
    sub.add_argument("--out", type=Path)
    sub.add_argument("--allow-change", action="append", default=[])
    sub = commands.add_parser("import-legacy")
    sub.add_argument("--db", type=Path, required=True)
    sub.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"regression", "evaluate"}:
            return pipeline(args)
        if args.command in {"run", "validate"}:
            mode = args.mode or ("offline" if args.command == "run" or args.cases else None)
            suite = select_suite(args.suite, mode=mode, cases_dir=args.cases)
            if args.command == "validate":
                print(f"Validated {len(suite.cases)} {suite.mode} cases")
                return 0
            if suite.mode != "offline":
                raise ValueError("Use evaluate for live-model evaluation and automatic assessments")
            print("Compatibility entry: prefer nemo-eval regression", file=sys.stderr)
            config = read_config(args.config) if args.config else {}
            summary = run(suite.cases, args.out, mode="offline", config=config, suite=suite.name)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return exit_code(summary)
        if args.command == "judge":
            from nemo_eval.judge import assess_run
            config = read_config(args.config)
            preflight_profile(config, "judge")
            results = assess_run(args.run, config)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            if any(r.get("interrupted") for r in results):
                return 130
            if any(r["status"] == "error" or (r.get("required") and r["verdict"] in {"error", "inconclusive"}) for r in results):
                return 3
            return 1 if any(r.get("required") and r["verdict"] == "fail" for r in results) else 0
        if args.command == "compare":
            rows = compare(args.current, args.baseline, allow_changes=args.allow_change, change=args.change,
                           current_assessment=args.current_assessment or initial_assessment(args.current),
                           baseline_assessment=args.baseline_assessment or initial_assessment(args.baseline))
            if args.out:
                save_comparison(rows, args.out)
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 1 if any(r.get("delta", 0) < 0 or (r["baseline"] == "pass" and r["current"] != "pass") for r in rows) else 0
        if args.command == "report":
            manifest = read_json(args.run / "manifest.json")
            if manifest.get("schema_version", 1) < 2:
                print((args.run / "report.md").read_text(encoding="utf-8"))
            else:
                from nemo_eval.reporting import markdown, save_report
                view = save_report(args.run, assessment=args.assessment or initial_assessment(args.run), out=args.out)
                print(markdown(view))
            return 0
        if args.command == "import-legacy":
            from nemo_eval.adapters.legacy import import_legacy
            print(json.dumps(import_legacy(args.db, args.out)))
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
