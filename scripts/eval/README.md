# Evaluation scripts

These commands operate on the local evaluation database (`data/traces.db` by
default). The database is runtime data and is not committed.

```powershell
# Create the maintained evaluation case set (idempotent by title).
uv run python -m scripts.eval.create_eval_cases

# Run the full evaluation with LLM-as-Judge scoring.
uv run python -m scripts.eval.run_eval_with_judge --label manual-with-judge

# Print the latest report, or select a run explicitly.
uv run python -m scripts.eval.report
uv run python -m scripts.eval.report --run-id <run-id>

# Inspect schema, runs, cases, or one run's results.
uv run python -m scripts.eval.inspect_db tables
uv run python -m scripts.eval.inspect_db schema --table eval_results
uv run python -m scripts.eval.inspect_db runs
uv run python -m scripts.eval.inspect_db results --run-id <run-id>
```

Pass `--db <path>` before the subcommand to inspect another database. The
case creation and evaluation commands also accept `--db`.
