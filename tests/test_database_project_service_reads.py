from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.book_analysis import BookAnalysisService
from open_novel.core.director import DirectorService
from open_novel.core.knowledge_base import KnowledgeBaseService
from open_novel.core.memory_topic import MemoryTopicService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.project import ProjectService
from open_novel.core.revision_plan import RevisionPlanService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.style_promotion import StyleProfilePromotionService
from open_novel.core.writing_assets import WritingAssetService
from open_novel.core.writing_formula import WritingFormulaService
from open_novel.core.writing_learning import WritingLearningService


def _database_project(tmp_path: Path) -> Path:
    return ProjectService().create_project(
        tmp_path / "database-book",
        title="数据库作品",
        database_only=True,
    ).root


def test_database_project_reopens_analysis_writing_memory_and_knowledge(
    tmp_path: Path,
) -> None:
    root = _database_project(tmp_path)
    writer = ProjectService()
    writer.write_text(
        root,
        "runs/book-analysis/001-001.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "startChapterId": "001",
                "endChapterId": "001",
                "path": "runs/book-analysis/001-001.json",
                "status": "pass",
                "chapters": [],
                "formulaCandidates": [],
                "notes": [],
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "memory/writing-formulas.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "formulas": [
                    {
                        "id": "ending_hook_grounded",
                        "title": "钩子从结果里长出来",
                        "guidance": "章末问题必须由本章结果引出。",
                        "status": "active",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_hook",
                        "category": "hook",
                        "lesson": "章末留下由结果引出的新问题。",
                        "status": "active",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "memory/long-term-memory.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "topics": [
                    {
                        "id": "topic_clock",
                        "kind": "fact",
                        "title": "钟楼来信",
                        "summary": "钟楼来信来自十年前。",
                    }
                ],
                "entityIndex": [],
                "writingGuidance": [],
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "knowledge/sources/clock.md",
        "# 钟楼规则\n\n钟楼只在午夜开放，来信会显示未来日期。",
    )

    report = BookAnalysisService().read_report(
        root,
        "runs/book-analysis/001-001.json",
    )
    formulas = WritingFormulaService().read_memory(root)
    assets = WritingAssetService().effective_assets(root)
    topic = MemoryTopicService().topic_detail(root, "topic_clock")
    knowledge = KnowledgeBaseService().rebuild_index(root)
    reopened_knowledge = KnowledgeBaseService().read_index(root)

    assert report.status == "pass"
    assert formulas.formulas[0].status == "active"
    assert assets["formulas"][0]["id"] == "ending_hook_grounded"
    assert assets["lessons"][0]["id"] == "lesson_hook"
    assert topic["topic"]["title"] == "钟楼来信"
    assert knowledge.chunks
    assert reopened_knowledge.chunks[0].source == "knowledge/sources/clock.md"
    assert not root.exists()


def test_database_project_reopens_director_revision_validation_and_usage(
    tmp_path: Path,
) -> None:
    root = _database_project(tmp_path)
    writer = ProjectService()
    plan = DirectorService().create_plan(root, "001", "补强章末钩子")
    writer.write_text(
        root,
        "runs/revision-plan-001-001.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "startChapterId": "001",
                "endChapterId": "001",
                "status": "needs-revision",
                "priorityChapters": ["001"],
                "chapters": [],
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "runs/writing-quality-001.json",
        json.dumps(
            {
                "issues": [
                    {
                        "type": "weak_ending_hook",
                        "severity": "high",
                        "message": "章末缺少追读问题。",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    writer.write_text(
        root,
        "story/context-packs/001.json",
        json.dumps(
            {
                "chapterId": "001",
                "included": [
                    {
                        "source": "memory/writing-lessons.json",
                        "data": {
                            "lessons": [
                                {
                                    "id": "lesson_hook",
                                    "_contextPriority": {"reasons": ["当前章节需要章末钩子"]},
                                }
                            ]
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    reopened_plan = DirectorService().read_plan(root, plan.planPath)
    revision = RevisionPlanService()
    revision_plan = revision.read_plan(root, "runs/revision-plan-001-001.json")
    issues = revision._chapter_issues(root, "001")
    validation = MemoryValidationService().validate_project(root)
    usage = WritingLearningService().lesson_usage(root)

    assert reopened_plan.planId == plan.planId
    assert revision_plan["status"] == "needs-revision"
    assert issues[0]["type"] == "weak_ending_hook"
    assert validation.status == "pass"
    assert usage["lesson_hook"][0]["path"] == "story/context-packs/001.json"
    assert not root.exists()


def test_database_project_reopens_style_promotion_artifacts(tmp_path: Path) -> None:
    root = _database_project(tmp_path)
    writer = ProjectService()
    profile = StyleProfileService().get_builtin_profile("generic-web-serial")
    exported = profile.model_dump(mode="json")
    exported["templateStatus"] = "active"
    exported["sourcePlannedSlotId"] = ""
    writer.write_text(
        root,
        "exports/style-profiles/generic-web-serial.json",
        json.dumps(exported, ensure_ascii=False),
    )
    writer.write_text(
        root,
        "runs/style-profile-promotions/generic-web-serial-001-005.json",
        json.dumps(
            {
                "candidateProfilePath": "story/style-profile.json",
                "recommendedNextAction": "ready-to-promote-style-profile",
            },
            ensure_ascii=False,
        ),
    )

    service = StyleProfilePromotionService()
    report = service._read_report(
        root,
        "runs/style-profile-promotions/generic-web-serial-001-005.json",
    )
    candidate = service._read_candidate(root, "story/style-profile.json")
    validation = service.validate_exported_profile(
        root,
        "exports/style-profiles/generic-web-serial.json",
    )

    assert report["recommendedNextAction"] == "ready-to-promote-style-profile"
    assert candidate.id == "project-style"
    assert validation["status"] == "pass"
    assert validation["issues"] == []
    assert not root.exists()
