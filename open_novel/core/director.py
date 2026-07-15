from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import SkillRunRequest, utc_now
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService

DIRECTOR_PLAN_DIR = "story/director-plans"
DIRECTOR_RUN_DIR = "runs/director"

DirectorStepStatus = Literal["pending", "ready", "complete", "blocked", "skipped"]


class DirectorIntent(BaseModel):
    chapterId: str
    intent: str
    mode: Literal["plan-only", "guided-run"] = "plan-only"


class DirectorStep(BaseModel):
    id: str
    action: str
    service: str
    status: DirectorStepStatus = "pending"
    artifact: str = ""
    requiresApproval: bool = False
    rationale: str = ""


class DirectorPlan(BaseModel):
    schemaVersion: int = 1
    planId: str
    chapterId: str
    intent: str
    status: Literal["planned", "running", "complete", "blocked"] = "planned"
    steps: list[DirectorStep] = Field(default_factory=list)
    allowedWritePrefixes: list[str] = Field(
        default_factory=lambda: ["runs/", "drafts/", "story/", "patches/", "reviews/"]
    )
    planPath: str = ""
    runReportPath: str = ""
    createdAt: datetime = Field(default_factory=utc_now)


class DirectorRunReport(BaseModel):
    schemaVersion: int = 1
    runId: str
    planId: str
    chapterId: str
    status: Literal["planned", "dry-run", "complete", "blocked"] = "planned"
    executedSteps: list[DirectorStep] = Field(default_factory=list)
    message: str = ""
    createdAt: datetime = Field(default_factory=utc_now)


