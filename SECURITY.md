# Security Policy

Nemo Assistant is a local-first desktop app, but it includes powerful features such as tool calling, file access, clipboard access, Python execution, web requests, and scheduled tasks. Please report security issues responsibly.

## Supported Versions

Security fixes are handled on the `main` branch until the project starts publishing stable release lines.

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities.

Report security concerns through GitHub's private vulnerability reporting for this repository, or contact the maintainer privately if that is unavailable.

Helpful details include:

- Affected commit, release, or installer.
- Operating system and Python version.
- Minimal reproduction steps.
- Whether the issue can expose local files, secrets, clipboard contents, command execution, or network requests.
- Logs or screenshots with secrets removed.

## Scope

Security-sensitive areas include:

- Tool execution and user-provided tool scripts.
- File read/write tools and path handling.
- Python and shell execution tools.
- Clipboard read/write behavior.
- Web fetching and SSRF protections.
- API key storage through the system keyring.
- Trace, eval, note, memory, and session persistence.

See [docs/security-model.md](docs/security-model.md) for the contributor-facing security model and release checklist.

## Maintainer Notes

Before publishing binary releases, review bundled dependency licenses and include required notices. This is especially important for GUI and HTML conversion dependencies that may carry copyleft obligations.
