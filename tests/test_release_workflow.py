from __future__ import annotations

from pathlib import Path


def test_release_check_workflow_runs_release_and_final_acceptance() -> None:
    workflow = Path(".github/workflows/release-check.yml").read_text(encoding="utf-8")

    assert "uv sync --extra dev" in workflow
    assert "uv run python scripts/release_check.py --skip-final" in workflow
    assert "uv run python scripts/final_acceptance.py" in workflow
    assert "actions/setup-python@v5" in workflow
    assert "python-version: \"3.11\"" in workflow


def test_tag_release_workflow_publishes_verified_update_assets() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert 'tags:\n      - "v*"' in workflow
    assert "npm --prefix frontend run build" in workflow
    assert "scripts/build_release_bundle.py" in workflow
    assert "open-novel-${RELEASE_TAG#v}.zip" in workflow
    assert "open-novel-${RELEASE_TAG#v}.zip.sha256" in workflow
    assert "gh release upload" in workflow
