from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from open_novel.core.jobs import JobController
from open_novel.core.quality_calibration import (
    QualityThresholdConfig,
    build_calibration_analysis,
)


class WorkbenchCalibrationService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def annotate(self, request: Any) -> dict[str, Any]:
        root = self._root(request.bookId)
        try:
            annotation = self.presenter.workbench_repository.upsert_calibration_annotation(
                root,
                request.chapterId,
                request.label,
                request.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": root.as_posix(), "annotation": annotation}

    def analysis(self, book_id: str = "") -> dict[str, Any]:
        root = self._root(book_id)
        current = self.presenter.workbench_repository.read_quality_thresholds(root)
        rows = self._annotated_quality_rows(root, current)
        return {
            "bookId": root.as_posix(),
            **build_calibration_analysis(rows, current),
        }

    def apply(self, request: Any) -> dict[str, Any]:
        root = self._root(request.bookId)
        previous = self.presenter.workbench_repository.read_quality_thresholds(root)
        analysis = build_calibration_analysis(
            self._annotated_quality_rows(root, previous),
            previous,
        )
        if not analysis["thresholdEligible"]:
            raise HTTPException(
                status_code=409,
                detail="当前校准证据不足，不能应用阈值："
                + "；".join(analysis["thresholdBlockers"]),
            )
        next_thresholds = QualityThresholdConfig.from_dict(request.model_dump(exclude={"bookId"}))
        before = self.presenter.export_service.training_readiness(
            root,
            threshold_config=previous,
        )
        after = self.presenter.export_service.training_readiness(
            root,
            threshold_config=next_thresholds,
        )
        before_by_id = {item.chapterId: item.eligible for item in before.items}
        changed = [
            item.chapterId
            for item in after.items
            if before_by_id.get(item.chapterId) != item.eligible
        ]
        self.presenter.workbench_repository.write_quality_thresholds(root, next_thresholds)
        return {
            "bookId": root.as_posix(),
            "currentThresholds": next_thresholds.to_dict(),
            "history": self.presenter.workbench_repository.list_quality_threshold_history(root),
            "message": "阈值已应用，可通过校准历史撤销到应用前版本。",
            "previousEligibleCount": before.eligibleCount,
            "nextEligibleCount": after.eligibleCount,
            "affectedChapterCount": len(changed),
            "affectedChapterIds": changed,
        }

    def history(self, book_id: str = "") -> dict[str, Any]:
        root = self._root(book_id)
        return {
            "bookId": root.as_posix(),
            "items": self.presenter.workbench_repository.list_quality_threshold_history(root),
        }

    def revert(self, request: Any) -> dict[str, Any]:
        root = self._root(request.bookId)
        applied_at = str(request.appliedAt or "").strip()
        if not applied_at:
            raise HTTPException(status_code=400, detail="缺少校准应用时间。")
        try:
            thresholds = self.presenter.workbench_repository.read_quality_threshold_history_item(
                root,
                applied_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        self.presenter.workbench_repository.write_quality_thresholds(root, thresholds)
        return {
            "bookId": root.as_posix(),
            "currentThresholds": thresholds.to_dict(),
            "history": self.presenter.workbench_repository.list_quality_threshold_history(root),
            "message": "已撤销到所选阈值版本。",
        }

    def rescore_all(self, book_id: str = "") -> dict[str, Any]:
        root = self._root(book_id)
        chapters = self.presenter.export_service._chapter_records(root)  # noqa: SLF001
        thresholds = self.presenter.workbench_repository.read_quality_thresholds(root)
        job = JobController().submit_background(
            root,
            kind="calibration-rescore",
            title="质量阈值批量重评",
            detail=f"将重新评估 {len(chapters)} 个章节的质量分和 gate 状态。",
            work=lambda current_job: self._run_rescore(root, thresholds, current_job),
            params={"bookId": root.as_posix(), "chapterCount": len(chapters)},
        )
        return {
            "bookId": root.as_posix(),
            "jobId": job.jobId,
            "job": self.presenter._job_summary(root, job),  # noqa: SLF001
        }

    def _run_rescore(
        self,
        root: Path,
        thresholds: QualityThresholdConfig,
        job: Any,
    ) -> dict[str, Any]:
        chapters = self.presenter.export_service._chapter_records(root)  # noqa: SLF001
        total = len(chapters)
        rescored = 0
        skipped: list[str] = []
        for index, chapter in enumerate(chapters, start=1):
            if JobController().is_cancel_requested(root, job.jobId):
                return {"status": "cancelled", "rescoredCount": rescored, "skipped": skipped}
            try:
                quality, gate = self.presenter.export_service._chapter_training_reports(  # noqa: SLF001
                    root,
                    chapter.chapterId,
                    thresholds,
                )
            except FileNotFoundError:
                skipped.append(chapter.chapterId)
            else:
                self.presenter.workbench_repository.update_chapter_quality_gate(
                    root,
                    chapter.chapterId,
                    quality.score,
                    gate.status,
                    gate.score,
                )
                rescored += 1
            percent = round(index / (total or 1) * 100)
            JobController().update_progress(
                root,
                job.jobId,
                {
                    "percent": percent,
                    "current": index,
                    "total": total,
                    "rescoredCount": rescored,
                },
                f"rescored {chapter.chapterId}",
            )
        return {"rescoredCount": rescored, "skipped": skipped}

    def _annotated_quality_rows(
        self,
        root: Path,
        thresholds: QualityThresholdConfig,
    ) -> list[dict[str, Any]]:
        annotations = self.presenter.workbench_repository.list_calibration_annotations(root)
        rows: list[dict[str, Any]] = []
        for annotation in annotations:
            chapter_id = str(annotation.get("chapterId") or "")
            try:
                report = self.presenter.writing_quality_service.evaluate_chapter(
                    root,
                    chapter_id,
                    draft_path=f"chapters/{chapter_id}.md",
                    threshold_config=thresholds,
                )
            except FileNotFoundError:
                continue
            rows.append(
                {
                    **annotation,
                    "score": report.score,
                    "metrics": report.metrics,
                    "issueTypes": [issue.type for issue in report.issues],
                }
            )
        return rows

    def _root(self, book_id: str = "") -> Path:
        root = self.presenter._target_root(book_id)  # noqa: SLF001
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可校准的作品。")
        return root
