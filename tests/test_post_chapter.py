from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import SceneContract
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def write_contract(root: Path) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            pov="主角",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            internalNeed="主角想证明自己不是任人踩踏的废物。",
            woundOrFear="主角害怕再次被当众否定。",
            stakes="如果失败，主角会失去进入宗门的机会。",
            cost="主角证明潜力的同时暴露异常，被长老盯上。",
            subtext="主角嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )


def test_post_chapter_review_patch_and_apply_updates_memory(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")

    service = PostChapterService()
    review = service.build_review(project.root, "001")
    patch = service.propose_canon_patch(project.root, "001")

    assert review.summary == "主角通过测试。"
    assert {item.kind for item in review.items} >= {"summary", "fact", "open_loop"}
    assert patch.sourceReview == "reviews/001.review.json"
    assert (project.root / "patches" / "001.canon-patch.json").exists()
    fact_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_fact_outcome"
    )
    timeline_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_timeline_outcome"
    )
    state_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_character_state"
    )
    promise_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_promise_01"
    )
    assert fact_operation.action == "defer"
    assert timeline_operation.action == "defer"
    assert state_operation.action == "defer"
    assert promise_operation.action == "defer"

    summary_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_summary"
    )
    assert summary_operation.status == "accepted"

    unapplied = service.apply_canon_patch(project.root, "001")

    assert next(
        operation for operation in unapplied.operations if operation.id == "op_review_001_summary"
    ).status == "applied"
    assert all(
        operation.status == "proposed"
        for operation in unapplied.operations
        if operation.id != "op_review_001_summary"
    )
    assert "fact_001_outcome" not in (project.root / "memory" / "facts.json").read_text(
        encoding="utf-8"
    )
    assert "event_001_outcome" not in (
        project.root / "memory" / "timeline-events.json"
    ).read_text(encoding="utf-8")
    character_state_memory = json.loads(
        (project.root / "memory" / "character-states.json").read_text(encoding="utf-8")
    )
    assert character_state_memory["characters"] == []

    service.accept_canon_patch(project.root, "001")
    applied = service.apply_canon_patch(project.root, "001")
    service.apply_canon_patch(project.root, "001")

    assert any(operation.status == "applied" for operation in applied.operations)
    fact_operation = next(
        operation
        for operation in applied.operations
        if operation.id == "op_review_001_fact_outcome"
    )
    assert fact_operation.status == "proposed"
    assert "主角通过测试。" in (project.root / "memory" / "chapter-summaries.json").read_text(
        encoding="utf-8"
    )
    assert "fact_001_outcome" not in (project.root / "memory" / "facts.json").read_text(
        encoding="utf-8"
    )
    assert "主角从压抑转为警惕" not in (
        project.root / "memory" / "character-states.json"
    ).read_text(encoding="utf-8")
    assert "废柴逆袭" not in (project.root / "memory" / "promises.json").read_text(
        encoding="utf-8"
    )


def test_post_chapter_review_learns_bounded_writing_lessons(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")

    service = PostChapterService()
    service.build_review(project.root, "001")
    service.build_review(project.root, "001")

    memory = json.loads(
        (project.root / "memory" / "writing-lessons.json").read_text(encoding="utf-8")
    )

    lessons = memory["lessons"]
    lesson_ids = {lesson["id"] for lesson in lessons}
    assert "lesson_emotion_emotionalbeat" in lesson_ids
    assert len(lesson_ids) == len(lessons)
    emotional_lesson = next(
        lesson for lesson in lessons if lesson["id"] == "lesson_emotion_emotionalbeat"
    )
    assert emotional_lesson["failureCount"] == 2
    assert "情绪节拍" in emotional_lesson["lesson"]


def test_post_chapter_patch_applies_supported_contract_claim(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角通过但被长老盯上。长老封锁消息。主角从压抑转为警惕。废柴逆袭。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    fact_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_fact_outcome"
    )
    timeline_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_timeline_outcome"
    )
    state_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_character_state"
    )
    promise_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_promise_01"
    )
    open_loop_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_open_loop_hook"
    )

    assert fact_operation.action == "add"
    assert timeline_operation.action == "add"
    assert state_operation.action == "add"
    assert promise_operation.action == "add"
    assert open_loop_operation.payload["expectedPayoffWindow"] == "chapter:004-009"
    assert promise_operation.payload["expectedPayoffWindow"] == "chapter:004-009"

    service.accept_canon_patch(
        project.root,
        "001",
        operation_ids=[
            fact_operation.id,
            timeline_operation.id,
            state_operation.id,
            promise_operation.id,
        ],
    )
    applied = service.apply_canon_patch(project.root, "001")

    assert (
        next(
            operation
            for operation in applied.operations
            if operation.id == "op_review_001_fact_outcome"
        ).status
        == "applied"
    )
    assert "fact_001_outcome" in (project.root / "memory" / "facts.json").read_text(
        encoding="utf-8"
    )
    assert "event_001_outcome" in (
        project.root / "memory" / "timeline-events.json"
    ).read_text(encoding="utf-8")
    character_states = (project.root / "memory" / "character-states.json").read_text(
        encoding="utf-8"
    )
    assert "主角从压抑转为警惕" in character_states
    assert "旧敌开始忌惮" not in character_states
    assert "废柴逆袭" in (project.root / "memory" / "promises.json").read_text(
        encoding="utf-8"
    )


