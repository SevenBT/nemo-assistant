# Release Checklist

> [中文](../zh/release-checklist.md)

Use this checklist before publishing a GitHub release or attaching a Windows executable.

## Source Release

- Run `uv sync --extra dev --frozen`.
- Run `uv run python scripts/check_repo.py`.
- Run `uv run pytest -q`.
- Confirm `git status --short` contains only intended release changes.
- Update `CHANGELOG.md`.

## Windows Binary Release

- Start from a clean or disposable `dist/` directory.
- Run `uv sync --extra build --frozen`.
- Run `uv run python -m PyInstaller --clean --noconfirm Nemo_Assistant.spec`.
- Confirm `dist/Nemo Assistant.exe` exists.
- Launch the executable once on Windows and verify the main window opens.
- Confirm the release archive does not contain local `config/`, `data/`, `logs/`, caches, API keys, or notes.

## License Review

Nemo Assistant source code is MIT licensed, but binary releases bundle third-party dependencies with their own licenses.

Before publishing binaries:

- Include `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `DEPENDENCY_LICENSES.md` in the release notes or archive.
- Regenerate a full dependency license inventory from the release environment.
- Review GPL obligations for PyQt6, pyqt6-fluent-widgets, and html2text.
- Make the corresponding source code available for the released binary.

Suggested inventory command:

```bash
uv run pip-licenses --with-license-file --format=markdown > build/dependency-licenses-full.md
```
