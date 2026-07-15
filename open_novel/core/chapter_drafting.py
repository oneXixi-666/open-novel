from __future__ import annotations

from pathlib import Path

from open_novel.core.active_prohibitions import ActiveProhibitionService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.models import SkillRunRequest, SkillRunResult
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_learning import WritingLearningService
from open_novel.core.writing_model import WritingModelService
from open_novel.core.writing_quality import WritingQualityService


class ChapterDraftService:
    """Draft chapters through the same gated path used by CLI and Web skills."""

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        skill_runner: SkillRunner | None = None,
        writing_model_service: WritingModelService | None = None,
        writing_learning_service: WritingLearningService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.skill_runner = skill_runner or SkillRunner(project_service=self.project_service)
        self.writing_model_service = writing_model_service or WritingModelService(
            self.project_service
        )
        self.writing_learning_service = writing_learning_service or WritingLearningService(
            self.project_service
        )

    def draft_chapter(
        self,
        project_root: Path,
        chapter_id: str,
        *,
        chapter_title: str = "",
        agent_id: str = "",
        model_profile: str | None = None,
        run_id: str | None = None,
        prefer_trained_model: bool = True,
        bypass_cache: bool = False,
    ) -> SkillRunResult:
        project = self.project_service.open_project(project_root)
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        resolved_agent, resolved_profile = self._resolve_drafting_route(
            project.root,
            agent_id=agent_id,
            model_profile=model_profile,
            prefer_trained_model=prefer_trained_model,
        )
        title = chapter_title.strip() or self._chapter_title(project.root, normalized)
        prohibitions = ActiveProhibitionService(self.project_service).format_for_prompt(
            project.root
        )
        result = self.skill_runner.run(
            SkillRunRequest(
                projectRoot=project.root,
                skillId="chapter-writer",
                variables={
                    "chapterId": normalized,
                    "chapterTitle": title,
                    "activeProhibitions": prohibitions,
                },
                agentId=resolved_agent,
                modelProfile=resolved_profile,
                runId=run_id,
                bypassCache=bypass_cache,
            )
        )
        self.project_service.write_text(
            project.root,
            f"drafts/{normalized}.generated.md",
            result.outputText,
        )
        return result

    def evaluate_and_learn(
        self,
        project_root: Path,
        chapter_id: str,
        *,
        draft_path: str | None = None,
    ) -> dict[str, object]:
        project = self.project_service.open_project(project_root)
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        source = draft_path or f"drafts/{normalized}.generated.md"
        quality = WritingQualityService(
            self.project_service,
            self.story_guidance,
        ).evaluate_chapter(project.root, normalized, draft_path=source)
        editorial = EditorialReviewService(
            self.project_service,
            self.story_guidance,
        ).review_chapter(project.root, normalized, draft_path=source)
        _, quality_learning = self.writing_learning_service.learn_from_writing_quality_with_summary(
            project.root,
            quality,
            min_severity="high",
        )
        _, success_learning = self.writing_learning_service.record_lesson_successes(
            project.root,
            normalized,
            quality,
            editorial,
        )
        gate = ChapterGateService().check_chapter(
            project.root,
            normalized,
            draft_path=source,
            include_review=False,
            include_draft=True,
        )
        return {
            "quality": quality,
            "editorial": editorial,
            "gate": gate,
            "lessonsPath": WritingLearningService.memory_path,
            "learning": {
                "quality": quality_learning,
                "success": success_learning,
            },
        }

    def _resolve_drafting_route(
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

    def _chapter_title(self, root: Path, chapter_id: str) -> str:
        try:
            contract = self.story_guidance.read_scene_contract(root, chapter_id)
        except FileNotFoundError:
            return f"Chapter {chapter_id}"
        return contract.title or f"Chapter {chapter_id}"