def test_canon_patch_operations_can_be_reviewed_individually(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角通过但被长老盯上。长老封锁消息。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    first_id = patch.operations[0].id
    second_id = patch.operations[1].id

    reviewed = service.update_canon_patch_operations(
        project.root,
        "001",
        [first_id],
        "accepted",
    )
    rejected = service.update_canon_patch_operations(
        project.root,
        "001",
        [second_id],
        "rejected",
    )

    first_reviewed = next(
        operation for operation in reviewed.operations if operation.id == first_id
    )
    assert first_reviewed.status == "accepted"
    assert next(
        operation for operation in rejected.operations if operation.id == second_id
    ).status == "rejected"

    applied = service.apply_canon_patch(project.root, "001")
    first_applied = next(operation for operation in applied.operations if operation.id == first_id)
    assert first_applied.status == "applied"
    assert next(
        operation for operation in applied.operations if operation.id == second_id
    ).status == "rejected"


def test_post_chapter_review_exposes_unsupported_contract_risks(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")

    service = PostChapterService()
    review = service.build_review(project.root, "001")
    patch = service.propose_canon_patch(project.root, "001")

    risks = [item for item in review.items if item.kind == "continuity_risk"]
    risk_fields = {str(item.payload["field"]) for item in risks}
    assert {"focus", "emotionalBeat", "stakes", "cost", "readerPromises_01"} <= risk_fields
    assert all(operation.target != "continuity_risk" for operation in patch.operations)
    assert not any(operation.id.startswith("op_review_001_risk_") for operation in patch.operations)


def test_post_chapter_review_accepts_rewritten_contract_support(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        (
            "# 第一章\n\n"
            "测试台前，主角第一次证明了自己的异常潜力。"
            "他通过测试，却也被长老盯上。长老随即封锁消息。"
            "主角先是压抑，随后变得警惕。废柴逆袭的期待被建立。"
            "他想证明自己不是任人踩踏的废物，也害怕再次被当众否定。"
            "如果失败，主角会失去进入宗门的机会。"
            "主角证明潜力的同时暴露异常，被长老盯上。"
            "主角嘴上冷静，实际是在保护最后一点尊严。"
            "读者应感到爽快，同时意识到更大危险来了。"
        ),
    )

    service = PostChapterService()
    review = service.build_review(project.root, "001")

    risk_fields = {
        str(item.payload["field"])
        for item in review.items
        if item.kind == "continuity_risk"
    }
    assert "focus" not in risk_fields
    assert "emotionalBeat" not in risk_fields
    assert "stakes" not in risk_fields
    assert "cost" not in risk_fields


def test_post_chapter_character_state_keeps_supported_relationship_shift(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角从压抑转为警惕。旧敌开始忌惮。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    state_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_character_state"
    )

    assert state_operation.action == "add"

    service.accept_canon_patch(project.root, "001", operation_ids=[state_operation.id])
    service.apply_canon_patch(project.root, "001")

    character_states = (project.root / "memory" / "character-states.json").read_text(
        encoding="utf-8"
    )
    assert "主角从压抑转为警惕" in character_states
    assert "旧敌开始忌惮" in character_states
    character_state_memory = json.loads(character_states)
    stored_state = character_state_memory["characters"][0]["states"][0]
    assert stored_state["continuityAnchors"][0]["claim"] == "忌惮"
    assert "毫不忌惮" in stored_state["continuityAnchors"][0]["forbiddenDraftPatterns"]


def test_post_chapter_relationship_state_tracks_supported_relationship_shift(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角从压抑转为警惕。旧敌开始忌惮。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    relationship_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_relationship_state"
    )

    assert relationship_operation.action == "add"
    assert relationship_operation.target == "memory/relationship-states.json"
    assert relationship_operation.payload["type"] == "respect"

    service.accept_canon_patch(project.root, "001", operation_ids=[relationship_operation.id])
    service.apply_canon_patch(project.root, "001")

    relationship_memory = json.loads(
        (project.root / "memory" / "relationship-states.json").read_text(encoding="utf-8")
    )
    stored = relationship_memory["relationships"][0]
    assert stored["toCharacterId"] == "旧敌"
    assert stored["status"] == "旧敌开始忌惮。"
    assert stored["quantifiedScore"] == 4.5
    assert stored["history"][0]["chapterId"] == "001"
    assert stored["history"][0]["score"] == 4.5


def test_post_chapter_apply_is_not_confused_by_text_mentions_of_operation_id(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        (
            '{"facts": [{"id": "fact_note", '
            '"text": "op_review_001_fact_outcome appears in prior canon text"}]}'
        ),
    )
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角通过但被长老盯上。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    fact_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_fact_outcome"
    )
    assert fact_operation.action == "add"

    service.accept_canon_patch(project.root, "001", operation_ids=[fact_operation.id])
    applied = service.apply_canon_patch(project.root, "001")

    assert any(operation.status == "applied" for operation in applied.operations)
    assert "fact_001_outcome" in (project.root / "memory" / "facts.json").read_text(
        encoding="utf-8"
    )


def test_post_chapter_updates_existing_promise_without_duplication(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/promises.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise_001_old",
                        "readerQuestion": "废柴逆袭",
                        "introducedAt": "chapter:001",
                        "status": "open",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n废柴逆袭的期待在测试后变得更明确。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    promise_operation = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_update_promise_001_old"
    )

    assert promise_operation.action == "update"

    service.accept_canon_patch(project.root, "001", operation_ids=[promise_operation.id])
    applied = service.apply_canon_patch(project.root, "001")

    assert next(
        operation for operation in applied.operations if operation.id == promise_operation.id
    ).status == "applied"
    promises_memory = json.loads(
        (project.root / "memory" / "promises.json").read_text(encoding="utf-8")
    )
    promises = promises_memory["promises"]
    assert len([item for item in promises if item["id"] == "promise_001_old"]) == 1
    assert promises[0]["status"] == "partial"
    assert promises[0]["lastTouchedAt"] == "chapter:001"


def test_post_chapter_refreshes_current_context_pack_after_apply(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    fact_operation = next(
        operation for operation in patch.operations if operation.id == "op_review_001_fact_outcome"
    )
    service.accept_canon_patch(project.root, "001", operation_ids=[fact_operation.id])
    service.apply_canon_patch(project.root, "001")

    context_pack = ContextPackService().read_context_pack(project.root, "001")
    contract_item = next(
        item for item in context_pack.included if item.source == "story/chapter-briefs/001.json"
    )
    assert contract_item.data["focus"] == "主角第一次证明异常潜力。"
    assert context_pack.path == "story/context-packs/001.json"


def test_post_chapter_refreshes_stale_context_pack_before_review(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一版",
            focus="旧重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ContextPackService().build_context_pack(project.root, "001")
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第二版",
            focus="新重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )

    patch = PostChapterService().build_review_and_patch(project.root, "001")
    review = PostChapterService().read_review(project.root, "001")

    assert review.source == "chapters/001.md"
    assert patch.sourceReview == "reviews/001.review.json"
    assert any(
        item.source == "story/chapter-briefs/001.json"
        and item.data["focus"] == "新重点"
        for item in ContextPackService().read_context_pack(project.root, "001").included
    )


def test_post_chapter_patch_can_close_touched_promise_and_open_loop(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
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
        "chapters/001.md",
        "# 第一章\n\n主角终于查清禁忌纹路的来历，也打破了长老封锁消息。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    close_promise = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_close_promise_001"
    )
    close_loop = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_close_loop_001"
    )

    assert close_promise.action == "close"
    assert close_loop.action == "close"

    service.accept_canon_patch(
        project.root,
        "001",
        operation_ids=[close_promise.id, close_loop.id],
    )
    service.apply_canon_patch(project.root, "001")
    service.apply_canon_patch(project.root, "001")

    promises = json.loads((project.root / "memory" / "promises.json").read_text(encoding="utf-8"))
    loops = json.loads((project.root / "memory" / "open-loops.json").read_text(encoding="utf-8"))
    assert promises["promises"][0]["status"] == "paid_off"
    assert promises["promises"][0]["payoffAt"] == "chapter:001"
    assert loops["loops"][0]["status"] == "paid_off"
    assert loops["loops"][0]["payoffAt"] == "chapter:001"


def test_post_chapter_rebuild_keeps_closed_progress_items_unique(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n主角通过测试，废柴逆袭的承诺继续推进，长老封锁消息。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    progress_operation_ids = [
        operation.id
        for operation in patch.operations
        if operation.target in {"memory/promises.json", "memory/open-loops.json"}
        and operation.action == "add"
    ]
    service.accept_canon_patch(
        project.root,
        "001",
        operation_ids=progress_operation_ids,
    )
    service.apply_canon_patch(project.root, "001")

    for relative_path, key in (
        ("memory/promises.json", "promises"),
        ("memory/open-loops.json", "loops"),
    ):
        data = json.loads((project.root / relative_path).read_text(encoding="utf-8"))
        data[key][0].update(
            {
                "status": "paid_off",
                "payoffAt": "chapter:002",
                "closedBy": "chapters/002.md",
                "_operationId": f"op_review_002_close_{data[key][0]['id']}",
            }
        )
        ProjectService().write_text(
            project.root,
            relative_path,
            json.dumps(data, ensure_ascii=False),
        )

    rebuilt = service.build_review_and_patch(project.root, "001")
    rebuilt_progress_ids = [
        operation.id
        for operation in rebuilt.operations
        if operation.target in {"memory/promises.json", "memory/open-loops.json"}
        and operation.action == "add"
    ]
    service.accept_canon_patch(
        project.root,
        "001",
        operation_ids=rebuilt_progress_ids,
    )
    service.apply_canon_patch(project.root, "001")

    promises = json.loads((project.root / "memory/promises.json").read_text(encoding="utf-8"))
    loops = json.loads((project.root / "memory/open-loops.json").read_text(encoding="utf-8"))
    assert len(promises["promises"]) == 1
    assert len(loops["loops"]) == 1
    assert promises["promises"][0]["status"] == "paid_off"
    assert loops["loops"][0]["status"] == "paid_off"
    assert promises["promises"][0]["payoffAt"] == "chapter:002"
    assert loops["loops"][0]["payoffAt"] == "chapter:002"


def test_post_chapter_patch_does_not_close_untouched_memory_items(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
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
        "chapters/001.md",
        "# 第一章\n\n主角只完成山门测试，没有追查旧谜题。",
    )

    patch = PostChapterService().build_review_and_patch(project.root, "001")

    assert not any(
        operation.id == "op_review_001_close_promise_001"
        for operation in patch.operations
    )


def test_post_chapter_patch_marks_touched_memory_item_partial(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
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
        "chapters/001.md",
        "# 第一章\n\n主角再次看见禁忌纹路的来历线索，但仍被迷雾挡住。",
    )

    service = PostChapterService()
    patch = service.build_review_and_patch(project.root, "001")
    update_promise = next(
        operation
        for operation in patch.operations
        if operation.id == "op_review_001_update_promise_001"
    )

    assert update_promise.action == "update"

    service.accept_canon_patch(project.root, "001", operation_ids=[update_promise.id])
    service.apply_canon_patch(project.root, "001")

    promises = json.loads((project.root / "memory" / "promises.json").read_text(encoding="utf-8"))
    assert promises["promises"][0]["status"] == "partial"
    assert promises["promises"][0]["lastTouchedAt"] == "chapter:001"
    assert "payoffAt" not in promises["promises"][0]
