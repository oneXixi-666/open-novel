from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.text_support import important_terms, text_supports_claim
from open_novel.core.writing_quality import WritingQualityService


class ChapterAnalysis(BaseModel):
    chapterId: str
    source: str
    wordCount: int = 0
    dialogueCount: int = 0
    conflictDensity: int = 0
    hookSupported: bool = False
    emotionSupported: bool = False
    readerPromiseSupported: bool = False
    qualityScore: int | None = None
    gateScore: int | None = None
    formulaCandidates: list[str] = Field(default_factory=list)


class BookAnalysisReport(BaseModel):
    schemaVersion: int = 1
    startChapterId: str
    endChapterId: str
    path: str
    status: Literal["pass", "warn"]
    chapters: list[ChapterAnalysis] = Field(default_factory=list)
    formulaCandidates: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BookAnalysisService:
    report_dir = "runs/book-analysis"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)

    def report_path(self, start_chapter_id: str, end_chapter_id: str) -> str:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        return f"{self.report_dir}/{start}-{end}.json"

    def analyze_range(
        self,
        root: Path,
        start_chapter_id: str,
        end_chapter_id: str,
    ) -> BookAnalysisReport:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        chapter_ids = self._chapter_ids(start, end)
        chapters: list[ChapterAnalysis] = []
        notes: list[str] = []
        for chapter_id in chapter_ids:
            try:
                chapters.append(self._analyze_chapter(root, chapter_id))
            except FileNotFoundError:
                notes.append(f"missing accepted chapter or contract: {chapter_id}")

        formula_candidates = self._formula_candidates(chapters)
        report = BookAnalysisReport(
            startChapterId=start,
            endChapterId=end,
            path=self.report_path(start, end),
            status="pass" if chapters else "warn",
            chapters=chapters,
            formulaCandidates=formula_candidates,
            notes=notes,
        )
        self.project_service.write_text(
            root,
            report.path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def read_report(self, root: Path, report_path: str) -> BookAnalysisReport:
        return BookAnalysisReport.model_validate_json(
            self.project_service.read_text(root, report_path)
        )

    def _analyze_chapter(self, root: Path, chapter_id: str) -> ChapterAnalysis:
        source = f"chapters/{chapter_id}.md"
        text = self.project_service.read_text(root, source)
        contract = self.story_guidance.read_scene_contract(root, chapter_id)
        contract_data = contract.model_dump(mode="json")
        quality_score = self._quality_score(root, chapter_id)
        gate_score = self._gate_score(root, chapter_id)
        conflict_terms = important_terms(str(contract_data.get("conflict") or ""))
        conflict_hits = sum(1 for term in conflict_terms if term and term in text)
        hook = str(contract_data.get("hook") or "")
        emotion = str(contract_data.get("emotionalBeat") or "")
        promises = [
            item for item in contract_data.get("readerPromises", []) if isinstance(item, str)
        ]
        promise_supported = any(self._supports(text, promise) for promise in promises)
        analysis = ChapterAnalysis(
            chapterId=chapter_id,
            source=source,
            wordCount=len(text),
            dialogueCount=self._dialogue_count(text),
            conflictDensity=conflict_hits,
            hookSupported=self._supports(text, hook),
            emotionSupported=self._supports(text, emotion),
            readerPromiseSupported=promise_supported,
            qualityScore=quality_score,
            gateScore=gate_score,
        )
        analysis.formulaCandidates = self._chapter_formula_candidates(analysis)
        return analysis

    def _chapter_formula_candidates(self, analysis: ChapterAnalysis) -> list[str]:
        candidates: list[str] = []
        if analysis.conflictDensity > 0:
            candidates.append("conflict_visible_in_scene")
        if analysis.dialogueCount >= 2:
            candidates.append("dialogue_carries_pressure")
        if analysis.hookSupported:
            candidates.append("ending_hook_grounded")
        if analysis.emotionSupported:
            candidates.append("emotion_named_and_enacted")
        if analysis.readerPromiseSupported:
            candidates.append("reader_promise_advanced")
        return candidates

    def _formula_candidates(self, chapters: list[ChapterAnalysis]) -> list[dict[str, Any]]:
        by_id: dict[str, list[str]] = {}
        for chapter in chapters:
            for candidate in chapter.formulaCandidates:
                by_id.setdefault(candidate, []).append(chapter.chapterId)
        return [
            {
                "id": formula_id,
                "evidenceChapters": chapter_ids,
                "confidence": min(1.0, 0.5 + len(chapter_ids) * 0.1),
            }
            for formula_id, chapter_ids in sorted(by_id.items())
            if chapter_ids
        ]

    def _chapter_ids(self, start: str, end: str) -> list[str]:
        if start.isdigit() and end.isdigit():
            start_number = int(start)
            end_number = int(end)
            if end_number < start_number:
                raise ValueError("end chapter must be greater than or equal to start chapter")
            return [f"{number:03d}" for number in range(start_number, end_number + 1)]
        if start != end:
            raise ValueError("non-numeric chapter ranges must use the same id")
        return [start]

    def _quality_score(self, root: Path, chapter_id: str) -> int | None:
        try:
            quality_service = WritingQualityService(
                self.project_service,
                self.story_guidance,
            )
            return quality_service.evaluate_chapter(
                root,
                chapter_id,
                draft_path=f"chapters/{chapter_id}.md",
            ).score
        except FileNotFoundError:
            return None

    def _gate_score(self, root: Path, chapter_id: str) -> int | None:
        relative_path = f"runs/chapter-gate-{chapter_id}.json"
        if not self.project_service.file_exists(root, relative_path):
            return None
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return None
        raw = data.get("score")
        return raw if isinstance(raw, int) else None

    def _supports(self, text: str, claim: str) -> bool:
        return bool(claim and (claim in text or text_supports_claim(text, claim)))

    def _dialogue_count(self, text: str) -> int:
        return text.count("“") + text.count('"') // 2
