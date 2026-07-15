from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.models import TrainingReadinessItem, TrainingReadinessReport
from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.quality_calibration import (
    QualityThresholdConfig,
    suggested_min_recommended_examples,
)
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.workbench_repository import WorkbenchRepository
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.core.writing_quality import WritingQualityService
from open_novel.security.path_guard import PathGuard


@dataclass(frozen=True)
class ChapterExportRecord:
    chapterId: str
    text: str
    source: str


class ExportService:
    min_recommended_training_examples = 20

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = StoryGuidanceService(self.project_service)
        self.plan_service = ProjectPlanService(self.project_service)
        self.writing_quality = WritingQualityService(self.project_service, self.story_guidance)
        self.chapter_gate = ChapterGateService(self.project_service)

    def export(self, project_root: Path, export_format: str) -> Path:
        project = self.project_service.open_project(project_root)
        export_format = export_format.lower()
        if export_format == "markdown":
            return self.export_markdown(project.root)
        if export_format == "txt":
            return self.export_txt(project.root)
        if export_format == "zip":
            return self.export_zip(project.root)
        raise ValueError(f"unsupported export format: {export_format}")

    def export_markdown(self, project_root: Path) -> Path:
        title = self.project_service.open_project(project_root).metadata.title
        content = self._combined_markdown(project_root, title)
        relative_path = "exports/manuscript.md"
        self.project_service.write_text(project_root, relative_path, content)
        return project_root / relative_path

    def export_txt(self, project_root: Path) -> Path:
        title = self.project_service.open_project(project_root).metadata.title
        markdown = self._combined_markdown(project_root, title)
        text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
        relative_path = "exports/manuscript.txt"
        self.project_service.write_text(project_root, relative_path, text)
        return project_root / relative_path

    def export_zip(self, project_root: Path) -> Path:
        if self.project_service.is_database_project(project_root):
            output = Path(tempfile.mkdtemp(prefix="open-novel-export-")) / "manuscript.zip"
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                for relative_path in self.project_service.list_paths(project_root, "chapters"):
                    if relative_path.endswith(".md"):
                        archive.writestr(
                            relative_path,
                            self.project_service.read_text(project_root, relative_path),
                        )
                for relative_path in [
                    "novel.json",
                    "bible.md",
                    "style.md",
                    "rules.md",
                    "outline.md",
                ]:
                    if self.project_service.file_exists(project_root, relative_path):
                        archive.writestr(
                            relative_path,
                            self.project_service.read_text(project_root, relative_path),
                        )
            return output
        output = PathGuard(project_root).resolve("exports/manuscript.zip")
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            for chapter in self._chapter_files(project_root):
                archive.write(chapter, f"chapters/{chapter.name}")
            for relative in ["novel.json", "bible.md", "style.md", "rules.md", "outline.md"]:
                path = PathGuard(project_root).resolve(relative)
                if path.exists():
                    archive.write(path, relative)
        return output

    def export_writing_training_jsonl(
        self,
        project_root: Path,
        threshold_config: QualityThresholdConfig | None = None,
        selected_chapter_ids: list[str] | None = None,
    ) -> Path:
        project = self.project_service.open_project(project_root)
        relative_path = "exports/writing-training.jsonl"
        readiness = self.training_readiness(project.root, threshold_config=threshold_config)
        selected_ids = {
            str(item).strip()
            for item in selected_chapter_ids or []
            if str(item).strip()
        }
        eligible_chapter_ids = (
            selected_ids
            if selected_ids
            else {item.chapterId for item in readiness.items if item.eligible}
        )
        labels = self._calibration_labels(project.root)
        lessons = self._read_json(project.root, "memory/writing-lessons.json")
        lines: list[str] = []
        for chapter in self._chapter_records(project.root):
            chapter_id = chapter.chapterId
            if chapter_id not in eligible_chapter_ids:
                continue
            try:
                contract = self.story_guidance.read_scene_contract(project.root, chapter_id)
            except FileNotFoundError:
                continue
            review = self._read_json(project.root, f"reviews/{chapter_id}.review.json")
            quality = self._read_json(project.root, f"runs/writing-quality-{chapter_id}.json")
            gate = self._read_json(project.root, f"runs/chapter-gate-{chapter_id}.json")
            quality_score = self._score_from_report(quality)
            gate_score = self._score_from_report(gate)
            gate_status = self._status_from_report(gate)
            calibration_label = labels.get(chapter_id, "")
            record = {
                "instruction": (
                    "Write a fast Chinese web-novel chapter with strong continuity, "
                    "clear focus, grounded emotion, conflict escalation, and an ending hook."
                ),
                "input": {
                    "projectTitle": project.metadata.title,
                    "language": project.metadata.language,
                    "styleProfile": "tomato",
                    "sceneContract": contract.model_dump(mode="json"),
                    "boundedWritingLessons": lessons,
                    "postChapterReview": review,
                },
                "output": chapter.text,
                "metadata": {
                    "chapterId": chapter_id,
                    "source": chapter.source,
                    "purpose": "offline_local_lora_or_adapter_training",
                    "qualityScore": quality_score,
                    "gateScore": gate_score,
                    "quality_score": quality_score,
                    "gate_score": gate_score,
                    "gate_status": gate_status,
                    "calibration_label": calibration_label,
                },
            }
            lines.append(json.dumps(record, ensure_ascii=False))
        self.project_service.write_text(
            project.root,
            relative_path,
            "\n".join(lines) + ("\n" if lines else ""),
        )
        return project.root / relative_path

    def training_readiness(
        self,
        project_root: Path,
        threshold_config: QualityThresholdConfig | None = None,
    ) -> TrainingReadinessReport:
        project = self.project_service.open_project(project_root)
        thresholds = threshold_config or WorkbenchRepository().read_quality_thresholds(project.root)
        min_recommended_examples = self._min_recommended_training_examples(
            project.root,
            thresholds,
        )
        items: list[TrainingReadinessItem] = []
        chapter_records = self._chapter_records(project.root)
        records_by_id = {chapter.chapterId: chapter for chapter in chapter_records}
        for chapter in chapter_records:
            chapter_id = chapter.chapterId
            try:
                self.story_guidance.read_scene_contract(project.root, chapter_id)
            except FileNotFoundError:
                items.append(
                    TrainingReadinessItem(
                        chapterId=chapter_id,
                        eligible=False,
                        reason="missing_scene_contract",
                        actionSuggestion=self._training_action_suggestion(
                            "missing_scene_contract",
                            [],
                            0.0,
                        ),
                    )
                )
                continue
            quality, gate = self._chapter_training_reports(
                project.root,
                chapter_id,
                thresholds,
            )
            eligible = quality.score >= 70 and gate.status == "pass"
            reason = "" if eligible else self._training_skip_reason(quality.score, gate.status)
            issue_types = [issue.type for issue in quality.issues]
            issue_types.extend(f"{issue.stage}:{issue.type}" for issue in gate.issues)
            if eligible and self._has_training_continuity_issue(issue_types):
                eligible = False
                reason = "continuity_failed"
            previous_similarity = self._previous_similarity(quality.metrics)
            items.append(
                TrainingReadinessItem(
                    chapterId=chapter_id,
                    eligible=eligible,
                    reason=reason,
                    qualityScore=quality.score,
                    gateStatus=gate.status,
                    gateScore=gate.score,
                    issueCount=len(quality.issues) + len(gate.issues),
                    blockerCount=sum(
                        1
                        for issue in [*quality.issues, *gate.issues]
                        if issue.severity == "blocker"
                    ),
                    previousSimilarity=previous_similarity,
                    issueTypes=issue_types[:6],
                    actionSuggestion=self._training_action_suggestion(
                        reason,
                        issue_types,
                        previous_similarity,
                    ),
                )
            )
        self._deduplicate_training_batch(items, records_by_id, thresholds)
        eligible_count = sum(1 for item in items if item.eligible)
        skipped_count = len(items) - eligible_count
        report = TrainingReadinessReport(
            status=self._training_readiness_status(
                eligible_count,
                min_recommended_examples,
            ),
            eligibleCount=eligible_count,
            skippedCount=skipped_count,
            minRecommendedExamples=min_recommended_examples,
            items=items,
            recommendedNextAction=self._training_recommended_next_action(
                eligible_count,
                skipped_count,
                min_recommended_examples,
            ),
        )
        self.project_service.write_text(
            project.root,
            "exports/training-readiness.json",
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _combined_markdown(self, project_root: Path, title: str) -> str:
        sections = [f"# {title}\n"]
        for chapter in self._chapter_records(project_root):
            sections.append(chapter.text.strip())
        return "\n\n".join(section for section in sections if section).strip() + "\n"

    def _chapter_records(self, project_root: Path) -> list[ChapterExportRecord]:
        repository_records = self._workbench_chapter_records(project_root)
        if repository_records:
            return repository_records
        if self.project_service.is_database_project(project_root):
            return [
                ChapterExportRecord(
                    chapterId=Path(relative_path).stem,
                    text=self.project_service.read_text(project_root, relative_path),
                    source=relative_path,
                )
                for relative_path in self.project_service.list_paths(project_root, "chapters")
                if relative_path.endswith(".md")
            ]
        return [
            ChapterExportRecord(
                chapterId=chapter.stem,
                text=chapter.read_text(encoding="utf-8"),
                source=chapter.relative_to(project_root).as_posix(),
            )
            for chapter in self._chapter_files(project_root)
        ]

    def _workbench_chapter_records(self, project_root: Path) -> list[ChapterExportRecord]:
        db_path = WorkspaceRegistryService.default_registry_path()
        if not db_path.exists():
            return []
        try:
            chapters = WorkbenchRepository(db_path).list_chapters(project_root)
        except (OSError, sqlite3.Error):
            return []
        return [
            ChapterExportRecord(
                chapterId=str(chapter.get("id") or ""),
                text=str(chapter.get("content") or ""),
                source=f"workbench:chapters/{chapter.get('id')}.md",
            )
            for chapter in chapters
            if str(chapter.get("id") or "").strip()
            and str(chapter.get("content") or "").strip()
        ]

    def _chapter_files(self, project_root: Path) -> list[Path]:
        chapters_dir = PathGuard(project_root).resolve("chapters")
        if not chapters_dir.exists():
            return []
        return sorted(
            [path for path in chapters_dir.glob("*.md") if path.is_file()],
            key=self._chapter_sort_key,
        )

    def _chapter_sort_key(self, path: Path) -> tuple[int, str]:
        match = re.match(r"(\d+)", path.stem)
        if match:
            return (int(match.group(1)), path.name)
        return (10**9, path.name)

    def _chapter_is_training_quality(self, project_root: Path, chapter_id: str) -> bool:
        quality, gate = self._chapter_training_reports(
            project_root,
            chapter_id,
            WorkbenchRepository().read_quality_thresholds(project_root),
        )
        return quality.score >= 70 and gate.status == "pass"

    def _chapter_training_reports(
        self,
        project_root: Path,
        chapter_id: str,
        threshold_config: QualityThresholdConfig,
    ):
        quality = self.writing_quality.evaluate_chapter(
            project_root,
            chapter_id,
            draft_path=f"chapters/{chapter_id}.md",
            threshold_config=threshold_config,
        )
        gate = self.chapter_gate.check_chapter(
            project_root,
            chapter_id,
            draft_path=f"chapters/{chapter_id}.md",
            include_review=False,
            threshold_config=threshold_config,
        )
        return quality, gate

    def _training_skip_reason(self, quality_score: int, gate_status: str) -> str:
        if quality_score < 70 and gate_status != "pass":
            return "quality_and_gate_failed"
        if quality_score < 70:
            return "quality_failed"
        return "gate_failed"

    def _previous_similarity(self, metrics: dict[str, object]) -> float:
        paragraph = metrics.get("previousParagraphSimilarity")
        if isinstance(paragraph, (int, float)) and paragraph > 0:
            return round(float(paragraph), 3)
        value = metrics.get("previousSimilarity")
        return round(float(value), 3) if isinstance(value, (int, float)) else 0.0

    def _deduplicate_training_batch(
        self,
        items: list[TrainingReadinessItem],
        records_by_id: dict[str, ChapterExportRecord],
        thresholds: QualityThresholdConfig,
    ) -> None:
        eligible_items = [item for item in items if item.eligible]
        if len(eligible_items) < 2:
            return
        parent = {item.chapterId: item.chapterId for item in eligible_items}
        pair_similarity: dict[tuple[str, str], float] = {}
        for left_index, left in enumerate(eligible_items):
            for right in eligible_items[left_index + 1 :]:
                similarity = self._training_pair_similarity(
                    records_by_id[left.chapterId],
                    records_by_id[right.chapterId],
                )
                if similarity < thresholds.similarity_high:
                    continue
                key = tuple(sorted([left.chapterId, right.chapterId]))
                pair_similarity[key] = similarity
                self._union(parent, left.chapterId, right.chapterId)

        clusters: dict[str, list[TrainingReadinessItem]] = {}
        for item in eligible_items:
            clusters.setdefault(self._find(parent, item.chapterId), []).append(item)
        for cluster in clusters.values():
            if len(cluster) < 2:
                continue
            winner = sorted(
                cluster,
                key=lambda item: (
                    -item.qualityScore,
                    -item.gateScore,
                    item.issueCount,
                    item.blockerCount,
                    item.chapterId,
                ),
            )[0]
            for item in cluster:
                if item.chapterId == winner.chapterId:
                    continue
                key = tuple(sorted([item.chapterId, winner.chapterId]))
                similarity = pair_similarity.get(key) or self._training_pair_similarity(
                    records_by_id[item.chapterId],
                    records_by_id[winner.chapterId],
                )
                item.eligible = False
                item.reason = "batch_duplicate"
                item.batchDuplicateOf = winner.chapterId
                item.batchSimilarity = round(similarity, 3)
                item.previousSimilarity = max(item.previousSimilarity, item.batchSimilarity)
                if "batch_duplicate" not in item.issueTypes:
                    item.issueTypes.append("batch_duplicate")
                item.actionSuggestion = (
                    f"与第 {winner.chapterId} 章训练证据重复，保留质量分更高的一章。"
                )

    def _training_pair_similarity(
        self,
        left: ChapterExportRecord,
        right: ChapterExportRecord,
    ) -> float:
        left_body = self.writing_quality._body_text(left.text)  # noqa: SLF001
        right_body = self.writing_quality._body_text(right.text)  # noqa: SLF001
        metrics = self.writing_quality.text_similarity_metrics(left_body, right_body)
        return metrics["paragraph"] if metrics["jaccard"] >= 0.5 else 0.0

    def _find(self, parent: dict[str, str], chapter_id: str) -> str:
        current = parent[chapter_id]
        if current != chapter_id:
            parent[chapter_id] = self._find(parent, current)
        return parent[chapter_id]

    def _union(self, parent: dict[str, str], left: str, right: str) -> None:
        left_root = self._find(parent, left)
        right_root = self._find(parent, right)
        if left_root != right_root:
            parent[right_root] = left_root

    def _min_recommended_training_examples(
        self,
        project_root: Path,
        thresholds: QualityThresholdConfig,
    ) -> int:
        default_min = QualityThresholdConfig().min_recommended_examples
        if thresholds.min_recommended_examples != default_min:
            return thresholds.min_recommended_examples
        chapter_count = self.plan_service.summarize(project_root).plan.targetChapterCount
        return suggested_min_recommended_examples(chapter_count)

    def _training_action_suggestion(
        self,
        reason: str,
        issue_types: list[str],
        previous_similarity: float,
    ) -> str:
        if not reason:
            return "保留为训练样本；继续积累同等质量的定稿章节。"
        if reason == "missing_scene_contract":
            return "先补齐本章合同，再重新运行质量和 gate 检查。"
        if reason == "batch_duplicate":
            return "本章和同批训练样本重复度偏高，保留质量分更高的一章。"
        if reason == "continuity_failed":
            return "先修复情绪承接或人物名称一致性问题，再纳入训练样本。"
        if previous_similarity >= 0.72 or "too_similar_to_previous" in issue_types:
            return "优先重写本章目标、阻力形式和结尾钩子，降低与前章重复。"
        if "too_short" in issue_types or "word_count_out_of_range" in issue_types:
            return "扩展冲突过程、人物选择和结果余波，再重新评估。"
        if reason == "gate_failed":
            return "按 gate 提示修复连续性、上下文或审稿问题后再纳入训练。"
        return "先修复质量分和 gate 问题，作者确认后再作为训练样本。"

    def _has_training_continuity_issue(self, issue_types: list[str]) -> bool:
        blocked_types = {
            "emotional_discontinuity",
            "character_name_inconsistency",
        }
        return any(issue_type in blocked_types for issue_type in issue_types)

    def _training_readiness_status(self, eligible_count: int, min_recommended_examples: int) -> str:
        if eligible_count == 0:
            return "block"
        if eligible_count < min_recommended_examples:
            return "warn"
        return "ready"

    def _training_recommended_next_action(
        self,
        eligible_count: int,
        skipped_count: int,
        min_recommended_examples: int,
    ) -> str:
        if eligible_count == 0:
            return "create-and-accept-quality-checked-chapters"
        if eligible_count < min_recommended_examples:
            return "collect-more-quality-checked-examples-before-training"
        if skipped_count:
            return "review-skipped-training-examples"
        return "ready-for-offline-local-tuning"

    def _score_from_report(self, report: object) -> int:
        if not isinstance(report, dict):
            return 0
        score = report.get("score")
        return score if isinstance(score, int) else 0

    def _status_from_report(self, report: object) -> str:
        if not isinstance(report, dict):
            return ""
        status = report.get("status")
        return status if isinstance(status, str) else ""

    def _calibration_labels(self, project_root: Path) -> dict[str, str]:
        try:
            annotations = WorkbenchRepository().list_calibration_annotations(project_root)
        except (OSError, sqlite3.Error):
            return {}
        return {
            str(item.get("chapterId") or ""): str(item.get("label") or "")
            for item in annotations
        }

    def _read_json(self, project_root: Path, relative_path: str) -> object:
        if not self.project_service.file_exists(project_root, relative_path):
            return {}
        try:
            return json.loads(self.project_service.read_text(project_root, relative_path))
        except json.JSONDecodeError:
            return {}
