from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.exporters.service import ExportService


def test_markdown_export_combines_chapters_in_numeric_order(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "chapters/010.md", "# 010\n\nTen")
    ProjectService().write_text(project.root, "chapters/002.md", "# 002\n\nTwo")

    output = ExportService().export_markdown(project.root)

    text = output.read_text(encoding="utf-8")
    assert text.index("# 001") < text.index("# 002") < text.index("# 010")
    assert text.startswith("# Demo")


def test_txt_export_removes_markdown_heading_marks(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    output = ExportService().export_txt(project.root)

    assert "# Demo" not in output.read_text(encoding="utf-8")


def test_zip_export_includes_canon_chapters_not_drafts(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "drafts/001.generated.md", "draft")

    output = ExportService().export_zip(project.root)

    with ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "chapters/001.md" in names
    assert "drafts/001.generated.md" not in names


def test_training_data_export_writes_contract_grounded_jsonl(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
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
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
            runId="training_export_draft",
        )
    )
    ProjectService().accept_draft(
        project.root,
        "drafts/001.generated.md",
        chapter_id="001",
    )
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_emotion",
                        "category": "emotion",
                        "lesson": "情绪要用动作落地。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    output = ExportService().export_writing_training_jsonl(project.root)

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["input"]["sceneContract"]["focus"] == "林澈在山门测试中证明异常潜力。"
    assert records[0]["input"]["boundedWritingLessons"]["lessons"][0]["id"] == "lesson_emotion"
    assert records[0]["metadata"]["qualityScore"] >= 70
    assert records[0]["metadata"]["gateScore"] == 100


