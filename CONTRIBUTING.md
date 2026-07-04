# Contributing Guide

Thanks for your interest in Nemo Assistant! This document explains how to set up
the development environment, run tests, and submit changes.

> This project is primarily developed and run on **Windows**. Some capabilities
> (global hotkeys, selection capture, screenshots) depend on Windows-only
> libraries (`keyboard`, `uiautomation`, `pywin32`). On other platforms the core
> logic and tests can run, but desktop interaction features are not guaranteed to
> work.

## Development Environment

Requires **Python 3.10+**.

```bash
git clone https://github.com/SevenBT/nemo-assistant.git
cd nemo-assistant

# A virtual environment is recommended
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install runtime + dev dependencies (editable install + dev group)
pip install -e ".[dev]"

# Launch the app
python main.py
```

Using `uv` for reproducible, locked dependencies is recommended:

```bash
uv sync --extra dev
uv run python main.py
```

After the first launch, open **Settings → API** to add a model and set it as the
default. API keys are stored securely through the system keyring and are never
written to plaintext config. Personal config is saved in
`config/app_config.json` (ignored by `.gitignore`; do not commit it).

## Running Tests

Tests use **pytest**. Because PyQt components are involved, a headless
environment (including CI) needs the offscreen platform plugin set. Importing
`litellm` fetches a pricing table over the network, so disabling it via an
environment variable speeds things up.

```bash
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
pytest -q

# Or with uv
uv run pytest -q

# macOS / Linux (bash)
export QT_QPA_PLATFORM=offscreen
export LITELLM_LOCAL_MODEL_COST_MAP=True
pytest -q
```

Check coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

Make sure all tests pass before opening a PR. When adding a feature or fixing a
bug, please add corresponding tests.

## Code Style

- Follow **PEP 8**, and add type annotations to function signatures where
  practical.
- Prefer small, focused files and functions (aim for <800 lines per file, <50
  lines per function).
- Handle errors explicitly; do not silently swallow exceptions.
- Never hard-code secrets. Secrets always go through the keyring or environment
  variables.
- Implementation conventions for PyQt6 frameless windows are documented in
  [docs/en/development-notes.md](docs/en/development-notes.md), which records the
  pitfalls and correct approaches for dragging, resizing, theming, FluentWindow,
  and more. Reading it before changing UI is recommended.

## Commits & PRs

- Commit messages are in **English** and follow the
  [Conventional Commits](https://www.conventionalcommits.org/) format:
  `feat: ...` / `fix: ...` / `refactor: ...` / `docs: ...` / `test: ...` / `chore: ...`
- Keep each PR focused on one thing; describe what changed, why, and how you
  verified it.
- Branch off `main` for feature work; do not push directly to `main`.

## Reporting Issues

When filing an issue, please include: your OS version, Python version,
reproduction steps, and the error stack from `crash.log` (if any).
