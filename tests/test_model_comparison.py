from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from open_novel.cli import app
from open_novel.core.model_comparison import ModelComparisonService
from open_novel.core.models import (
    ChapterSequenceEvaluationItem,
    ChapterSequenceEvaluationReport,
    ModelComparisonCandidateReport,
    ModelComparisonSummary,
    SceneContract,
)
from open_novel.core.project import ProjectService
from open_novel.core.quality_calibration import QualityThresholdConfig
from open_novel.core.story_guidance import StoryGuidanceService


def _write_ready_project(root: Path) -> Path:
    project = ProjectService().create_project(root, title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "主角曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    for index in range(1, 6):
        StoryGuidanceService().write_scene_contract(
            project.root,
            SceneContract(
                chapterId=f"{index:03d}",
                title=f"第{index}章",
                focus="主角推进测试。",
                goal="主角想通过测试。",
                conflict="旧敌阻挠。",
                turn="测试石异动。",
                outcome="主角通过但被盯上。",
                hook="长老封锁消息。",
                emotionalBeat="主角从压抑转为警惕。",
                relationshipBeat="旧敌开始忌惮。",
                internalNeed="主角想证明自己。",
                woundOrFear="主角害怕再被否定。",
                stakes="失败会失去机会。",
                cost="暴露异常潜力。",
                subtext="嘴上冷静，实际在忍。",
                aftertaste="爽感后留下不安。",
                logicDependencies=["主角曾被视为残缺灵根"],
                mustInclude=["测试石"],
                mustAvoid=["提前揭秘"],
                readerPromises=["废柴逆袭"],
            ),
        )
    return project.root


def test_compare_rejects_missing_second_profile(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "base-model",
                "profiles": [
                    {
                        "id": "base-model",
                        "label": "Base",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "base",
                        "adapterPath": "models/adapters/base",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "Path(r'{output_file}').write_text('# base'); "
                            "print(Path(r'{output_file}').read_text())\""
                        ),
                        "timeoutSeconds": 60,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    try:
        ModelComparisonService().compare_five_chapter_profiles(
            root,
            base_profile_id="base-model",
        )
    except ValueError as exc:
        assert "second writing model profile" in str(exc)
    else:
        raise AssertionError("comparison should require two distinct profiles")


def test_compare_writes_report_and_summary(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "base-model",
                "profiles": [
                    {
                        "id": "base-model",
                        "label": "Base",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "base",
                        "adapterPath": "models/adapters/base",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "Path(r'{output_file}').write_text("
                            "'# base\\n\\n测试石前，主角稳住局势。'); "
                            "print(Path(r'{output_file}').read_text())\""
                        ),
                        "timeoutSeconds": 60,
                    },
                    {
                        "id": "tuned-model",
                        "label": "Tuned",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "base",
                        "adapterPath": "models/adapters/tuned",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "Path(r'{output_file}').write_text("
                            "'# tuned\\n\\n测试石前，主角稳住局势，旧敌开始忌惮。'); "
                            "print(Path(r'{output_file}').read_text())\""
                        ),
                        "timeoutSeconds": 60,
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = ModelComparisonService().compare_five_chapter_profiles(
        root,
        base_profile_id="base-model",
        tuned_profile_id="tuned-model",
        include_reference_agent=False,
    )

    report_path = root / "runs" / "model-comparisons" / f"{report.comparisonId}.json"
    stored = json.loads(report_path.read_text(encoding="utf-8"))

    assert report.baseProfileId == "base-model"
    assert report.tunedProfileId == "tuned-model"
    assert report.summary.baseCandidateId == "base-model"
    assert report.summary.tunedCandidateId == "tuned-model"
    assert report.candidates[0].editorial.chapterCount == 5
    assert report.summary.baseEditorialScore > 0
    assert report.summary.tunedEditorialScore > 0
    assert report.summary.promotionDecision
    assert isinstance(report.summary.promotionReasons, list)
    assert report.summary.safeToSetDefault is False
    assert report.recommendedNextAction
    assert stored["comparisonId"] == report.comparisonId
    assert "editorialDelta" in stored["summary"]
    assert "promotionDecision" in stored["summary"]
    assert "safeToSetDefault" in stored["summary"]
    assert stored["candidates"][0]["editorial"]["chapterCount"] == 5
    assert stored["candidates"][0]["editorial"]["styleProfileIds"] == ["project-style"]
    assert stored["summary"]["bestCandidateId"]
    assert stored["candidates"][0]["sequence"]["status"] in {"pass", "warn", "block"}


def test_model_comparison_decision_marks_only_clear_tuned_win_safe() -> None:
    summary = ModelComparisonSummary(
        bestCandidateId="tuned-model",
        bestCandidateLabel="tuned",
        bestStatus="pass",
        baseCandidateId="base-model",
        baseQualityScore=88,
        baseGateScore=90,
        baseEditorialScore=82,
        baseEditorialHighOrBlockerCount=2,
        tunedCandidateId="tuned-model",
        tunedQualityScore=94,
        tunedGateScore=95,
        tunedEditorialScore=90,
        tunedEditorialHighOrBlockerCount=0,
    )

    decision, reasons, safe_to_set_default = ModelComparisonService()._promotion_decision(summary)

    assert decision == "promote-tuned-profile"
    assert reasons == ["tuned-profile-passed-and-improved"]
    assert safe_to_set_default is True


def test_model_comparison_decision_rejects_tuned_regression() -> None:
    summary = ModelComparisonSummary(
        bestCandidateId="base-model",
        bestCandidateLabel="base",
        bestStatus="pass",
        baseCandidateId="base-model",
        baseQualityScore=92,
        baseGateScore=92,
        baseEditorialScore=88,
        tunedCandidateId="tuned-model",
        tunedQualityScore=86,
        tunedGateScore=92,
        tunedEditorialScore=90,
    )

    decision, reasons, safe_to_set_default = ModelComparisonService()._promotion_decision(summary)

    assert decision == "reject-tuned-profile"
    assert "quality-or-gate-regression:quality" in reasons
    assert safe_to_set_default is False


def test_model_comparison_regression_tolerance_comes_from_thresholds() -> None:
    def candidate(candidate_id: str, gate_scores: list[int]) -> ModelComparisonCandidateReport:
        return ModelComparisonCandidateReport(
            label=candidate_id,
            candidateId=candidate_id,
            agentId="local-model",
            scratchRoot="/tmp/demo",
            sequenceReportPath="runs/sequence.json",
            sequence=ChapterSequenceEvaluationReport(
                startChapterId="001",
                endChapterId="002",
                status="pass",
                chapters=[
                    ChapterSequenceEvaluationItem(
                        chapterId=f"{index + 1:03d}",
                        qualityScore=90,
                        qualityIssueCount=0,
                        gateStatus="pass",
                        gateScore=score,
                        gateIssueCount=0,
                    )
                    for index, score in enumerate(gate_scores)
                ],
                minQualityScore=90,
                minGateScore=min(gate_scores),
            ),
        )

    service = ModelComparisonService()
    strict = service._summarize(
        candidate("base", [90, 90]),
        candidate("tuned", [87, 87]),
        None,
        QualityThresholdConfig(regression_gate_tolerance=2.0),
    )
    relaxed = service._summarize(
        candidate("base", [90, 90]),
        candidate("tuned", [87, 87]),
        None,
        QualityThresholdConfig(regression_gate_tolerance=4.0),
    )

    assert strict.regressionPassed is False
    assert relaxed.regressionPassed is True


def _write_registry_and_comparison_report(
    root: Path,
    *,
    safe: bool,
    report_path: str = "runs/model-comparisons/safe.json",
) -> str:
    ProjectService().write_text(
        root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "base-model",
                "profiles": [
                    {"id": "base-model", "label": "Base", "backend": "local-command"},
                    {"id": "tuned-model", "label": "Tuned", "backend": "local-command"},
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        root,
        report_path,
        json.dumps(
            {
                "schemaVersion": 1,
                "comparisonId": "safe",
                "sourceProject": root.as_posix(),
                "startChapterId": "001",
                "endChapterId": "005",
                "chapterCount": 5,
                "baseProfileId": "base-model",
                "tunedProfileId": "tuned-model",
                "summary": {
                    "bestCandidateId": "tuned-model" if safe else "base-model",
                    "bestCandidateLabel": "tuned" if safe else "base",
                    "bestStatus": "pass",
                    "baseCandidateId": "base-model",
                    "baseQualityScore": 88,
                    "baseGateScore": 90,
                    "baseEditorialScore": 82,
                    "baseEditorialHighOrBlockerCount": 2,
                    "tunedCandidateId": "tuned-model",
                    "tunedQualityScore": 94 if safe else 82,
                    "tunedGateScore": 95 if safe else 90,
                    "tunedEditorialScore": 90 if safe else 80,
                    "tunedEditorialHighOrBlockerCount": 0 if safe else 3,
                    "promotionDecision": (
                        "promote-tuned-profile" if safe else "reject-tuned-profile"
                    ),
                    "promotionReasons": (
                        ["tuned-profile-passed-and-improved"]
                        if safe
                        else ["quality-or-gate-regression:quality"]
                    ),
                    "safeToSetDefault": safe,
                },
            },
            ensure_ascii=False,
        ),
    )
    return report_path


def test_promote_tuned_profile_from_safe_comparison_report(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    report_path = _write_registry_and_comparison_report(root, safe=True)

    registry = ModelComparisonService().promote_tuned_profile_from_report(root, report_path)

    stored = json.loads((root / "models" / "writing-models.json").read_text(encoding="utf-8"))
    assert registry.defaultProfileId == "tuned-model"
    assert stored["defaultProfileId"] == "tuned-model"


def test_promote_tuned_profile_rejects_unsafe_comparison_report(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    report_path = _write_registry_and_comparison_report(root, safe=False)

    try:
        ModelComparisonService().promote_tuned_profile_from_report(root, report_path)
    except ValueError as exc:
        assert "not safe to promote" in str(exc)
    else:
        raise AssertionError("unsafe comparison report should not promote default model")


def test_promote_tuned_profile_rejects_report_path_traversal(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    _write_registry_and_comparison_report(root, safe=True)

    try:
        ModelComparisonService().promote_tuned_profile_from_report(
            root,
            "runs/model-comparisons/../../models/writing-models.json",
        )
    except ValueError as exc:
        assert "runs/model-comparisons" in str(exc)
    else:
        raise AssertionError("comparison report path traversal should be rejected")


def test_promote_tuned_profile_cli_uses_safe_report(tmp_path: Path) -> None:
    root = _write_ready_project(tmp_path / "demo")
    report_path = _write_registry_and_comparison_report(root, safe=True)

    result = CliRunner().invoke(
        app,
        ["model", "promote-comparison", "--project", str(root), report_path],
    )

    stored = json.loads((root / "models" / "writing-models.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert "Default" in result.stdout
    assert stored["defaultProfileId"] == "tuned-model"
