from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from open_novel.cli import app
from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.regression_scenario import RegressionScenarioService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.style_promotion import StyleProfilePromotionService


def test_create_project_writes_standard_files(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    assert project.metadata.title == "Demo"
    assert (project.root / "novel.json").exists()
    assert (project.root / "chapters" / "001.md").exists()
    assert (project.root / "memory" / "facts.json").exists()
    open_loops = json.loads(
        (project.root / "memory" / "open-loops.json").read_text(encoding="utf-8")
    )
    assert open_loops == {"schemaVersion": 1, "loops": []}
    assert (project.root / "memory" / "timeline-events.json").exists()
    assert (project.root / "memory" / "chapter-summaries.json").exists()
    assert (project.root / "memory" / "promises.json").exists()
    assert (project.root / "memory" / "emotional-arcs.json").exists()
    assert (project.root / "memory" / "writing-lessons.json").exists()
    active_prohibitions = json.loads(
        (project.root / "memory" / "active-prohibitions.json").read_text(encoding="utf-8")
    )
    assert active_prohibitions == {"schemaVersion": 1, "items": []}
    writing_formulas = json.loads(
        (project.root / "memory" / "writing-formulas.json").read_text(encoding="utf-8")
    )
    assert writing_formulas == {"schemaVersion": 1, "formulas": []}
    assert (project.root / "memory" / "relationship-states.json").exists()
    character_assets = json.loads(
        (project.root / "memory" / "character-assets.json").read_text(encoding="utf-8")
    )
    assert character_assets == {"schemaVersion": 1, "assets": []}
    assert (project.root / "knowledge").exists()
    assert (project.root / "knowledge" / "sources").exists()
    assert (project.root / "knowledge" / "chunks").exists()
    style_profile = json.loads(
        (project.root / "story" / "style-profile.json").read_text(encoding="utf-8")
    )
    assert style_profile["extends"] == "generic-web-serial"
    assert style_profile["id"] == "project-style"


def test_database_project_keeps_documents_out_of_project_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    root = tmp_path / "database-demo"
    service = ProjectService()

    project = service.create_project(root, title="Database Demo", database_only=True)
    service.write_text(project.root, "chapters/001.md", "# 第一章\n\n数据库正文。\n")

    assert not root.exists()
    assert service.is_database_project(root)
    assert service.read_text(root, "chapters/001.md").endswith("数据库正文。\n")
    assert "chapters/001.md" in service.list_paths(root, "chapters")


def test_import_file_project_to_database_preserves_documents(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    service = ProjectService()
    project = service.create_project(tmp_path / "legacy-demo", title="Legacy Demo")
    service.write_text(project.root, "chapters/001.md", "# 第一章\n\n旧版正文。\n")

    imported = service.import_file_project_to_database(project.root)

    assert service.is_database_project(imported.root)
    assert service.read_text(imported.root, "chapters/001.md").endswith("旧版正文。\n")
    assert (project.root / "models").exists()
    assert (project.root / "models" / "adapters").exists()
    character_states = json.loads(
        (project.root / "memory" / "character-states.json").read_text(encoding="utf-8")
    )
    assert character_states == {"schemaVersion": 1, "characters": []}
    assert (project.root / "story" / "chapter-briefs").exists()


def test_style_profile_catalog_can_apply_platform_template(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StyleProfileService()

    applied = service.write_project_profile_from_builtin(
        project.root,
        "fanqie-xuanhuan-upgrade",
    )
    resolved = service.read_project_profile(project.root)
    stored = json.loads((project.root / "story" / "style-profile.json").read_text(encoding="utf-8"))

    assert applied.extends == "fanqie-xuanhuan-upgrade"
    assert stored["extends"] == "fanqie-xuanhuan-upgrade"
    assert resolved.platform == "fanqie"
    assert "xuanhuan" in resolved.genres
    assert "爽点兑现" in resolved.editorialFocus


def test_style_profile_catalog_exposes_planned_maintenance_slots() -> None:
    slots = StyleProfileService().list_planned_profile_slots()

    slot_ids = {str(slot["id"]) for slot in slots}
    assert "qidian-xianxia-longform" in slot_ids
    assert "jjwxc-romance-slowburn" in slot_ids
    assert "suspense-crime-investigation" in slot_ids
    assert "workplace-business-growth" in slot_ids
    assert "fanqie-xuanhuan-upgrade" not in slot_ids


def test_style_profile_catalog_exposes_broad_coverage_matrix() -> None:
    coverage = StyleProfileService().list_coverage_catalog()

    by_platform = {str(item["platform"]): item for item in coverage}
    assert "fanqie" in by_platform
    assert "qidian" in by_platform
    assert "jjwxc" in by_platform
    assert "generic" in by_platform
    assert "extension" in by_platform
    assert "fanqie-xuanhuan-upgrade" in by_platform["fanqie"]["templateIds"]
    assert "qidian-xianxia-longform" in by_platform["qidian"]["plannedTemplateIds"]
    assert "workplace-business-growth" in by_platform["generic"]["plannedTemplateIds"]
    assert "项目写法配置" in by_platform["extension"]["maintenanceNotes"]


def test_style_profile_catalog_exposes_reserved_template_pack() -> None:
    service = StyleProfileService()
    packs = service.list_template_packs()
    planned_ids = {str(slot["id"]) for slot in service.list_planned_profile_slots()}

    by_id = {str(pack["id"]): pack for pack in packs}
    reserve = by_id["builtin-broad-genre-reserve"]
    assert reserve["status"] == "reserved"
    assert planned_ids.issubset(set(reserve["plannedProfileIds"]))
    assert "douyin-micro-drama-reversal" in reserve["plannedProfileIds"]
    assert "generic-food-healing-slice-of-life" in reserve["plannedProfileIds"]
    assert "broad-reserve" in reserve["coveragePlatforms"]


def test_regression_scenario_seeds_fanqie_five_chapter_contracts(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    report = RegressionScenarioService().seed(
        project.root,
        scenario="fanqie-xuanhuan-upgrade",
    )
    first_contract = json.loads(
        (project.root / "story" / "chapter-briefs" / "001.json").read_text(encoding="utf-8")
    )
    fifth_contract = json.loads(
        (project.root / "story" / "chapter-briefs" / "005.json").read_text(encoding="utf-8")
    )
    style_profile = json.loads(
        (project.root / "story" / "style-profile.json").read_text(encoding="utf-8")
    )
    facts = json.loads((project.root / "memory" / "facts.json").read_text(encoding="utf-8"))

    assert report["scenario"] == "fanqie-xuanhuan-upgrade"
    assert len(report["contracts"]) == 5
    assert style_profile["extends"] == "fanqie-xuanhuan-upgrade"
    assert "测试石" in first_contract["mustInclude"]
    assert "无代价碾压" in first_contract["mustAvoid"]
    assert "公开审问" in fifth_contract["title"]
    assert facts["facts"][0]["importance"] == "critical"


def test_style_profile_catalog_validates_maintenance_references() -> None:
    result = StyleProfileService().validate_catalog()

    assert result["profileCount"] >= 4
    assert result["plannedSlotCount"] >= 10
    assert result["coverageCount"] >= 5
    assert result["templatePackCount"] >= 1
    assert result["policy"]["plannedSlotActivationCriteria"]["requiredSampleChapters"] == 5
    assert result["policy"]["plannedSlotActivationCriteria"]["minimumGateScore"] >= 90


def test_style_profile_catalog_validate_cli() -> None:
    result = CliRunner().invoke(app, ["style", "validate-catalog"])

    assert result.exit_code == 0
    assert "STYLE_CATALOG: PASS" in result.stdout
    assert "planned-samples=5" in result.stdout
    assert "packs=" in result.stdout


def test_style_profile_catalog_list_cli_shows_maturity() -> None:
    result = CliRunner().invoke(app, ["style", "list"])

    assert result.exit_code == 0
    assert "fanqie-xuanhuan-upgrade" in result.stdout
    assert "maturity=candidate" in result.stdout
    assert "builtin-broad-genre-reserve" in result.stdout


def test_style_profile_drafts_candidate_from_planned_slot(tmp_path: Path) -> None:
    service = StyleProfileService()
    profile = service.draft_profile_from_planned_slot("workplace-business-growth")
    output = tmp_path / "candidate.json"
    result = CliRunner().invoke(
        app,
        [
            "style",
            "draft-profile",
            "workplace-business-growth",
            "--output",
            str(output),
        ],
    )
    stored = json.loads(output.read_text(encoding="utf-8"))

    assert profile.id == "workplace-business-growth"
    assert profile.extends == "generic-web-serial"
    assert profile.platform == "generic"
    assert profile.model_dump(mode="json")["templateStatus"] == "candidate"
    assert profile.model_dump(mode="json")["sourcePlannedSlotId"] == "workplace-business-growth"
    assert profile.model_dump(mode="json")["promotionCriteria"]["requiredSampleChapters"] == 5
    assert result.exit_code == 0
    assert stored["id"] == "workplace-business-growth"
    assert stored["promotionCriteria"]["minimumGateScore"] >= 90


def test_style_profile_promotion_evaluates_candidate_against_sequence(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StyleProfileService()
    ProjectService().write_text(
        project.root,
        "story/candidate-style.json",
        service.draft_profile_text_from_planned_slot("workplace-business-growth"),
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=[],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
        )
    )

    report = StyleProfilePromotionService().evaluate_candidate(
        project.root,
        "story/candidate-style.json",
        "001",
        "001",
    )
    cli = CliRunner().invoke(
        app,
        [
            "style",
            "evaluate-promotion",
            "--project",
            str(project.root),
            "--candidate",
            "story/candidate-style.json",
            "--start-chapter",
            "001",
            "--end-chapter",
            "001",
        ],
    )

    assert report["status"] == "block"
    assert report["sequence"]["chapters"][0]["chapterId"] == "001"
    assert any(issue["type"] == "candidate_contains_todo" for issue in report["issues"])
    assert any(issue["type"] == "insufficient_sample_chapters" for issue in report["issues"])
    report_path = (
        project.root
        / "runs"
        / "style-profile-promotions"
        / "workplace-business-growth-001-001.json"
    )
    assert report_path.exists()
    assert cli.exit_code == 0
    assert "profile=workplace-business-growth" in cli.stdout


def test_style_profile_exports_ready_promotion_for_human_review(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    candidate = json.loads(
        StyleProfileService().draft_profile_text_from_planned_slot("workplace-business-growth")
    )
    candidate.update(
        {
            "tone": ["workplace pressure"],
            "readerExpectations": ["business choice must carry cost"],
            "plotRhythm": ["pressure, choice, consequence, hook"],
            "emotionGuidance": ["show ambition through negotiation choices"],
            "descriptionGuidance": ["describe spaces through hierarchy and pressure"],
            "taboo": ["do not solve business conflict without cost"],
        }
    )
    ProjectService().write_text(
        project.root,
        "story/candidate-style.json",
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
    )
    ProjectService().write_text(
        project.root,
        "runs/style-profile-promotions/workplace-business-growth-001-005.json",
        json.dumps(
            {
                "profileId": "workplace-business-growth",
                "candidateProfilePath": "story/candidate-style.json",
                "recommendedNextAction": "ready-to-promote-style-profile",
                "issues": [],
            },
            ensure_ascii=False,
        ),
    )

    result = StyleProfilePromotionService().export_promotable_profile(
        project.root,
        "runs/style-profile-promotions/workplace-business-growth-001-005.json",
    )
    validation = StyleProfilePromotionService().validate_exported_profile(
        project.root,
        "exports/style-profiles/workplace-business-growth.json",
    )
    cli = CliRunner().invoke(
        app,
        [
            "style",
            "export-promoted-profile",
            "--project",
            str(project.root),
            "--report",
            "runs/style-profile-promotions/workplace-business-growth-001-005.json",
        ],
    )
    validate_cli = CliRunner().invoke(
        app,
        [
            "style",
            "validate-exported-profile",
            "--project",
            str(project.root),
            "--profile",
            "exports/style-profiles/workplace-business-growth.json",
        ],
    )
    exported = json.loads(
        (project.root / "exports" / "style-profiles" / "workplace-business-growth.json").read_text(
            encoding="utf-8"
        )
    )

    assert result["outputPath"] == "exports/style-profiles/workplace-business-growth.json"
    assert exported["templateStatus"] == "active"
    assert "sourcePlannedSlotId" not in exported
    assert "Exported from promotion report" in exported["notes"]
    assert validation["status"] == "pass"
    assert cli.exit_code == 0
    assert "Exported" in cli.stdout
    assert validate_cli.exit_code == 0
    assert "ready-for-human-catalog-merge" in validate_cli.stdout


def test_style_profile_export_validation_blocks_unfinished_profile(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "exports/style-profiles/bad.json",
        '{"id":"bad","templateStatus":"candidate","tone":["TODO"],'
        '"promotionCriteria":{"requiredSampleChapters":1,"reviewChecklist":[]}}',
    )

    result = StyleProfilePromotionService().validate_exported_profile(
        project.root,
        "exports/style-profiles/bad.json",
    )

    assert result["status"] == "block"
    assert any(issue["type"] == "active_status_required" for issue in result["issues"])
    assert any(issue["type"] == "export_contains_todo" for issue in result["issues"])


def test_project_read_write_is_guarded(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    ProjectService().write_text(project.root, "drafts/001.generated.md", "hello")

    assert ProjectService().read_text(project.root, "drafts/001.generated.md") == "hello"
    with pytest.raises(ValueError):
        ProjectService().write_text(project.root, "../outside.md", "nope")


def test_list_runs_reads_run_records(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        '{"runId": "run_001", "skillId": "chapter-writer", "agentId": "local"}',
    )

    runs = ProjectService().list_runs(project.root)

    assert runs[0]["runId"] == "run_001"
    assert runs[0]["path"] == "runs/run_001/run.json"


def test_get_run_reads_prompt_and_output(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        '{"runId": "run_001", "skillId": "chapter-writer", "agentId": "local"}',
    )
    ProjectService().write_text(project.root, "runs/run_001/prompt.md", "# Prompt")
    ProjectService().write_text(project.root, "runs/run_001/output.md", "# Output")

    run = ProjectService().get_run(project.root, "run_001")

    assert run["prompt"] == "# Prompt"
    assert run["output"] == "# Output"


def test_create_and_list_characters(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    path = ProjectService().create_character(project.root, "hero", name="林澈")

    assert path == "characters/hero.md"
    assert ProjectService().list_characters(project.root) == ["characters/hero.md"]
    assert "# 林澈" in (project.root / path).read_text(encoding="utf-8")


def test_sync_timeline_events_from_markdown(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n- 第1章：林澈通过山门测试\n- 入夜 - 长老发现禁忌传承痕迹\n",
    )

    memory = ProjectService().sync_timeline_events_from_markdown(project.root)

    assert [event.id for event in memory.events] == ["event_001", "event_002"]
    assert memory.events[0].chapterId == "001"
    assert memory.events[0].label == "林澈通过山门测试"
    assert memory.events[1].time == "入夜"
    assert (project.root / "memory" / "timeline-events.json").read_text(encoding="utf-8")


def test_sync_timeline_events_preserves_structured_enrichment(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n- 第1章：林澈通过山门测试\n",
    )
    ProjectService().write_text(
        project.root,
        "memory/timeline-events.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "events": [
                    {
                        "id": "event_001",
                        "order": 99,
                        "label": "旧标签",
                        "time": "旧时间",
                        "chapterId": "001",
                        "source": "timeline.md",
                        "evidence": ["timeline.md#line:99"],
                        "entities": ["林澈"],
                        "summary": "旧摘要",
                        "importance": "high",
                    },
                    {
                        "id": "event_001_outcome",
                        "order": 1001,
                        "label": "林澈被长老盯上",
                        "chapterId": "001",
                        "source": "chapters/001.md",
                        "evidence": ["chapters/001.md"],
                        "summary": "林澈被长老盯上",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    memory = ProjectService().sync_timeline_events_from_markdown(project.root)
    serialized = json.loads(
        (project.root / "memory" / "timeline-events.json").read_text(encoding="utf-8")
    )

    assert [event.id for event in memory.events] == ["event_001", "event_001_outcome"]
    assert memory.events[0].order == 1
    assert memory.events[0].label == "林澈通过山门测试"
    assert memory.events[0].entities == ["林澈"]
    assert serialized["events"][0]["importance"] == "high"
    assert serialized["events"][1]["source"] == "chapters/001.md"


def test_sync_timeline_events_refreshes_context_packs(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="旧重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n- 第1章：林澈通过山门测试\n- 第2章：长老发现禁忌传承痕迹\n",
    )

    memory = ProjectService().sync_timeline_events_from_markdown(project.root)

    assert memory.events[-1].label == "长老发现禁忌传承痕迹"
    assert memory.events[-1].order == 2
    assert (project.root / "memory" / "timeline-events.json").exists()
    assert (project.root / "story" / "context-packs" / "001.json").exists()
