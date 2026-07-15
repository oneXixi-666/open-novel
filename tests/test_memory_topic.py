from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.memory_topic import MemoryTopicService
from open_novel.core.models import ContextPack, ContextPackItem
from open_novel.core.project import ProjectService


def test_memory_topic_detail_links_entities_related_topics_and_context(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
                        "title": "旧山门线",
                        "summary": "林澈曾在旧山门测试中发现禁忌纹路。",
                        "keywords": ["林澈", "旧山门"],
                        "priority": 50,
                        "source": "memory/chapter-summaries.json",
                        "chapterRef": "001-006",
                        "writingGuidance": ["先写林澈忍住羞辱，再写他反击。"],
                    },
                    {
                        "id": "fact_origin",
                        "kind": "fact",
                        "summary": "禁忌纹路与旧山门测试有关。",
                        "keywords": ["旧山门"],
                        "priority": 70,
                    },
                ],
                "entityIndex": [
                    {"name": "旧山门", "topicIds": ["arc_000", "fact_origin"]},
                    {"name": "林澈", "topicIds": ["arc_000"]},
                ],
                "writingGuidance": [
                    {"id": "lesson_emotion", "lesson": "情绪必须用动作和对白落地。"}
                ],
            },
            ensure_ascii=False,
        ),
    )
    context_pack = ContextPack(
        chapterId="010",
        path="story/context-packs/010.json",
        included=[
            ContextPackItem(
                source="memory/long-term-memory.json",
                reason="keyword match",
                data={"topics": [{"id": "arc_000"}]},
            )
        ],
        excluded=[],
        estimatedTokens=100,
    )
    ProjectService().write_text(
        project.root,
        context_pack.path,
        json.dumps(context_pack.model_dump(mode="json"), ensure_ascii=False),
    )

    detail = MemoryTopicService().topic_detail(project.root, "arc_000", "010")

    assert detail["topic"]["title"] == "旧山门线"
    assert detail["source"] == "memory/chapter-summaries.json"
    assert detail["contextStatus"]["included"] is True
    assert {entity["name"] for entity in detail["relatedEntities"]} == {"旧山门", "林澈"}
    assert detail["relatedTopics"][0]["id"] == "fact_origin"
    assert detail["writingGuidance"][0]["lesson"] == "先写林澈忍住羞辱，再写他反击。"
    assert detail["writingGuidance"][1]["id"] == "lesson_emotion"
