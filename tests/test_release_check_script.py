from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_release_check_script_exposes_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/release_check.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--skip-final" in completed.stdout
    assert "--skip-frontend" in completed.stdout
    assert "release readiness" in completed.stdout


def test_release_check_runs_frontend_build() -> None:
    source = Path("scripts/release_check.py").read_text(encoding="utf-8")

    assert 'run_step("frontend build", ["npm", "--prefix", "frontend", "run", "build"])' in source


def test_readme_lists_frontend_check_in_verification_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "npm --prefix frontend run check" in readme
    assert "构建 React 前端" in normalized