class DirectorService:
    """Plan auditable chapter production work without touching canon files."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def create_plan(self, root: Path, chapter_id: str, intent: str) -> DirectorPlan:
        project = self.project_service.open_project(root)
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        plan_id = f"director-{normalized}-{utc_now().strftime('%Y%m%d%H%M%S')}"
        plan_path = f"{DIRECTOR_PLAN_DIR}/{normalized}.json"
        run_report_path = f"{DIRECTOR_RUN_DIR}/{plan_id}.json"
        plan = DirectorPlan(
            planId=plan_id,
            chapterId=normalized,
            intent=intent.strip(),
            steps=self._build_steps(project.root, normalized, intent),
            planPath=plan_path,
            runReportPath=run_report_path,
        )
        self._assert_safe_plan(plan)
        self.project_service.write_text(
            project.root,
            plan_path,
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        report = DirectorRunReport(
            runId=plan_id,
            planId=plan_id,
            chapterId=normalized,
            status="planned",
            executedSteps=[],
            message="导演计划已创建，计划确认与实际执行保持分离。",
        )
        self.project_service.write_text(
            project.root,
            run_report_path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
        )
        return plan

    def read_plan(self, root: Path, plan_path: str) -> DirectorPlan:
        return DirectorPlan.model_validate_json(
            self.project_service.read_text(root, plan_path)
        )

    def dry_run(self, root: Path, plan_path: str) -> DirectorRunReport:
        plan = self.read_plan(root, plan_path)
        self._assert_safe_plan(plan)
        report = DirectorRunReport(
            runId=plan.planId,
            planId=plan.planId,
            chapterId=plan.chapterId,
            status="dry-run",
            executedSteps=[
                step.model_copy(update={"status": "skipped", "rationale": "dry run"})
                for step in plan.steps
            ],
            message="试运行已完成，未写入正文或正式记忆。",
        )
        self.project_service.write_text(
            root,
            plan.runReportPath,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
        )
        return report

    def run(self, root: Path, plan_path: str) -> DirectorRunReport:
        project = self.project_service.open_project(root)
        plan = self.read_plan(project.root, plan_path)
        self._assert_safe_plan(plan)
        executed: list[DirectorStep] = []
        blocked = False

        for step in plan.steps:
            if step.requiresApproval:
                executed.append(
                    step.model_copy(
                        update={
                            "status": "skipped",
                            "rationale": f"{step.rationale} Awaiting explicit approval.",
                        }
                    )
                )
                continue
            try:
                artifact = self._execute_step(project.root, plan, step)
            except Exception as exc:
                executed.append(
                    step.model_copy(
                        update={
                            "status": "blocked",
                            "rationale": f"{step.rationale} Blocked: {exc}",
                        }
                    )
                )
                blocked = True
                break
            executed.append(
                step.model_copy(
                    update={
                        "status": "complete",
                        "artifact": artifact or step.artifact,
                    }
                )
            )

        report = DirectorRunReport(
            runId=plan.planId,
            planId=plan.planId,
            chapterId=plan.chapterId,
            status="blocked" if blocked else "complete",
            executedSteps=executed,
            message=(
                "Guided run blocked before completion."
                if blocked
                else "Guided run completed without accepting drafts or applying memory patches."
            ),
        )
        self.project_service.write_text(
            project.root,
            plan.runReportPath,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
        )
        return report

    def _execute_step(self, root: Path, plan: DirectorPlan, step: DirectorStep) -> str:
        chapter_id = plan.chapterId
        if step.id == "scene_contract":
            path = StoryGuidanceService(self.project_service).contract_path(chapter_id)
            if not self.project_service.file_exists(root, path):
                StoryGuidanceService(self.project_service).create_scene_contract(root, chapter_id)
            return path
        if step.id == "context_pack":
            context_pack = ContextPackService(self.project_service).build_context_pack(
                root,
                chapter_id,
            )
            return context_pack.path
        if step.id == "draft":
            result = SkillRunner(project_service=self.project_service).run(
                SkillRunRequest(
                    projectRoot=root,
                    skillId="chapter-writer",
                    variables={"chapterId": chapter_id, "chapterTitle": f"Chapter {chapter_id}"},
                    agentId="local-dry-run",
                    runId=f"{plan.planId}-draft",
                )
            )
            return result.outputPath or step.artifact
        if step.id == "gate":
            ChapterGateService(self.project_service).check_chapter(
                root,
                chapter_id,
                draft_path=f"drafts/{chapter_id}.generated.md",
                include_review=False,
            )
            return step.artifact
        if step.id == "post_review":
            review = PostChapterService(self.project_service).build_review(root, chapter_id)
            return PostChapterService(self.project_service).review_path(review.chapterId)
        if step.id == "canon_patch":
            patch = PostChapterService(self.project_service).propose_canon_patch(
                root,
                chapter_id,
            )
            return PostChapterService(self.project_service).patch_path(patch.chapterId)
        raise ValueError(f"unsupported director step: {step.id}")

    def _build_steps(self, root: Path, chapter_id: str, intent: str) -> list[DirectorStep]:
        steps: list[DirectorStep] = []
        contract_path = f"story/chapter-briefs/{chapter_id}.json"
        context_path = f"story/context-packs/{chapter_id}.json"
        draft_path = f"drafts/{chapter_id}.generated.md"
        gate_path = f"runs/chapter-gate-{chapter_id}.json"
        review_path = f"reviews/{chapter_id}.review.json"
        patch_path = f"patches/{chapter_id}.canon-patch.json"
        contract_exists = self.project_service.file_exists(root, contract_path)
        context_exists = self.project_service.file_exists(root, context_path)
        if self._needs_direction(intent):
            steps.append(
                DirectorStep(
                    id="suggest_direction",
                    action="suggest plot direction options from the user intent",
                    service="PlotDirectionService",
                    artifact=f"story/branches/{chapter_id}.direction-report.json",
                    requiresApproval=True,
                    rationale="Intent asks for conflict, hook, pacing, or direction changes.",
                )
            )
        steps.extend(
            [
                DirectorStep(
                    id="scene_contract",
                    action="create or update the scene contract",
                    service="StoryGuidanceService",
                    status="ready" if contract_exists else "pending",
                    artifact=contract_path,
                    requiresApproval=contract_exists,
                    rationale="Drafting should start from an auditable scene contract.",
                ),
                DirectorStep(
                    id="context_pack",
                    action="build bounded context for the chapter",
                    service="ContextPackService",
                    status="ready" if context_exists else "pending",
                    artifact=context_path,
                    rationale="The writer should consume a recorded context pack.",
                ),
                DirectorStep(
                    id="draft",
                    action="run chapter-writer into drafts only",
                    service="SkillRunner",
                    artifact=draft_path,
                    rationale="Generated prose must stay outside canonical chapters.",
                ),
                DirectorStep(
                    id="gate",
                    action="run chapter gate before acceptance",
                    service="ChapterGateService",
                    artifact=gate_path,
                    rationale="Acceptance remains guarded by readiness and continuity checks.",
                ),
                DirectorStep(
                    id="post_review",
                    action="build post-chapter review",
                    service="PostChapterService",
                    artifact=review_path,
                    requiresApproval=True,
                    rationale="Review output is a proposal for the author.",
                ),
                DirectorStep(
                    id="canon_patch",
                    action="propose canon memory patch",
                    service="PostChapterService",
                    artifact=patch_path,
                    requiresApproval=True,
                    rationale="Memory changes require explicit accept/apply later.",
                ),
            ]
        )
        return steps

    def _needs_direction(self, intent: str) -> bool:
        lowered = intent.lower()
        keywords = ["conflict", "hook", "direction", "pacing", "冲突", "钩子", "节奏", "方向"]
        return any(keyword in lowered for keyword in keywords)

    def _assert_safe_plan(self, plan: DirectorPlan) -> None:
        forbidden = ("chapters/", "memory/")
        allowed = tuple(plan.allowedWritePrefixes)
        for step in plan.steps:
            if not step.artifact:
                continue
            if step.artifact.startswith(forbidden):
                raise ValueError(f"director plan may not write canon artifact: {step.artifact}")
            if not step.artifact.startswith(allowed):
                raise ValueError(
                    f"director plan artifact is outside proposal space: {step.artifact}"
                )
