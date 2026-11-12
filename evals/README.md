# Offline regression and live-model evaluation

Evaluation is a developer tool. Normal conversations never invoke a Judge.
The adapter runs the production Agent without Qt, desktop settings or the
user's runtime database. Run from the repository root. The everyday entry points
each perform a complete pipeline and create a unique output directory:

```powershell
# Scripted production execution regression; no model calls or credentials.
uv run --project evals --frozen nemo-eval regression

# Real target model + required Judge + final report, after one-time configuration.
uv run --project evals --frozen nemo-eval evaluate
```

See the [Chinese maintainer guide](../docs/zh/agent-evaluation.md) for setup and
prompt-release examples. `regression` defaults to offline-core (3 cases, once).
`evaluate` defaults to live-release (12 tasks, three repetitions = 36 task
executions). `evaluate --suite live-smoke` runs four tasks once and needs no Judge.
Every task can require several model calls. This is not a dollar spending limit.

Both commands print the complete report path. Optional `--out` must name a new
directory; otherwise directories are created under artifacts/eval/offline or live.
JSON, JUnit and Markdown distinguish execution completion from task acceptance.
Every planned repetition has a result, including errors, interruptions and tasks
not executed after budget exhaustion. Missing required evidence never passes.

## Cases and evidence

Typed suite manifests live in suites/. Offline and live cases are separate; a
suite cannot run through the other entry point. Live cases require scenario
input and forbid model_script or fixtures.system_prompt. Scripted responses are
only execution regression evidence, never a real-model quality score.

JSON cases declare schema_version, stable id/revision, reviewed status, input,
fixtures and explicit expectations. snapshot preserves supplied API messages;
scenario submits user steps through the production prompt builder and preserves
actual assistant/tool history. Fixtures use temporary workspaces and explicit
tool profiles. The first profile exposes production read_file and save_file,
with folder-opening disabled. save_file creates a new file, without overwriting
an existing file. Text checks normalize line endings; actual byte hashes remain.

Offline scripts provide normalized stream events and optional request-context
assertions. They validate execution and acceptance mechanics, not real-model
tool selection. Worker imports forbid Qt and desktop config, outbound sockets
are blocked, and each case has a process deadline. This handles trusted fixtures;
it is not an OS security sandbox for arbitrary shell code.

Tool checks distinguish success, attempts, errors and policy rejections. no_tools
is explicit; empty required does not forbid tools. Optional tools.order pairs refer
to required-rule indexes and require completion before a later iteration starts;
parallel calls in one iteration are not treated as ordered. Artifacts verify actual files
instead of trusting the answer. Reference facts and rubric stay evaluator-side.

## Optional paid runs

Copy [configs/live.example.toml](configs/live.example.toml) to configs/live.toml
and [configs/judge.example.toml](configs/judge.example.toml) to configs/judge.toml.
Choose models/providers/protocols/base URLs and populate their named environment
variables. These local configs are gitignored. No personal config or keyring
lookup occurs. All required profiles, credentials and budgets are checked before
the first target request. `evaluate` automatically judges rubric cases and emits
the assessed report; no separate judge/report command is needed:

```powershell
uv run --project evals --frozen nemo-eval evaluate

# Quickly check target connectivity and representative tasks, without Judge.
uv run --project evals --frozen nemo-eval evaluate --suite live-smoke

# Override the default production prompt with a versioned text variant.
uv run --project evals --frozen nemo-eval evaluate --variant evals/variants/examples/custom-prompt.toml

# Evaluate, judge, report and compare against an existing compatible baseline.
uv run --project evals --frozen nemo-eval evaluate --variant evals/variants/examples/custom-prompt.toml --baseline artifacts/eval/live/BASELINE_RUN --change prompt
```

Variants live outside task fixtures. A text-file variant replaces only the
user-editable system prompt; the production builder still composes tool
instructions and context. No variant means the current production default.
Resolved text and actual requests are frozen as evidence. Source changes to
defaults/tools/builders use --change application and separate old/new checkouts.

Judge has an independent profile/client and sees task context, reference facts,
rubric, tool outcomes and artifacts. Failed hard checks remain failed. Cases
without a rubric need no Judge. A rubric is optional by default; an explicit
judge_required=true keeps the raw verdict inconclusive until an assessment.
Assessments are saved separately for every repetition, never rerunning tools.
The pipeline freezes its chosen assessment in pipeline.json; rejudging never
silently changes the initial report. Explicit --assessment / --current-assessment
/ --baseline-assessment select another view. Judge quality is diagnostic, not a mandatory CI release gate. Unknown
usage and prices remain unknown, never interpreted as free calls.

## Legacy data

```powershell
uv run --project evals --frozen nemo-eval import-legacy --db data/traces.db --out artifacts/eval/drafts
```

The source DB opens read-only. Imports remain drafts with incomplete context;
old expected_tools becomes observed_tools, never inferred requirements. Reimport
is idempotent by source and case id. Supply fixtures and reviewed expectations
before adding drafts to suites. Legacy results are archived, not new baselines.
Runtime DB V3 backs up old databases, retains old tables, and copies iteration
observations without scores once in a transaction. Reopening does not restore
pruned observations.

Exit codes: 0 pass, 1 acceptance failed, 2 invalid input/config/output,
3 incomplete execution/required assessment, 130 interrupted.


## Current scope and limits

The supported fixture surface is text-only snapshot messages or sequential user
steps, temporary UTF-8 workspace files, supplied memory text, a fixed clock,
and explicit tool blocking. Unknown fixture and expectation fields fail validation.
There is no attachment, notes-database, desktop-interaction, mid-turn human-input
or context-consolidation fixture adapter yet. Add those as explicit adapters when
their regression suites are introduced. Artifact evidence is limited to 2 MB per
file; exceeding this fails execution rather than silently truncating evidence.

Paid runs reserve model-call count and maximum output tokens across the suite.
They require one provider attempt per request; this is an output reservation,
not an input-token or dollar spending ceiling. Profiles may provide explicit
per-million-token pricing; missing prices or usage remain unknown. Cost records
identify target versus Judge, with independent assessments and budget usage.
Judge input is redacted, capped at 60,000 characters and rejected if too large;
requests, hashes, sanitized responses and structured verdicts are saved.
Execution artifacts remain local and contain full fixture data. CI uploads only
summary, JUnit and Markdown from reviewed synthetic cases.

Baseline comparison refuses changed tasks, modes, repeat counts, environment,
evaluator source and undeclared model/configuration changes. --change prompt
requires the same application source; --change application permits changed app
code. Selected Judge assessments must use the same profile/template. Incomplete
execution or required assessment cannot be formally compared. Reports show
per-case pass counts, critical cases, failures, usage, cost and duration; small
samples do not establish statistical significance or automatically approve a release.
For deliberate model experiments, the compatibility --allow-change target.model
option remains available; do not combine it with --change prompt/application.
Run directories are immutable; select a new --out for every attempt. Local
artifact cleanup is manual. No live-model or Judge request is part of CI.

## Evaluator development and compatibility

```powershell
uv sync --project evals --extra dev --frozen
uv run --project evals --frozen pytest evals/tests -q
uv run --project evals --frozen nemo-eval validate --suite offline-core
uv run --project evals --frozen nemo-eval validate --suite live-release
```

The old run --suite core --mode offline remains an offline compatibility alias.
The old core/live combination fails before any model call and directs developers
to evaluate. Historical schema-1 reports remain readable, but cannot be formally
compared against schema-2 repeated runs. Controlled-client tests verify pipeline
contracts, not actual provider connectivity or real-model quality.
