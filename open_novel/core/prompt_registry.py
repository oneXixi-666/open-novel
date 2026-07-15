from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from open_novel.core.skills import SkillLoader, default_skills_dir


class PromptRegistryEntry(BaseModel):
    id: str
    kind: Literal["skill", "editorial", "workflow"] = "skill"
    skillId: str = ""
    source: str
    slots: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    status: Literal["active", "planned", "retired"] = "active"


class PromptRegistryIssue(BaseModel):
    severity: Literal["low", "medium", "high", "blocker"]
    entryId: str
    message: str


class PromptRegistryReport(BaseModel):
    schemaVersion: int = 1
    status: Literal["pass", "warn", "block"]
    entries: list[PromptRegistryEntry] = Field(default_factory=list)
    issues: list[PromptRegistryIssue] = Field(default_factory=list)


class PromptRegistryService:
    """Build and validate a registry over existing Open Novel prompts."""

    known_slots = {
        "chapterId",
        "chapterTitle",
        "runId",
        "scene_contract",
        "context_pack",
        "style_profile",
        "writing_lessons",
        "sourceText",
    }

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or default_skills_dir()
        self.loader = SkillLoader(self.skills_dir)

    def build_from_skills(self) -> PromptRegistryReport:
        entries: list[PromptRegistryEntry] = []
        for manifest in self.loader.list_skills():
            prompt_path = self.skills_dir / manifest.id / "prompt.md"
            entries.append(
                PromptRegistryEntry(
                    id=f"{manifest.id}.v1",
                    skillId=manifest.id,
                    source=prompt_path.as_posix(),
                    slots=self._infer_slots(manifest.inputs),
                    outputs=manifest.outputs,
                    guardrails=self._guardrails_for_manifest(manifest.writePolicy),
                    status="active",
                )
            )
        return self.validate(PromptRegistryReport(status="pass", entries=entries))

    def validate(self, report: PromptRegistryReport) -> PromptRegistryReport:
        issues: list[PromptRegistryIssue] = []
        ids: set[str] = set()
        for entry in report.entries:
            if entry.id in ids:
                issues.append(
                    PromptRegistryIssue(
                        severity="blocker",
                        entryId=entry.id,
                        message="提示词登记编号重复。",
                    )
                )
            ids.add(entry.id)
            source = Path(entry.source)
            if not source.is_absolute():
                source = Path(entry.source)
            if not source.is_file():
                issues.append(
                    PromptRegistryIssue(
                        severity="blocker",
                        entryId=entry.id,
                        message=f"missing prompt source: {entry.source}",
                    )
                )
            unknown_slots = sorted(set(entry.slots) - self.known_slots)
            if unknown_slots:
                issues.append(
                    PromptRegistryIssue(
                        severity="medium",
                        entryId=entry.id,
                        message=f"unknown slots: {', '.join(unknown_slots)}",
                    )
                )
        status: Literal["pass", "warn", "block"] = "pass"
        if any(issue.severity == "blocker" for issue in issues):
            status = "block"
        elif issues:
            status = "warn"
        report.issues = issues
        report.status = status
        return report

    def write_builtin_catalog(self, output_path: Path) -> PromptRegistryReport:
        report = self.build_from_skills()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return report

    def _infer_slots(self, inputs: list[str]) -> list[str]:
        slots = {"chapterId", "chapterTitle", "runId"}
        for input_path in inputs:
            if "chapter-briefs" in input_path:
                slots.add("scene_contract")
            if "context-packs" in input_path:
                slots.add("context_pack")
            if "style-profile" in input_path:
                slots.add("style_profile")
            if "writing-lessons" in input_path:
                slots.add("writing_lessons")
        return sorted(slots)

    def _guardrails_for_manifest(self, write_policy: str) -> list[str]:
        guardrails = ["no_canon_write"]
        if write_policy == "draft-only":
            guardrails.append("draft_only_output")
        if write_policy == "proposal-only":
            guardrails.append("proposal_only_output")
        return guardrails
