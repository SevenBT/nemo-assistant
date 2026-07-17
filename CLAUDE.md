# Nemo Assistant Agent Notes

This file is for AI coding agents working in this repository. Public contributor documentation lives in `CONTRIBUTING.md` and `docs/`.

## Communication

- Reply in Chinese when working with the maintainer.
- Keep explanations concise and evidence-based.

## Git

- Use English Conventional Commits, for example `fix: ...`, `docs: ...`, `chore: ...`.
- Keep commits focused. Split unrelated changes.
- Start each new task from the latest `main` on a dedicated branch; do not branch from unmerged task branches.
- Keep one independent task per branch and pull request. Finish and merge that PR before starting the next task.
- After CI passes, use Squash and merge so each PR becomes one focused commit on `main`, then delete the task branch and sync local `main`.

## Development

- Prefer the existing PyQt6/qfluentwidgets patterns.
- Read `docs/en/development-notes.md` before changing frameless-window, selection, screenshot, theme, or embedded-dialog behavior.
- Read `docs/en/security-model.md` before changing tools, file access, shell/Python execution, clipboard access, web fetching, traces, notes, memory, or scheduling.
- Use `uv sync --extra dev` for reproducible development dependencies.
- Run `uv run python scripts/check_repo.py` and `uv run pytest -q` before claiming a change is ready.

## Packaging

- Read `docs/en/release-checklist.md` before publishing a binary release.
- Keep local `config/`, `data/`, logs, caches, and generated build output out of git.
