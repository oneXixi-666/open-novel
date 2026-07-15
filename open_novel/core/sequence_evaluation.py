from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.models import (
    ChapterSequenceEvaluationItem,
    ChapterSequenceEvaluationReport,
)
from open_novel.core.project import ProjectService
from open_novel.core.writing_quality import WritingQualityService


class ChapterSequenceEvaluationService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        writing_quality_service: WritingQualityService | None = None,
        chapter_gate_service: ChapterGateService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.writing_quality_service = writing_quality_service or WritingQualityService(
            self.project_service
        )
        self.chapter_gate_service = chapter_gate_service or ChapterGateService(
            self.project_service
        )

    def report_path(self, start_chapter_id: str, end_chapter_id: str) -> str:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        return f"runs/sequence-evaluation-{start}-{end}.json"

    def evaluate(
        self,
        root: Path,
        start_chapter_id: str,
        end_chapter_id: str,
        prefer_drafts: bool = True,
    ) -> ChapterSequenceEvaluationReport:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        chapter_ids = self._chapter_ids(start, end)
        chapters: list[ChapterSequenceEvaluationItem] = []
        for chapter_id in chapter_ids:
            draft_path = (
                self._draft_path(root, chapter_id)
                if prefer_drafts
                else f"chapters/{chapter_id}.md"
            )
            quality = self.writing_quality_service.evaluate_chapter(
                root,
                chapter_id,
                draft_path=draft_path,
            )
            gate = self.chapter_gate_service.check_chapter(
                root,
                chapter_id,
                draft_path=draft_path,
                include_review=False,
            )
            chapters.append(
                ChapterSequenceEvaluationItem(
                    chapterId=chapter_id,
                    qualityScore=quality.score,
                    qualityIssueCount=len(quality.issues),
                    gateStatus=gate.status,
                    gateScore=gate.score,
                    gateIssueCount=len(gate.issues),
                )
            )
        report = ChapterSequenceEvaluationReport(
            startChapterId=start,
            endChapterId=end,
            status=self._status(chapters),
            chapters=chapters,
            minQualityScore=min((item.qualityScore for item in chapters), default=0),
            minGateScore=min((item.gateScore for item in chapters), default=0),
            recommendedNextAction=self._recommended_next_action(chapters),
        )
        self.project_service.write_text(
            root,
            self.report_path(start, end),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _chapter_ids(self, start: str, end: str) -> list[str]:
        if not start.isdigit() or not end.isdigit():
            raise ValueError("chapter range must use numeric chapter ids")
        start_number = int(start)
        end_number = int(end)
        if start_number > end_number:
            raise ValueError("start chapter must be before or equal to end chapter")
        return [f"{number:03d}" for number in range(start_number, end_number + 1)]

    def _draft_path(self, root: Path, chapter_id: str) -> str | None:
        relative_path = f"drafts/{chapter_id}.generated.md"
        try:
            self.project_service.read_text(root, relative_path)
        except FileNotFoundError:
            return None
        return relative_path

    def _status(self, chapters: list[ChapterSequenceEvaluationItem]) -> str:
        if any(item.gateStatus == "block" for item in chapters):
            return "block"
        if any(item.qualityScore < 70 or item.gateStatus == "warn" for item in chapters):
            return "warn"
        return "pass"

    def _recommended_next_action(self, chapters: list[ChapterSequenceEvaluationItem]) -> str:
        if any(item.gateStatus == "block" for item in chapters):
            return "fix-blocking-sequence-issues"
        if any(item.qualityScore < 70 for item in chapters):
            return "revise-low-quality-chapters"
        if any(item.gateStatus == "warn" for item in chapters):
            return "review-warning-level-sequence-issues"
        return "ready"
