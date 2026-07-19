"""Validate release metadata and extract notes for GitHub Releases."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>[^]]+)] - (?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.MULTILINE,
)


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as file:
        data = tomllib.load(file)
    return str(data["project"]["version"])


def _locked_project_version(root: Path) -> str:
    with (root / "uv.lock").open("rb") as file:
        data = tomllib.load(file)

    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise ValueError("uv.lock package entries must be an array")

    matching_packages: list[dict[str, object]] = []
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock package entry must be a table")
        source = package.get("source", {})
        if not isinstance(source, dict):
            raise ValueError("uv.lock package source must be a table")
        if package.get("name") == "nemo-assistant" and source.get("editable") == ".":
            matching_packages.append(package)

    if len(matching_packages) != 1:
        raise ValueError("uv.lock must contain one editable nemo-assistant package")
    return str(matching_packages[0]["version"])


def extract_release_notes(root: Path, version: str) -> str:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = list(RELEASE_HEADING_PATTERN.finditer(changelog))
    matches = [
        (index, heading)
        for index, heading in enumerate(headings)
        if heading.group("version") == version
    ]
    if len(matches) != 1:
        return ""

    index, heading = matches[0]
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    return changelog[heading.end() : end].strip() + "\n"


def _release_heading_errors(
    headings: list[re.Match[str]], version: str
) -> list[str]:
    matching_headings = [
        heading for heading in headings if heading.group("version") == version
    ]
    errors: list[str] = []
    for heading in matching_headings:
        release_date = heading.group("date")
        try:
            date.fromisoformat(release_date)
        except ValueError:
            errors.append(
                f"CHANGELOG.md release date {release_date} for version "
                f"{version} is invalid"
            )
    if not matching_headings:
        errors.append(
            f"CHANGELOG.md has no dated release heading for version {version}"
        )
    elif len(matching_headings) > 1:
        errors.append(
            f"CHANGELOG.md has multiple dated release headings for version {version}"
        )
    return errors


def validate_release(root: Path, tag: str) -> list[str]:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        return [f"invalid release tag {tag!r}; expected vMAJOR.MINOR.PATCH"]

    version = tag.removeprefix("v")
    errors: list[str] = []

    project_version = _project_version(root)
    if project_version != version:
        errors.append(
            f"tag version {version} does not match pyproject.toml version "
            f"{project_version}"
        )

    lock_version = _locked_project_version(root)
    if lock_version != version:
        errors.append(
            f"tag version {version} does not match uv.lock project version "
            f"{lock_version}"
        )

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = list(RELEASE_HEADING_PATTERN.finditer(changelog))
    heading_errors = _release_heading_errors(headings, version)
    errors.extend(heading_errors)
    if not heading_errors and not extract_release_notes(root, version).strip():
        errors.append(f"CHANGELOG.md release notes for version {version} are empty")

    return errors


def _write_github_output(path: Path, version: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(f"version={version}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        help="Release tag. Defaults to v<project.version> for candidate builds.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--notes-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        project_version = _project_version(args.root)
        tag = args.tag or f"v{project_version}"
        errors = validate_release(args.root, tag)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1

        version = tag.removeprefix("v")
        if args.notes_output:
            args.notes_output.write_text(
                extract_release_notes(args.root, version), encoding="utf-8"
            )
        if args.github_output:
            _write_github_output(args.github_output, version)
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR: could not validate release metadata: {exc}", file=sys.stderr)
        return 1

    print(f"Release metadata is valid for {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
