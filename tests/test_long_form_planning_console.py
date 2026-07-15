from __future__ import annotations

import json

from open_novel.core.context_pack import ContextPackService
from open_novel.core.long_form_planning import LongFormPlanService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def _volume(index: int) -> dict[str, object]:
    start = (index - 1) * 10 + 1
    end = index * 10
    return {
        "volumeId": f"volume-{index:03d}",
        "title": f"第 {index} 卷",
        "chapterRange": f"{start:03d}-{end:03d}",
        "goal": f"推进第 {index} 卷共同目标",
        "mainConflict": f"第 {index} 卷冲突",
        "payoffs": [f"第 {index} 卷兑现"],
        "endingChange": f"第 {index} 卷局势变化",
        "failureCondition": f"第 {index} 卷失败代价",
        "beatSegments": [
            {
                "segmentId": f"volume-{index:03d}-segment-01",
                "title": "加压",
                "chapterRange": f"{start:03d}-{start + 4:03d}",
                "purpose": "增加压力",
                "pressure": "选择收窄",
                "payoff": "获得线索",
                "density": "升级",
            },
            {
                "segmentId": f"volume-{index:03d}-segment-02",
                "title": "兑现",
                "chapterRange": f"{start + 5:03d}-{end:03d}",
                "purpose": "兑现阶段承诺",
                "pressure": "代价落地",
                "payoff": "卷目标推进",
                "density": "兑现",
            },
        ],
    }


def _landing(index: int) -> dict[str, object]:
    volume = (index - 1) // 10 + 1
    segment = 1 if (index - 1) % 10 < 5 else 2
    return {
        "chapterId": f"{index:03d}",
        "title": f"第 {index} 章",
        "goal": "重复调查" if index in {3, 4} else f"推进线索 {index}",
        "hook": "无" if index in {1, 2} else f"危险 {index} 逼近",
        "characterChange": "无变化" if index in {5, 6} else f"主角作出选择 {index}",
        "promiseProgression": f"推进承诺 {index}",
        "logicDependencies": [] if index == 1 else [f"承接第 {index - 1} 章"],
        "segmentId": f"volume-{volume:03d}-segment-{segment:02d}",
    }