def test_training_data_export_skips_low_quality_chapters(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n太短。")

    output = ExportService().export_writing_training_jsonl(project.root)

    assert output.read_text(encoding="utf-8") == ""


def test_training_readiness_reports_eligible_and_skipped_chapters(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
            runId="training_readiness_good",
        )
    )
    ProjectService().accept_draft(project.root, "drafts/001.generated.md", chapter_id="001")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            title="第二章",
            focus="主角继续追查。",
            goal="主角想查清线索。",
            conflict="阻力出现。",
            turn="局势变化。",
            outcome="主角暂时脱身。",
            hook="新问题出现。",
            emotionalBeat="主角从压抑转为警惕。",
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(project.root, "chapters/002.md", "# 第二章\n\n太短。")

    report = ExportService().training_readiness(project.root)

    assert report.status == "warn"
    assert report.minRecommendedExamples == 50
    assert report.eligibleCount == 1
    assert report.skippedCount == 1
    assert report.items[0].eligible is True
    assert report.items[1].eligible is False
    assert report.items[1].reason
    assert report.items[1].issueCount > 0
    assert report.items[1].issueTypes
    assert report.items[1].previousSimilarity >= 0
    assert report.items[1].actionSuggestion
    assert (project.root / "exports" / "training-readiness.json").exists()

    output = ExportService().export_writing_training_jsonl(project.root)
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    exported_ids = {record["metadata"]["chapterId"] for record in records}
    eligible_ids = {item.chapterId for item in report.items if item.eligible}
    assert exported_ids == eligible_ids
    first_metadata = records[0]["metadata"]
    assert "quality_score" in first_metadata
    assert "gate_status" in first_metadata
    assert "calibration_label" in first_metadata

    selected_output = ExportService().export_writing_training_jsonl(
        project.root,
        selected_chapter_ids=["002"],
    )
    selected_records = [
        json.loads(line)
        for line in selected_output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {record["metadata"]["chapterId"] for record in selected_records} == {"002"}


def test_training_readiness_deduplicates_same_batch_examples(tmp_path: Path, monkeypatch) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    for index in range(1, 4):
        chapter_id = f"{index:03d}"
        service.write_scene_contract(
            project.root,
            SceneContract(
                chapterId=chapter_id,
                title=f"第{index}章",
                focus="林澈在测试后继续追查异常潜力。",
                goal="林澈想查清测试石异常。",
                conflict="旧敌和长老同时阻挠。",
                turn="测试石裂纹指向新线索。",
                outcome="林澈拿到下一步证据。",
                hook="更深势力盯上林澈。",
                emotionalBeat="林澈从压抑转为警惕。",
                relationshipBeat="旧敌从轻蔑转为忌惮。",
                logicDependencies=["林澈曾被视为残缺灵根"],
                mustInclude=["测试石"],
                mustAvoid=["提前揭秘"],
                readerPromises=["废柴逆袭"],
            ),
        )
    duplicate_text = (
        "林澈握紧测试石，胸口压着旧敌留下的羞辱。"
        "长老冷声追问时，他选择把裂纹玉牌按在石面。"
        "测试石忽然亮起，旧敌的笑意僵住，围观弟子开始后退。"
        "林澈知道自己暴露了异常，也知道再退一步就会被夺走证据。"
        "他压下发冷的呼吸，顺势逼问长老为什么要封锁消息。"
        "如果这次失败，他会失去追查灵根真相的入口。"
        "测试石的裂纹最终指向禁地，新的危险在夜色里亮起。"
    )
    distinct_text = (
        "星港雨幕落下，苏晚把门禁卡藏进袖口。"
        "巡逻队忽然改道，她只能选择穿过废弃泊位。"
        "录音带在掌心发烫，里面的三秒呼吸声不断逼近。"
        "如果她被拦下，档案修正会就会销毁整条线索。"
        "她故意引爆警报，把追兵压向另一条通道。"
        "泊位尽头的黑门打开，名单上的第一个名字正是她自己。"
    )
    ProjectService().write_text(project.root, "chapters/001.md", f"# 第一章\n\n{duplicate_text}")
    ProjectService().write_text(project.root, "chapters/002.md", f"# 第二章\n\n{distinct_text}")
    ProjectService().write_text(
        project.root,
        "chapters/003.md",
        (project.root / "chapters" / "001.md").read_text(encoding="utf-8"),
    )

    export_service = ExportService()

    def passing_reports(_root: Path, _chapter_id: str, _thresholds: object):
        return (
            SimpleNamespace(score=90, issues=[], metrics={}),
            SimpleNamespace(status="pass", score=100, issues=[]),
        )

    monkeypatch.setattr(export_service, "_chapter_training_reports", passing_reports)

    report = export_service.training_readiness(project.root)

    duplicate = next(item for item in report.items if item.chapterId == "003")
    assert duplicate.eligible is False
    assert duplicate.reason == "batch_duplicate"
    assert duplicate.batchDuplicateOf == "001"
    assert duplicate.batchSimilarity >= 0.72
    assert report.eligibleCount == 2

    output = export_service.export_writing_training_jsonl(project.root)
    exported_ids = {
        json.loads(line)["metadata"]["chapterId"]
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "003" not in exported_ids


def test_training_readiness_excludes_continuity_failed_chapters(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈在山门测试中证明异常潜力。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过但被长老盯上。",
            hook="门外忽然传来一道声音。",
            emotionalBeat="林澈从压抑转为警惕。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n林澈平静地走到测试石前。门外忽然传来一道声音。",
    )
    export_service = ExportService()

    def continuity_failed_reports(_root: Path, _chapter_id: str, _thresholds: object):
        return (
            SimpleNamespace(
                score=90,
                issues=[SimpleNamespace(type="emotional_discontinuity", severity="high")],
                metrics={},
            ),
            SimpleNamespace(status="pass", score=100, issues=[]),
        )

    monkeypatch.setattr(export_service, "_chapter_training_reports", continuity_failed_reports)

    report = export_service.training_readiness(project.root)

    item = report.items[0]
    assert item.eligible is False
    assert item.reason == "continuity_failed"
    assert "emotional_discontinuity" in item.issueTypes
