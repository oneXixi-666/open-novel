from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_novel.cli import app
from open_novel.core.chapter_pipeline import ChapterPipelineService
from open_novel.core.director import DirectorPlan, DirectorService, DirectorStep
from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.prompt_eval import PromptEvalService
from open_novel.core.prompt_registry import PromptRegistryService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService


def test_director_plan_writes_only_proposal_artifacts(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="导演测试")

    plan = DirectorService().create_plan(project.root, "001", "增强冲突和结尾钩子")

    assert plan.chapterId == "001"
    assert plan.planPath == "story/director-plans/001.json"
    assert (project.root / plan.planPath).is_file()
    assert (project.root / plan.runReportPath).is_file()
    assert not any(
        step.artifact.startswith(("chapters/", "memory/")) for step in plan.steps
    )
    assert "suggest_direction" in {step.id for step in plan.steps}


def test_director_rejects_canon_artifacts(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="安全测试")
    plan = DirectorPlan(
        planId="bad",
        chapterId="001",
        intent="bad",
        steps=[
            DirectorStep(
                id="bad",
                action="write canon",
                service="BadService",
                artifact="chapters/001.md",
            )
        ],
    )

    with pytest.raises(ValueError, match="canon artifact"):
        DirectorService()._assert_safe_plan(plan)

    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == "# 001\n\n"


def test_director_dry_run_does_not_write_canon(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="干跑测试")
    original_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    original_memory = (project.root / "memory" / "facts.json").read_text(encoding="utf-8")
    service = DirectorService()
    plan = service.create_plan(project.root, "001", "补强节奏")

    report = service.dry_run(project.root, plan.planPath)

    assert report.status == "dry-run"
    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == original_chapter
    assert (project.root / "memory" / "facts.json").read_text(encoding="utf-8") == original_memory


def test_director_guided_run_executes_safe_steps_without_writing_canon(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="调度测试")
    StoryGuidanceService().write_scene_contract(
        project.root,
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
        ),
    )
    original_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    original_memory = (project.root / "memory" / "facts.json").read_text(encoding="utf-8")
    service = DirectorService()
    plan = service.create_plan(project.root, "001", "补强章节推进")

    report = service.run(project.root, plan.planPath)

    assert report.status == "complete"
    by_id = {step.id: step for step in report.executedSteps}
    assert by_id["scene_contract"].status == "skipped"
    assert by_id["context_pack"].status == "complete"
    assert by_id["draft"].status == "complete"
    assert by_id["gate"].status == "complete"
    assert (project.root / "drafts" / "001.generated.md").is_file()
    assert (project.root / "runs" / "chapter-gate-001.json").is_file()
    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == original_chapter
    assert (project.root / "memory" / "facts.json").read_text(encoding="utf-8") == original_memory


def test_prompt_registry_indexes_existing_skills() -> None:
    report = PromptRegistryService().build_from_skills()

    assert report.status == "pass"
    entry_ids = {entry.id for entry in report.entries}
    assert "chapter-writer.v1" in entry_ids
    chapter_writer = next(entry for entry in report.entries if entry.id == "chapter-writer.v1")
    assert "no_canon_write" in chapter_writer.guardrails
    assert "draft_only_output" in chapter_writer.guardrails
    assert chapter_writer.outputs == ["drafts/{chapterId}.generated.md"]


def test_prompt_eval_runs_chapter_writer_without_writing_canon(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="提示词评测")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角发现异常规则。",
            goal="主角要证明规则被篡改。",
            conflict="守门人阻止主角继续验证。",
            turn="证据在众人面前反向亮起。",
            outcome="主角赢得一次发言机会。",
            hook="真正篡改规则的人留下了新线索。",
            emotionalBeat="主角从压抑转为警惕。",
        ),
    )
    original_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    original_memory = (project.root / "memory" / "facts.json").read_text(encoding="utf-8")

    report = PromptEvalService().evaluate(
        project.root,
        entry_id="chapter-writer.v1",
        chapter_id="001",
        chapter_title="第一章",
    )

    assert report.status == "pass"
    assert report.entries == ["chapter-writer.v1"]
    assert report.results[0].outputPath == "drafts/001.generated.md"
    assert report.path.startswith("runs/prompt-evals/chapter-writer-v1-001-")
    assert (project.root / report.path).is_file()
    assert (project.root / "drafts" / "001.generated.md").is_file()
    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == original_chapter
    assert (project.root / "memory" / "facts.json").read_text(encoding="utf-8") == original_memory


