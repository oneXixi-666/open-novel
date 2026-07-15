from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from pathlib import Path

from open_novel.core.models import CliRunResult


class CliProcessRunner:
    async def run(
        self,
        command: list[str],
        cwd: Path,
        timeout_seconds: int | None = 120,
        cancel_check: Callable[[], bool] | None = None,
    ) -> CliRunResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )

        timed_out = False
        cancelled = False
        communicate_task = asyncio.create_task(process.communicate())
        try:
            started = asyncio.get_running_loop().time()
            while True:
                done, _pending = await asyncio.wait(
                    {communicate_task},
                    timeout=0.2,
                )
                if done:
                    stdout_bytes, stderr_bytes = communicate_task.result()
                    break
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    stdout_bytes, stderr_bytes = await _finish_process_tree(
                        process,
                        communicate_task,
                    )
                    break
                if (
                    timeout_seconds is not None
                    and asyncio.get_running_loop().time() - started >= timeout_seconds
                ):
                    timed_out = True
                    stdout_bytes, stderr_bytes = await _finish_process_tree(
                        process,
                        communicate_task,
                    )
                    break
        except BaseException:
            await _finish_process_tree(process, communicate_task)
            raise

        return CliRunResult(
            command=command,
            cwd=cwd,
            exitCode=process.returncode if process.returncode is not None else -1,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            timedOut=timed_out,
            cancelled=cancelled,
        )


async def _finish_process_tree(
    process: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    terminate_grace_seconds: float = 2,
) -> tuple[bytes, bytes]:
    _signal_process_tree(process, signal.SIGTERM)
    try:
        return await asyncio.wait_for(
            asyncio.shield(communicate_task),
            timeout=terminate_grace_seconds,
        )
    except TimeoutError:
        _signal_process_tree(process, signal.SIGKILL)
        return await communicate_task


def _signal_process_tree(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif process.returncode is None:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
    except ProcessLookupError:
        pass
