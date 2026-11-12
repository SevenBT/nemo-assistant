"""Deprecated evaluation entry point; never runs or modifies the legacy DB."""
import sys

def main(argv=None):
    print("Evaluation moved to evals/. Run: uv run --project evals nemo-eval --help. Import old data explicitly with import-legacy --db <path> --out <drafts>.", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
