from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.book_assets import BookAssetService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.knowledge_base import KnowledgeBaseService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.workbench_repository import WorkbenchRepository


def test_build_context_pack_selects_relevant_memory(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈通过山门测试并暴露禁忌纹路。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石显出禁忌纹路。",
            outcome="林澈通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            logicDependencies=["林澈是残缺灵根"],
            mustAvoid=["提前解释禁忌传承"],
            readerPromises=["禁忌传承谜题"],
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
                        "id": "event_001",
                        "order": 1,
                        "label": "林澈通过山门测试",
                        "chapterId": "001",
                    }
                ],
            },
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
                        "id": "promise_001",
                        "readerQuestion": "禁忌传承谜题",
                        "introducedAt": "chapter:001",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "001")

    sources = {item.source for item in context_pack.included}
    assert context_pack.path == "story/context-packs/001.json"
    assert "story/style-profile.json" in sources
    assert "story/chapter-briefs/001.json" in sources
    assert "memory/timeline-events.json" in sources
    assert "memory/promises.json" in sources
    assert context_pack.estimatedTokens > 0
    assert (project.root / "story/context-packs/001.json").exists()


def test_context_pack_includes_project_style_profile_override(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "story/style-profile.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "project-xuanhuan",
                "extends": "generic-web-serial",
                "platform": "custom-platform",
                "genres": ["玄幻"],
                "readerExpectations": ["升级承诺必须和个人代价绑定。"],
            },
            ensure_ascii=False,
        ),
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈通过山门测试并暴露禁忌纹路。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石显出禁忌纹路。",
            outcome="林澈通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            readerPromises=["禁忌传承谜题"],
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "001")

    style_item = next(
        item for item in context_pack.included if item.source == "story/style-profile.json"
    )
    assert style_item.data["id"] == "project-xuanhuan"
    assert style_item.data["platform"] == "custom-platform"
    assert style_item.data["genres"] == ["玄幻"]
    full_profile = StyleProfileService().read_project_profile(project.root)
    assert "适合连载" in full_profile.tone


