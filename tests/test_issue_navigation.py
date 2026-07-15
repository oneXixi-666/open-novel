from __future__ import annotations

from open_novel.core.issue_navigation import IssueNavigationService


def test_issue_navigation_maps_issues_to_contract_and_source_targets() -> None:
    navigation = IssueNavigationService().build_navigation(
        "001",
        {
            "editorial": {
                "issues": [
                    {
                        "type": "abstract_human_core",
                        "severity": "high",
                        "dimension": "character",
                        "message": "人情味字段没有进入正文。",
                        "evidence": [
                            "drafts/001.generated.md",
                            "story/chapter-briefs#internalNeed",
                            "story/chapter-briefs#stakes",
                        ],
                    }
                ]
            }
        },
    )

    item = navigation["items"][0]
    targets = item["targets"]

    assert navigation["count"] == 1
    assert item["primaryTarget"]["kind"] == "source"
    assert any(
        target["kind"] == "contract"
        and target["path"] == "story/chapter-briefs/001.json"
        and target["field"] == "internalNeed"
        for target in targets
    )
    assert "章节合同字段" in item["suggestedAction"]


def test_issue_navigation_maps_memory_issue_to_memory_file() -> None:
    navigation = IssueNavigationService().build_navigation(
        "002",
        {
            "gate": {
                "issues": [
                    {
                        "stage": "continuity",
                        "type": "relationship_state_contradiction",
                        "severity": "high",
                        "message": "关系状态反转缺少过渡。",
                        "evidence": ["drafts/002.generated.md"],
                    }
                ]
            }
        },
    )

    targets = navigation["items"][0]["targets"]

    assert any(
        target["kind"] == "memory" and target["path"] == "memory/relationship-states.json"
        for target in targets
    )


def test_issue_navigation_maps_relationship_review_to_edge_page() -> None:
    navigation = IssueNavigationService().build_navigation(
        "003",
        {
            "continuity": {
                "issues": [
                    {
                        "stage": "continuity",
                        "type": "relationship_transition_needs_review",
                        "severity": "medium",
                        "message": "关系跳变需要审阅。",
                        "evidence": [
                            "drafts/003.generated.md",
                            "memory/relationship-states.json#rel_002",
                            "/relationships/edge?edgeId=林澈__旧敌__rivalry",
                        ],
                    }
                ]
            }
        },
    )

    item = navigation["items"][0]
    targets = item["targets"]

    assert any(
        target["kind"] == "relationship-edge"
        and target["field"] == "林澈__旧敌__rivalry"
        for target in targets
    )
    assert any(
        target["kind"] == "memory" and target["path"] == "memory/relationship-states.json"
        for target in targets
    )
    assert "关系历史页" in item["suggestedAction"]
