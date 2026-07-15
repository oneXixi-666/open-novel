from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def test_memory_validation_passes_standard_project(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    report = MemoryValidationService().validate_project(project.root)

    assert report.status == "pass"
    assert report.score == 100
    assert report.issues == []
    assert (project.root / "runs" / "memory-validation.json").exists()


def test_memory_validation_flags_invalid_json(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "memory/facts.json", "{bad json")

    report = MemoryValidationService().validate_project(project.root)

    issue = next(issue for issue in report.issues if issue.path == "memory/facts.json")
    assert report.status == "block"
    assert issue.type == "invalid_json"
    assert issue.severity == "blocker"


def test_memory_validation_flags_writing_lesson_without_text(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [{"id": "lesson_focus", "category": "focus"}],
            },
            ensure_ascii=False,
        ),
    )

    report = MemoryValidationService().validate_project(project.root)

    issue = next(issue for issue in report.issues if issue.path == "memory/writing-lessons.json")
    assert issue.type == "missing_text"


def test_memory_validation_flags_character_state_schema_errors(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {
                        "states": [
                            {
                                "chapterId": "001",
                                "emotion": "林澈开始信任长老。",
                            }
                        ]
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = MemoryValidationService().validate_project(project.root)

    issue = next(
        issue for issue in report.issues if issue.path == "memory/character-states.json"
    )
    assert report.status == "block"
    assert issue.type == "schema_error"
    assert issue.severity == "blocker"


def test_memory_validation_flags_semantic_memory_quality_issues(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/promises.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise_001",
                        "readerQuestion": "禁忌纹路真相",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:006-004",
                    },
                    {
                        "id": "promise_001",
                        "readerQuestion": "",
                        "introducedAt": "chapter 2",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = MemoryValidationService().validate_project(project.root)

    issues = {(issue.path, issue.type) for issue in report.issues}
    assert report.status == "block"
    assert ("memory/promises.json", "duplicate_id") in issues
    assert ("memory/promises.json", "missing_text") in issues
    assert ("memory/promises.json", "invalid_payoff_window") in issues
    assert ("memory/promises.json", "invalid_chapter_ref") in issues


def test_memory_validation_flags_missing_emotional_continuity(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/emotional-arcs.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {
                        "characterId": "lin_che",
                        "beats": [{"chapterId": "001"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {
                        "characterId": "lin_che",
                        "states": [{"chapterId": "001", "externalGoal": "通过测试"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/relationship-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "relationships": [
                    {
                        "id": "rel_001",
                        "fromCharacterId": "lin_che",
                        "toCharacterId": "old_enemy",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = MemoryValidationService().validate_project(project.root)

    issues = {(issue.path, issue.type) for issue in report.issues}
    assert report.status in {"warn", "block"}
    assert ("memory/emotional-arcs.json", "missing_emotional_beat") in issues
    assert ("memory/character-states.json", "missing_emotion") in issues
    assert ("memory/relationship-states.json", "missing_relationship_status") in issues


def test_memory_repair_proposal_suggests_safe_list_field_patch(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "memory/facts.json", "{}")

    proposal = MemoryValidationService().propose_repair(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/facts.json"
    )
    assert operation.action == "add_missing_list"
    assert operation.payload == {"field": "facts", "value": []}
    assert json.loads((project.root / "memory" / "facts.json").read_text(encoding="utf-8")) == {}
    assert (project.root / "runs" / "memory-repair-proposal.json").exists()


def test_memory_repair_proposal_keeps_invalid_json_manual(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "memory/facts.json", "{bad json")

    proposal = MemoryValidationService().propose_repair(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/facts.json"
    )
    assert operation.action == "manual_fix"
    assert operation.payload["issueType"] == "invalid_json"
    assert (project.root / "memory" / "facts.json").read_text(encoding="utf-8") == "{bad json"


def test_memory_repair_proposal_can_suggest_missing_file_creation(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    (project.root / "memory" / "promises.json").unlink()

    proposal = MemoryValidationService().propose_repair(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/promises.json"
    )
    assert operation.action == "create_file"
    assert operation.payload["content"] == {"schemaVersion": 1, "promises": []}
    assert not (project.root / "memory" / "promises.json").exists()


def test_apply_safe_memory_repairs_adds_missing_list_field(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "memory/facts.json", "{}")

    proposal = MemoryValidationService().apply_safe_repairs(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/facts.json"
    )
    assert operation.status == "applied"
    assert operation.action == "add_missing_list"
    assert json.loads((project.root / "memory" / "facts.json").read_text(encoding="utf-8")) == {
        "facts": []
    }
    assert MemoryValidationService().validate_project(project.root).status == "pass"


def test_apply_safe_memory_repairs_creates_missing_file(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    (project.root / "memory" / "promises.json").unlink()

    proposal = MemoryValidationService().apply_safe_repairs(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/promises.json"
    )
    assert operation.status == "applied"
    assert json.loads(
        (project.root / "memory" / "promises.json").read_text(encoding="utf-8")
    ) == {
        "schemaVersion": 1,
        "promises": [],
    }


def test_apply_safe_memory_repairs_refreshes_context_packs(tmp_path: Path) -> None:
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
    ContextPackService().build_context_pack(project.root, "001")
    ProjectService().write_text(
        project.root,
        "story/chapter-briefs/001.json",
        SceneContract(
            chapterId="001",
            focus="新重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ).model_dump_json(indent=2) + "\n",
    )
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_001",
                        "text": "新事实：主角通过测试。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    before = ContextPackService().read_context_pack(project.root, "001")
    before_contract = next(
        item for item in before.included if item.source == "story/chapter-briefs/001.json"
    )
    assert before_contract.data["focus"] == "旧重点"

    MemoryValidationService().apply_safe_repairs(project.root)

    after = ContextPackService().read_context_pack(project.root, "001")
    after_contract = next(
        item for item in after.included if item.source == "story/chapter-briefs/001.json"
    )
    assert after_contract.data["focus"] == "新重点"
    assert MemoryValidationService().validate_project(project.root).status == "pass"


def test_apply_safe_memory_repairs_skips_manual_fix(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "memory/facts.json", "{bad json")

    proposal = MemoryValidationService().apply_safe_repairs(project.root)

    operation = next(
        operation for operation in proposal.operations if operation.target == "memory/facts.json"
    )
    assert operation.status == "skipped"
    assert operation.action == "manual_fix"
    assert (project.root / "memory" / "facts.json").read_text(encoding="utf-8") == "{bad json"
    assert MemoryValidationService().validate_project(project.root).status == "block"
