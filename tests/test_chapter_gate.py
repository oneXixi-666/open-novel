from __future__ import annotations

import json
import sys
from pathlib import Path

from open_novel.core.book_assets import BookAssetService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.editorial_profile import EditorialProfileService
from open_novel.core.models import SceneContract
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.workbench_repository import WorkbenchRepository


def write_contract(root: Path) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )


def test_chapter_gate_blocks_missing_contract_and_context(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "drafts/002.generated.md", "# Draft")

    report = ChapterGateService().check_chapter(project.root, "002")

    assert report.status == "block"
    assert "fix-blocking-chapter-issues" == report.recommendedNextAction
    assert {issue.stage for issue in report.issues} >= {"readiness", "context"}
    assert (project.root / "runs" / "chapter-gate-002.json").exists()


def test_chapter_gate_aggregates_continuity_and_review_risks(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(project.root, "drafts/001.generated.md", "测试石提前揭秘。")
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")
    PostChapterService().build_review_and_patch(project.root, "001")

    report = ChapterGateService().check_chapter(project.root, "001")

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("continuity", "violated_must_avoid") in issue_keys
    assert ("review", "emotionalBeat") in issue_keys
    assert report.status == "block"
    assert "story/context-packs/001.json" in report.generatedArtifacts
    assert "runs/continuity-001.json" in report.generatedArtifacts


def test_chapter_gate_includes_writing_quality_issues(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "# 第一章\n\n太短。")

    report = ChapterGateService().check_chapter(
        project.root,
        "001",
        draft_path="drafts/001.generated.md",
        include_review=False,
    )

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("quality", "too_short") in issue_keys
    assert any(stage == "editorial" for stage, _ in issue_keys)
    assert "runs/writing-quality-001.json" in report.generatedArtifacts
    assert "runs/editorial-review-001.json" in report.generatedArtifacts


def test_chapter_gate_reruns_editorial_review_for_requested_profile(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "# 第一章\n\n主角沉默。")
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "report = {'reviewer': 'gate-profile-editor', 'score': 70, 'status': 'warn', "
        "'issues': [{'type': 'reader_focus_diffuse', 'severity': 'medium', "
        "'dimension': 'pacing', 'evidence': ['drafts/001.generated.md'], "
        "'message': '读者焦点不够集中。', 'suggestions': ['聚焦本章核心承诺。']}]}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    EditorialProfileService().register_profile(
        project.root,
        profile_id="gate-editor",
        backend="command",
        command_template=f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
    )

    report = ChapterGateService().check_chapter(
        project.root,
        "001",
        draft_path="drafts/001.generated.md",
        include_review=False,
        editorial_profile_id="gate-editor",
    )

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    stored = (project.root / "runs" / "editorial-review-001.json").read_text(
        encoding="utf-8"
    )
    assert ("editorial", "reader_focus_diffuse") in issue_keys
    assert "gate-profile-editor" in stored


def test_chapter_gate_ignores_human_core_readiness_advice(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        '{"facts": [{"id": "fact_linggen", "text": "主角曾被视为残缺灵根。"}]}',
    )
    ContextPackService().build_context_pack(project.root, "001")

    readiness = StoryGuidanceService().check_readiness(project.root, "001")
    report = ChapterGateService().check_chapter(
        project.root,
        "001",
        include_draft=False,
        include_review=False,
    )

    assert {"internalNeed", "stakes", "cost"} <= {issue.field for issue in readiness.issues}
    assert report.status == "pass"
    assert ("readiness", "stakes") not in {(issue.stage, issue.type) for issue in report.issues}


def test_chapter_gate_keeps_low_score_without_blockers_as_warning(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章 试音\n\n"
        + "主角沿着雨夜站台追查异常声纹，阻力迫使他改变选择并承担暴露行踪的代价。" * 180,
    )

    report = ChapterGateService().check_chapter(project.root, "001")

    assert report.score < 60
    assert not any(issue.severity == "blocker" for issue in report.issues)
    assert report.status == "warn"


