# Security Model

Nemo Assistant is local-first, but it can still perform powerful actions on the user's machine. This document describes the intended safety boundaries for contributors and maintainers.

## Trust Boundaries

- User notes, memories, sessions, traces, screenshots, and config live under local `data/` and `config/` directories.
- Provider API keys and search API keys are stored through the operating system keyring.
- Built-in tools run inside the local desktop app process unless the tool explicitly creates a subprocess.
- User-added tools are local code and should be treated as trusted user extensions.

## Dangerous Capabilities

The following tool classes need extra care:

- File reads and writes.
- Shell command execution.
- Python code execution.
- Clipboard read/write.
- Web fetching and search.
- Scheduled tasks and reminders.
- Note and memory mutation.

High-risk tools should stay disabled by default in example configs unless a user explicitly enables them.

## Current Defaults

`config/app_config.example.json` disables the highest-risk tool states by default:

- `exec`
- `run_python`
- `save_file`

Search providers that require API keys store those keys in keyring; if a configured key is missing, web search falls back to DuckDuckGo.

## Contributor Checklist

When adding or changing tools:

- Validate file paths through shared helpers instead of manual string checks.
- Keep network requests bounded by explicit timeouts.
- Redact keys, tokens, passwords, and authorization headers from traces and logs.
- Avoid passing the full parent process environment into subprocess tools.
- Prefer read-only tools where possible; mark mutation clearly in tool descriptions.
- Add tests for path traversal, SSRF, command execution, and secret redaction when relevant.

## Release Checklist

Before shipping a binary release:

- Run the test suite.
- Run `python scripts/check_repo.py`.
- Run a PyInstaller build from a clean `dist/` directory.
- Review bundled dependency licenses.
- Check that packaged builds do not contain local `config/`, `data/`, logs, caches, or API keys.