def test_three_volume_thirty_chapter_console_risks_and_context_pack(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "serial", title="三卷连载")
    service = LongFormPlanService()
    plan = {
        "schemaVersion": 1,
        "mainline": "查清城市真相",
        "endingDirection": "居民共同决定城市规则",
        "longTermOpposition": "公开真相与维持秩序冲突",
        "corePromises": ["声音来源", "城市选择"],
        "estimatedVolumes": 3,
        "currentVolumeId": "volume-001",
        "volumes": [_volume(index) for index in range(1, 4)],
        "manualRevisionAt": "2026-07-12T01:00:00+00:00",
        "lastPlannedRevisionAt": "2026-07-11T01:00:00+00:00",
    }
    ProjectService().write_text(
        project.root, service.plan_path, json.dumps(plan, ensure_ascii=False)
    )
    for volume in plan["volumes"]:
        service._write_volume_and_arc(project.root, volume)  # noqa: SLF001
    ProjectService().write_text(
        project.root,
        "story/chapter-blueprint.json",
        json.dumps(
            {"schemaVersion": 2, "chapters": [_landing(index) for index in range(1, 31)]},
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/promises.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise-001",
                        "text": "声音来源",
                        "openedIn": "chapter:001",
                        "status": "active",
                        "payoffWindow": "1-3 chapters",
                        "relatedChapters": ["001", "003"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    landings = service.chapter_landings(project.root)
    risks = {item["key"]: item for item in service.serial_risks(project.root)}

    assert len(landings) == 30
    assert len(plan["volumes"]) == 3
    assert all(
        risks[key]["status"] == "risk"
        for key in {
            "weak_hooks",
            "promise_pressure",
            "rhythm_imbalance",
            "character_stagnation",
            "volume_deviation",
        }
    )
    assert all(item["evidenceChapters"] for item in risks.values())
    assert risks["weak_hooks"]["evidenceChapters"] == ["001", "002"]
    assert risks["rhythm_imbalance"]["evidenceChapters"] == ["003", "004"]
    assert risks["character_stagnation"]["evidenceChapters"] == ["005", "006"]

    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="004",
            title="第四章",
            focus="追查第四条线索",
            goal="取得证据",
            conflict="封锁阻拦",
            turn="证据反转",
            outcome="确认入口",
            hook="追兵出现",
            emotionalBeat="主角转为警惕",
            logicDependencies=["旧依赖"],
        ),
    )
    context = ContextPackService().build_context_pack(project.root, "004")
    contract = next(
        item for item in context.included if item.source == "story/chapter-briefs/004.json"
    )
    assert contract.data["arcContext"]["arcGoal"] == "推进第 1 卷共同目标"
    assert contract.data["planningLanding"]["segmentId"] == "volume-001-segment-01"
    assert contract.data["planningLanding"]["logicDependencies"] == ["承接第 3 章"]


def test_long_form_plan_warns_when_volume_themes_converge() -> None:
    service = LongFormPlanService()
    payload = {
        "bookPlan": {
            "mainline": "主角重建城市",
            "endingDirection": "城市恢复自治",
            "longTermOpposition": "旧制度阻挠",
            "corePromises": ["共同治理"],
        },
        "volumes": [_volume(index) for index in range(1, 4)],
    }
    payload["volumes"][0]["goal"] = "争取共同授权并重建社区供能"
    payload["volumes"][0]["mainConflict"] = "共同授权对抗单点牺牲"
    payload["volumes"][1]["goal"] = "争取共同授权并重建社区供能"
    payload["volumes"][1]["mainConflict"] = "共同授权对抗单点牺牲"
    payload["volumes"][2]["goal"] = "调查远海失踪船队"
    payload["volumes"][2]["mainConflict"] = "风暴航线与救援时限冲突"

    plan = service.validate_plan(payload)

    warning = next(item for item in plan["warnings"] if item["type"] == "volume_theme_convergence")
    assert warning["severity"] == "warn"
    assert warning["volumeIds"] == ["volume-001", "volume-002"]
    assert warning["overlap"] >= 0.6
    assert all("volume-003" not in item["volumeIds"] for item in plan["warnings"])


def test_replan_preserves_finalized_landing_and_updates_future_context(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "serial", title="重规划保护")
    service = LongFormPlanService()
    plan = {
        "schemaVersion": 1,
        "mainline": "主线",
        "endingDirection": "终局",
        "longTermOpposition": "对立",
        "corePromises": ["承诺"],
        "estimatedVolumes": 3,
        "currentVolumeId": "volume-001",
        "volumes": [_volume(index) for index in range(1, 4)],
        "chapterAdjustments": [
            {
                "chapterId": chapter_id,
                "segmentId": "volume-001-segment-02",
                "goal": f"新目标 {chapter_id}",
                "hook": f"新钩子 {chapter_id}",
                "promiseProgression": f"新承诺 {chapter_id}",
                "logicDependencies": ["新依赖"],
            }
            for chapter_id in ["001", "004"]
        ],
    }
    ProjectService().write_text(
        project.root,
        "story/chapter-blueprint.json",
        json.dumps(
            {"schemaVersion": 2, "chapters": [_landing(index) for index in range(1, 31)]},
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/workbench-chapter-states.json",
        json.dumps(
            {"schemaVersion": 1, "chapters": {"001": "完成", "004": "待写"}}, ensure_ascii=False
        ),
    )
    ProjectService().write_text(
        project.root,
        service.replan_candidate_path,
        json.dumps(
            {"status": "candidate", "runId": "run-replan", "plan": plan}, ensure_ascii=False
        ),
    )
    before = {item["chapterId"]: item for item in service.chapter_landings(project.root)}

    service.apply_candidate(project.root, service.replan_candidate_path)
    after = {item["chapterId"]: item for item in service.chapter_landings(project.root)}

    assert after["001"]["goal"] == before["001"]["goal"]
    assert after["004"]["goal"] == "新目标 004"
    assert after["004"]["logicDependencies"] == ["新依赖"]


def test_volume_update_is_atomic_when_boundary_is_invalid(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "serial", title="原子更新")
    service = LongFormPlanService()
    plan = {
        "schemaVersion": 1,
        "mainline": "主线",
        "endingDirection": "终局",
        "longTermOpposition": "对立",
        "corePromises": ["承诺"],
        "estimatedVolumes": 3,
        "currentVolumeId": "volume-001",
        "volumes": [_volume(index) for index in range(1, 4)],
    }
    ProjectService().write_text(
        project.root, service.plan_path, json.dumps(plan, ensure_ascii=False)
    )

    try:
        service.update_volume(project.root, "volume-001", goal="不应保存", chapter_range="001-003")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid boundary must fail")

    saved = service.read_plan(project.root)
    assert saved["volumes"][0]["goal"] == "推进第 1 卷共同目标"
    assert saved["volumes"][0]["chapterRange"] == "001-010"
