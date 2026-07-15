from __future__ import annotations

import json
import tempfile
from pathlib import Path, PurePosixPath

from open_novel.core.models import (
    EditorialReviewReport,
    ModelComparisonCandidateReport,
    ModelComparisonEditorialSummary,
    ModelComparisonReport,
    ModelComparisonSummary,
    SkillRunRequest,
    WritingModelProfile,
    WritingModelRegistry,
    utc_now,
)
from open_novel.core.project import ProjectService
from open_novel.core.quality_calibration import QualityThresholdConfig
from open_novel.core.regression_scenario import RegressionScenarioService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_model import WritingModelService


class ModelComparisonService:
    report_dir = "runs/model-comparisons"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()
        self.writing_model_service = WritingModelService(self.project_service)
        self.story_guidance = StoryGuidanceService(self.project_service)
        self.sequence_evaluation_service = ChapterSequenceEvaluationService(self.project_service)
        self.regression_scenarios = RegressionScenarioService(
            self.project_service,
            self.story_guidance,
        )

    def report_path(self, comparison_id: str) -> str:
        return f"{self.report_dir}/{comparison_id}.json"

    def promote_tuned_profile_from_report(
        self,
        project_root: Path,
        comparison_report_path: str,
    ) -> WritingModelRegistry:
        project = self.project_service.open_project(project_root)
        relative_path = (comparison_report_path or "").strip()
        report_path = PurePosixPath(relative_path)
        if not relative_path.startswith(f"{self.report_dir}/") or not relative_path.endswith(
            ".json"
        ) or report_path.is_absolute() or ".." in report_path.parts:
            raise ValueError("comparison report path must be under runs/model-comparisons/")
        raw = self.project_service.read_text(project.root, relative_path)
        report = ModelComparisonReport.model_validate_json(raw)
        summary = report.summary
        if (
            not summary.safeToSetDefault
            or summary.promotionDecision != "promote-tuned-profile"
        ):
            reasons = ", ".join(summary.promotionReasons) or "report is not safe to promote"
            raise ValueError(f"comparison report is not safe to promote: {reasons}")
        if not report.tunedProfileId:
            raise ValueError("comparison report has no tuned profile id")
        if summary.tunedCandidateId and summary.tunedCandidateId != report.tunedProfileId:
            raise ValueError("comparison report tuned candidate does not match tuned profile")
        if summary.bestCandidateId != report.tunedProfileId:
            raise ValueError("comparison report tuned profile is not the best candidate")
        return self.writing_model_service.set_default_profile(project.root, report.tunedProfileId)

    def compare_five_chapter_profiles(
        self,
        project_root: Path,
        *,
        start_chapter_id: str = "001",
        chapter_count: int = 5,
        base_profile_id: str = "",
        tuned_profile_id: str = "",
        reference_agent_id: str = "local-dry-run",
        include_reference_agent: bool = True,
    ) -> ModelComparisonReport:
        project = self.project_service.open_project(project_root)
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        if not start.isdigit():
            raise ValueError("start chapter id must be numeric")
        count = max(1, min(chapter_count, 10))
        start_number = int(start)
        end = f"{start_number + count - 1:03d}"

        registry = self.writing_model_service.read_registry(project.root)
        profiles = self._resolve_profiles(registry, base_profile_id, tuned_profile_id)

        comparison_id = self._comparison_id(
            start,
            end,
            profiles["base"].id,
            profiles["tuned"].id,
            reference_agent_id,
        )
        candidates: list[ModelComparisonCandidateReport] = []

        base_candidate = self._run_profile_candidate(
            project.root,
            comparison_id,
            "base",
            profiles["base"],
            start_number,
            count,
            start,
            end,
        )
        tuned_candidate = self._run_profile_candidate(
            project.root,
            comparison_id,
            "tuned",
            profiles["tuned"],
            start_number,
            count,
            start,
            end,
        )
        candidates.extend([base_candidate, tuned_candidate])

        reference_candidate: ModelComparisonCandidateReport | None = None
        if include_reference_agent:
            reference_candidate = self._run_reference_candidate(
                project.root,
                comparison_id,
                "reference",
                reference_agent_id,
                start_number,
                count,
                start,
                end,
            )
            candidates.append(reference_candidate)

        thresholds = QualityThresholdConfig.from_dict(project.metadata.qualityThresholds)
        summary = self._summarize(
            base_candidate,
            tuned_candidate,
            reference_candidate,
            thresholds,
        )
        report = ModelComparisonReport(
            comparisonId=comparison_id,
            sourceProject=project.root.as_posix(),
            startChapterId=start,
            endChapterId=end,
            chapterCount=count,
            createdAt=utc_now(),
            baseProfileId=profiles["base"].id,
            tunedProfileId=profiles["tuned"].id,
            referenceAgentId=reference_agent_id if include_reference_agent else "",
            candidates=candidates,
            summary=summary,
            recommendedNextAction=self._recommended_next_action(summary),
        )
        self.project_service.write_text(
            project.root,
            self.report_path(comparison_id),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _run_profile_candidate(
        self,
        source_root: Path,
        comparison_id: str,
        label: str,
        profile: WritingModelProfile,
        start_number: int,
        count: int,
        start: str,
        end: str,
    ) -> ModelComparisonCandidateReport:
        scratch_root = self._scratch_project_root(source_root, comparison_id, label)
        self._seed_five_chapter_project(scratch_root, start_number, count)
        run_ids = self._run_five_chapter_loop(
            scratch_root,
            start_number,
            count,
            agent_id="local-model",
            model_profile=profile.id,
        )
        sequence = self.sequence_evaluation_service.evaluate(scratch_root, start, end)
        editorial = self._editorial_summary(scratch_root, start_number, count)
        return ModelComparisonCandidateReport(
            label=label,
            candidateId=profile.id,
            agentId="local-model",
            modelProfileId=profile.id,
            scratchRoot=scratch_root.as_posix(),
            runIds=run_ids,
            sequenceReportPath=self.sequence_evaluation_service.report_path(start, end),
            sequence=sequence,
            editorial=editorial,
        )

    def _run_reference_candidate(
        self,
        source_root: Path,
        comparison_id: str,
        label: str,
        agent_id: str,
        start_number: int,
        count: int,
        start: str,
        end: str,
    ) -> ModelComparisonCandidateReport:
        scratch_root = self._scratch_project_root(source_root, comparison_id, label)
        self._seed_five_chapter_project(scratch_root, start_number, count)
        run_ids = self._run_five_chapter_loop(
            scratch_root,
            start_number,
            count,
            agent_id=agent_id,
            model_profile="",
        )
        sequence = self.sequence_evaluation_service.evaluate(scratch_root, start, end)
        editorial = self._editorial_summary(scratch_root, start_number, count)
        return ModelComparisonCandidateReport(
            label=label,
            candidateId=agent_id,
            agentId=agent_id,
            modelProfileId="",
            scratchRoot=scratch_root.as_posix(),
            runIds=run_ids,
            sequenceReportPath=self.sequence_evaluation_service.report_path(start, end),
            sequence=sequence,
            editorial=editorial,
        )

    def _editorial_summary(
        self,
        project_root: Path,
        start_number: int,
        count: int,
    ) -> ModelComparisonEditorialSummary:
        reports: list[EditorialReviewReport] = []
        report_paths: list[str] = []
        for chapter_number in range(start_number, start_number + count):
            chapter_id = f"{chapter_number:03d}"
            relative_path = f"runs/editorial-review-{chapter_id}.json"
            path = project_root / relative_path
            if not path.is_file():
                continue
            report = EditorialReviewReport.model_validate_json(path.read_text(encoding="utf-8"))
            reports.append(report)
            report_paths.append(relative_path)
        if not reports:
            return ModelComparisonEditorialSummary()
        scores = [report.score for report in reports]
        high_or_blocker = sum(
            1
            for report in reports
            for issue in report.issues
            if issue.severity in {"high", "blocker"}
        )
        blocker_count = sum(
            1
            for report in reports
            for issue in report.issues
            if issue.severity == "blocker"
        )
        style_profile_ids = sorted(
            {
                str(report.metrics.get("styleProfileId") or "")
                for report in reports
                if str(report.metrics.get("styleProfileId") or "")
            }
        )
        return ModelComparisonEditorialSummary(
            minScore=min(scores),
            averageScore=round(sum(scores) / len(scores), 2),
            issueCount=sum(len(report.issues) for report in reports),
            highOrBlockerCount=high_or_blocker,
            blockerCount=blocker_count,
            chapterCount=len(reports),
            styleProfileIds=style_profile_ids,
            reportPaths=report_paths,
        )

    def _seed_five_chapter_project(
        self,
        project_root: Path,
        start_number: int,
        count: int,
    ) -> None:
        self.regression_scenarios.seed(
            project_root,
            start_chapter_id=f"{start_number:03d}",
            chapter_count=count,
            scenario=RegressionScenarioService.fanqie_xuanhuan_upgrade,
        )

    def _run_five_chapter_loop(
        self,
        project_root: Path,
        start_number: int,
        count: int,
        *,
        agent_id: str,
        model_profile: str,
    ) -> list[str]:
        run_ids: list[str] = []
        for chapter_number in range(start_number, start_number + count):
            chapter_id = f"{chapter_number:03d}"
            contract = self.story_guidance.read_scene_contract(project_root, chapter_id)
            result = SkillRunner().run(
                SkillRunRequest(
                    projectRoot=project_root,
                    skillId="chapter-writer",
                    variables={
                        "chapterId": chapter_id,
                        "chapterTitle": contract.title or f"Chapter {chapter_id}",
                    },
                    agentId=agent_id,
                    modelProfile=model_profile or None,
                    runId=f"{agent_id}_{model_profile or 'default'}_{chapter_id}",
                )
            )
            run_ids.append(result.runId)
            if not result.outputPath:
                raise RuntimeError(
                    f"candidate {agent_id}/{model_profile or 'default'} did not "
                    f"produce a draft for {chapter_id}"
                )
        return run_ids

    def _resolve_profiles(
        self,
        registry: WritingModelRegistry,
        base_profile_id: str,
        tuned_profile_id: str,
    ) -> dict[str, WritingModelProfile]:
        if not registry.profiles:
            raise FileNotFoundError(
                "no writing model profiles registered; register a base and tuned profile first"
            )
        base = self._select_profile(registry, base_profile_id, registry.defaultProfileId)
        tuned = self._select_tuned_profile(registry, tuned_profile_id, base.id)
        if tuned.id == base.id:
            raise ValueError("base and tuned writing model profiles must be different")
        return {"base": base, "tuned": tuned}

    def _select_profile(
        self,
        registry: WritingModelRegistry,
        profile_id: str,
        fallback: str,
    ) -> WritingModelProfile:
        selected = (profile_id or fallback or "").strip()
        if not selected:
            if not registry.profiles:
                raise FileNotFoundError("no writing model profiles registered")
            return registry.profiles[0]
        for profile in registry.profiles:
            if profile.id == selected:
                return profile
        raise FileNotFoundError(f"missing writing model profile: {selected}")

    def _select_tuned_profile(
        self,
        registry: WritingModelRegistry,
        profile_id: str,
        base_profile_id: str,
    ) -> WritingModelProfile:
        selected = (profile_id or "").strip()
        if selected:
            return self._select_profile(registry, selected, "")
        for profile in registry.profiles:
            if profile.id != base_profile_id:
                return profile
        raise ValueError("register a second writing model profile before running comparison")

    def _scratch_project_root(self, project_root: Path, comparison_id: str, label: str) -> Path:
        tmp_root = Path(tempfile.mkdtemp(prefix=f"open-novel-compare-{comparison_id}-{label}-"))
        scratch_root = tmp_root / project_root.name
        self.project_service.clone_project(project_root, scratch_root)
        return scratch_root

    def _comparison_id(
        self,
        start: str,
        end: str,
        base_profile_id: str,
        tuned_profile_id: str,
        reference_agent_id: str,
    ) -> str:
        slug = "-".join(
            part
            for part in [
                start,
                end,
                base_profile_id or "base",
                tuned_profile_id or "tuned",
                reference_agent_id or "reference",
            ]
            if part
        )
        return slug.replace(" ", "_")

    def _summarize(
        self,
        base: ModelComparisonCandidateReport,
        tuned: ModelComparisonCandidateReport,
        reference: ModelComparisonCandidateReport | None,
        thresholds: QualityThresholdConfig | None = None,
    ) -> ModelComparisonSummary:
        threshold_config = thresholds or QualityThresholdConfig()
        base_average_gate = self._average_gate_score(base)
        tuned_average_gate = self._average_gate_score(tuned)
        summary = ModelComparisonSummary(
            baseCandidateId=base.candidateId,
            baseQualityScore=base.sequence.minQualityScore,
            baseGateScore=base.sequence.minGateScore,
            baseAverageGateScore=base_average_gate,
            baseEditorialScore=base.editorial.minScore,
            baseEditorialHighOrBlockerCount=base.editorial.highOrBlockerCount,
            tunedCandidateId=tuned.candidateId,
            tunedQualityScore=tuned.sequence.minQualityScore,
            tunedGateScore=tuned.sequence.minGateScore,
            tunedAverageGateScore=tuned_average_gate,
            regressionPassed=(
                tuned_average_gate >= base_average_gate - threshold_config.regression_gate_tolerance
                and self._blocker_count(tuned) <= self._blocker_count(base)
            ),
            tunedEditorialScore=tuned.editorial.minScore,
            tunedEditorialHighOrBlockerCount=tuned.editorial.highOrBlockerCount,
            qualityDelta=tuned.sequence.minQualityScore - base.sequence.minQualityScore,
            gateDelta=tuned.sequence.minGateScore - base.sequence.minGateScore,
            editorialDelta=tuned.editorial.minScore - base.editorial.minScore,
            editorialHighOrBlockerDelta=(
                tuned.editorial.highOrBlockerCount - base.editorial.highOrBlockerCount
            ),
        )
        if reference is not None:
            summary.referenceCandidateId = reference.candidateId
            summary.referenceQualityScore = reference.sequence.minQualityScore
            summary.referenceGateScore = reference.sequence.minGateScore
            summary.referenceEditorialScore = reference.editorial.minScore
            summary.referenceDeltaQualityVsTuned = (
                reference.sequence.minQualityScore - tuned.sequence.minQualityScore
            )
            summary.referenceDeltaGateVsTuned = (
                reference.sequence.minGateScore - tuned.sequence.minGateScore
            )
            summary.referenceDeltaEditorialVsTuned = (
                reference.editorial.minScore - tuned.editorial.minScore
            )

        ranked = sorted(
            [
                (
                    self._status_rank(base.sequence.status),
                    base.sequence.minGateScore,
                    base.sequence.minQualityScore,
                    base.editorial.minScore,
                    -base.editorial.highOrBlockerCount,
                    base.label,
                    base.candidateId,
                ),
                (
                    self._status_rank(tuned.sequence.status),
                    tuned.sequence.minGateScore,
                    tuned.sequence.minQualityScore,
                    tuned.editorial.minScore,
                    -tuned.editorial.highOrBlockerCount,
                    tuned.label,
                    tuned.candidateId,
                ),
                *(
                    [
                        (
                            self._status_rank(reference.sequence.status),
                            reference.sequence.minGateScore,
                            reference.sequence.minQualityScore,
                            reference.editorial.minScore,
                            -reference.editorial.highOrBlockerCount,
                            reference.label,
                            reference.candidateId,
                        )
                    ]
                    if reference is not None
                    else []
                ),
            ],
            reverse=True,
        )
        if ranked:
            (
                best_rank,
                best_gate,
                best_quality,
                _best_editorial,
                _best_issue_rank,
                best_label,
                best_candidate_id,
            ) = ranked[0]
            summary.bestCandidateId = best_candidate_id
            summary.bestCandidateLabel = best_label
            summary.bestGateScore = best_gate
            summary.bestQualityScore = best_quality
            summary.bestStatus = self._status_from_rank(best_rank)
        decision, reasons, safe_to_set_default = self._promotion_decision(summary)
        summary.promotionDecision = decision
        summary.promotionReasons = reasons
        summary.safeToSetDefault = safe_to_set_default
        return summary

    def _status_rank(self, status: str) -> int:
        return {"pass": 3, "warn": 2, "block": 1}.get(status, 0)

    def _status_from_rank(self, rank: int) -> str:
        if rank >= 3:
            return "pass"
        if rank == 2:
            return "warn"
        return "block"

    def _average_gate_score(self, candidate: ModelComparisonCandidateReport) -> float:
        scores = [chapter.gateScore for chapter in candidate.sequence.chapters]
        return round(sum(scores) / len(scores), 2) if scores else 0.0

    def _blocker_count(self, candidate: ModelComparisonCandidateReport) -> int:
        sequence_blockers = sum(
            1 for chapter in candidate.sequence.chapters if chapter.gateStatus == "block"
        )
        return sequence_blockers + candidate.editorial.blockerCount

    def _recommended_next_action(self, summary: ModelComparisonSummary) -> str:
        if not summary.promotionDecision:
            decision, reasons, safe_to_set_default = self._promotion_decision(summary)
            summary.promotionDecision = decision
            summary.promotionReasons = reasons
            summary.safeToSetDefault = safe_to_set_default
        if summary.promotionDecision == "promote-tuned-profile":
            return "promote-tuned-profile-or-run-cli-baseline-comparison"
        if summary.promotionDecision == "reject-tuned-profile":
            if any("quality-or-gate-regression" in reason for reason in summary.promotionReasons):
                return "do-not-promote-tuned-profile-regressed-quality-or-gate"
            return "do-not-promote-tuned-profile-regressed-editorial-style"
        if summary.promotionDecision == "collect-more-data":
            return "collect-more-five-chapter-comparison-data-before-promoting"
        return "revise-candidate-or-collect-better-five-chapter-examples"

    def _promotion_decision(
        self,
        summary: ModelComparisonSummary,
    ) -> tuple[str, list[str], bool]:
        reasons: list[str] = []
        if summary.bestStatus != "pass":
            reasons.append("best-candidate-did-not-pass-five-chapter-gate")
        if summary.bestCandidateId != summary.tunedCandidateId:
            reasons.append("tuned-profile-is-not-best-candidate")
        if not summary.regressionPassed:
            reasons.append("quality-or-gate-regression:regression-standard")
        if summary.tunedQualityScore < summary.baseQualityScore:
            reasons.append("quality-or-gate-regression:quality")
        if summary.tunedEditorialScore < summary.baseEditorialScore:
            reasons.append("editorial-regression:score")
        if (
            summary.tunedEditorialHighOrBlockerCount
            > summary.baseEditorialHighOrBlockerCount
        ):
            reasons.append("editorial-regression:high-or-blocker-issues")
        improved = any(
            [
                summary.tunedGateScore > summary.baseGateScore,
                summary.tunedAverageGateScore > summary.baseAverageGateScore,
                summary.tunedQualityScore > summary.baseQualityScore,
                summary.tunedEditorialScore > summary.baseEditorialScore,
                summary.tunedEditorialHighOrBlockerCount
                < summary.baseEditorialHighOrBlockerCount,
            ]
        )
        if not improved:
            reasons.append("no-measured-improvement-over-base")
        if summary.referenceCandidateId and (
            summary.referenceQualityScore > summary.tunedQualityScore
            or summary.referenceGateScore > summary.tunedGateScore
            or summary.referenceEditorialScore > summary.tunedEditorialScore
        ):
            reasons.append("reference-agent-outperformed-tuned-profile")

        hard_rejection = any(
            reason.startswith("quality-or-gate-regression")
            or reason.startswith("editorial-regression")
            for reason in reasons
        )
        if hard_rejection:
            return "reject-tuned-profile", reasons, False
        if not reasons:
            return "promote-tuned-profile", ["tuned-profile-passed-and-improved"], True
        if (
            summary.bestStatus == "pass"
            and summary.bestCandidateId == summary.tunedCandidateId
            and improved
        ):
            return "collect-more-data", reasons, False
        return "revise-tuned-profile", reasons, False
