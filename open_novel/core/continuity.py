from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_novel.core.character_state import state_anchors_from_state
from open_novel.core.models import ContinuityIssue, ContinuityReport
from open_novel.core.project import ProjectService
from open_novel.core.relationship_graph import RelationshipGraphService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.text_support import important_terms, text_supports_claim


class ContinuityService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)

    def report_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"runs/continuity-{normalized}.json"

    def check_draft(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None = None,
    ) -> ContinuityReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        source = draft_path or f"drafts/{normalized}.generated.md"
        text = self.project_service.read_text(root, source)
        contract = self.story_guidance.read_scene_contract(root, normalized)
        issues: list[ContinuityIssue] = []

        for required in contract.mustInclude:
            if required and not text_supports_claim(text, required):
                issues.append(
                    ContinuityIssue(
                        type="missing_must_include",
                        severity="high",
                        evidence=[source, f"story/chapter-briefs/{normalized}.json#mustInclude"],
                        message=f"草稿缺少必须包含内容：{required}",
                        suggestions=[f"补入并推动剧情中的“{required}”。"],
                    )
                )

        for forbidden in contract.mustAvoid:
            if forbidden and forbidden in text:
                issues.append(
                    ContinuityIssue(
                        type="violated_must_avoid",
                        severity="blocker",
                        evidence=[source, f"story/chapter-briefs/{normalized}.json#mustAvoid"],
                        message=f"草稿触碰禁止事项：{forbidden}",
                        suggestions=[f"删除或延后“{forbidden}”。"],
                    )
                )

        focus_terms = self._important_terms(contract.focus)
        if focus_terms and not self._text_supports(text, contract.focus):
            issues.append(
                ContinuityIssue(
                    type="focus_drift",
                    severity="medium",
                    evidence=[source, f"story/chapter-briefs/{normalized}.json#focus"],
                    message="草稿没有明显承接本章重点。",
                    suggestions=["重写关键场景，让主要行动服务 focus。"],
                )
            )

        outcome_terms = self._important_terms(contract.outcome)
        if outcome_terms and not self._text_supports(text, contract.outcome):
            issues.append(
                ContinuityIssue(
                    type="outcome_drift",
                    severity="high",
                    evidence=[source, f"story/chapter-briefs/{normalized}.json#outcome"],
                    message="草稿没有明显落实本章结果，章节结束后的状态变化不清楚。",
                    suggestions=["补明确认结果的行动、代价、关系变化或局势变化。"],
                )
            )

        hook_terms = self._important_terms(contract.hook)
        if hook_terms and not self._text_supports(text, contract.hook):
            issues.append(
                ContinuityIssue(
                    type="hook_drift",
                    severity="medium",
                    evidence=[source, f"story/chapter-briefs/{normalized}.json#hook"],
                    message="草稿没有明显承接本章结尾钩子。",
                    suggestions=["补入能牵引下一章的问题、危险、承诺或未完成动作。"],
                )
            )

        emotional_terms = self._important_terms(contract.emotionalBeat)
        if emotional_terms and not self._text_supports(text, contract.emotionalBeat):
            issues.append(
                ContinuityIssue(
                    type="emotional_discontinuity",
                    severity="medium",
                    evidence=[source, f"story/chapter-briefs/{normalized}.json#emotionalBeat"],
                    message="草稿没有明显承接本章情绪节拍。",
                    suggestions=["增加角色反应、对话余波或内心动作来落实情绪变化。"],
                )
            )

        relationship_terms = self._important_terms(contract.relationshipBeat)
        if relationship_terms and not self._text_supports(text, contract.relationshipBeat):
            issues.append(
                ContinuityIssue(
                    type="relationship_discontinuity",
                    severity="medium",
                    evidence=[
                        source,
                        f"story/chapter-briefs/{normalized}.json#relationshipBeat",
                    ],
                    message="草稿没有明显落实本章关系节拍。",
                    suggestions=["通过互动、态度转变或后续选择写出关系变化。"],
                )
            )

        for promise in contract.readerPromises:
            promise_terms = self._important_terms(promise)
            if promise_terms and not self._text_supports(text, promise):
                issues.append(
                    ContinuityIssue(
                        type="reader_promise_drift",
                        severity="medium",
                        evidence=[
                            source,
                            f"story/chapter-briefs/{normalized}.json#readerPromises",
                        ],
                        message=f"草稿没有明显推进本章读者承诺：{promise}",
                        suggestions=["补入能让读者感到该承诺被建立、推进或部分兑现的场景。"],
                    )
                )

        issues.extend(self._check_logic_dependencies(root, normalized, contract.logicDependencies))
        issues.extend(
            self._check_character_state_contradictions(
                root,
                normalized,
                source,
                text,
                contract.pov,
            )
        )
        issues.extend(
            self._check_relationship_state_contradictions(
                root,
                normalized,
                source,
                text,
            )
        )
        issues.extend(self._check_relationship_transition_reviews(root, normalized, source))
        issues.extend(self._check_payoff_windows(root, normalized, source, text))
        issues.extend(self._check_timeline_order(root, normalized, source, text))

        blocker_count = sum(1 for issue in issues if issue.severity == "blocker")
        high_count = sum(1 for issue in issues if issue.severity == "high")
        score = max(0, 100 - blocker_count * 35 - high_count * 20 - len(issues) * 8)
        report = ContinuityReport(
            chapterId=normalized,
            source=source,
            score=score,
            issues=issues,
        )
        self.project_service.write_text(
            root,
            self.report_path(normalized),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _important_terms(self, text: str) -> list[str]:
        return important_terms(text)

    def _text_supports(self, text: str, claim: str) -> bool:
        return text_supports_claim(text, claim)

    def _check_logic_dependencies(
        self,
        root: Path,
        chapter_id: str,
        dependencies: list[str],
    ) -> list[ContinuityIssue]:
        if not dependencies:
            return []
        grounding_text = json.dumps(
            {
                "facts": self._read_json_if_exists(root, "memory/facts.json"),
                "timelineEvents": self._read_json_if_exists(root, "memory/timeline-events.json"),
                "characterStates": self._read_json_if_exists(root, "memory/character-states.json"),
                "chapterSummaries": self._read_json_if_exists(
                    root,
                    "memory/chapter-summaries.json",
                ),
                "architecture": self._read_json_if_exists(
                    root,
                    "story/workbench-architecture.json",
                ),
                "blueprint": self._read_json_if_exists(
                    root,
                    "story/chapter-blueprint.json",
                ),
                "idea": self._read_text_if_exists(root, "notes/ideas.md"),
                "bible": self._read_text_if_exists(root, "bible.md"),
            },
            ensure_ascii=False,
        )
        issues: list[ContinuityIssue] = []
        for dependency in dependencies:
            terms = self._important_terms(dependency)
            if not terms or text_supports_claim(grounding_text, dependency):
                continue
            issues.append(
                ContinuityIssue(
                    type="ungrounded_logic_dependency",
                    severity="high",
                    evidence=[
                        f"story/chapter-briefs/{chapter_id}.json#logicDependencies",
                        "memory/facts.json",
                        "memory/timeline-events.json",
                        "memory/character-states.json",
                        "memory/chapter-summaries.json",
                        "story/workbench-architecture.json",
                        "story/chapter-blueprint.json",
                    ],
                    message=f"本章逻辑依赖尚未在已确认记忆中找到支撑：{dependency}",
                    suggestions=["先补入前置章节记忆，或重写本章使该依赖在正文中自然交代。"],
                )
            )
        return issues

    def _read_text_if_exists(self, root: Path, relative_path: str) -> str:
        return self.project_service.read_text_if_exists(root, relative_path)

    def _check_timeline_order(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        draft_text: str,
    ) -> list[ContinuityIssue]:
        memory = self._read_json_if_exists(root, "memory/timeline-events.json")
        if not isinstance(memory, dict):
            return []
        events = memory.get("events")
        if not isinstance(events, list):
            return []
        issues: list[ContinuityIssue] = []
        current_order = self._chapter_order(chapter_id)
        for event in events:
            if not isinstance(event, dict):
                continue
            event_chapter = event.get("chapterId")
            event_order = self._chapter_order(str(event_chapter)) if event_chapter else None
            if current_order is None or event_order is None or event_order <= current_order:
                continue
            event_text = " ".join(
                str(event.get(key, ""))
                for key in ("label", "summary")
                if isinstance(event.get(key), str)
            )
            if not self._timeline_event_is_explicitly_mentioned(draft_text, event):
                continue
            event_id = str(event.get("id") or "future_event")
            issues.append(
                ContinuityIssue(
                    type="timeline_order_conflict",
                    severity="blocker",
                    evidence=[
                        source,
                        f"memory/timeline-events.json#{event_id}",
                    ],
                    message=f"草稿疑似提前写入未来时间线事件：{event_text}",
                    suggestions=["删除提前发生的事件，或调整结构化时间线中的章节归属。"],
                )
            )
        return issues

    def _timeline_event_is_explicitly_mentioned(
        self,
        draft_text: str,
        event: dict[str, Any],
    ) -> bool:
        normalized_draft = "".join(draft_text.split())
        statements = {
            str(event.get(key) or "").strip()
            for key in ("label", "summary")
            if isinstance(event.get(key), str)
        }
        return any(
            len(statement) >= 4 and "".join(statement.split()) in normalized_draft
            for statement in statements
        )

    def _check_character_state_contradictions(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        draft_text: str,
        pov: str,
    ) -> list[ContinuityIssue]:
        memory = self._read_json_if_exists(root, "memory/character-states.json")
        if not isinstance(memory, dict):
            return []
        characters = memory.get("characters")
        if not isinstance(characters, list):
            return []

        issues: list[ContinuityIssue] = []
        for character in characters:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("characterId") or "")
            if pov and character_id and pov not in {
                character_id,
                str(character.get("name") or ""),
            }:
                continue
            state = self._latest_character_state_before_chapter(character, chapter_id)
            if state is None:
                continue
            for anchor in state_anchors_from_state(state):
                claim = str(anchor["claim"])
                contradictions = anchor["forbiddenDraftPatterns"]
                markers = anchor["allowedTransitionMarkers"]
                for contradiction in contradictions:
                    if contradiction not in draft_text:
                        continue
                    if self._has_transition_context(draft_text, claim, contradiction, markers):
                        continue
                    state_chapter = str(state.get("chapterId") or "latest")
                    issues.append(
                        ContinuityIssue(
                            type="character_state_contradiction",
                            severity="high",
                            evidence=[
                                source,
                                f"memory/character-states.json#{character_id}:{state_chapter}",
                            ],
                            message=(
                                f"草稿疑似违背最新人物状态：已知状态包含“{claim}”，"
                                f"但草稿出现“{contradiction}”。"
                            ),
                            suggestions=[
                                "补写状态转变的原因和过程，或调整人物状态记忆后再继续。",
                            ],
                        )
                    )
                    break
        return issues

    def _latest_character_state_before_chapter(
        self,
        character: dict[str, Any],
        chapter_id: str,
    ) -> dict[str, Any] | None:
        states = character.get("states")
        if not isinstance(states, list):
            return None
        current_order = self._chapter_order(chapter_id)
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for index, state in enumerate(states):
            if not isinstance(state, dict):
                continue
            state_chapter = str(
                state.get("chapterId")
                or str(state.get("validFrom") or "").removeprefix("chapter:")
            )
            state_order = self._chapter_order(state_chapter)
            if (
                current_order is not None
                and state_order is not None
                and state_order >= current_order
            ):
                continue
            candidates.append((state_order or -1, index, state))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def _check_relationship_state_contradictions(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        draft_text: str,
    ) -> list[ContinuityIssue]:
        memory = self._read_json_if_exists(root, "memory/relationship-states.json")
        if not isinstance(memory, dict):
            return []
        relationships = memory.get("relationships")
        if not isinstance(relationships, list):
            return []
        issues: list[ContinuityIssue] = []
        for relationship in self._latest_relationships_before_chapter(
            relationships,
            chapter_id,
        ):
            relation_id = str(relationship.get("id") or "relationship")
            relation_type = str(relationship.get("type") or "other")
            status = str(relationship.get("status") or "")
            for claim, contradictions in self._relationship_anchors(
                relation_type,
                status,
            ):
                for contradiction in contradictions:
                    if contradiction not in draft_text:
                        continue
                    if self._has_transition_context(
                        draft_text,
                        claim,
                        contradiction,
                        ["从", "转为", "变成", "开始", "不再", "重新", "逐渐", "终于"],
                    ):
                        continue
                    issues.append(
                        ContinuityIssue(
                            type="relationship_state_contradiction",
                            severity="high",
                            evidence=[
                                source,
                                f"memory/relationship-states.json#{relation_id}",
                            ],
                            message=(
                                f"草稿疑似违背最新关系状态：已知关系包含“{claim}”，"
                                f"但草稿出现“{contradiction}”。"
                            ),
                            suggestions=[
                                "补写关系转变的触发、代价和互动过程，或先修正关系状态记忆。",
                            ],
                        )
                    )
                    break
        return issues

    def _latest_relationships_before_chapter(
        self,
        relationships: list[Any],
        chapter_id: str,
    ) -> list[dict[str, Any]]:
        current_order = self._chapter_order(chapter_id)
        latest: dict[str, tuple[int, int, dict[str, Any]]] = {}
        for index, relationship in enumerate(relationships):
            if not isinstance(relationship, dict):
                continue
            relation_id = str(relationship.get("id") or "")
            if not relation_id:
                continue
            relation_order = self._chapter_order(str(relationship.get("chapterId") or ""))
            if (
                current_order is not None
                and relation_order is not None
                and relation_order >= current_order
            ):
                continue
            candidate = (relation_order or -1, index, relationship)
            if relation_id not in latest or candidate[:2] > latest[relation_id][:2]:
                latest[relation_id] = candidate
        return [item[2] for item in latest.values()]

    def _check_relationship_transition_reviews(
        self,
        root: Path,
        chapter_id: str,
        source: str,
    ) -> list[ContinuityIssue]:
        try:
            graph = RelationshipGraphService(self.project_service).build_graph(root)
        except (FileNotFoundError, ValueError):
            return []
        current_order = self._chapter_order(chapter_id)
        edges = graph.get("edges")
        if not isinstance(edges, list):
            return []
        issues: list[ContinuityIssue] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            history = edge.get("history")
            if not isinstance(history, list):
                continue
            for event in history:
                if not isinstance(event, dict):
                    continue
                if not self._relationship_event_needs_review(event, current_order):
                    continue
                event_id = str(event.get("id") or "relationship")
                chapter = str(event.get("chapterId") or "-")
                edge_id = str(edge.get("id") or "")
                issues.append(
                    ContinuityIssue(
                        type="relationship_transition_needs_review",
                        severity="medium",
                        evidence=[
                            source,
                            f"memory/relationship-states.json#{event_id}",
                            f"/relationships/edge?edgeId={edge_id}",
                        ],
                        message=(
                            f"关系历史在第 {chapter} 章出现未审跳变："
                            f"{event.get('status') or ''}"
                        ),
                        suggestions=[
                            "在关系历史页补充显式过渡、证据或修正该关系事件。",
                        ],
                    )
                )
        return issues

    def _relationship_event_needs_review(
        self,
        event: dict[str, Any],
        current_order: int | None,
    ) -> bool:
        if str(event.get("transition") or "") != "shifted":
            return False
        signals = event.get("transitionSignals")
        if isinstance(signals, list) and "explicit-transition" in signals:
            return False
        event_order = self._chapter_order(str(event.get("chapterId") or ""))
        if current_order is not None and event_order is not None and event_order > current_order:
            return False
        return True

    def _relationship_anchors(
        self,
        relation_type: str,
        status: str,
    ) -> list[tuple[str, list[str]]]:
        anchors: dict[str, list[str]] = {
            "trust": ["从未信任", "毫不信任", "完全不信任", "不再信任"],
            "debt": ["两清", "毫无亏欠", "没有欠", "互不相欠"],
            "fear": ["毫不害怕", "完全不怕", "毫无惧意"],
            "misunderstanding": ["彻底解开误会", "误会全消", "再无误解"],
            "rivalry": ["亲密无间", "毫无敌意", "完全和解"],
            "protection": ["袖手旁观", "不再保护", "任由受伤"],
            "suspicion": ["完全放心", "毫无戒心", "不再怀疑"],
            "respect": ["毫不忌惮", "仍旧轻蔑", "依旧轻蔑", "完全看不起"],
            "hostility": ["完全和解", "亲密无间", "毫无敌意"],
        }
        claim = self._relationship_claim(relation_type, status)
        contradictions = anchors.get(relation_type, [])
        return [(claim, contradictions)] if claim and contradictions else []

    def _relationship_claim(self, relation_type: str, status: str) -> str:
        labels = {
            "trust": "信任",
            "debt": "亏欠",
            "fear": "害怕",
            "misunderstanding": "误会",
            "rivalry": "对立",
            "protection": "保护",
            "suspicion": "怀疑",
            "respect": "忌惮",
            "hostility": "敌意",
        }
        label = labels.get(relation_type, "")
        if label and label in status:
            return label
        return label

    def _has_transition_context(
        self,
        draft_text: str,
        anchor: str,
        contradiction: str,
        transition_markers: list[str],
    ) -> bool:
        contradiction_index = draft_text.find(contradiction)
        anchor_index = draft_text.find(anchor)
        if contradiction_index < 0 or anchor_index < 0:
            return False
        start = max(0, min(contradiction_index, anchor_index) - 16)
        end = min(len(draft_text), max(contradiction_index, anchor_index) + 24)
        window = draft_text[start:end]
        window_without_contradiction = window.replace(contradiction, "")
        return (
            any(term in window for term in transition_markers)
            and anchor in window_without_contradiction
        )

    def _check_payoff_windows(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        draft_text: str,
    ) -> list[ContinuityIssue]:
        current_order = self._chapter_order(chapter_id)
        if current_order is None:
            return []
        items = [
            *self._payoff_items(
                root,
                "memory/promises.json",
                "promises",
                ("readerQuestion", "text"),
            ),
            *self._payoff_items(
                root,
                "memory/open-loops.json",
                "loops",
                ("text", "readerQuestion"),
            ),
        ]
        issues: list[ContinuityIssue] = []
        for item in items:
            start, end = self._parse_payoff_window(str(item.get("expectedPayoffWindow", "")))
            if start is None or end is None or current_order < start:
                continue
            item_text = " ".join(
                str(item.get(key, "")) for key in ("readerQuestion", "text") if item.get(key)
            )
            terms = self._important_terms(item_text)
            if terms and any(term in draft_text for term in terms):
                continue
            item_id = str(item.get("id") or "payoff_item")
            is_overdue = current_order > end
            issues.append(
                ContinuityIssue(
                    type="payoff_overdue" if is_overdue else "payoff_due_soon",
                    severity="high" if is_overdue else "medium",
                    evidence=[
                        source,
                        f"{item['_memorySource']}#{item_id}",
                    ],
                    message=(
                        f"已超过兑现窗口但草稿未明显触碰：{item_text}"
                        if is_overdue
                        else f"已进入兑现窗口但草稿未明显触碰：{item_text}"
                    ),
                    suggestions=["安排回收、部分兑现、延期解释，或调整记忆中的 payoff window。"],
                )
            )
        return issues

    def _payoff_items(
        self,
        root: Path,
        relative_path: str,
        list_key: str,
        text_keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        memory = self._read_json_if_exists(root, relative_path)
        if not isinstance(memory, dict):
            return []
        values = memory.get(list_key)
        if not isinstance(values, list):
            return []
        items: list[dict[str, Any]] = []
        for value in values:
            if not isinstance(value, dict) or value.get("status") not in (None, "open", "partial"):
                continue
            if not value.get("expectedPayoffWindow"):
                continue
            if not any(value.get(key) for key in text_keys):
                continue
            items.append({**value, "_memorySource": relative_path})
        return items

    def _parse_payoff_window(self, value: str) -> tuple[int | None, int | None]:
        match = re.fullmatch(r"chapter:(?P<start>\d{1,4})-(?P<end>\d{1,4})", value.strip())
        if match is None:
            return None, None
        return int(match.group("start")), int(match.group("end"))

    def _read_json_if_exists(self, root: Path, relative_path: str) -> Any:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            return json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}

    def _chapter_order(self, chapter_id: str) -> int | None:
        return int(chapter_id) if chapter_id.isdigit() else None