def test_context_pack_diff_previews_without_overwriting_saved_pack(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈通过山门测试并暴露禁忌纹路。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石显出禁忌纹路。",
            outcome="林澈通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            readerPromises=["禁忌传承谜题"],
        ),
    )
    service = ContextPackService()
    saved = service.build_context_pack(project.root, "001")
    saved_text = (project.root / saved.path).read_text(encoding="utf-8")
    ProjectService().write_text(
        project.root,
        "memory/promises.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise_001",
                        "readerQuestion": "禁忌传承谜题",
                        "introducedAt": "chapter:001",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    diff = service.context_pack_diff(project.root, "001")

    assert diff["changed"] is True
    assert "memory/promises.json" in diff["addedSources"]
    assert (project.root / saved.path).read_text(encoding="utf-8") == saved_text


def test_build_context_pack_includes_relevant_writing_lessons(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="林澈在追查中保持情绪克制。",
            goal="林澈想确认长老封锁消息的原因。",
            conflict="长老阻挠。",
            turn="旧敌说出半句真相。",
            outcome="林澈确认有人隐瞒测试石异常。",
            hook="旧敌递来一枚碎裂玉牌。",
            emotionalBeat="林澈从压抑转为警惕。",
            readerPromises=["禁忌传承谜题"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_emotion_emotionalbeat",
                        "category": "emotion",
                        "lesson": "情绪节拍要用动作、对白、选择和余波落地。",
                        "severity": "high",
                        "status": "active",
                        "failureCount": 3,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "002")

    lesson_item = next(
        item for item in context_pack.included if item.source == "memory/writing-lessons.json"
    )
    assert lesson_item.data["lessons"][0]["id"] == "lesson_emotion_emotionalbeat"


def test_context_pack_includes_editorial_learned_lessons(tmp_path: Path) -> None:
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
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            internalNeed="林澈想证明自己不是任人踩踏的废物。",
            woundOrFear="林澈害怕再次被当众否定。",
            stakes="失败会失去机会。",
            cost="暴露异常潜力。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "lessons": [
                    {
                        "id": "lesson_emotion_emotion_told_not_felt",
                        "category": "emotion",
                        "lesson": (
                            "情绪不能只靠说明，要用动作、停顿、对白、身体反应和选择让读者感到。"
                        ),
                        "source": "drafts/001.generated.md#emotion_told_not_felt",
                        "evidence": ["drafts/001.generated.md"],
                        "appliesTo": ["emotion", "emotion_told_not_felt"],
                        "severity": "high",
                        "status": "active",
                        "failureCount": 2,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "001")
    lesson_item = next(
        item for item in context_pack.included if item.source == "memory/writing-lessons.json"
    )

    assert lesson_item.data["lessons"][0]["id"] == "lesson_emotion_emotion_told_not_felt"
    assert lesson_item.data["lessons"][0]["_contextPriority"]["reasons"]


def test_build_context_pack_prioritizes_payoff_and_partial_memory(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="006",
            focus="林澈追查禁忌纹路。",
            goal="林澈想找到禁忌纹路线索。",
            conflict="长老阻挠。",
            turn="线索出现。",
            outcome="林澈确认方向。",
            hook="旧敌发现异常。",
            emotionalBeat="疑惑 警惕",
            readerPromises=["禁忌传承谜题"],
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
                        "id": "promise_low",
                        "readerQuestion": "禁忌传承谜题",
                        "introducedAt": "chapter:002",
                        "expectedPayoffWindow": "chapter:009-012",
                        "status": "open",
                    },
                    {
                        "id": "promise_due",
                        "readerQuestion": "禁忌纹路的来历",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:006-008",
                        "status": "open",
                    },
                    {
                        "id": "promise_partial",
                        "readerQuestion": "林澈为何能激活测试石",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:004-006",
                        "status": "partial",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "006")

    promises_item = next(
        item for item in context_pack.included if item.source == "memory/promises.json"
    )
    assert isinstance(promises_item.data, dict)
    promises = promises_item.data["promises"]
    assert [promise["id"] for promise in promises] == [
        "promise_partial",
        "promise_due",
        "promise_low",
    ]
    assert "payoff_due_soon" in promises[0]["_contextPriority"]["reasons"]
    assert "partial" in promises[0]["_contextPriority"]["reasons"]
    assert "payoff_due_soon" in promises[1]["_contextPriority"]["reasons"]


def test_build_context_pack_includes_pressure_memory_without_keyword_match(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="010",
            focus="林澈准备进入内门。",
            goal="林澈稳住局势。",
            conflict="旧敌追查。",
            turn="局势升级。",
            outcome="林澈暂时脱身。",
            hook="新危机出现。",
            emotionalBeat="紧张 冷静",
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
                        "id": "loop_future",
                        "text": "遥远支线",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:020-030",
                        "status": "open",
                    },
                    {
                        "id": "loop_overdue",
                        "text": "失踪玉佩",
                        "introducedAt": "chapter:001",
                        "expectedPayoffWindow": "chapter:004-009",
                        "status": "open",
                    },
                    {
                        "id": "loop_partial",
                        "text": "旧日密信",
                        "introducedAt": "chapter:002",
                        "expectedPayoffWindow": "chapter:020-030",
                        "status": "partial",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "010")

    loops_item = next(
        item for item in context_pack.included if item.source == "memory/open-loops.json"
    )
    assert isinstance(loops_item.data, dict)
    loops = loops_item.data["loops"]
    assert [loop["id"] for loop in loops] == ["loop_overdue", "loop_partial"]
    assert "payoff_overdue" in loops[0]["_contextPriority"]["reasons"]
    assert "partial" in loops[1]["_contextPriority"]["reasons"]


def test_build_context_pack_prioritizes_importance_confidence_and_recency(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="006",
            focus="林澈准备复查山门测试。",
            goal="林澈想确认测试规则。",
            conflict="长老隐瞒记录。",
            turn="旧记录出现。",
            outcome="林澈找到疑点。",
            hook="旧敌也发现记录。",
            emotionalBeat="谨慎 怀疑",
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_keyword_low",
                        "text": "林澈准备复查山门测试记录曾被誊抄",
                        "importance": "low",
                        "confidence": 0.95,
                        "validFrom": "chapter:002",
                    },
                    {
                        "id": "fact_recent",
                        "text": "长老在上一章藏起一页记录",
                        "importance": "medium",
                        "confidence": 0.95,
                        "validFrom": "chapter:005",
                    },
                    {
                        "id": "fact_high_no_keyword",
                        "text": "林澈的身世真相仍不可提前揭开",
                        "importance": "high",
                        "confidence": 0.95,
                        "validFrom": "chapter:001",
                    },
                    {
                        "id": "fact_low_confidence",
                        "text": "测试规则可能被旧敌篡改",
                        "importance": "high",
                        "confidence": 0.3,
                        "validFrom": "chapter:005",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "006")

    facts_item = next(item for item in context_pack.included if item.source == "memory/facts.json")
    assert isinstance(facts_item.data, dict)
    facts = facts_item.data["facts"]
    assert [fact["id"] for fact in facts] == [
        "fact_recent",
        "fact_high_no_keyword",
        "fact_low_confidence",
        "fact_keyword_low",
    ]
    assert "recent_previous_chapter" in facts[0]["_contextPriority"]["reasons"]
    assert "importance_high" in facts[1]["_contextPriority"]["reasons"]
    assert "low_confidence" in facts[2]["_contextPriority"]["reasons"]
    assert "importance_low" in facts[3]["_contextPriority"]["reasons"]


def test_build_context_pack_trims_low_priority_memory_to_budget(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="006",
            focus="林澈复查测试规则。",
            goal="林澈想确认记录。",
            conflict="长老阻挠。",
            turn="记录出现。",
            outcome="林澈发现疑点。",
            hook="旧敌接近档案。",
            emotionalBeat="谨慎 怀疑",
        ),
    )
    facts = [
        {
            "id": "fact_critical",
            "text": "测试规则最高优先级记忆。" + "关键线索" * 20,
            "importance": "critical",
            "confidence": 0.95,
            "validFrom": "chapter:005",
        }
    ]
    facts.extend(
        {
            "id": f"fact_low_{index:02d}",
            "text": f"林澈复查测试规则低优先级背景 {index}。" + "旁支资料" * 60,
            "importance": "low",
            "confidence": 0.95,
            "validFrom": "chapter:001",
        }
        for index in range(12)
    )
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps({"schemaVersion": 1, "facts": facts}, ensure_ascii=False),
    )

    context_pack = ContextPackService().build_context_pack(
        project.root,
        "006",
        max_estimated_tokens=520,
    )

    assert context_pack.estimatedTokens <= 520
    assert context_pack.included[0].source == "story/chapter-briefs/006.json"
    facts_item = next(item for item in context_pack.included if item.source == "memory/facts.json")
    assert isinstance(facts_item.data, dict)
    kept_ids = [fact["id"] for fact in facts_item.data["facts"]]
    assert "fact_critical" in kept_ids
    assert len(kept_ids) < len(facts)
    excluded_facts = next(
        item for item in context_pack.excluded if item.source == "memory/facts.json"
    )
    assert "预算" in excluded_facts.reason
    assert excluded_facts.data["facts"]["droppedCount"] == len(facts) - len(kept_ids)
    assert "fact_critical" not in excluded_facts.data["facts"]["droppedIds"]
    assert excluded_facts.data["facts"]["droppedIds"]
    assert excluded_facts.data["facts"]["highestDroppedPriority"] > 0


