from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.project import ProjectService
from open_novel.core.relationship_graph import RelationshipGraphService


def test_relationship_graph_groups_history_and_latest_state(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
                        "source": "review:001",
                    },
                    {
                        "id": "rel_002",
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "rivalry",
                        "status": "旧敌从轻蔑转为开始忌惮林澈。",
                        "pressure": "忌惮但仍敌对",
                        "unresolvedEmotion": "不甘",
                        "chapterId": "003",
                        "source": "review:003",
                    },
                    {
                        "id": "rel_003",
                        "fromCharacterId": "林澈",
                        "toCharacterId": "旧敌",
                        "type": "rivalry",
                        "status": "旧敌秘密保护林澈。",
                        "pressure": "敌对压力突然缓和",
                        "chapterId": "004",
                        "source": "review:004",
                    },
                ],
            },
            ensure_ascii=False,
        ),
    )

    graph = RelationshipGraphService().build_graph(project.root)
    edge = graph["edges"][0]
    detail = RelationshipGraphService().edge_detail(project.root, edge["id"])

    assert graph["nodeCount"] == 2
    assert graph["edgeCount"] == 1
    assert edge["fromCharacterId"] == "林澈"
    assert edge["toCharacterId"] == "旧敌"
    assert edge["latestStatus"] == "旧敌秘密保护林澈。"
    assert edge["latestPressure"] == "敌对压力突然缓和"
    assert edge["latestUnresolvedEmotion"] == ""
    assert edge["latestChapterId"] == "004"
    assert edge["latestTransition"] == "shifted"
    assert edge["latestTransitionSignals"] == [
        "hostility",
        "protection",
        "rivalry",
        "pressure",
        "softening",
    ]
    assert edge["eventCount"] == 3
    assert len(edge["history"]) == 3
    assert edge["history"][0]["transition"] == "established"
    assert edge["history"][1]["transition"] == "explicit-shift"
    assert edge["history"][2]["transition"] == "shifted"
    assert detail["edge"]["id"] == "林澈__旧敌__rivalry"
    assert detail["eventCount"] == 3
    assert detail["timeline"][2]["needsReview"] is True
    assert detail["reviewSummary"]["needsReviewCount"] == 1
    assert detail["reviewSummary"]["reviewEventIds"] == ["rel_003"]


def test_relationship_graph_updates_reviewed_event(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
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
                        "type": "respect",
                        "status": "旧敌仍旧轻蔑林澈。",
                        "pressure": "公开羞辱",
                        "chapterId": "001",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = RelationshipGraphService().update_relationship_event(
        project.root,
        "rel_001",
        status="旧敌从轻蔑转为开始忌惮林澈。",
        pressure="忌惮但仍敌对",
        unresolved_emotion="不甘",
        evidence=["chapters/001.md#12"],
    )
    stored = json.loads(
        (project.root / "memory" / "relationship-states.json").read_text(encoding="utf-8")
    )
    event = stored["relationships"][0]

    assert result["updatedEvent"]["status"] == "旧敌从轻蔑转为开始忌惮林澈。"
    assert result["edge"]["latestTransitionSignals"][0] == "explicit-transition"
    assert event["reviewStatus"] == "reviewed"
    assert event["pressure"] == "忌惮但仍敌对"
    assert event["unresolvedEmotion"] == "不甘"
    assert event["evidence"] == ["chapters/001.md#12"]
