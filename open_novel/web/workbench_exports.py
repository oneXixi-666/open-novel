from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from open_novel.exporters.service import ExportService
from open_novel.security.path_guard import PathGuard


class WorkbenchExportService:
    def __init__(self, export_service: ExportService) -> None:
        self.export_service = export_service

    def readiness(
        self,
        root: Path,
        kind: str,
        book: dict[str, Any],
        reviews: list[dict[str, Any]],
        materials: list[dict[str, Any]],
        generation_state: dict[str, Any],
    ) -> dict[str, Any]:
        chapters = book["chapters"]
        chapter_ids = [str(item.get("id") or "") for item in chapters]
        open_reviews = [item for item in reviews if item["status"] != "已确认"]
        draft_chapters = [item for item in chapters if item["status"] != "完成"]
        low_materials = [item for item in materials if int(item.get("confidence", 0) or 0) < 75]
        generation_risks = self._generation_risks(generation_state)
        generation_stage_label = str(generation_state.get("stageLabel") or "生成状态")
        title = book["title"]
        if kind == "正文":
            risks = [
                *([f"仍有 {len(open_reviews)} 条未确认审稿项"] if open_reviews else []),
                *([f"仍有 {len(draft_chapters)} 章不是完成状态"] if draft_chapters else []),
                *generation_risks,
            ]
            return {
                "bookId": str(root),
                "kind": kind,
                "chapterIds": chapter_ids,
                "ready": not risks,
                "summary": f"当前书可导出 {len(chapters)} 个章节。",
                "checks": [
                    f"章节 {len(chapters)} 章",
                    f"未确认审稿 {len(open_reviews)} 条",
                    f"未完成章节 {len(draft_chapters)} 章",
                    f"生成状态：{generation_stage_label}",
                ],
                "risks": risks or ["未发现阻断风险"],
                "resultName": f"{title}-正文.txt",
            }
        if kind == "训练数据":
            return {**self._training_readiness(root, title, kind), "chapterIds": chapter_ids}
        if kind == "审稿报告":
            high_reviews = [item for item in reviews if item["priority"] == "高"]
            risks = [f"仍有 {len(open_reviews)} 条未确认审稿项"] if open_reviews else []
            return {
                "bookId": str(root),
                "kind": kind,
                "chapterIds": chapter_ids,
                "ready": True,
                "summary": f"可汇总 {len(reviews)} 条审稿项。",
                "checks": [
                    f"审稿项 {len(reviews)} 条",
                    f"高优先级 {len(high_reviews)} 条",
                    f"未确认 {len(open_reviews)} 条",
                ],
                "risks": risks or ["审稿项均已确认"],
                "resultName": f"{title}-审稿报告.md",
            }
        risks = [f"有 {len(low_materials)} 条资料可信度低于 75"] if low_materials else []
        return {
            "bookId": str(root),
            "kind": kind,
            "chapterIds": chapter_ids,
            "ready": True,
            "summary": f"可导出 {len(materials)} 条资料。",
            "checks": [
                f"资料 {len(materials)} 条",
                *[
                    (
                        f"{material_type} "
                        f"{sum(1 for item in materials if item['type'] == material_type)} 条"
                    )
                    for material_type in ["人物", "地点", "势力", "伏笔"]
                ],
            ],
            "risks": risks or ["资料可信度良好"],
            "resultName": f"{title}-资料包.zip",
        }

    def write_export(
        self,
        root: Path,
        kind: str,
        reviews: list[dict[str, Any]],
        materials: list[dict[str, Any]],
        training_chapter_ids: list[str] | None = None,
    ) -> Path:
        if kind == "正文":
            return self.export_service.export_txt(root)
        if kind == "训练数据":
            return self.export_service.export_writing_training_jsonl(
                root,
                selected_chapter_ids=training_chapter_ids,
            )
        if kind == "审稿报告":
            return self._write_review_report(root, reviews)
        return self._write_material_package(root, materials)

    def _training_readiness(self, root: Path, title: str, kind: str) -> dict[str, Any]:
        try:
            report = self.export_service.training_readiness(root)
            risks = self._training_risks(
                report.status,
                report.skippedCount,
                report.minRecommendedExamples,
            )
            return {
                "bookId": str(root),
                "kind": kind,
                "ready": report.status == "ready",
                "summary": (
                    f"可用训练样本 {report.eligibleCount} 章，建议样本 "
                    f"{report.minRecommendedExamples} 章。"
                ),
                "checks": [
                    f"可用样本 {report.eligibleCount} 章",
                    f"跳过 {report.skippedCount} 章",
                    report.recommendedNextAction,
                ],
                "risks": risks or ["未发现训练导出阻断"],
                "resultName": f"{title}-training.jsonl",
                "trainingPreview": self._training_preview(report),
            }
        except (FileNotFoundError, ValueError) as exc:
            return {
                "bookId": str(root),
                "kind": kind,
                "ready": False,
                "summary": "训练数据检查未通过。",
                "checks": ["训练就绪检查失败"],
                "risks": [str(exc)],
                "resultName": f"{title}-training.jsonl",
                "trainingPreview": {"eligibleCount": 0, "skippedCount": 0, "items": []},
            }

    def _training_preview(self, report: Any) -> dict[str, Any]:
        return {
            "eligibleCount": report.eligibleCount,
            "skippedCount": report.skippedCount,
            "items": [
                {
                    "chapterId": item.chapterId,
                    "eligible": item.eligible,
                    "reason": item.reason,
                    "reasonLabel": self._training_reason_label(item.reason),
                    "qualityScore": item.qualityScore,
                    "gateStatus": item.gateStatus or "unknown",
                    "gateScore": item.gateScore,
                    "previousSimilarity": item.previousSimilarity,
                    "batchSimilarity": item.batchSimilarity,
                    "batchDuplicateOf": item.batchDuplicateOf,
                    "actionSuggestion": item.actionSuggestion,
                }
                for item in report.items
            ],
        }

    def _training_reason_label(self, reason: str) -> str:
        labels = {
            "missing_scene_contract": "缺少章节合同",
            "quality_and_gate_failed": "质量和 gate 均未通过",
            "quality_failed": "质量分不足",
            "gate_failed": "gate 未通过",
            "batch_duplicate": "同批训练样本重复",
            "continuity_failed": "连贯性问题未修复",
        }
        return labels.get(reason, reason)

    def _training_risks(
        self,
        status: str,
        skipped_count: int,
        min_recommended_examples: int,
    ) -> list[str]:
        risks = [f"跳过 {skipped_count} 章"] if skipped_count else []
        if status == "block":
            risks.append("当前没有可用于训练的数据样本")
        elif status == "warn":
            risks.append(f"训练样本未达到建议数量 {min_recommended_examples} 章")
        return risks or ["未发现训练导出阻断"]

    def _generation_risks(self, generation_state: dict[str, Any]) -> list[str]:
        status = str(generation_state.get("status") or "")
        if status == "waiting_confirm":
            return ["仍有生成候选等待确认"]
        if status == "blocked":
            blockers = self._string_list(generation_state.get("blockers"))
            return [blockers[0] if blockers else "生成流程存在阻断项"]
        if status == "paused":
            return ["生成流程已暂停"]
        if status == "running":
            return ["生成流程仍在推进中"]
        return []

    def _write_review_report(self, root: Path, reviews: list[dict[str, Any]]) -> Path:
        lines = ["# 审稿报告", ""]
        for review in reviews:
            lines.extend([
                f"## {review['title']}",
                "",
                f"- 状态：{review['status']}",
                f"- 优先级：{review['priority']}",
                f"- 章节：{review['chapterId']}",
                f"- 建议：{review['suggestion']}",
                "",
            ])
        relative_path = "exports/review-report.md"
        self.export_service.project_service.write_text(
            root,
            relative_path,
            "\n".join(lines),
        )
        return root / relative_path

    def _write_material_package(self, root: Path, materials: list[dict[str, Any]]) -> Path:
        output = (
            Path(tempfile.mkdtemp(prefix="open-novel-export-")) / "material-package.zip"
            if self.export_service.project_service.is_database_project(root)
            else PathGuard(root).resolve("exports/material-package.zip")
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schemaVersion": 1, "materials": materials},
            ensure_ascii=False,
            indent=2,
        )
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("materials.json", payload)
        return output

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
