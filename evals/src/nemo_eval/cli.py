"""Explicit offline/live CLI; reports never trigger model execution."""
import argparse
import json
import sys
import tomllib
from pathlib import Path

from nemo_eval.artifacts import compare
from nemo_eval.contracts import load_suite
from nemo_eval.runner import exit_code, run


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nemo-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[2] / "cases")
        sub.add_argument("--suite", default="core")
        sub.add_argument("--mode", choices=["offline", "live"], default="offline")
        if command == "run":
            sub.add_argument("--out", type=Path, required=True)
            sub.add_argument("--config", type=Path)
    sub = commands.add_parser("judge")
    sub.add_argument("--run", type=Path, required=True)
    sub.add_argument("--config", type=Path, required=True)
    sub = commands.add_parser("report")
    sub.add_argument("--run", type=Path, required=True)
    sub = commands.add_parser("compare")
    sub.add_argument("--current", type=Path, required=True)
    sub.add_argument("--baseline", type=Path, required=True)
    sub.add_argument("--allow-change", action="append", default=[], help="Explicit target configuration dimension, e.g. target.model")
    sub = commands.add_parser("import-legacy")
    sub.add_argument("--db", type=Path, required=True)
    sub.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"run", "validate"}:
            cases = load_suite(args.cases, args.suite, args.mode)
            if args.command == "validate":
                print(f"Validated {len(cases)} cases")
                return 0
            config = tomllib.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
            if args.mode == "offline" and config.get("target"):
                raise ValueError("Offline mode rejects live target configuration")
            summary = run(cases, args.out, mode=args.mode, config=config)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return exit_code(summary)
        if args.command == "judge":
            from nemo_eval.judge import assess_run
            results = assess_run(args.run, tomllib.loads(args.config.read_text(encoding="utf-8")))
            print(json.dumps(results, ensure_ascii=False, indent=2))
            if any(r["status"] == "error" or (r.get("required") and r["verdict"] in {"error", "inconclusive"}) for r in results):
                return 3
            return 1 if any(r.get("required") and r["verdict"] == "fail" for r in results) else 0
        if args.command == "compare":
            rows = compare(args.current, args.baseline, allow_changes=args.allow_change)
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 1 if any(r["baseline"] == "pass" and r["current"] != "pass" for r in rows) else 0
        if args.command == "report":
            print((args.run / "report.md").read_text(encoding="utf-8"))
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
