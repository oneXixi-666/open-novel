from __future__ import annotations

import json
from typing import Any

STATE_CONTRADICTION_PATTERNS = {
    "信任": ["从未信任", "毫不信任", "完全不信任", "不再信任", "仍不信任", "依旧不信任"],
    "忌惮": ["毫不忌惮", "并不忌惮", "仍旧轻蔑", "依旧轻蔑", "继续轻蔑"],
    "警惕": ["毫无戒心", "完全放心", "放下戒备", "不再警惕"],
    "冷静": ["彻底失控", "完全慌乱", "陷入慌乱"],
    "坚定": ["彻底动摇", "完全退缩", "放弃目标"],
    "敌视": ["完全和解", "亲密无间"],
}

TRANSITION_MARKERS = ["从", "转为", "变成", "开始", "不再", "重新", "逐渐", "终于"]


def anchors_for_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    state_text = json.dumps(state, ensure_ascii=False)
    anchors: list[dict[str, Any]] = []
    for claim, forbidden_patterns in STATE_CONTRADICTION_PATTERNS.items():
        if claim not in state_text:
            continue
        anchors.append(
            {
                "claim": claim,
                "forbiddenDraftPatterns": forbidden_patterns,
                "allowedTransitionMarkers": TRANSITION_MARKERS,
            }
        )
    return anchors


def state_anchors_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = state.get("continuityAnchors")
    if isinstance(explicit, list):
        anchors = [_valid_anchor(anchor) for anchor in explicit]
        anchors = [anchor for anchor in anchors if anchor is not None]
        if anchors:
            return anchors
    return anchors_for_state(state)


def _valid_anchor(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    claim = str(value.get("claim") or "").strip()
    forbidden = value.get("forbiddenDraftPatterns")
    if not claim or not isinstance(forbidden, list):
        return None
    forbidden_patterns = [str(item).strip() for item in forbidden if str(item).strip()]
    if not forbidden_patterns:
        return None
    markers = value.get("allowedTransitionMarkers")
    if isinstance(markers, list):
        transition_markers = [str(item).strip() for item in markers if str(item).strip()]
    else:
        transition_markers = TRANSITION_MARKERS
    return {
        "claim": claim,
        "forbiddenDraftPatterns": forbidden_patterns,
        "allowedTransitionMarkers": transition_markers or TRANSITION_MARKERS,
    }
