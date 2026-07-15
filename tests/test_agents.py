from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from open_novel.agents.cli_runner import CliProcessRunner
from open_novel.agents.detection import AgentDetectionService, AgentProbe


def test_agent_detection_reports_missing_command() -> None:
    result = AgentDetectionService(
        [AgentProbe("missing", "Missing", "definitely-open-novel-missing-command")]
    ).detect_all()[0]

    assert result.installed is False
    assert result.path is None


def test_cli_runner_captures_stdout(tmp_path: Path) -> None:
    result = asyncio.run(
        CliProcessRunner().run(
            [sys.executable, "-c", "print('hello')"],
            cwd=tmp_path,
            timeout_seconds=5,
        )
    )

    assert result.exitCode == 0
    assert result.stdout.strip() == "hello"
    assert result.timedOut is False


def test_cli_runner_closes_stdin_for_non_interactive_commands(tmp_path: Path) -> None:
    result = asyncio.run(
        CliProcessRunner().run(
            [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
            cwd=tmp_path,
            timeout_seconds=5,
        )
    )

    assert result.exitCode == 0
    assert result.stdout.strip() == "0"


def test_cli_runner_timeout_kills_child_process_tree(tmp_path: Path) -> None:
    child_code = (
        "import time; from pathlib import Path; "
        "time.sleep(0.8); Path('late.txt').write_text('late')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(30)"
    )
    started = time.monotonic()

    result = asyncio.run(
        CliProcessRunner().run(
            [sys.executable, "-c", parent_code],
            cwd=tmp_path,
            timeout_seconds=0.1,
        )
    )
    elapsed = time.monotonic() - started
    time.sleep(1)

    assert result.timedOut is True
    assert result.cancelled is False
    assert elapsed < 3
    assert not (tmp_path / "late.txt").exists()


def test_cli_runner_cancels_running_process(tmp_path: Path) -> None:
    cancelled = True

    result = asyncio.run(
        CliProcessRunner().run(
            [
                sys.executable,
                "-c",
                (
                    "import time; from pathlib import Path; "
                    "time.sleep(5); Path('late.txt').write_text('late')"
                ),
            ],
            cwd=tmp_path,
            timeout_seconds=30,
            cancel_check=lambda: cancelled,
        )
    )

    assert result.cancelled is True
    assert result.timedOut is False
    assert not (tmp_path / "late.txt").exists()
