# Security Model

> [中文](../zh/security-model.md)

Nemo Assistant is local-first, but it can still perform powerful actions on the user's machine. This document describes the intended safety boundaries for contributors and maintainers.

## Trust Boundaries

- User notes, memories, sessions, traces, screenshots, and config live under local `data/` and `config/` directories.
- Provider API keys and search API keys are stored through the operating system keyring.
- Built-in tools run inside the local desktop app process unless the tool explicitly creates a subprocess.
- Existing user-added tools remain compatible local extensions, but generated code is not built-in trusted code and must not be trusted merely because it is local.

## Generated Tool Build Boundary

Generated code is not built-in trusted code. `cwd` and temporary staging workspaces are not OS-level sandboxes; their use does not limit a process's operating-system permissions.

Phase 1 does not automatically install strict-tool dependencies and does not execute generated code. A new generated tool must provide a strict manifest v1 and pass deterministic independent validation before installation. Validation checks loadability only — manifest structure and strict-v1 conformance, a present and syntactically valid Python entrypoint, an allowed and bounded source tree, and the Phase-1 constraint that dependencies are empty. Validation does NOT perform capability or permission analysis: manifest `permissions` are recorded as declarative metadata and are not independently detected, cross-checked, or separately approved by the user, and runtime execution does not enforce them. The validation, review, and installation paths do not execute generated code. The installer accepts only the independently revalidated artifact and rejects conflicts unless overwrite is explicitly requested. Initial installation uses atomic no-clobber move or replacement steps. Overwrite is a multi-step process. Rollback runs only when the root, endpoint, and backup identities and target state remain safely verifiable; otherwise it must fail closed and preserve the evidence. It does not guarantee a kernel-level transaction and does not guarantee recovery. Disabled-tool execution gate checks reject a disabled tool before any runtime validation, retry, or execution. The review UI exposes the readiness status and any blocking issues, with the artifact available for inspection and edit. Runtime execution remains outside an OS sandbox.

Every blocking finding means the tool could not load or run as-is (invalid or missing manifest, invalid Python syntax, a broken or wrong-type entrypoint, declared dependencies, or a source tree that could not be safely read within bounds). Blocking findings are not user-overridable: the user must fix the source and re-validate. Because installation no longer gates on requested capabilities, users must judge for themselves whether to install and enable a generated tool. Static validation is not a proof of safety, does not analyse behaviour, and the tool is not run in a sandbox — a passing validation means the tool is well-formed and loadable, not that it is safe.

Legacy tools can still load for compatibility, but they are legacy/unreviewed: they have not passed the strict manifest v1 and deterministic validation protocol, and compatibility loading cannot satisfy the new-installation requirements. Their historical legacy execution path may automatically install missing dependencies on first explicit execution; this can use network access and package build code. Review legacy manifests and dependencies before execution.

Deterministic validation includes bounded static AST checks for the defined protocol and obvious prohibited behavior. It is not a proof of safety, a complete behavior analysis, or an OS sandbox; ambiguous behavior is not automatically approved for installation. Windows path APIs reduce path-boundary exposure, but the final TOCTOU window cannot be eliminated by this static validation and filesystem checks alone.

External Claude Code/Codex Agents, ProcessRunner, PTY/ConPTY, automatic repair loops, multi-file Agent execution, and OS-level sandboxing are not delivered in Phase 1. Resume after user clarification also remains future work. They must not be described as current protections or capabilities, and the complete advanced-generation design is not complete.

## Policy Metadata

This stable metadata mirrors the human-readable boundary above; it does not replace it.

| Policy ID | Value |
| --- | --- |
| generated_code_trust | untrusted_extension |
| workspace_is_os_sandbox | false |
| strict_dependencies_auto_install | false |
| strict_generated_code_exec_during_review | false |
| strict_manifest_required | true |
| strict_manifest_version | v1 |
| validation_type | deterministic |
| validation_scope | loadability_only |
| independent_validation_required | true |
| capability_ast_analysis | not_performed |
| permission_detection_and_approval | not_performed |
| manifest_permissions_are | declarative_metadata |
| runtime_permission_enforcement | false |
| explicit_install_confirmation_required | true |
| atomic_move_steps_and_conditional_rollback | true |
| disabled_tool_execution_gate | true |
| review_ui | implemented |
| legacy_review_status | legacy_unreviewed |
| windows_path_final_toctou | not_eliminated |
| static_analysis_is_safety_proof | false |
| external_agent | not_implemented |
| user_clarification_resume | not_implemented |
| process_runner | not_implemented |
| pty | not_implemented |
| os_sandbox | not_implemented |
| risk_acknowledged_override_install | not_applicable |
| blocking_findings_are_overridable | false |

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