def test_build_context_pack_includes_latest_emotional_baseline_for_pov(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            pov="林澈",
            focus="林澈进入内门。",
            goal="林澈想稳住局面。",
            conflict="长老暗中观察。",
            turn="内门令牌出现异常。",
            outcome="林澈被迫继续隐藏。",
            hook="令牌留下新的禁制痕迹。",
            emotionalBeat="林澈从警惕转为克制。",
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
                        "characterId": "lin-che",
                        "name": "林澈",
                        "beats": [
                            {
                                "chapterId": "001",
                                "emotionBefore": "疲惫",
                                "emotionAfter": "困惑",
                                "trigger": "钟声异常",
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
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {
                        "characterId": "lin-che",
                        "name": "林澈",
                        "states": [
                            {
                                "chapterId": "001",
                                "externalGoal": "通过山门测试",
                                "emotion": "困惑",
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
        "memory/relationship-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "relationships": [
                    {
                        "id": "rel_lin-che_old-enemy_respect",
                        "fromCharacterId": "lin-che",
                        "toCharacterId": "old-enemy",
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

    context_pack = ContextPackService().build_context_pack(project.root, "002")

    emotional_item = next(
        item for item in context_pack.included if item.source == "memory/emotional-arcs.json"
    )
    state_item = next(
        item for item in context_pack.included if item.source == "memory/character-states.json"
    )
    relationship_item = next(
        item for item in context_pack.included if item.source == "memory/relationship-states.json"
    )
    assert isinstance(emotional_item.data, dict)
    assert isinstance(state_item.data, dict)
    assert isinstance(relationship_item.data, dict)
    beat = emotional_item.data["characters"][0]["beats"][0]
    state = state_item.data["characters"][0]["states"][0]
    relationship = relationship_item.data["relationships"][0]
    assert "latest_emotional_baseline" in beat["_contextPriority"]["reasons"]
    assert "latest_character_state" in state["_contextPriority"]["reasons"]
    assert "latest_relationship_state" in relationship["_contextPriority"]["reasons"]


def test_context_pack_includes_relevant_character_assets(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="003",
            pov="lin-che",
            focus="林澈利用禁忌纹路反制旧敌。",
            goal="林澈想保住测试资格。",
            conflict="旧敌逼他公开纹路秘密。",
            turn="禁忌纹路短暂回应。",
            outcome="林澈暂时反制。",
            hook="长老认出纹路来源。",
            emotionalBeat="林澈从克制转为决断。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/character-assets.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "assets": [
                    {
                        "id": "asset_lin_che_forbidden_mark",
                        "characterId": "lin-che",
                        "kind": "secret_power",
                        "summary": "林澈的禁忌纹路会在被羞辱或逼入绝境时回应。",
                        "status": "active",
                        "importance": "high",
                        "evidence": ["chapters/001.md"],
                    },
                    {
                        "id": "asset_retired",
                        "characterId": "old-enemy",
                        "summary": "已废弃资源。",
                        "status": "retired",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "003")

    asset_item = next(
        item for item in context_pack.included if item.source == "memory/character-assets.json"
    )
    assert isinstance(asset_item.data, dict)
    assets = asset_item.data["assets"]
    assert [asset["id"] for asset in assets] == ["asset_lin_che_forbidden_mark"]
    assert "keyword_match" in assets[0]["_contextPriority"]["reasons"]


def test_context_pack_includes_relevant_knowledge_chunks(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="004",
            focus="林澈研究山门测试石异常。",
            goal="林澈想确认测试石为什么会响应禁忌纹路。",
            conflict="长老封锁测试石记录。",
            turn="旧记录提到测试石会记住灵力波纹。",
            outcome="林澈找到追查方向。",
            hook="测试石深处出现第二道波纹。",
            emotionalBeat="林澈从怀疑转为冷静。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "knowledge/sources/testing-stone.md",
        "# 测试石设定\n\n测试石会记录灵力波纹，并在禁忌纹路接近时产生二次响应。\n",
    )
    service = KnowledgeBaseService()

    context_pack = ContextPackService(knowledge_base=service).build_context_pack(
        project.root,
        "004",
    )

    knowledge_item = next(
        item for item in context_pack.included if item.source == "knowledge/index.json"
    )
    assert isinstance(knowledge_item.data, dict)
    result = knowledge_item.data["results"][0]
    assert result["source"] == "knowledge/sources/testing-stone.md"
    assert "测试石" in result["excerpt"]
    assert (project.root / "knowledge" / "index.json").exists()
    assert list((project.root / "knowledge" / "chunks").glob("*.json"))


def test_context_pack_reasons_show_materials_participate_in_writing_loop(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="005",
            pov="lin-che",
            focus="林澈用测试石异常反制旧敌。",
            goal="林澈想保住测试资格。",
            conflict="旧敌逼他暴露禁忌纹路。",
            turn="测试石再次发烫。",
            outcome="林澈暂时反制。",
            hook="长老发现第二道波纹。",
            emotionalBeat="林澈从压抑转为决断。",
            readerPromises=["禁忌纹路谜题"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/character-assets.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "assets": [
                    {
                        "id": "asset_lin_che_mark",
                        "characterId": "lin-che",
                        "kind": "secret_power",
                        "summary": "林澈的禁忌纹路会在测试石前回应。",
                        "status": "active",
                        "importance": "high",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "knowledge/sources/testing-stone.md",
        "# 测试石设定\n\n测试石会在禁忌纹路靠近时发烫，并留下第二道波纹。\n",
    )

    context_pack = ContextPackService().build_context_pack(project.root, "005")
    reasons_by_source = {item.source: item.reason for item in context_pack.included}

    assert "memory/character-assets.json" in reasons_by_source
    assert "角色资源账本" in reasons_by_source["memory/character-assets.json"]
    assert "knowledge/index.json" in reasons_by_source
    assert "参考片段" in reasons_by_source["knowledge/index.json"]


def test_context_pack_excludes_empty_character_assets_and_knowledge(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="林澈通过山门测试。",
            goal="林澈想进入内门。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从紧张转为警惕。",
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "001")

    included_sources = {item.source for item in context_pack.included}
    excluded_sources = {item.source for item in context_pack.excluded}
    assert "memory/character-assets.json" not in included_sources
    assert "knowledge/index.json" not in included_sources
    assert "memory/character-assets.json" in excluded_sources
    assert "knowledge/index.json" in excluded_sources


def test_context_pack_includes_previous_chapter_ending_as_strong_context(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="林澈承接上一章玉牌危机。",
            goal="林澈想查清玉牌来源。",
            conflict="长老封锁消息。",
            turn="玉牌再次发烫。",
            outcome="林澈拿到新线索。",
            hook="名单上出现他的名字。",
            emotionalBeat="林澈从警惕转为决断。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n林澈推开门。\n\n门外有人递来裂开的玉牌。\n\n玉牌背面刻着他的名字。",
    )

    context_pack = ContextPackService().build_context_pack(project.root, "002")
    ending_item = next(
        item for item in context_pack.included if item.source == "chapters/001.md#ending"
    )

    assert "上一章结尾2段" in ending_item.reason
    assert "玉牌背面刻着他的名字" in ending_item.data["endingText"]


def test_context_pack_contract_includes_incoming_emotional_context(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            focus="林澈承接上一章师徒冲突。",
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

    context_pack = ContextPackService().build_context_pack(project.root, "002")
    contract_item = next(
        item for item in context_pack.included if item.source == "story/chapter-briefs/002.json"
    )

    assert contract_item.data["emotionalContext"] == {
        "characterId": "林澈",
        "incomingEmotion": "林澈愤怒且不信任师父。",
        "incomingSource": "chapter:001",
        "transitionRequired": True,
    }


def test_context_pack_contract_includes_matching_arc_context(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="015",
            focus="林澈在宗门大比初战失利。",
            goal="林澈想确认自己的短板。",
            conflict="强敌逼出他的弱点。",
            turn="旧招式失效。",
            outcome="林澈初战失利。",
            hook="对手认出禁忌纹路。",
            emotionalBeat="林澈从自信转为警惕。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "story/arc-contracts/arc_001.json",
        json.dumps(
            {
                "arcId": "arc_001",
                "title": "宗门大比篇",
                "chapterRange": "010-025",
                "arcGoal": "主角赢得宗门大比，证明实力",
                "antagonist": "血影宗天才",
                "emotionalArc": "从自卑到自信",
                "keyMilestones": [
                    {"chapterId": "015", "milestone": "初战失利，暴露弱点"},
                    {"chapterId": "020", "milestone": "顿悟新招式"},
                ],
                "status": "in_progress",
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "015")
    contract_item = next(
        item for item in context_pack.included if item.source == "story/chapter-briefs/015.json"
    )

    assert contract_item.data["arcContext"]["arcId"] == "arc_001"
    assert contract_item.data["arcContext"]["progress"] == 38
    assert (
        contract_item.data["arcContext"]["currentMilestones"][0]["milestone"]
        == "初战失利，暴露弱点"
    )
    assert contract_item.data["arcContext"]["upcomingMilestones"][0]["chapterId"] == "020"


def test_context_pack_semantic_recall_matches_synonym_topic(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="003",
            focus="林澈怀疑师父背叛。",
            goal="林澈想查清师父为何隐瞒。",
            conflict="师父回避问题。",
            turn="旧信物出现。",
            outcome="林澈确认师父说谎。",
            hook="师门旧账浮出水面。",
            emotionalBeat="林澈从信任转为怀疑。",
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/long-term-memory.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "topics": [
                    {
                        "id": "topic_shizun",
                        "summary": "师尊曾出卖旧盟友，留下旧信物。",
                        "sourceChapters": ["001"],
                    }
                ],
                "entityIndex": [],
                "writingGuidance": [],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "003")
    memory_item = next(
        item for item in context_pack.included if item.source == "memory/long-term-memory.json"
    )

    assert memory_item.data["topics"][0]["id"] == "topic_shizun"
    assert "semantic_keyword_match" in memory_item.data["topics"][0]["_contextPriority"]["reasons"]


def test_context_pack_includes_confirmed_world_and_character_assets(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="004",
            pov="林澈",
            focus="林澈穿过无潮港寻找姐姐留下的信标。",
            goal="确认信标来源。",
            conflict="无潮港规则限制潜水设备。",
            turn="旧信标突然发出回应。",
            outcome="林澈确认姐姐来过这里。",
            hook="港底出现第二束信号。",
            emotionalBeat="林澈从怀疑转为克制的希望。",
        ),
    )
    repository = WorkbenchRepository(tmp_path / "workbench.sqlite3")
    repository.upsert_material(
        project.root,
        {
            "id": "world-no-tide-port",
            "type": "设定",
            "title": "无潮港潜水规则",
            "summary": "无潮港禁止启动明火推进器。",
            "influence": "潜水员只能使用冷推进设备。",
            "related": ["世界设定确认记录", "第 004 章"],
            "confidence": 96,
            "details": {"规则": "禁止：启动明火推进器", "例外": "无"},
        },
    )
    repository.upsert_material(
        project.root,
        {
            "id": "character-lin-che",
            "type": "人物",
            "title": "林澈",
            "summary": "维修潜水员，正在寻找姐姐。",
            "related": ["人物确认记录"],
            "confidence": 90,
        },
    )
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {"characterId": "character-lin-che", "chapterId": "003", "state": "受伤"}
                ],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService(book_assets=BookAssetService(repository)).build_context_pack(
        project.root, "004"
    )

    item = next(
        item for item in context_pack.included if item.source == BookAssetService.context_source
    )
    assert isinstance(item.data, dict)
    assert len(item.data["worldAssets"]) == 1
    assert item.data["worldAssets"][0]["hardRules"][0]["forbidden"] == "启动明火推进器"
    assert item.data["characterRoster"][0]["currentStates"][0]["state"] == "受伤"
    assert item.data["worldAssets"][0]["evidence"] == ["世界设定确认记录", "第 004 章"]


def test_knowledge_index_deduplicates_and_explains_scoped_recall(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    content = "# 港区记录\n\nchapter:004\n人物：林澈\n时间：雨夜\n旧信标会在退潮后回应。\n"
    ProjectService().write_text(project.root, "knowledge/sources/a.md", content)
    ProjectService().write_text(project.root, "knowledge/sources/b.md", content)
    service = KnowledgeBaseService()

    index = service.rebuild_index(project.root)
    results = service.search(
        project.root,
        {"信标"},
        chapter_id="004",
        character_id="林澈",
        time_scope="雨夜",
    )
    context = service.context_data(project.root, {"信标"})

    assert len(index.chunks) == 1
    assert results[0].matchedTerms == ["信标"]
    assert "章节范围匹配：004" in results[0].matchReasons
    assert "人物范围匹配：林澈" in results[0].matchReasons
    assert context["results"][0]["enteredContext"] is True
    assert context["results"][0]["matchReasons"]
