# Release Checklist

> [中文](../zh/release-checklist.md)

Use this checklist before publishing a GitHub release or attaching a Windows executable.

## When to Release

Do not release on a fixed calendar date. Release when a coherent user-facing
milestone is ready and the previous release's known blockers are closed.

For this project, prefer a small release every few meaningful improvements:

- `patch` (`0.1.1`): a backward-compatible bug fix or packaging correction.
- `minor` (`0.2.0`): a user-visible feature set or a meaningful workflow improvement.
- `major` (`1.0.0`): a stable compatibility and support commitment.

After `v0.1.0`, the chat reliability fixes and rendering performance work form a
reasonable `v0.2.0` candidate once the packaged executable passes the Windows
smoke check below.

## Automated Release Flow

1. Create a release PR from `main` that updates `pyproject.toml`, `uv.lock`, and
   the dated section in `CHANGELOG.md`.
2. Merge the PR after the normal `tests` check passes.
3. Create and push an annotated tag from the merged commit, for example:

   ```bash
   git switch main
   git pull --ff-only
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```

4. The `package-windows` workflow validates the tag and version metadata, runs
   repository checks and tests, builds the executable, creates a license-aware
   ZIP and SHA256 file, and creates a GitHub **Draft Release**.
5. Download the assets from that Draft Release, complete the Windows and license
   checks below, then click **Publish release**. The workflow does not publish
   a Draft automatically.

The workflow accepts strict stable tags in the `vMAJOR.MINOR.PATCH` form. A
manual run is useful for testing a candidate package, but it does not create a
Release. Do not move or delete a tag after a failed or published release;
prepare a new patch version instead.

## Source Release

- Run `uv sync --extra dev --frozen`.
- Run `uv run python scripts/check_repo.py`.
- Run `uv run python -m pytest -q`.
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
