from __future__ import annotations

import subprocess
from dataclasses import dataclass
from shutil import which

from open_novel.core.models import AgentDetectionResult


@dataclass(frozen=True)
class AgentProbe:
    id: str
    display_name: str
    command: str
    version_args: tuple[str, ...] = ("--version",)


DEFAULT_PROBES = [
    AgentProbe("codex-cli", "Codex CLI", "codex"),
    AgentProbe("claude-cli", "Claude Code", "claude"),
    AgentProbe("qwen-cli", "Qwen Code", "qwen"),
]


class AgentDetectionService:
    def __init__(self, probes: list[AgentProbe] | None = None) -> None:
        self.probes = probes or DEFAULT_PROBES

    def detect_all(self) -> list[AgentDetectionResult]:
        return [self.detect(probe) for probe in self.probes]

    def detect(self, probe: AgentProbe) -> AgentDetectionResult:
        path = which(probe.command)
        if path is None:
            return AgentDetectionResult(
                id=probe.id,
                displayName=probe.display_name,
                command=probe.command,
                installed=False,
            )

        try:
            completed = subprocess.run(
                [path, *probe.version_args],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AgentDetectionResult(
                id=probe.id,
                displayName=probe.display_name,
                command=probe.command,
                installed=True,
                path=path,
                error=str(exc),
            )

        version = (completed.stdout or completed.stderr).strip().splitlines()
        return AgentDetectionResult(
            id=probe.id,
            displayName=probe.display_name,
            command=probe.command,
            installed=True,
            path=path,
            version=version[0] if version else None,
            error=None if completed.returncode == 0 else completed.stderr.strip() or None,
        )
