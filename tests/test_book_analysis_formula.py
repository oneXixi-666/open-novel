from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from open_novel.cli import app
from open_novel.core.book_analysis import BookAnalysisService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_formula import WritingFormulaService


def seed_accepted_chapter(root: Path) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角发现测试石异常规则。",
            goal="主角要证明测试规则被篡改。",
            conflict="守门人阻止主角继续验证。",
            turn="测试石在众人面前反向亮起。",
            outcome="主角赢得一次发言机会。",
            hook="真正篡改规则的人留下了新线索。",
            emotionalBeat="主角从压抑转为警惕。",
            readerPromises=["测试石异常谜题"],
        ),
    )
    ProjectService().write_text(
        root,
        "chapters/001.md",
        (
            "# 第一章\n\n"
            "守门人阻止主角继续验证，冷声说：“你确定还要碰测试石？”\n\n"
            "主角没有退，压抑的情绪被测试石的冷光逼成警惕。他把手按上去，"
            "测试石在众人面前反向亮起。\n\n"
            "测试石异常谜题终于露出线索。真正篡改规则的人留下了新线索。\n"
        ),
    )


def test_book_analysis_report_and_formula_promotion(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="分析测试")
    original_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    seed_accepted_chapter(project.root)
    accepted_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")

    report = BookAnalysisService().analyze_range(project.root, "001", "001")
    memory = WritingFormulaService().promote_from_analysis(project.root, report.path)

    assert report.status == "pass"
    assert report.path == "runs/book-analysis/001-001.json"
    assert (project.root / report.path).is_file()
    assert report.chapters[0].chapterId == "001"
    assert report.chapters[0].hookSupported is True
    assert report.formulaCandidates
    assert memory.formulas
    formula_data = json.loads(
        (project.root / "memory" / "writing-formulas.json").read_text(encoding="utf-8")
    )
    assert formula_data["formulas"][0]["status"] == "suggested"
    assert "001" in formula_data["formulas"][0]["evidenceChapters"]
    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == accepted_chapter
    assert accepted_chapter != original_chapter


def test_book_analysis_and_formula_cli(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="CLI 分析")
    seed_accepted_chapter(project.root)
    runner = CliRunner()

    analysis = runner.invoke(
        app,
        [
            "project",
            "analyze-book",
            "--project",
            str(project.root),
            "--start-chapter",
            "001",
            "--end-chapter",
            "001",
        ],
    )
    promote = runner.invoke(
        app,
        [
            "project",
            "promote-writing-formulas",
            "--project",
            str(project.root),
            "runs/book-analysis/001-001.json",
        ],
    )

    assert analysis.exit_code == 0
    assert "runs/book-analysis/001-001.json" in analysis.stdout
    assert promote.exit_code == 0
    assert "memory/writing-formulas.json" in promote.stdout


class FormulaRunner:
    def __init__(self, output: object) -> None:
        self.output = output
        self.request = None

    def run(self, request):
        self.request = request
        return SimpleNamespace(
            outputText=json.dumps(self.output, ensure_ascii=False),
            runId="run-formula-extract",
            agentId=request.agentId,
        )


def test_external_formula_candidates_require_review_before_promotion(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="外部写法提取")
    source = "门外只响了三声。她没有开门，而是先熄灭屋里唯一的灯。"
    runner = FormulaRunner(
        [
            {
                "id": "silence_before_response",
                "title": "回应前留白",
                "guidance": "先用可见动作延迟回应，再让冲突进入对白。",
                "evidenceQuotes": ["她没有开门，而是先熄灭屋里唯一的灯"],
                "confidence": 0.86,
            }
        ]
    )
    service = WritingFormulaService(skill_runner=runner)

    artifact, candidate_path = service.extract_external_candidates(
        project.root,
        source_text=source,
        source_label="公开样本文本",
        agent_id="codex-cli",
    )

    assert artifact.candidates[0].id == "silence_before_response"
    assert runner.request.variables["sourceText"] == source
    assert (project.root / candidate_path).is_file()
    assert WritingFormulaService().read_memory(project.root).formulas == []

    memory = service.promote_from_external_candidates(
        project.root,
        candidate_path,
        ["silence_before_response"],
    )
    formula = memory.formulas[0]
    assert formula.id not in WritingFormulaService.formula_catalog
    assert formula.evidenceQuotes == ["她没有开门，而是先熄灭屋里唯一的灯"]
    assert formula.evidenceChapters == []


def test_external_formula_candidates_reject_invented_evidence(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="外部写法提取")
    runner = FormulaRunner(
        [
            {
                "id": "invented_quote",
                "title": "虚构证据",
                "guidance": "不应落库。",
                "evidenceQuotes": ["原文里不存在的句子"],
                "confidence": 0.5,
            }
        ]
    )
    service = WritingFormulaService(skill_runner=runner)

    with pytest.raises(ValueError, match="不在原文"):
        service.extract_external_candidates(
            project.root,
            source_text="这是真实原文。",
            source_label="测试",
            agent_id="codex-cli",
        )

    assert not (project.root / "story/formula-candidates/run-formula-extract.json").exists()
