from __future__ import annotations

from pathlib import Path

from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def test_create_scene_contract_writes_structured_brief(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    contract = StoryGuidanceService().create_scene_contract(
        project.root,
        "1",
        title="山门测试",
    )

    assert contract.chapterId == "001"
    assert (project.root / "story" / "chapter-briefs" / "001.json").exists()
    assert (project.root / "story" / "context-packs" / "001.json").exists()


def test_readiness_blocks_missing_focus_and_emotion(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().create_scene_contract(project.root, "001")

    report = StoryGuidanceService().check_readiness(project.root, "001")

    fields = {issue.field for issue in report.issues}
    assert report.status == "block"
    assert "focus" in fields
    assert "emotionalBeat" in fields
    assert "relationshipBeat" in fields
    assert "internalNeed" in fields
    assert "stakes" in fields
    assert "cost" in fields
    assert "logicDependencies" in fields


def test_readiness_passes_complete_contract(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="山门测试",
            focus="本章重点是让主角第一次证明异常潜力。",
            goal="主角想通过山门测试。",
            conflict="旧敌和执事阻挠测试。",
            turn="测试石显出禁忌纹路。",
            outcome="主角通过测试但被长老盯上。",
            hook="长老封锁消息并带走主角。",
            emotionalBeat="主角从压抑转为震惊和警惕。",
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            internalNeed="主角想证明自己不是任人踩踏的废物。",
            woundOrFear="主角害怕再次被当众否定。",
            stakes="如果失败，他会失去进入宗门的机会。",
            cost="他证明潜力的同时暴露异常，被长老盯上。",
            subtext="主角嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            logicDependencies=["主角被认为是残缺灵根"],
            mustAvoid=["提前解释禁忌传承"],
            readerPromises=["废柴逆袭"],
        ),
    )

    report = service.check_readiness(project.root, "001")

    assert report.status == "pass"
    assert report.score == 100
