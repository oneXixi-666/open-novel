from __future__ import annotations

from pathlib import Path

import pytest

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import SceneContract
from open_novel.core.plot_direction import PlotDirectionService
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def test_plot_direction_suggests_options_and_flags_forbidden_intent(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="测试石异动",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前解释禁忌传承全部真相"],
            readerPromises=["废柴逆袭"],
        ),
    )

    report = PlotDirectionService().suggest_directions(project.root, "001", "我想提前揭秘")

    assert len(report.options) == 3
    assert report.recommendedOptionId
    risks = [risk for option in report.options for risk in option.risks]
    assert any("提前解释禁忌传承全部真相" in risk for risk in risks)
    assert (project.root / "story" / "branches" / "001.direction-report.json").exists()


def test_apply_plot_direction_updates_contract_and_context(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="测试石异动",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前解释禁忌传承全部真相"],
            readerPromises=["废柴逆袭"],
        ),
    )
    service = PlotDirectionService()
    report = service.suggest_directions(project.root, "001", "我想强化情感代价")

    contract = service.apply_direction(project.root, "001", report.options[1].id)

    assert "强化人物代价" in contract.focus
    assert contract.emotionalBeat == "旧敌开始忌惮。"
    assert (project.root / "story" / "context-packs" / "001.json").exists()


def test_apply_plot_direction_rejects_risky_option(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="测试石异动",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前解释禁忌传承全部真相"],
            readerPromises=["废柴逆袭"],
        ),
    )
    service = PlotDirectionService()
    report = service.suggest_directions(project.root, "001", "我想提前揭秘")

    with pytest.raises(ValueError, match="risky direction"):
        service.apply_direction(project.root, "001", report.options[2].id)


def test_plot_direction_refreshes_stale_context_pack(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="旧分支重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ContextPackService().build_context_pack(project.root, "001")
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="新分支重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )

    PlotDirectionService().suggest_directions(project.root, "001", "我想强化情感代价")

    context_pack = ContextPackService().read_context_pack(project.root, "001")
    assert context_pack.included[0].data["focus"] == "新分支重点"
