from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.models import StyleProfile
from open_novel.core.project import ProjectService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService


class StyleProfilePromotionService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        sequence_service: ChapterSequenceEvaluationService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.sequence_service = sequence_service or ChapterSequenceEvaluationService(
            self.project_service
        )

    def report_path(self, profile_id: str, start_chapter_id: str, end_chapter_id: str) -> str:
        profile = self.project_service._normalize_slug(profile_id, "style profile id")
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        return f"runs/style-profile-promotions/{profile}-{start}-{end}.json"

    def evaluate_candidate(
        self,
        root: Path,
        candidate_profile_path: str,
        start_chapter_id: str,
        end_chapter_id: str,
        *,
        prefer_drafts: bool = True,
    ) -> dict[str, object]:
        candidate = self._read_candidate(root, candidate_profile_path)
        candidate_data = candidate.model_dump(mode="json")
        criteria = candidate_data.get("promotionCriteria")
        if not isinstance(criteria, dict):
            criteria = {}
        sequence = self.sequence_service.evaluate(
            root,
            start_chapter_id,
            end_chapter_id,
            prefer_drafts=prefer_drafts,
        )
        required_chapters = int(criteria.get("requiredSampleChapters") or 5)
        minimum_gate = int(criteria.get("minimumGateScore") or 90)
        minimum_quality = int(criteria.get("minimumQualityScore") or 90)
        issues = self._issues(
            candidate_data,
            sequence.model_dump(mode="json"),
            required_chapters=required_chapters,
            minimum_gate=minimum_gate,
            minimum_quality=minimum_quality,
        )
        status = "pass" if not issues else "block"
        report = {
            "schemaVersion": 1,
            "profileId": candidate.id,
            "candidateProfilePath": candidate_profile_path,
            "sourcePlannedSlotId": str(candidate_data.get("sourcePlannedSlotId") or ""),
            "status": status,
            "startChapterId": sequence.startChapterId,
            "endChapterId": sequence.endChapterId,
            "requiredSampleChapters": required_chapters,
            "minimumGateScore": minimum_gate,
            "minimumQualityScore": minimum_quality,
            "sequence": sequence.model_dump(mode="json"),
            "issues": issues,
            "promotionCriteria": criteria,
            "recommendedNextAction": self._recommended_next_action(issues),
        }
        self.project_service.write_text(
            root,
            self.report_path(candidate.id, sequence.startChapterId, sequence.endChapterId),
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def export_promotable_profile(
        self,
        root: Path,
        promotion_report_path: str,
        *,
        output_path: str = "",
    ) -> dict[str, object]:
        report = self._read_report(root, promotion_report_path)
        if str(report.get("recommendedNextAction") or "") != "ready-to-promote-style-profile":
            raise ValueError("style profile promotion report is not ready to promote")
        candidate_path = str(report.get("candidateProfilePath") or "")
        if not candidate_path:
            raise ValueError("promotion report missing candidateProfilePath")
        candidate = self._read_candidate(root, candidate_path)
        data = candidate.model_dump(mode="json")
        data["templateStatus"] = "active"
        data.pop("sourcePlannedSlotId", None)
        notes = self._active_notes(str(data.get("notes") or "").strip())
        suffix = f"Exported from promotion report {promotion_report_path}; review before merging."
        data["notes"] = f"{notes} {suffix}".strip()
        profile_id = self.project_service._normalize_slug(str(data["id"]), "style profile id")
        output = output_path or f"exports/style-profiles/{profile_id}.json"
        self.project_service.write_text(
            root,
            output,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        )
        return {
            "profileId": profile_id,
            "sourceReportPath": promotion_report_path,
            "candidateProfilePath": candidate_path,
            "outputPath": output,
            "profile": data,
        }

    def validate_exported_profile(
        self,
        root: Path,
        exported_profile_path: str,
    ) -> dict[str, object]:
        raw = json.loads(self.project_service.read_text(root, exported_profile_path))
        if not isinstance(raw, dict):
            raise ValueError("exported style profile must be a JSON object")
        profile = StyleProfile.model_validate(raw)
        data = profile.model_dump(mode="json")
        issues: list[dict[str, object]] = []
        if str(data.get("templateStatus") or "") != "active":
            issues.append(
                {
                    "severity": "blocker",
                    "type": "active_status_required",
                    "message": "Exported profile must declare templateStatus=active.",
                }
            )
        if str(data.get("sourcePlannedSlotId") or ""):
            issues.append(
                {
                    "severity": "blocker",
                    "type": "source_slot_not_removed",
                    "message": "Exported profile must not retain sourcePlannedSlotId.",
                }
            )
        todo_paths = self._todo_paths(data)
        if todo_paths:
            issues.append(
                {
                    "severity": "blocker",
                    "type": "export_contains_todo",
                    "message": "Exported profile still contains TODO guidance.",
                    "paths": todo_paths,
                }
            )
        criteria = data.get("promotionCriteria")
        if not isinstance(criteria, dict):
            issues.append(
                {
                    "severity": "blocker",
                    "type": "missing_promotion_criteria",
                    "message": "Exported profile must retain promotionCriteria.",
                }
            )
        else:
            if int(criteria.get("requiredSampleChapters") or 0) < 5:
                issues.append(
                    {
                        "severity": "blocker",
                        "type": "insufficient_required_sample_chapters",
                        "message": "requiredSampleChapters must be at least 5.",
                    }
                )
            checklist = criteria.get("reviewChecklist")
            if not isinstance(checklist, list) or len(checklist) < 3:
                issues.append(
                    {
                        "severity": "blocker",
                        "type": "insufficient_review_checklist",
                        "message": (
                            "promotionCriteria.reviewChecklist must contain at least 3 items."
                        ),
                    }
                )
        status = "pass" if not issues else "block"
        return {
            "schemaVersion": 1,
            "profileId": profile.id,
            "exportedProfilePath": exported_profile_path,
            "status": status,
            "issues": issues,
            "recommendedNextAction": (
                "ready-for-human-catalog-merge"
                if status == "pass"
                else "fix-exported-profile-before-catalog-merge"
            ),
        }

    def _read_report(self, root: Path, promotion_report_path: str) -> dict[str, object]:
        raw = json.loads(self.project_service.read_text(root, promotion_report_path))
        if not isinstance(raw, dict):
            raise ValueError("style promotion report must be a JSON object")
        return raw

    def _read_candidate(self, root: Path, candidate_profile_path: str) -> StyleProfile:
        raw = json.loads(self.project_service.read_text(root, candidate_profile_path))
        if not isinstance(raw, dict):
            raise ValueError("candidate style profile must be a JSON object")
        return StyleProfile.model_validate(raw)

    def _active_notes(self, notes: str) -> str:
        if not notes or "TODO" in notes:
            return (
                "Active style profile exported from a promoted candidate; keep this template "
                "maintained through catalog review instead of project-specific canon."
            )
        return notes

    def _issues(
        self,
        candidate: dict[str, Any],
        sequence: dict[str, Any],
        *,
        required_chapters: int,
        minimum_gate: int,
        minimum_quality: int,
    ) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        if str(candidate.get("templateStatus") or "") != "candidate":
            issues.append(
                {
                    "severity": "blocker",
                    "type": "candidate_status_required",
                    "message": "Candidate profile must declare templateStatus=candidate.",
                }
            )
        if not str(candidate.get("sourcePlannedSlotId") or ""):
            issues.append(
                {
                    "severity": "high",
                    "type": "missing_source_planned_slot",
                    "message": "Candidate profile should retain sourcePlannedSlotId.",
                }
            )
        todo_paths = self._todo_paths(candidate)
        if todo_paths:
            issues.append(
                {
                    "severity": "blocker",
                    "type": "candidate_contains_todo",
                    "message": "Candidate profile still contains TODO guidance.",
                    "paths": todo_paths,
                }
            )
        chapters = sequence.get("chapters", [])
        if not isinstance(chapters, list) or len(chapters) < required_chapters:
            issues.append(
                {
                    "severity": "blocker",
                    "type": "insufficient_sample_chapters",
                    "message": f"Need at least {required_chapters} evaluated chapters.",
                }
            )
        if str(sequence.get("status") or "") != "pass":
            issues.append(
                {
                    "severity": "blocker",
                    "type": "sequence_not_pass",
                    "message": "Five-chapter sequence evaluation must pass.",
                }
            )
        if int(sequence.get("minGateScore") or 0) < minimum_gate:
            issues.append(
                {
                    "severity": "blocker",
                    "type": "gate_score_below_threshold",
                    "message": f"Minimum gate score must be >= {minimum_gate}.",
                }
            )
        if int(sequence.get("minQualityScore") or 0) < minimum_quality:
            issues.append(
                {
                    "severity": "blocker",
                    "type": "quality_score_below_threshold",
                    "message": f"Minimum quality score must be >= {minimum_quality}.",
                }
            )
        return issues

    def _todo_paths(self, value: Any, path: str = "$") -> list[str]:
        paths: list[str] = []
        if isinstance(value, str):
            if "TODO" in value:
                paths.append(path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                paths.extend(self._todo_paths(item, f"{path}[{index}]"))
        elif isinstance(value, dict):
            for key, item in value.items():
                paths.extend(self._todo_paths(item, f"{path}.{key}"))
        return paths

    def _recommended_next_action(self, issues: list[dict[str, object]]) -> str:
        if any(issue["type"] == "candidate_contains_todo" for issue in issues):
            return "complete-candidate-profile-fields-before-promotion"
        if any(issue["type"] == "insufficient_sample_chapters" for issue in issues):
            return "run-five-chapter-template-evaluation"
        if issues:
            return "revise-candidate-template-and-rerun-promotion-evaluation"
        return "ready-to-promote-style-profile"
