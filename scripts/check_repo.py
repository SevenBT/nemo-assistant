"""Repository consistency checks used by CI.

The checks intentionally stay dependency-light so they can run before tests and
catch release/readme drift early.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".claude",
    ".idea",
    "build",
    "dist",
    "data",
    "logs",
    "work",
    ".pytest_cache",
}
SKIP_FILES = {
    Path("config/app_config.json"),
}

STALE_PATTERNS = [
    "AI Agent",
    "AI_Agent",
    "TODO_SCREENSHOT_AI",
    "<repo-url>",
    "Ctrl+Alt+H",
]


def _iter_markdown_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.md")
        if path.relative_to(ROOT) not in SKIP_FILES
        and not any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts)
    ]


def check_metadata() -> list[str]:
    errors: list[str] = []
    try:
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - only fails on broken metadata
        errors.append(f"pyproject.toml does not parse: {exc}")

    try:
        json.loads((ROOT / "config" / "app_config.example.json").read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - only fails on broken metadata
        errors.append(f"config/app_config.example.json does not parse: {exc}")
    return errors


def check_markdown_links() -> list[str]:
    errors: list[str] = []
    md_link = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    html_img = re.compile(r"<img\s+[^>]*src=\"([^\"]+)\"", re.IGNORECASE)

    for path in _iter_markdown_files():
        # Some local-only trees (e.g. macOS AppleDouble ._ files) may carry
        # non-UTF-8 bytes; degrade gracefully instead of crashing the check.
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (md_link, html_img):
            for match in pattern.finditer(text):
                target = match.group(1).strip()
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = target.split("#", 1)[0].strip("<>")
                if not target:
                    continue
                candidate = (path.parent / target).resolve()
                if not candidate.exists():
                    line = text.count("\n", 0, match.start()) + 1
                    errors.append(f"{path.relative_to(ROOT)}:{line} missing {target}")
    return errors


def check_stale_strings() -> list[str]:
    errors: list[str] = []
    text_extensions = {".bat", ".json", ".md", ".py", ".spec", ".toml", ".txt", ".yml"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_extensions:
            continue
        rel = path.relative_to(ROOT)
        if rel == Path("scripts/check_repo.py"):
            continue
        if rel in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for stale in STALE_PATTERNS:
            if stale in text:
                errors.append(f"{rel} contains stale string: {stale}")
    return errors


def check_hiddenimports() -> list[str]:
    errors: list[str] = []
    spec = (ROOT / "Nemo_Assistant.spec").read_text(encoding="utf-8")
    in_hiddenimports = False
    hidden: list[str] = []
    for raw_line in spec.splitlines():
        line = raw_line.strip()
        if line.startswith("hiddenimports=["):
            in_hiddenimports = True
            continue
        if in_hiddenimports and line.startswith("]"):
            break
        if in_hiddenimports:
            match = re.match(r"['\"]([^'\"]+)['\"],", line)
            if match:
                hidden.append(match.group(1))

    for module_name in hidden:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"Nemo_Assistant.spec hidden import {module_name!r} is not importable: {exc}")
    return errors


def main() -> int:
    errors = []
    errors.extend(check_metadata())
    errors.extend(check_markdown_links())
    errors.extend(check_stale_strings())
    errors.extend(check_hiddenimports())

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Repository checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
