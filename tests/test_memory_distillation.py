from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.memory_distillation import MemoryDistillationService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def test_distill_project_writes_bounded_long_term_memory(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/chapter-summaries.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "chapters": [
                    {
                        "chapterId": f"{index:03d}",
                        "summary": f"林澈追查禁忌纹路旧线索 {index}。",
                    }
                    for index in range(1, 8)
                ],
            },
            ensure_ascii=False,
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
                        "id": "fact_core_origin",
                        "text": "禁忌纹路与旧山门测试有关。",
                        "importance": "high",
                        "validFrom": "chapter:002",
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
                        "id": "promise_keep_hot",
                        "readerQuestion": "禁忌纹路真正来历是什么",
                        "status": "open",
                        "introducedAt": "chapter:001",
                    }
                ],
            },
            ensure_ascii=False,
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
                        "id": "lesson_emotion",
                        "category": "emotion",
                        "lesson": "情绪必须用动作和对白落地。",
                        "severity": "high",
                        "failureCount": 3,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    report = MemoryDistillationService().distill_project(
        project.root,
        "010",
        hot_window_chapters=3,
        max_topics=10,
    )

    memory = json.loads(
        (project.root / "memory" / "long-term-memory.json").read_text(encoding="utf-8")
    )
    topic_ids = {topic["id"] for topic in memory["topics"]}
    assert report.topicCount == len(memory["topics"])
    assert report.outputPath == "memory/long-term-memory.json"
    assert "arc_000" in topic_ids
    assert "fact_fact_core_origin" in topic_ids
    assert not any("promise_keep_hot" in topic_id for topic_id in topic_ids)
    assert memory["entityIndex"]
    assert memory["writingGuidance"][0]["id"] == "lesson_emotion"
    assert (project.root / "runs" / "memory-distillation.json").exists()


def test_context_pack_retrieves_distilled_long_term_memory(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="010",
            focus="林澈追查禁忌纹路的旧山门线索。",
            goal="林澈想确认禁忌纹路来源。",
            conflict="长老阻挠。",
            turn="旧记录出现。",
            outcome="林澈找到一条新线索。",
            hook="旧山门钟声再次响起。",
            emotionalBeat="林澈从克制转为警惕。",
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
                        "id": "arc_000",
                        "kind": "chapter_arc",
                        "title": "第 001-006 章剧情压缩",
                        "summary": "林澈曾在旧山门测试中发现禁忌纹路。",
                        "keywords": ["林澈", "旧山门", "禁忌纹路"],
                        "priority": 50,
                    }
                ],
                "entityIndex": [],
                "writingGuidance": [],
            },
            ensure_ascii=False,
        ),
    )

    context_pack = ContextPackService().build_context_pack(project.root, "010")

    long_term_item = next(
        item for item in context_pack.included if item.source == "memory/long-term-memory.json"
    )
    assert isinstance(long_term_item.data, dict)
    assert long_term_item.data["topics"][0]["id"] == "arc_000"
    assert "keyword_match" in long_term_item.data["topics"][0]["_contextPriority"]["reasons"]
