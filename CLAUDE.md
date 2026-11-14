# Nemo Assistant Agent Notes

This file is for AI coding agents working in this repository. Public contributor documentation lives in `CONTRIBUTING.md` and `docs/`.

## Communication

- Reply in Chinese when working with the maintainer.
- Keep explanations concise and evidence-based.

## Git

- Keep commits focused. Split unrelated changes into separate commits.
- Before editing, run `git branch --show-current` and `git status --short` to check the starting branch and existing changes.
- Unless the user explicitly asks for a new branch, work on the branch that was checked out when the task started, provided it is not `main` or `master`. A new independent task does not require creating a branch, switching to main, or merging the current branch first.
- Never edit or commit task code directly on `main` or `master`. If the task starts on a main branch, first create a `codex/<task-name>` working branch from the latest available main. Follow an explicit user request for a specific working branch or a new branch, while keeping task code off main branches.
- Preserve existing user changes and their staging state when switching branches or moving task changes off main. Never discard unrelated work with a blanket reset, clean, or overwrite.
- Choose your own merge strategy: use a regular merge or rebase merge to preserve the full commit history from the branch. Squash is not required.

## Development

- Prefer the existing PyQt6/qfluentwidgets patterns.
- Read `docs/en/development-notes.md` before changing frameless-window, selection, screenshot, theme, or embedded-dialog behavior.
- Read `docs/en/security-model.md` before changing tools, file access, shell/Python execution, clipboard access, web fetching, traces, notes, memory, or scheduling.
- Use `uv sync --extra dev` for reproducible development dependencies.
- Run `uv run python scripts/check_repo.py` and `uv run pytest -q` before claiming a change is ready.

## Packaging

- Read `docs/en/release-checklist.md` before publishing a binary release.
- Keep local `config/`, `data/`, logs, caches, and generated build output out of git.
