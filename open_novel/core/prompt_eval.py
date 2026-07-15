from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from open_novel.core.models import SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.prompt_registry import PromptRegistryEntry, PromptRegistryService
from open_novel.core.skills import SkillRunner
from open_novel.security.path_guard import PathGuard

PromptEvalStatus = Literal["pass", "warn", "block"]


class PromptEvalIssue(BaseModel):
    severity: Literal["low", "medium", "high", "blocker"]
    entryId: str
    type: str
    message: str


class PromptEvalResult(BaseModel):
    entryId: str
    skillId: str
    status: PromptEvalStatus
    score: int
    runId: str = ""
    outputPath: str = ""
    runDir: str = ""
    issues: list[PromptEvalIssue] = Field(default_factory=list)


class PromptEvalReport(BaseModel):
    schemaVersion: int = 1
    evalId: str
    status: PromptEvalStatus
    projectRoot: str
    chapterId: str
    entries: list[str] = Field(default_factory=list)
    results: list[PromptEvalResult] = Field(default_factory=list)
    issues: list[PromptEvalIssue] = Field(default_factory=list)
    path: str = ""
    createdAt: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromptEvalService:
    """Run deterministic prompt/skill checks without writing canonical story state."""

    report_dir = "runs/prompt-evals"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        registry_service: PromptRegistryService | None = None,
        skill_runner: SkillRunner | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.registry_service = registry_service or PromptRegistryService()
        self.skill_runner = skill_runner or SkillRunner(project_service=self.project_service)

    def evaluate(
        self,
        root: Path,
        *,
        entry_id: str = "chapter-writer.v1",
        chapter_id: str = "001",
        chapter_title: str = "",
        all_active: bool = False,
    ) -> PromptEvalReport:
        project = self.project_service.open_project(root)
        normalized_chapter = self.project_service.normalize_chapter_id(chapter_id)
        registry = self.registry_service.build_from_skills()
        entries = [
            entry
            for entry in registry.entries
            if entry.status == "active" and (all_active or entry.id == entry_id)
        ]
        if not entries:
            entries = []

        eval_id = self._eval_id(entry_id if not all_active else "all", normalized_chapter)
        results: list[PromptEvalResult] = []
        issues: list[PromptEvalIssue] = [
            PromptEvalIssue(
                severity=issue.severity,
                entryId=issue.entryId,
                type="registry",
                message=issue.message,
            )
            for issue in registry.issues
            if all_active or issue.entryId == entry_id
        ]
        if registry.status == "block":
            results = [
                PromptEvalResult(
                    entryId=entry.id,
                    skillId=entry.skillId,
                    status="block",
                    score=0,
                    issues=[
                        issue
                        for issue in issues
                        if issue.entryId == entry.id and issue.severity == "blocker"
                    ],
                )
                for entry in entries
            ]
        else:
            for entry in entries:
                results.append(
                    self._evaluate_entry(
                        project.root,
                        entry,
                        eval_id,
                        normalized_chapter,
                        chapter_title,
                    )
                )

        if not entries:
            issues.append(
                PromptEvalIssue(
                    severity="blocker",
                    entryId=entry_id,
                    type="entry_not_found",
                    message=f"prompt registry entry not found: {entry_id}",
                )
            )

        all_issues = issues + [issue for result in results for issue in result.issues]
        status = self._status_from_issues(all_issues)
        report = PromptEvalReport(
            evalId=eval_id,
            status=status,
            projectRoot=project.root.as_posix(),
            chapterId=normalized_chapter,
            entries=[entry.id for entry in entries],
            results=results,
            issues=all_issues,
        )
        report.path = self._write_report(project.root, report)
        return report

    def _evaluate_entry(
        self,
        root: Path,
        entry: PromptRegistryEntry,
        eval_id: str,
        chapter_id: str,
        chapter_title: str,
    ) -> PromptEvalResult:
        issues: list[PromptEvalIssue] = []
        run_id = f"{eval_id}-{entry.skillId}"
        output_path = ""
        run_dir = ""
        protected_snapshot = self._protected_snapshot(root, chapter_id)
        try:
            result = self.skill_runner.run(
                SkillRunRequest(
                    projectRoot=root,
                    skillId=entry.skillId,
                    variables={
                        "chapterId": chapter_id,
                        "chapterTitle": chapter_title or f"Chapter {chapter_id}",
                    },
                    agentId="local-dry-run",
                    runId=run_id,
                )
            )
            output_path = result.outputPath or ""
            run_dir = result.runDir.relative_to(PathGuard(root).root).as_posix()
        except Exception as exc:
            issues.append(
                PromptEvalIssue(
                    severity="blocker",
                    entryId=entry.id,
                    type="execution_failed",
                    message=str(exc),
                )
            )

        issues.extend(
            self._guardrail_issues(root, entry, output_path, protected_snapshot)
        )
        status = self._status_from_issues(issues)
        return PromptEvalResult(
            entryId=entry.id,
            skillId=entry.skillId,
            status=status,
            score=self._score(status, issues),
            runId=run_id,
            outputPath=output_path,
            runDir=run_dir,
            issues=issues,
        )

    def _guardrail_issues(
        self,
        root: Path,
        entry: PromptRegistryEntry,
        output_path: str,
        protected_snapshot: dict[str, str | None],
    ) -> list[PromptEvalIssue]:
        issues: list[PromptEvalIssue] = []
        source = Path(entry.source)
        if not source.is_file():
            issues.append(
                PromptEvalIssue(
                    severity="blocker",
                    entryId=entry.id,
                    type="missing_prompt_source",
                    message=f"missing prompt source: {entry.source}",
                )
            )
        if "draft_only_output" in entry.guardrails and not output_path.startswith("drafts/"):
            issues.append(
                PromptEvalIssue(
                    severity="blocker",
                    entryId=entry.id,
                    type="draft_only_output",
                    message=f"expected drafts/ output, got {output_path or '-'}",
                )
            )
        if output_path.startswith(("chapters/", "memory/")):
            issues.append(
                PromptEvalIssue(
                    severity="blocker",
                    entryId=entry.id,
                    type="canon_write",
                    message=f"prompt eval wrote canonical path: {output_path}",
                )
            )

        guard = PathGuard(root)
        for relative_path, before in protected_snapshot.items():
            path = guard.resolve(relative_path)
            after = path.read_text(encoding="utf-8") if path.is_file() else None
            if after != before:
                issues.append(
                    PromptEvalIssue(
                        severity="high",
                        entryId=entry.id,
                        type="protected_file_changed",
                        message=f"protected file changed during eval: {relative_path}",
                    )
                )
        return issues

    def _protected_snapshot(self, root: Path, chapter_id: str) -> dict[str, str | None]:
        guard = PathGuard(root)
        protected_paths = [
            f"chapters/{chapter_id}.md",
            "memory/facts.json",
            "memory/open-loops.json",
            "memory/character-states.json",
            "memory/relationship-states.json",
            "memory/timeline-events.json",
            "memory/chapter-summaries.json",
            "memory/promises.json",
            "memory/emotional-arcs.json",
            "memory/writing-lessons.json",
            "memory/writing-formulas.json",
            "memory/long-term-memory.json",
        ]
        snapshot: dict[str, str | None] = {}
        for relative_path in protected_paths:
            path = guard.resolve(relative_path)
            snapshot[relative_path] = path.read_text(encoding="utf-8") if path.is_file() else None
        return snapshot

    def _write_report(self, root: Path, report: PromptEvalReport) -> str:
        relative_path = f"{self.report_dir}/{report.evalId}.json"
        report.path = relative_path
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
        )
        return relative_path

    def _eval_id(self, entry_id: str, chapter_id: str) -> str:
        safe_entry = entry_id.replace("/", "-").replace(".", "-")
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return f"{safe_entry}-{chapter_id}-{stamp}"

    def _status_from_issues(self, issues: list[PromptEvalIssue]) -> PromptEvalStatus:
        if any(issue.severity == "blocker" for issue in issues):
            return "block"
        if any(issue.severity in {"medium", "high"} for issue in issues):
            return "warn"
        return "pass"

    def _score(self, status: PromptEvalStatus, issues: list[PromptEvalIssue]) -> int:
        if status == "block":
            return 0
        penalty = 0
        for issue in issues:
            penalty += {"low": 5, "medium": 15, "high": 30, "blocker": 100}[issue.severity]
        return max(0, 100 - penalty)
