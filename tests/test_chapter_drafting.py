from __future__ import annotations

import json
import sys
from pathlib import Path

from open_novel.core.chapter_drafting import ChapterDraftService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def _ready_project(root: Path) -> Path:
    project = ProjectService().create_project(root, title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "林澈曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="林澈在山门测试中证明异常潜力。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            internalNeed="林澈想证明自己不是任人踩踏的废物。",
            woundOrFear="林澈害怕再次被当众否定。",
            stakes="如果失败，林澈会失去进入宗门和追查测试石异常的机会。",
            cost="林澈证明潜力的同时暴露异常，被长老盯上。",
            subtext="林澈嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    return project.root


def test_draft_chapter_falls_back_to_local_dry_run_without_model(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")

    result = ChapterDraftService().draft_chapter(root, "001")

    assert result.agentId == "local-dry-run"
    assert result.modelProfile is None
    assert result.outputPath == "drafts/001.generated.md"
    assert (root / "drafts" / "001.generated.md").exists()


def test_draft_chapter_prefers_registered_trained_model(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "tomato-trained",
                "profiles": [
                    {
                        "id": "tomato-trained",
                        "label": "Tomato trained",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "base",
                        "adapterPath": "models/adapters/latest",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "Path(r'{output_file}').write_text("
                            "'# 训练模型章\\n\\n测试石前，林澈没有解释，只把手按了上去。'); "
                            "print(Path(r'{output_file}').read_text())\""
                        ),
                        "timeoutSeconds": 60,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = ChapterDraftService().draft_chapter(root, "001")
    run_record = json.loads((root / result.runDir / "run.json").read_text(encoding="utf-8"))

    assert result.agentId == "local-model"
    assert result.modelProfile == "tomato-trained"
    assert "训练模型章" in (root / "drafts" / "001.generated.md").read_text(encoding="utf-8")
    assert run_record["modelProfile"] == "tomato-trained"


def test_evaluate_and_learn_records_quality_lessons(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "drafts/001.generated.md",
        "# 第一章\n\n这里介绍山门规则。事实上规则很多。最后主角通过了测试。",
    )

    result = ChapterDraftService().evaluate_and_learn(root, "001")
    memory = json.loads((root / "memory/writing-lessons.json").read_text(encoding="utf-8"))
    lesson_ids = {lesson["id"] for lesson in memory["lessons"]}

    assert result["lessonsPath"] == "memory/writing-lessons.json"
    assert result["learning"]["quality"]["addedCount"] >= 2
    assert "weak_subtext" in result["learning"]["quality"]["skipped"]
    assert "lesson_style_too_short" in lesson_ids
    assert "lesson_emotion_weak_emotional_grounding" in lesson_ids
    assert "lesson_relationship_weak_subtext" not in lesson_ids


def test_evaluate_and_learn_records_lesson_success_once(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_focus_custom_success",
                        "category": "focus",
                        "lesson": "本章要保持测试现场的单一核心压力。",
                        "appliesTo": ["custom_success_marker"],
                        "severity": "high",
                        "status": "active",
                        "failureCount": 2,
                        "successCount": 0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ContextPackService().build_context_pack(root, "001")
    ProjectService().write_text(
        root,
        "drafts/001.generated.md",
        (
            "# 第一章\n\n"
            "测试石前，林澈把手按上去。旧敌冷笑，长老沉默，所有目光都压在他背上。"
            "他没有解释，只在灵光亮起时收紧指节。通过测试的欢呼刚起，长老便封锁消息。"
        ),
    )

    first = ChapterDraftService().evaluate_and_learn(root, "001")
    second = ChapterDraftService().evaluate_and_learn(root, "001")
    memory = json.loads((root / "memory/writing-lessons.json").read_text(encoding="utf-8"))
    lesson = next(item for item in memory["lessons"] if item["id"] == "lesson_focus_custom_success")

    assert first["learning"]["success"]["succeeded"] == ["lesson_focus_custom_success"]
    assert second["learning"]["success"]["succeeded"] == []
    assert lesson["successCount"] == 1
    assert "success:story/context-packs/001.json" in lesson["evidence"]


def test_evaluate_and_learn_blocks_success_when_issue_still_unresolved(
    tmp_path: Path,
) -> None:
    root = _ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_style_too_short",
                        "category": "style",
                        "lesson": "章节不能短成梗概。",
                        "appliesTo": ["too_short"],
                        "severity": "high",
                        "status": "active",
                        "failureCount": 2,
                        "successCount": 0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ContextPackService().build_context_pack(root, "001")
    ProjectService().write_text(root, "drafts/001.generated.md", "# 第一章\n\n林澈通过测试。")

    result = ChapterDraftService().evaluate_and_learn(root, "001")
    memory = json.loads((root / "memory/writing-lessons.json").read_text(encoding="utf-8"))
    lesson = next(item for item in memory["lessons"] if item["id"] == "lesson_style_too_short")

    assert "lesson_style_too_short" in result["learning"]["success"]["blocked"]
    assert lesson["successCount"] == 0
