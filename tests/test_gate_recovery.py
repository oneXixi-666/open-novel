from __future__ import annotations

from open_novel.core.gate_recovery import GateRecoveryService


def test_gate_recovery_groups_steps_by_stage_and_targets() -> None:
    gate = {
        "chapterId": "001",
        "status": "block",
        "score": 42,
        "issues": [
            {
                "stage": "continuity",
                "type": "violated_must_avoid",
                "severity": "blocker",
                "message": "草稿触犯 mustAvoid。",
                "evidence": [
                    "drafts/001.generated.md",
                    "story/chapter-briefs/001.json#mustAvoid",
                ],
            },
            {
                "stage": "editorial",
                "type": "emotion_told_not_felt",
                "severity": "medium",
                "message": "情绪只被说明。",
                "evidence": ["drafts/001.generated.md"],
            },
        ],
    }

    recovery = GateRecoveryService().recovery_plan(gate)

    assert recovery["blocked"] is True
    assert recovery["recommendedNextAction"] == "resolve-continuity-issues-and-rerun-chapter-gate"
    assert [step["stage"] for step in recovery["steps"]] == ["continuity", "editorial"]
    continuity = recovery["steps"][0]
    assert continuity["severity"] == "blocker"
    assert continuity["issueCount"] == 1
    assert "violated_must_avoid" in continuity["types"]
    assert any(target["field"] == "mustAvoid" for target in continuity["targets"])
