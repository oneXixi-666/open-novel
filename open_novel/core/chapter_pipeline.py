from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from open_novel.core.models import utc_now
from open_novel.core.project import ProjectService

PipelineStatus = Literal["missing", "pending", "ready", "blocked", "skipped"]

PIPELINE_DIR = "story/chapter-pipelines"


class ChapterPipelineStep(BaseModel):
    id: str
    status: PipelineStatus = "pending"
    artifact: str = ""
    runId: str = ""
    message: str = ""
    updatedAt: datetime = Field(default_factory=utc_now)


class ChapterPipeline(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    steps: list[ChapterPipelineStep] = Field(default_factory=list)
    updatedAt: datetime = Field(default_factory=utc_now)


class ChapterPipelineService:
    """Maintain the auditable per-chapter production pipeline artifact."""

    step_order = [
        "scene_contract",
        "readiness",
        "context_pack",
        "draft",
        "gate",
        "post_review",
        "canon_patch",
    ]

    default_artifacts = {
        "scene_contract": "story/chapter-briefs/{chapter_id}.json",
        "readiness": "runs/readiness-{chapter_id}.json",
        "context_pack": "story/context-packs/{chapter_id}.json",
        "draft": "drafts/{chapter_id}.generated.md",
        "gate": "runs/chapter-gate-{chapter_id}.json",
        "post_review": "reviews/{chapter_id}.review.json",
        "canon_patch": "patches/{chapter_id}.canon-patch.json",
    }

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def pipeline_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"{PIPELINE_DIR}/{normalized}.json"

    def read_pipeline(self, root: Path, chapter_id: str) -> ChapterPipeline:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        relative_path = self.pipeline_path(normalized)
        if not self.project_service.file_exists(root, relative_path):
            return self.refresh(root, normalized)
        return ChapterPipeline.model_validate_json(
            self.project_service.read_text(root, relative_path)
        )

    def refresh(self, root: Path, chapter_id: str) -> ChapterPipeline:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        steps: list[ChapterPipelineStep] = []
        for step_id in self.step_order:
            artifact = self.default_artifacts[step_id].format(chapter_id=normalized)
            exists = self.project_service.file_exists(root, artifact)
            steps.append(
                ChapterPipelineStep(
                    id=step_id,
                    status="ready" if exists else "pending",
                    artifact=artifact,
                    message="产物已准备" if exists else "等待生成产物",
                )
            )
        pipeline = ChapterPipeline(chapterId=normalized, steps=steps, updatedAt=utc_now())
        self.write_pipeline(root, pipeline)
        return pipeline

    def update_step(
        self,
        root: Path,
        chapter_id: str,
        step_id: str,
        *,
        status: PipelineStatus = "ready",
        artifact: str = "",
        run_id: str = "",
        message: str = "",
    ) -> ChapterPipeline:
        if step_id not in self.step_order:
            raise ValueError(f"unknown pipeline step: {step_id}")
        pipeline = self.read_pipeline(root, chapter_id)
        by_id = {step.id: step for step in pipeline.steps}
        default_artifact = self.default_artifacts[step_id].format(
            chapter_id=pipeline.chapterId
        )
        by_id[step_id] = ChapterPipelineStep(
            id=step_id,
            status=status,
            artifact=artifact or by_id.get(step_id, ChapterPipelineStep(id=step_id)).artifact
            or default_artifact,
            runId=run_id,
            message=message,
            updatedAt=utc_now(),
        )
        pipeline.steps = [by_id[step_id] for step_id in self.step_order]
        pipeline.updatedAt = utc_now()
        self.write_pipeline(root, pipeline)
        return pipeline

    def write_pipeline(self, root: Path, pipeline: ChapterPipeline) -> None:
        self.project_service.write_text(
            root,
            self.pipeline_path(pipeline.chapterId),
            json.dumps(pipeline.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
        )