def test_chapter_pipeline_refreshes_from_existing_artifacts(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="管线测试")
    StoryGuidanceService().create_scene_contract(project.root, "001")

    pipeline = ChapterPipelineService().refresh(project.root, "001")
    by_id = {step.id: step for step in pipeline.steps}

    assert by_id["scene_contract"].status == "ready"
    assert by_id["context_pack"].status == "ready"
    assert by_id["draft"].status == "pending"
    assert (project.root / "story" / "chapter-pipelines" / "001.json").is_file()


def test_chapter_pipeline_update_step_preserves_order(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="管线更新")

    pipeline = ChapterPipelineService().update_step(
        project.root,
        "001",
        "draft",
        artifact="drafts/001.generated.md",
        run_id="run_001",
        message="draft created",
    )

    assert [step.id for step in pipeline.steps] == ChapterPipelineService.step_order
    draft = next(step for step in pipeline.steps if step.id == "draft")
    assert draft.status == "ready"
    assert draft.runId == "run_001"
    assert draft.message == "draft created"


def test_skill_runner_updates_pipeline_draft_step(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="草稿管线")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角发现异常规则。",
            goal="主角要证明规则被篡改。",
            conflict="守门人阻止主角继续验证。",
            turn="证据在众人面前反向亮起。",
            outcome="主角赢得一次发言机会。",
            hook="真正篡改规则的人留下了新线索。",
            emotionalBeat="主角从压抑转为警惕。",
        ),
    )

    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
        )
    )
    pipeline = ChapterPipelineService().read_pipeline(project.root, "001")
    draft = next(step for step in pipeline.steps if step.id == "draft")

    assert result.outputPath == "drafts/001.generated.md"
    assert draft.status == "ready"
    assert draft.artifact == "drafts/001.generated.md"
    assert draft.runId == result.runId


def test_director_and_pipeline_cli_commands(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="CLI 测试")
    runner = CliRunner()

    plan = runner.invoke(
        app,
        [
            "director",
            "plan",
            "--project",
            str(project.root),
            "--chapter-id",
            "001",
            "增强冲突和结尾钩子",
        ],
    )
    pipeline = runner.invoke(
        app,
        [
            "project",
            "pipeline",
            "--project",
            str(project.root),
            "--chapter-id",
            "001",
        ],
    )

    assert plan.exit_code == 0
    assert "story/director-plans/001.json" in plan.stdout
    assert pipeline.exit_code == 0
    assert "scene_contract" in pipeline.stdout
    assert "story/chapter-pipelines/001.json" in pipeline.stdout


def test_director_run_cli_executes_safe_steps(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="CLI 调度")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="主角发现异常规则。",
            goal="主角要证明规则被篡改。",
            conflict="守门人阻止主角继续验证。",
            turn="证据在众人面前反向亮起。",
            outcome="主角赢得一次发言机会。",
            hook="真正篡改规则的人留下了新线索。",
            emotionalBeat="主角从压抑转为警惕。",
        ),
    )
    runner = CliRunner()
    plan = DirectorService().create_plan(project.root, "001", "补强章节推进")

    result = runner.invoke(
        app,
        [
            "director",
            "run",
            "--project",
            str(project.root),
            plan.planPath,
        ],
    )

    assert result.exit_code == 0
    assert "complete" in result.stdout
    assert "draft" in result.stdout
    assert "gate" in result.stdout
    assert (project.root / "drafts" / "001.generated.md").is_file()
    assert (project.root / "runs" / "chapter-gate-001.json").is_file()


def test_prompt_registry_cli_validate() -> None:
    result = CliRunner().invoke(app, ["prompt-registry", "validate"])

    assert result.exit_code == 0
    assert "entries=" in result.stdout
    assert result.stdout.startswith("pass")


def test_prompt_registry_cli_eval_writes_report(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="CLI 提示词评测")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角发现异常规则。",
            goal="主角要证明规则被篡改。",
            conflict="守门人阻止主角继续验证。",
            turn="证据在众人面前反向亮起。",
            outcome="主角赢得一次发言机会。",
            hook="真正篡改规则的人留下了新线索。",
            emotionalBeat="主角从压抑转为警惕。",
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "prompt-registry",
            "eval",
            "--project",
            str(project.root),
            "--entry-id",
            "chapter-writer.v1",
            "--chapter-id",
            "001",
            "--chapter-title",
            "第一章",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout.startswith("pass")
    assert "runs/prompt-evals/chapter-writer-v1-001-" in result.stdout
    assert "drafts/001.generated.md" in result.stdout
    assert list((project.root / "runs" / "prompt-evals").glob("chapter-writer-v1-001-*.json"))
