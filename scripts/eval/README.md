# Evaluation commands moved

The independent evaluation package now lives in [evals](../../evals/README.md).
The old commands return a migration message and never call models or mutate the
legacy database. Import old cases explicitly using nemo-eval import-legacy;
imported cases are drafts and historical tool calls are observations only.
