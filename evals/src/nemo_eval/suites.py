"""Typed suites keep scripted regressions separate from live tasks."""
from dataclasses import dataclass
import json
from pathlib import Path
import tomllib

from nemo_eval.contracts import load_suite, safe_path, validate

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Suite:
    name: str
    mode: str
    repeat: int
    cases: list[dict]


def select_suite(name, *, mode=None, cases_dir=None):
    original_name = name
    if name == "core":
        if mode == "live":
            raise ValueError("core is offline-only; use evaluate --suite live-smoke or live-release")
        name = "offline-core"
    if cases_dir is not None:
        if mode is None:
            raise ValueError("Custom --cases requires an explicit mode")
        cases = load_suite(cases_dir, original_name, mode)
        return Suite(name, mode, 1, cases)
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError("Invalid suite name")
    spec = tomllib.loads((ROOT / "suites" / f"{name}.toml").read_text(encoding="utf-8"))
    if set(spec) != {"type", "repeat", "cases"} or spec["type"] not in {"offline", "live"}:
        raise ValueError("Invalid suite manifest")
    if mode is not None and spec["type"] != mode:
        raise ValueError(f"Suite {name} is {spec['type']}, not {mode}")
    repeat = spec["repeat"]
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 100:
        raise ValueError("Suite repeat must be between 1 and 100")
    if not isinstance(spec["cases"], list) or not spec["cases"]:
        raise ValueError("Suite requires cases")
    cases = []
    for filename in spec["cases"]:
        path = safe_path(ROOT, filename)
        case = json.loads(path.read_text(encoding="utf-8"))
        validate(case, spec["type"])
        cases.append(case)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case ids")
    return Suite(name, spec["type"], repeat, cases)
