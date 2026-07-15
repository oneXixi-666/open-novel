from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from shutil import which


def run_cancellable_process(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    cancel_check: Callable[[], bool] | None = None,
    poll_seconds: float = 0.2,
    terminate_grace_seconds: float = 2,
) -> dict[str, object]:
    started = time.monotonic()
    command = _normalize_command(command)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    cancelled = False
    timed_out = False
    stdout = ""
    stderr = ""
    while True:
        try:
            stdout, stderr = process.communicate(timeout=poll_seconds)
            break
        except subprocess.TimeoutExpired:
            if cancel_check is not None and cancel_check():
                cancelled = True
                process.terminate()
                stdout, stderr = finish_process(process, terminate_grace_seconds)
                break
            if time.monotonic() - started >= timeout_seconds:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
                break
    return {
        "command": command,
        "cwd": cwd,
        "exitCode": process.returncode if process.returncode is not None else -1,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "cancelled": cancelled,
    }


def _normalize_command(command: list[str]) -> list[str]:
    if not command:
        return command
    executable = command[0]
    if executable in {"python", "python3"}:
        return [sys.executable, *command[1:]]
    if "/" not in executable:
        resolved = which(executable)
        if resolved is not None:
            return [resolved, *command[1:]]
    return command


def finish_process(
    process: subprocess.Popen[str],
    terminate_grace_seconds: float = 2,
) -> tuple[str, str]:
    try:
        return process.communicate(timeout=terminate_grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()