def test_chapter_gate_includes_memory_validation_issues(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(project.root, "memory/facts.json", "{bad json")

    report = ChapterGateService().check_chapter(project.root, "001")

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("memory", "invalid_json") in issue_keys
    assert "runs/memory-validation.json" in report.generatedArtifacts
    assert report.status == "block"


def test_chapter_gate_flags_stale_context_pack_against_latest_contract(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "story/chapter-briefs/001.json",
        SceneContract(
            chapterId="001",
            focus="更新后的重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ).model_dump_json(indent=2) + "\n",
    )

    report = ChapterGateService().check_chapter(project.root, "001")

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("context", "stale_context_pack") in issue_keys
    assert report.status == "block"


def test_chapter_gate_still_blocks_missing_contract(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    report = ChapterGateService().check_chapter(project.root, "001")

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("readiness", "sceneContract") in issue_keys
    assert report.status == "block"


def test_chapter_gate_flags_relevant_character_asset_missing_from_context(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "memory/character-assets.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "assets": [
                    {
                        "id": "asset_testing_stone_secret",
                        "characterId": "主角",
                        "kind": "secret_power",
                        "summary": "主角能让测试石显出异常潜力。",
                        "status": "active",
                        "importance": "high",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = ChapterGateService().check_chapter(
        project.root,
        "001",
        include_draft=False,
        include_review=False,
    )

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("context", "missing_character_asset_context") in issue_keys
    assert "memory/character-assets.json" in report.generatedArtifacts


def test_chapter_gate_flags_character_asset_reuse_risk(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/character-assets.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "assets": [
                    {
                        "id": "asset_testing_stone_secret",
                        "characterId": "主角",
                        "kind": "secret_power",
                        "summary": "主角能让测试石显出异常潜力。",
                        "status": "active",
                        "importance": "high",
                        "cooldown": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ContextPackService().build_context_pack(project.root, "001")

    report = ChapterGateService().check_chapter(
        project.root,
        "001",
        include_draft=False,
        include_review=False,
    )

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("context", "character_asset_reuse_risk") in issue_keys


def test_chapter_gate_blocks_draft_that_denies_confirmed_memory(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_artifact",
                        "text": "林澈获得神器A。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈从未见过神器A，甚至不相信它存在。",
    )

    report = ChapterGateService().check_chapter(project.root, "001", include_review=False)

    issue_keys = {(issue.stage, issue.type) for issue in report.issues}
    assert ("memory", "memory_conflict") in issue_keys
    assert report.status == "block"


def test_chapter_gate_does_not_block_unrelated_negative_sentence(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_artifact",
                        "text": "林澈获得神器A。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈没有退后。他把神器A收入袖中，继续寻找出口。",
    )

    report = ChapterGateService().check_chapter(project.root, "001", include_review=False)

    assert ("memory", "memory_conflict") not in {
        (issue.stage, issue.type) for issue in report.issues
    }


def test_chapter_gate_blocks_confirmed_hard_world_rule_conflict(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    repository = WorkbenchRepository(tmp_path / "workbench.sqlite3")
    repository.upsert_material(
        project.root,
        {
            "id": "world-testing-stone",
            "type": "设定",
            "title": "测试石规则",
            "summary": "测试区禁止启动明火推进器。",
            "influence": "所有参与者必须使用冷推进设备。",
            "related": ["世界设定确认记录"],
            "confidence": 98,
            "details": {"规则": "禁止：启动明火推进器"},
        },
    )
    book_assets = BookAssetService(repository)
    context_service = ContextPackService(book_assets=book_assets)
    context_service.build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角握住测试石，随后启动明火推进器冲过封锁。",
    )

    report = ChapterGateService(
        context_pack_service=context_service,
        book_asset_service=book_assets,
    ).check_chapter(project.root, "001", include_review=False)

    world_rule_issues = [item for item in report.issues if item.type == "world_rule_conflict"]
    assert len(world_rule_issues) == 1
    issue = world_rule_issues[0]
    assert issue.severity == "blocker"
    assert report.status == "block"
    assert "测试石规则" in issue.message


def test_chapter_gate_ignores_later_generated_memory_and_subject_negation(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_002_outcome",
                        "text": "林澈与居民协作救出受困孩子并恢复排水。",
                        "validFrom": "chapter:002",
                        "confidence": 1,
                        "_operationId": "op_review_002_fact_outcome",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈没有回答。他握住测试石，继续向前。",
    )

    report = ChapterGateService().check_chapter(project.root, "001", include_review=False)

    assert ("memory", "memory_conflict") not in {
        (issue.stage, issue.type) for issue in report.issues
    }
