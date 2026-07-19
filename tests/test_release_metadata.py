from pathlib import Path

import pytest

from scripts.release_metadata import extract_release_notes, main, validate_release


def _write_release_files(
    root: Path,
    *,
    project_version: str = "1.2.3",
    lock_version: str = "1.2.3",
    changelog: str | None = None,
) -> Path:
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "nemo-assistant"',
                f'version = "{project_version}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "\n".join(
            [
                "version = 1",
                "revision = 1",
                "",
                "[[package]]",
                'name = "nemo-assistant"',
                f'version = "{lock_version}"',
                'source = { editable = "." }',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        changelog
        or """# Changelog

## [Unreleased]

## [1.2.3] - 2026-07-19

### Added

- Automated release validation.

## [1.2.2] - 2026-07-01

- Previous release.
""",
        encoding="utf-8",
    )
    return root


def test_accepts_matching_release_metadata(tmp_path: Path) -> None:
    root = _write_release_files(tmp_path)

    assert validate_release(root, "v1.2.3") == []


@pytest.mark.parametrize(
    "tag",
    ["", "1.2.3", "v1.2", "v1.2.3.4", "v01.2.3", "release-1.2.3"],
)
def test_rejects_invalid_release_tag(tmp_path: Path, tag: str) -> None:
    root = _write_release_files(tmp_path)

    assert validate_release(root, tag) == [
        f"invalid release tag {tag!r}; expected vMAJOR.MINOR.PATCH"
    ]


def test_rejects_project_version_mismatch(tmp_path: Path) -> None:
    root = _write_release_files(tmp_path, project_version="1.2.4")

    assert validate_release(root, "v1.2.3") == [
        "tag version 1.2.3 does not match pyproject.toml version 1.2.4"
    ]


def test_rejects_lock_version_mismatch(tmp_path: Path) -> None:
    root = _write_release_files(tmp_path, lock_version="1.2.4")

    assert validate_release(root, "v1.2.3") == [
        "tag version 1.2.3 does not match uv.lock project version 1.2.4"
    ]


def test_rejects_missing_changelog_release(tmp_path: Path) -> None:
    root = _write_release_files(
        tmp_path,
        changelog="# Changelog\n\n## [Unreleased]\n\nMentions 1.2.3 only.\n",
    )

    assert validate_release(root, "v1.2.3") == [
        "CHANGELOG.md has no dated release heading for version 1.2.3"
    ]


def test_rejects_empty_changelog_release(tmp_path: Path) -> None:
    root = _write_release_files(
        tmp_path,
        changelog="""# Changelog

## [1.2.3] - 2026-07-19

## [1.2.2] - 2026-07-01

- Previous release.
""",
    )

    assert validate_release(root, "v1.2.3") == [
        "CHANGELOG.md release notes for version 1.2.3 are empty"
    ]


def test_rejects_invalid_changelog_date(tmp_path: Path) -> None:
    root = _write_release_files(
        tmp_path,
        changelog="""# Changelog

## [1.2.3] - 2026-02-30

- Impossible date.
""",
    )

    assert validate_release(root, "v1.2.3") == [
        "CHANGELOG.md release date 2026-02-30 for version 1.2.3 is invalid"
    ]


def test_cli_handles_malformed_lock_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_release_files(tmp_path)
    (root / "uv.lock").write_text(
        """version = 1
revision = 1

[[package]]
name = "nemo-assistant"
version = "1.2.3"
source = "invalid"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["release_metadata.py", "--root", str(root), "--tag", "v1.2.3"]
    )

    assert main() == 1
    assert "uv.lock package source must be a table" in capsys.readouterr().err


def test_extracts_only_requested_release_notes(tmp_path: Path) -> None:
    root = _write_release_files(tmp_path)

    assert extract_release_notes(root, "1.2.3") == (
        "### Added\n\n- Automated release validation.\n"
    )
