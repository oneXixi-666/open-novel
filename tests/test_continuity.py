from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.continuity import ContinuityService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def test_continuity_checker_flags_missing_required_and_forbidden_text(tmp_path: Path) -> None:
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
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(project.root, "drafts/001.generated.md", "这里提前揭秘。")

    report = ContinuityService().check_draft(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "missing_must_include" in issue_types
    assert "violated_must_avoid" in issue_types
    assert "outcome_drift" in issue_types
    assert "hook_drift" in issue_types
    assert "emotional_discontinuity" in issue_types
    assert "relationship_discontinuity" in issue_types
    assert "reader_promise_drift" in issue_types
    assert "ungrounded_logic_dependency" in issue_types
    assert report.score < 100
    assert (project.root / "runs" / "continuity-001.json").exists()


def test_continuity_checker_accepts_semantically_supported_required_content(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="维修员进入旧井恢复信标。",
            goal="在涨潮前恢复通信。",
            conflict="封锁规定和坍塌风险阻止下潜。",
            turn="失踪亲人的声音通过信标响起。",
            outcome="信标恢复并确认声音来自实时现场。",
            hook="低地排水系统即将倒灌。",
            mustInclude=[
                "以退潮倒计时建立明确行动窗口，并让潮水回升持续改变下潜和撤离条件。"
            ],
            mustAvoid=["提前揭示最终真相"],
            readerPromises=["潮汐抢险"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        (
            "退潮警戒屏用倒计时标出仅剩五十分钟的行动窗口。"
            "随着潮水持续回升，维修员的下潜条件不断恶化，撤离时间也被压缩。"
            "他在井口被淹前恢复了通信。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "001")

    assert "missing_must_include" not in {issue.type for issue in report.issues}


def test_continuity_checker_uses_memory_for_cross_chapter_logic(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="测试石异动",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/timeline-events.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "events": [
                    {
                        "id": "event_002_truth",
                        "order": 2,
                        "label": "第二章真相揭开",
                        "chapterId": "002",
                        "summary": "第二章真相揭开",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "测试石异动。主角压抑后变得警惕。第二章真相揭开。",
    )

    report = ContinuityService().check_draft(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "ungrounded_logic_dependency" in issue_types
    assert "timeline_order_conflict" in issue_types


def test_continuity_checker_does_not_infer_future_event_from_shared_vocabulary(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="005",
            focus="抢救潮位传感器。",
            goal="取得低地实测数据。",
            conflict="仓储层持续进水。",
            turn="众人放弃导航备件。",
            outcome="十二枚传感器获救。",
            hook="官方潮峰预报偏低。",
            mustInclude=["传感器"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/timeline-events.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "events": [
                    {
                        "id": "event_006_outcome",
                        "chapterId": "006",
                        "label": "实时潮位网开始运行",
                        "summary": (
                            "实时潮位网开始运行，证明两小时后的潮峰将同时威胁"
                            "低地社区与新城东堤，单向泄洪已经无法保住任何一方。"
                        ),
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/005.generated.md",
        (
            "沈砚与顾岑从仓储层救出潮位传感器。"
            "低地社区与新城都需要实测数据，但实时潮位网尚未开始运行，"
            "现在不能证明两小时后的潮峰会威胁哪里。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "005")

    assert "timeline_order_conflict" not in {issue.type for issue in report.issues}


def test_continuity_checker_accepts_supported_logic_dependency(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="主角复测灵根",
            goal="主角证明自己。",
            conflict="长老怀疑。",
            turn="测试石再次异动。",
            outcome="主角获得入门资格。",
            hook="长老开始调查。",
            emotionalBeat="紧张 坚定",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
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
                        "id": "fact_001_spirit_root",
                        "text": "主角曾被视为残缺灵根",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        "测试石再次异动。主角从紧张变得坚定。",
    )

    report = ContinuityService().check_draft(project.root, "002")

    assert "ungrounded_logic_dependency" not in {issue.type for issue in report.issues}


def test_continuity_checker_tracks_reader_promise_progress(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="测试石异动",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过。",
            hook="长老封锁消息。",
            emotionalBeat="压抑 警惕",
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "测试石异动。主角从压抑变得警惕。废柴逆袭的期待被建立。",
    )

    report = ContinuityService().check_draft(project.root, "001")

    assert "reader_promise_drift" not in {issue.type for issue in report.issues}


def test_continuity_checker_accepts_rewritten_focus_and_emotional_beat(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈从被轻视到暴露异常潜力的第一步反转",
            goal="林澈想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过测试。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑忍耐转为震惊和警惕",
            relationshipBeat="旧敌从轻蔑转为忌惮",
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        (
            "测试石忽然亮起。众人一直轻视林澈，可异常潜力在山门前暴露，"
            "这一场成了他的第一步反转。林澈压抑地忍着，随后震惊，又立刻警惕。"
            "林澈通过测试。长老封锁消息。旧敌从轻蔑转为忌惮。废柴逆袭的期待被建立。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "focus_drift" not in issue_types
    assert "outcome_drift" not in issue_types
    assert "hook_drift" not in issue_types
    assert "emotional_discontinuity" not in issue_types
    assert "relationship_discontinuity" not in issue_types


def test_continuity_checker_flags_payoff_window_pressure(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="006",
            focus="主角继续调查禁忌纹路",
            goal="主角寻找线索。",
            conflict="长老阻挠。",
            turn="线索被藏起。",
            outcome="主角发现新疑点。",
            hook="长老再次封锁消息。",
            emotionalBeat="疑惑 警惕",
            mustInclude=["线索"],
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
                        "id": "promise_001",
                        "readerQuestion": "禁忌纹路的来历",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:006-008",
                        "status": "open",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/006.generated.md",
        "线索被长老藏起。主角从疑惑变得警惕。",
    )

    report = ContinuityService().check_draft(project.root, "006")

    issue = next(issue for issue in report.issues if issue.type == "payoff_due_soon")
    assert issue.severity == "medium"
    assert "promise_001" in issue.evidence[1]


def test_continuity_checker_flags_overdue_payoff(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="010",
            focus="主角进入内门",
            goal="主角稳住局势。",
            conflict="旧敌追查。",
            turn="局势升级。",
            outcome="主角暂时脱身。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["局势"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/open-loops.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "loops": [
                    {
                        "id": "loop_001",
                        "text": "长老封锁消息",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:004-009",
                        "status": "open",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/010.generated.md",
        "局势升级。主角从紧张变得冷静。",
    )

    report = ContinuityService().check_draft(project.root, "010")

    issue = next(issue for issue in report.issues if issue.type == "payoff_overdue")
    assert issue.severity == "high"
    assert "loop_001" in issue.evidence[1]


def test_continuity_checker_ignores_touched_payoff_item(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="006",
            focus="主角继续调查禁忌纹路",
            goal="主角寻找线索。",
            conflict="长老阻挠。",
            turn="线索出现。",
            outcome="主角确认禁忌纹路另有来历。",
            hook="新疑点出现。",
            emotionalBeat="疑惑 警惕",
            mustInclude=["线索"],
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
                        "id": "promise_001",
                        "readerQuestion": "禁忌纹路的来历",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:006-008",
                        "status": "open",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/006.generated.md",
        "线索出现。主角从疑惑变得警惕，并开始追查禁忌纹路的来历。",
    )

    report = ContinuityService().check_draft(project.root, "006")

    issue_types = {issue.type for issue in report.issues}
    assert "payoff_due_soon" not in issue_types
    assert "payoff_overdue" not in issue_types


def test_continuity_checker_flags_latest_character_state_contradiction(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            pov="林澈",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断长老的真实意图。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时接受长老安排。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "characterId": "林澈",
                        "states": [
                            {
                                "chapterId": "001",
                                "emotion": "林澈开始信任长老。",
                                "relationshipChanges": ["林澈开始信任长老。"],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时接受长老安排。旧敌发现异常。主角从紧张变得冷静。"
            "林澈从未信任长老。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "002")

    issue = next(
        issue for issue in report.issues if issue.type == "character_state_contradiction"
    )
    assert issue.severity == "high"
    assert "林澈:001" in issue.evidence[1]


def test_continuity_checker_allows_explicit_character_state_transition(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            pov="林澈",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断长老的真实意图。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时接受长老安排。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "characterId": "林澈",
                        "states": [
                            {
                                "chapterId": "001",
                                "emotion": "林澈开始信任长老。",
                                "relationshipChanges": ["林澈开始信任长老。"],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时接受长老安排。旧敌发现异常。主角从紧张变得冷静。"
            "林澈过去从未信任长老，转为开始信任长老。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "002")

    issue_types = {issue.type for issue in report.issues}
    assert "character_state_contradiction" not in issue_types


def test_continuity_checker_uses_explicit_character_state_anchor(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            pov="林澈",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断长老的真实意图。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时接受长老安排。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "characterId": "林澈",
                        "states": [
                            {
                                "chapterId": "001",
                                "emotion": "林澈愿意承认和长老之间的暂时羁绊。",
                                "continuityAnchors": [
                                    {
                                        "claim": "暂时羁绊",
                                        "forbiddenDraftPatterns": ["否认羁绊"],
                                        "allowedTransitionMarkers": ["转为", "变成"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时接受长老安排。旧敌发现异常。主角从紧张变得冷静。"
            "林澈否认羁绊。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "002")

    issue = next(
        issue for issue in report.issues if issue.type == "character_state_contradiction"
    )
    assert "暂时羁绊" in issue.message
    assert "否认羁绊" in issue.message


def test_continuity_checker_flags_relationship_state_contradiction(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断旧敌的试探。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时稳住局面。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "id": "rel_linche_enemy_respect",
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "respect",
                        "status": "旧敌开始忌惮林澈。",
                        "pressure": "旧敌阻挠。",
                        "unresolvedEmotion": "林澈仍在保护尊严。",
                        "chapterId": "001",
                        "source": "chapters/001.md",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时稳住局面。旧敌发现异常。主角从紧张变得冷静。"
            "旧敌仍旧轻蔑，完全没有把林澈放在眼里。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "002")

    issue = next(
        issue for issue in report.issues if issue.type == "relationship_state_contradiction"
    )
    assert issue.severity == "high"
    assert "rel_linche_enemy_respect" in issue.evidence[1]
    assert "忌惮" in issue.message


def test_continuity_checker_allows_explicit_relationship_transition(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断旧敌的试探。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时稳住局面。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "id": "rel_linche_enemy_respect",
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "respect",
                        "status": "旧敌开始忌惮林澈。",
                        "chapterId": "001",
                        "source": "chapters/001.md",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时稳住局面。旧敌发现异常。主角从紧张变得冷静。"
            "旧敌从忌惮转为仍旧轻蔑。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "002")

    issue_types = {issue.type for issue in report.issues}
    assert "relationship_state_contradiction" not in issue_types


def test_continuity_checker_flags_unreviewed_relationship_transition(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="003",
            focus="主角进入内门后稳住局势。",
            goal="主角想判断旧敌的试探。",
            conflict="旧敌继续试探。",
            turn="长老给出新线索。",
            outcome="主角暂时稳住局面。",
            hook="旧敌发现异常。",
            emotionalBeat="紧张 冷静",
            mustInclude=["新线索"],
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
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "rivalry",
                        "status": "旧敌轻蔑林澈。",
                        "pressure": "公开羞辱",
                        "chapterId": "001",
                    },
                    {
                        "id": "rel_002",
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "rivalry",
                        "status": "旧敌秘密保护林澈。",
                        "pressure": "敌对压力突然缓和",
                        "chapterId": "002",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/003.generated.md",
        (
            "新线索出现。主角进入内门后稳住局势。长老给出新线索。"
            "主角暂时稳住局面。旧敌发现异常。主角从紧张变得冷静。"
        ),
    )

    report = ContinuityService().check_draft(project.root, "003")

    issue = next(
        issue for issue in report.issues if issue.type == "relationship_transition_needs_review"
    )
    assert issue.severity == "medium"
    assert "rel_002" in issue.evidence[1]
    assert "未审跳变" in issue.message
