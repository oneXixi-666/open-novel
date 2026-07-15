from __future__ import annotations

import re
from pathlib import Path

from open_novel.core.models import SkillRunRequest, SkillRunResult
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.writing_model import WritingModelService


class ChapterPolishService:
    """Create reviewable polished drafts from an existing chapter or draft file."""

    def __init__(
        self,
        project_service: ProjectService | None = None,
        skill_runner: SkillRunner | None = None,
        writing_model_service: WritingModelService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.skill_runner = skill_runner or SkillRunner(project_service=self.project_service)
        self.writing_model_service = writing_model_service or WritingModelService(
            self.project_service
        )

    def polish_file(
        self,
        project_root: Path,
        source_path: str,
        *,
        instruction: str = "",
        agent_id: str = "",
        model_profile: str | None = None,
        prefer_trained_model: bool = True,
        run_id: str | None = None,
    ) -> SkillRunResult:
        project = self.project_service.open_project(project_root)
        source_text = self.project_service.read_text(project.root, source_path)
        target_name = self._target_name(source_path)
        resolved_agent, resolved_profile = self._resolve_polish_route(
            project.root,
            agent_id=agent_id,
            model_profile=model_profile,
            prefer_trained_model=prefer_trained_model,
        )
        return self.skill_runner.run(
            SkillRunRequest(
                projectRoot=project.root,
                skillId="line-editor",
                variables={
                    "sourcePath": source_path,
                    "sourceText": source_text,
                    "targetName": target_name,
                    "instruction": instruction.strip()
                    or (
                        "在不改变剧情事实、人物关系和章节结构的前提下，"
                        "提升可读性、节奏、细节和情绪表达。"
                    ),
                },
                agentId=resolved_agent,
                modelProfile=resolved_profile,
                runId=run_id,
            )
        )

    def _resolve_polish_route(
        self,
        root: Path,
        *,
        agent_id: str,
        model_profile: str | None,
        prefer_trained_model: bool,
    ) -> tuple[str, str | None]:
        if agent_id.strip():
            return agent_id.strip(), model_profile
        if model_profile:
            return "local-model", model_profile
        if not prefer_trained_model:
            return "local-dry-run", None

        registry = self.writing_model_service.read_registry(root)
        default_profile_id = registry.defaultProfileId.strip()
        for profile in registry.profiles:
            if profile.id == default_profile_id and profile.commandTemplate.strip():
                return "local-model", profile.id
        for profile in registry.profiles:
            if profile.commandTemplate.strip():
                return "local-model", profile.id
        return "local-dry-run", None

    def _target_name(self, source_path: str) -> str:
        name = Path(source_path).name
        stem = name.removesuffix(".md").removesuffix(".generated").removesuffix(".polished")
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")
        if not stem:
            return "selection"
        if stem.isdigit():
            return self.project_service.normalize_chapter_id(stem)
        return stem
