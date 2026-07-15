from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import which

from open_novel.agents.cli_runner import CliProcessRunner
from open_novel.core.models import CliRunResult


@dataclass(frozen=True)
class CliAgentCommand:
    command: list[str]
    parseMode: str


class CliAgentCommandBuilder:
    def build(self, agent_id: str, prompt: str, writable: bool = False) -> CliAgentCommand:
        if agent_id == "codex-cli":
            sandbox = "workspace-write" if writable else "read-only"
            return CliAgentCommand(
                command=[
                    "codex",
                    "exec",
                    "--json",
                    "--sandbox",
                    sandbox,
                    "--skip-git-repo-check",
                    prompt,
                ],
                parseMode="jsonl",
            )
        if agent_id == "claude-cli":
            return CliAgentCommand(
                command=[
                    "claude",
                    "-p",
                    prompt,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                ],
                parseMode="stream-json",
            )
        if agent_id == "qwen-cli":
            return CliAgentCommand(
                command=[
                    "qwen",
                    "-p",
                    prompt,
                    "--output-format",
                    "stream-json",
                    "--include-partial-messages",
                ],
                parseMode="stream-json",
            )
        raise ValueError(f"unsupported cli agent: {agent_id}")


class CliAgentService:
    def __init__(
        self,
        command_builder: CliAgentCommandBuilder | None = None,
        runner: CliProcessRunner | None = None,
    ) -> None:
        self.command_builder = command_builder or CliAgentCommandBuilder()
        self.runner = runner or CliProcessRunner()

    async def run_prompt(
        self,
        agent_id: str,
        prompt: str,
        cwd: Path,
        writable: bool = False,
        timeout_seconds: int = 300,
        cancel_check: Callable[[], bool] | None = None,
    ) -> CliRunResult:
        command = self.command_builder.build(agent_id, prompt, writable=writable)
        executable = command.command[0]
        executable_path = which(executable)
        if executable_path is None:
            raise FileNotFoundError(f"missing CLI executable: {executable}")

        resolved_command = [executable_path, *command.command[1:]]
        result = await self.runner.run(
            resolved_command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            cancel_check=cancel_check,
        )
        if result.exitCode == 0 and not result.timedOut and not result.cancelled:
            result = result.model_copy(
                update={"stdout": self._extract_assistant_text(result.stdout, command.parseMode)}
            )
        return result

    @staticmethod
    def _extract_assistant_text(stdout: str, parse_mode: str) -> str:
        messages: list[str] = []
        final_result = ""
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if parse_mode == "jsonl" and event.get("type") == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    text = str(item.get("text") or "").strip()
                    if text:
                        messages.append(text)
            if parse_mode == "stream-json" and event.get("type") == "assistant":
                message = event.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    text = "\n".join(
                        str(item.get("text") or "").strip()
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") == "text"
                        and str(item.get("text") or "").strip()
                    )
                    if text:
                        messages.append(text)
            if parse_mode == "stream-json" and event.get("type") == "result":
                final_result = str(event.get("result") or "").strip()
        if final_result:
            return final_result
        if messages:
            return messages[-1]
        return stdout.strip()
