from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_quality import WritingQualityService


def write_contract(root: Path) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
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
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )


def test_writing_quality_flags_flat_draft(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n这里介绍山门规则。据说规则很多。事实上规则是这样的。原来还有设定。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "too_short" in issue_types
    assert "weak_emotional_grounding" in issue_types
    assert "weak_ending_hook" in issue_types
    assert (project.root / "runs" / "writing-quality-001.json").exists()


def test_writing_quality_rewards_tomato_style_draft(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "测试石前，林澈握紧指尖，胸口那口压抑的气几乎要炸开。\n\n"
        "旧敌冷笑着拦在前方：“你这种残缺灵根，也配站上去？”\n\n"
        "林澈没有退。他选择踏上石阶，咬牙把掌心按在测试石上。\n\n"
        "下一刻，测试石忽然异动，暗纹从石心亮起，所有嘲笑都被压了下去。\n\n"
        "执事想把异动压成意外，旧敌却先一步变了脸色。谁都看得出，这不是残缺灵根该有的反应。\n\n"
        "林澈压住发抖的手，没有解释，也没有求饶。他只盯着测试石，选择把最后一缕灵力推入暗纹。\n\n"
        "石面轰然亮起，废柴逆袭的第一声惊呼在人群里炸开。那些嘲笑他的人，被光刺得下意识后退。\n\n"
        "长老脸色变了，立刻抬手封锁消息。林澈通过但被长老盯上，旧敌开始忌惮。\n\n"
        "旧敌咬牙想再拦，长老的目光却先压了过去。林澈这才明白，自己证明了异常潜力，也把危险引到了身上。\n\n"
        "如果失败，林澈会失去进入宗门和追查测试石异常的机会。可他嘴上冷静，实际是在保护最后一点尊严。\n\n"
        "林澈从压抑转为警惕。他刚要追问，门外却有人送来一枚裂开的玉牌。读者应感到爽快，同时意识到更大危险来了。\n\n",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert report.score >= 70
    assert "weak_ending_hook" not in {issue.type for issue in report.issues}


def test_writing_quality_flags_missing_human_core(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "测试石前，林澈握紧指尖，胸口压抑。\n\n"
        "旧敌冷笑着拦他：“你也配？”\n\n"
        "林澈选择踏上石阶，咬牙把掌心按在测试石上。\n\n"
        "下一刻，测试石忽然异动，废柴逆袭的惊呼炸开。\n\n"
        "林澈通过测试，旧敌开始忌惮。\n\n"
        "林澈从压抑转为警惕。门外忽然送来一枚玉牌。\n\n",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "missing_stakes" in issue_types
    assert "missing_cost" in issue_types


def test_writing_quality_counts_marker_frequency_and_distinct_markers(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈选择踏前，选择咬牙，选择把测试石推到所有人面前。门外忽然传来一道声音。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert report.metrics["choiceMarkers"] >= 3
    assert report.metrics["choiceMarkersDistinct"] < report.metrics["choiceMarkers"]


def test_writing_quality_flags_emotional_discontinuity_from_previous_beat(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="林澈和师父讨论修炼。",
            goal="林澈想查清师父隐瞒的线索。",
            conflict="师父回避关键问题。",
            turn="旧信物再次出现。",
            outcome="林澈发现师父仍在隐瞒。",
            hook="门外忽然传来一道声音。",
            emotionalBeat="林澈从愤怒转为克制。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/emotional-arcs.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {
                        "characterId": "林澈",
                        "beats": [
                            {
                                "chapterId": "001",
                                "beat": "林澈愤怒且不信任师父。",
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
        "# 第二章\n\n林澈坐在石桌前，平静地听师父讲解修炼口诀。\n\n门外忽然传来一道声音。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "002")

    assert "emotional_discontinuity" in {issue.type for issue in report.issues}


def test_writing_quality_flags_character_name_inconsistency(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [{"characterId": "lin-che", "name": "林澈", "states": []}],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林彻说道，测试石忽然变了。门外忽然传来一道声音。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert "character_name_inconsistency" in {issue.type for issue in report.issues}


def test_writing_quality_reports_multiple_suspicious_character_names(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {"characterId": "lin-che", "name": "林澈", "states": []},
                    {"characterId": "li-wei", "name": "李薇", "states": []},
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林彻说道，测试石忽然变了。李微问他是否还要继续。门外忽然传来一道声音。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    issues = [issue for issue in report.issues if issue.type == "character_name_inconsistency"]
    assert len(issues) == 2
    assert any("林彻" in issue.message for issue in issues)
    assert any("李微" in issue.message for issue in issues)


def test_writing_quality_name_candidates_ignore_common_non_names(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [{"characterId": "lin-che", "name": "林澈", "states": []}],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n今天的测试忽然变了。这个问题应该继续追查。门外忽然传来一道声音。",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert "character_name_inconsistency" not in {issue.type for issue in report.issues}


def test_writing_quality_handles_empty_and_very_long_text(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "# 第一章\n\n")

    empty_report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert "too_short" in {issue.type for issue in empty_report.issues}

    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n" + "林澈选择继续追查，旧敌拦住去路，门外忽然传来一道声音。\n" * 700,
    )

    long_report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert "word_count_out_of_range" in {issue.type for issue in long_report.issues}


def test_writing_quality_flags_dialogue_ratio_scene_switches_and_ai_trace(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        + "“你还要继续？”旧敌问。\n\n"
        + "“继续。”林澈说。\n\n"
        + "“代价呢？”\n\n"
        + "“我自己承担。”\n\n"
        + "“长老不会同意。”\n\n"
        + "“那就让他来拦。”\n\n"
        + ("“我不会退。”\n\n" * 80)
        + "林澈握住测试石，旧敌的阻拦让人群压低了呼吸。\n\n"
        + "他选择继续，咬牙把最后一点灵力推向暗纹。\n\n"
        + "石阶忽然震动，长老抬手压住所有议论。\n\n"
        + "代价已经出现，他的异常被更多人看见。\n\n"
        "与此同时，山门另一边传来异响。\n\n"
        "另一边，执事回到石阶前。\n\n"
        "同一时间，镜头一转，画面一转，几分钟后又转到旧敌身后。\n\n"
        "这让他意识到命运的齿轮已经转动，内心深处涌起一种复杂的情绪。\n\n",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "dialogue_ratio_out_of_range" in issue_types
    assert "scene_switch_too_frequent" in issue_types
    assert "anti_ai_trace" in issue_types
    assert report.metrics["dialogueRatio"] > 0.6
    assert report.metrics["sceneSwitches"] > 5
    assert report.metrics["antiAiMarkers"] >= 2


def test_writing_quality_detects_extended_ending_pull_patterns(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "林澈握紧测试石，压下胸口的不安。\n\n"
        "旧敌拦住去路，他选择踏前逼问真相。\n\n"
        "长老沉默片刻，递来一封血书。\n\n",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "001")

    assert "weak_ending_hook" not in {issue.type for issue in report.issues}


def test_writing_quality_blocks_repeated_adjacent_chapter(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            title="第二章",
            focus="林澈继续追查测试石异常。",
            goal="林澈想确认第二条线索的来源。",
            conflict="旧敌和长老继续阻挠。",
            turn="测试石留下新的异常痕迹。",
            outcome="林澈暂时脱身但被更深势力盯上。",
            hook="裂纹玉牌指向新的禁地。",
            emotionalBeat="林澈从压抑转为警惕。",
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            internalNeed="林澈想证明自己不是任人踩踏的废物。",
            woundOrFear="林澈害怕再次被当众否定。",
            stakes="如果失败，林澈会失去继续追查测试石异常的机会。",
            cost="林澈证明潜力的同时暴露异常，被更深势力盯上。",
            subtext="林澈嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )
    repeated_body = (
        "测试石前，林澈握紧指尖，胸口那口压抑的气几乎要炸开。"
        "旧敌冷笑着拦在前方，林澈选择踏上石阶。下一刻，测试石忽然异动。"
        "林澈通过测试，旧敌开始忌惮。如果失败，林澈会失去继续追查测试石异常的机会。"
        "林澈证明潜力的同时暴露异常，被更深势力盯上。裂纹玉牌指向新的禁地。"
    )
    ProjectService().write_text(project.root, "chapters/001.md", f"# 第一章\n\n{repeated_body}")
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        f"# 第二章\n\n{repeated_body}",
    )

    report = WritingQualityService().evaluate_chapter(project.root, "002")

    issue = next(item for item in report.issues if item.type == "too_similar_to_previous")
    assert issue.severity == "blocker"
    assert report.metrics["previousSimilarity"] >= 0.86
    assert report.metrics["previousJaccardSimilarity"] >= 0.86
    assert report.metrics["previousParagraphSimilarity"] >= 0.86


def test_five_chapter_local_dry_run_quality_evaluation_passes_baseline(
    tmp_path: Path,
) -> None:
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
    service = StoryGuidanceService()
    for index in range(1, 6):
        chapter_id = f"{index:03d}"
        service.write_scene_contract(
            project.root,
            SceneContract(
                chapterId=chapter_id,
                title=f"第{index}章",
                focus=f"林澈推进第{index}个测试危机。",
                goal="林澈想稳住局势并继续追查测试石异常。",
                conflict="旧敌和长老同时施压。",
                turn="测试石留下新的异常痕迹。",
                outcome="林澈暂时脱身但被更深势力盯上。",
                hook="裂纹玉牌指向新的禁地。",
                emotionalBeat="林澈从压抑转为警惕。",
                relationshipBeat="旧敌从轻蔑转为忌惮。",
                internalNeed="林澈想证明自己不是任人踩踏的废物。",
                woundOrFear="林澈害怕再次被当众否定。",
                stakes="如果失败，林澈会失去继续追查测试石异常的机会。",
                cost="林澈证明潜力的同时暴露异常，被更深势力盯上。",
                subtext="林澈嘴上冷静，实际是在保护最后一点尊严。",
                aftertaste="读者应感到爽快，同时意识到更大危险来了。",
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
                variables={"chapterId": chapter_id, "chapterTitle": f"第{index}章"},
                runId=f"run_quality_{chapter_id}",
            )
        )

    reports = [
        WritingQualityService().evaluate_chapter(project.root, f"{index:03d}")
        for index in range(1, 6)
    ]

    assert len(reports) == 5
    assert all(
        (project.root / "runs" / f"writing-quality-{index:03d}.json").exists()
        for index in range(1, 6)
    )
    assert min(report.score for report in reports) >= 70

    sequence = ChapterSequenceEvaluationService().evaluate(project.root, "001", "005")

    assert sequence.status == "pass"
    assert sequence.minQualityScore == 100
    assert sequence.minGateScore == 100
    assert len(sequence.chapters) == 5
    assert (project.root / "runs" / "sequence-evaluation-001-005.json").exists()
