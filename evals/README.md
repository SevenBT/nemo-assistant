# Independent evaluation

Evaluation is a developer tool. Normal conversations never invoke a Judge.
The adapter runs the production Agent without Qt, desktop settings or the
user's runtime database. Run from the repository root:

```powershell
uv sync --project evals --extra dev --frozen
uv run --project evals --frozen nemo-eval validate --suite core
uv run --project evals --frozen pytest evals/tests -q
uv run --project evals --frozen nemo-eval run --suite core --out artifacts/eval/my-run
uv run --project evals --frozen nemo-eval report --run artifacts/eval/my-run
uv run --project evals --frozen nemo-eval compare --current artifacts/eval/new --baseline artifacts/eval/baseline
```

Output directories must be new. Every selected case has a result, including
errors and timeout. JSON, JUnit and Markdown separate execution completion from
task acceptance; missing required evidence never passes.

## Cases and evidence

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

Copy [configs/live.example.toml](configs/live.example.toml), choose a model and
populate the named environment variable. No personal config or keyring lookup
occurs. An explicit live command permits paid model calls:

```powershell
uv run --project evals --frozen nemo-eval run --suite core --mode live --config evals/configs/live.toml --out artifacts/eval/live-run
uv run --project evals --frozen nemo-eval judge --run artifacts/eval/live-run --config evals/configs/judge.toml
```

Judge has an independent profile/client and sees task context, reference facts,
rubric, tool outcomes and artifacts. Failed hard checks remain failed. Cases
without a rubric need no Judge. A rubric is optional by default; an explicit
judge_required=true keeps the initial verdict inconclusive until an assessment. Assessments are saved separately, never rerunning
tools. Judge quality is diagnostic, not a mandatory CI release gate. Unknown
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

Baseline comparison refuses changed cases, modes, evaluator versions and
configuration. To compare model choices deliberately, repeat --allow-change
target.model (or an explicitly supported target profile field); all other
configuration must match, and changed conditions are included in the output.
Run directories are immutable; select a new --out for every attempt. Local
artifact cleanup is manual. No live-model or Judge request is part of CI.
