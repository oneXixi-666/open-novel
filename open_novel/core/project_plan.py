from __future__ import annotations

import json
import re
from pathlib import Path

from open_novel.core.models import ProjectPlan, ProjectPlanSummary, utc_now
from open_novel.core.project import ProjectService

PROJECT_PLAN_PATH = "story/project-plan.json"


class ProjectPlanService:
    """Read, write, and summarize a creator-facing publishing plan."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_plan(self, root: Path) -> ProjectPlan:
        if not self.project_service.file_exists(root, PROJECT_PLAN_PATH):
            project = self.project_service.open_project(root)
            return ProjectPlan(
                targetWordsPerChapter=project.metadata.chapterWordTarget,
                platform="通用网文",
            )
        return ProjectPlan.model_validate_json(
            self.project_service.read_text(root, PROJECT_PLAN_PATH)
        )

    def write_plan(
        self,
        root: Path,
        *,
        target_chapter_count: int,
        target_words_per_chapter: int,
        target_chapters_per_plot: int | None = None,
        platform: str = "通用网文",
        cadence: str = "稳定连载",
        notes: str = "",
    ) -> ProjectPlan:
        plot_chapter_target = target_chapters_per_plot
        if plot_chapter_target is None:
            plot_chapter_target = (
                self.read_plan(root).targetChaptersPerPlot
                if self.project_service.file_exists(root, PROJECT_PLAN_PATH)
                else 10
            )
        plan = ProjectPlan(
            targetChapterCount=self._clamp(target_chapter_count, 1, 5000),
            targetWordsPerChapter=self._clamp(target_words_per_chapter, 300, 30000),
            targetChaptersPerPlot=self._clamp(plot_chapter_target, 1, 100),
            platform=platform.strip() or "通用网文",
            cadence=cadence.strip() or "稳定连载",
            notes=notes.strip(),
            updatedAt=utc_now(),
        )
        self.project_service.write_text(
            root,
            PROJECT_PLAN_PATH,
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return plan

    def ensure_plan(
        self,
        root: Path,
        *,
        target_chapter_count: int | None = None,
        target_words_per_chapter: int | None = None,
        target_chapters_per_plot: int | None = None,
        platform: str = "",
        cadence: str = "",
    ) -> ProjectPlan:
        existing = self.read_plan(root)
        return self.write_plan(
            root,
            target_chapter_count=target_chapter_count or existing.targetChapterCount,
            target_words_per_chapter=(
                target_words_per_chapter or existing.targetWordsPerChapter
            ),
            target_chapters_per_plot=(
                target_chapters_per_plot or existing.targetChaptersPerPlot
            ),
            platform=platform or existing.platform,
            cadence=cadence or existing.cadence,
            notes=existing.notes,
        )

    def summarize(self, root: Path) -> ProjectPlanSummary:
        plan = self.read_plan(root)
        completed_chapters, accepted_words = self._chapter_progress(root)
        target_total_words = plan.targetChapterCount * plan.targetWordsPerChapter
        average = int(accepted_words / completed_chapters) if completed_chapters else 0
        return ProjectPlanSummary(
            plan=plan,
            completedChapterCount=completed_chapters,
            acceptedWordCount=accepted_words,
            targetTotalWords=target_total_words,
            nextChapterId=self.project_service.next_chapter_id(root),
            chapterProgressPercent=self._percent(completed_chapters, plan.targetChapterCount),
            wordProgressPercent=self._percent(accepted_words, target_total_words),
            averageWordsPerCompletedChapter=average,
        )

    def _chapter_progress(self, root: Path) -> tuple[int, int]:
        completed = 0
        accepted_words = 0
        chapter_paths = [
            path
            for path in self.project_service.list_paths(root, "chapters")
            if path.endswith(".md")
        ]
        for relative_path in chapter_paths:
            body = self._body_without_heading(
                self.project_service.read_text(root, relative_path)
            )
            count = self._cn_word_count(body)
            if count > 0:
                completed += 1
                accepted_words += count
        return completed, accepted_words

    def _body_without_heading(self, text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("#"):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _cn_word_count(self, text: str) -> int:
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_words = len(re.findall(r"[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*", text))
        other_visible = len(re.findall(r"[^\s\W_]", text, flags=re.UNICODE)) - cjk_chars
        return max(0, cjk_chars + latin_words + other_visible)

    def _percent(self, value: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(0, min(100, round(value * 100 / total)))

    def _clamp(self, value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(int(value), maximum))
