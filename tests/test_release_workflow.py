from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-windows.yml"


def test_release_workflow_builds_draft_release_from_version_tag() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "tags:" in workflow
    assert "'v*'" in workflow
    assert "scripts/release_metadata.py" in workflow
    assert "uv run python scripts/check_repo.py" in workflow
    assert "uv run python -m pytest -q" in workflow
    assert "DEPENDENCY_LICENSES.md" in workflow
    assert "THIRD_PARTY_NOTICES.md" in workflow
    assert "SHA256SUMS.txt" in workflow
    assert "release/release-notes.md" in workflow
    assert 'notes_file="release-assets/release-notes.md"' in workflow
    assert '--notes-file "$notes_file"' in workflow
    assert 'gh api "repos/$GITHUB_REPOSITORY/releases/tags/$RELEASE_TAG"' in workflow
    assert 'gh release create "$RELEASE_TAG"' in workflow
    assert '--repo "$GITHUB_REPOSITORY"' in workflow
    assert "--draft" in workflow
    assert "contents: write" in workflow
    assert "uv sync --locked --extra dev --extra build" in workflow
    assert "$fetchExitCode = $LASTEXITCODE" in workflow
    assert "github.run_attempt" in workflow
    assert "RELEASE_SHA" in workflow
    assert "commits/$RELEASE_TAG" in workflow
