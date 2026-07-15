from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService


class RelationshipGraphService:
    memory_path = "memory/relationship-states.json"
    transition_markers = ("从", "转为", "变成", "开始", "不再", "重新", "逐渐", "终于", "被迫")
    signal_terms = {
        "trust": ("信任", "托付", "相信"),
        "trust_loss": ("不信任", "怀疑", "戒备", "防备"),
        "respect": ("忌惮", "敬重", "尊重", "认可"),
        "contempt": ("轻蔑", "看不起", "羞辱"),
        "fear": ("害怕", "恐惧", "畏惧"),
        "hostility": ("敌意", "敌对", "阻挠", "追杀"),
        "protection": ("保护", "护住", "挡下", "牺牲"),
        "debt": ("亏欠", "欠", "人情", "债"),
        "misunderstanding": ("误会", "误解", "错认"),
        "rivalry": ("竞争", "对立", "旧敌", "较量"),
        "pressure": ("压力", "施压", "逼迫", "公开", "威胁"),
        "softening": ("缓和", "动摇", "不忍", "心软"),
    }

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def build_graph(self, root: Path) -> dict[str, object]:
        memory = self._read_memory(root)
        relationships = memory.get("relationships")
        if not isinstance(relationships, list):
            relationships = []
        edges_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
        for index, relationship in enumerate(relationships):
            if not isinstance(relationship, dict):
                continue
            edge_key = self._edge_key(relationship)
            event = self._event(relationship, index)
            edge = edges_by_key.setdefault(
                edge_key,
                {
                    "id": self._edge_id(edge_key),
                    "fromCharacterId": edge_key[0],
                    "toCharacterId": edge_key[1],
                    "type": edge_key[2],
                    "latestStatus": "",
                    "latestPressure": "",
                    "latestUnresolvedEmotion": "",
                    "latestChapterId": "",
                    "latestSource": "",
                    "eventCount": 0,
                    "history": [],
                },
            )
            history = edge["history"]
            if isinstance(history, list):
                history.append(event)
            edge["eventCount"] = int(edge["eventCount"]) + 1
            if self._is_later_event(event, edge):
                edge["latestStatus"] = event["status"]
                edge["latestPressure"] = event["pressure"]
                edge["latestUnresolvedEmotion"] = event["unresolvedEmotion"]
                edge["latestChapterId"] = event["chapterId"]
                edge["latestSource"] = event["source"]
        for edge in edges_by_key.values():
            history = edge.get("history")
            if isinstance(history, list):
                history.sort(
                    key=lambda event: (
                        self._chapter_order(str(event.get("chapterId") or "")),
                        int(event.get("sequenceIndex") or 0),
                    )
                )
                self._annotate_transitions(history)
                latest = history[-1] if history else {}
                edge["latestTransition"] = str(latest.get("transition") or "")
                edge["latestTransitionSignals"] = self._string_list(
                    latest.get("transitionSignals")
                )
        edges = sorted(
            edges_by_key.values(),
            key=lambda edge: (
                str(edge.get("latestChapterId") or ""),
                str(edge.get("fromCharacterId") or ""),
                str(edge.get("toCharacterId") or ""),
                str(edge.get("type") or ""),
            ),
            reverse=True,
        )
        return {
            "schemaVersion": 1,
            "source": self.memory_path,
            "nodeCount": len(self._nodes_from_edges(edges)),
            "edgeCount": len(edges),
            "nodes": self._nodes_from_edges(edges),
            "edges": edges,
        }

    def edge_detail(self, root: Path, edge_id: str) -> dict[str, object]:
        normalized_edge_id = edge_id.strip()
        if not normalized_edge_id:
            raise ValueError("缺少关系编号。")
        graph = self.build_graph(root)
        edges = graph.get("edges")
        if not isinstance(edges, list):
            raise FileNotFoundError(f"missing relationship edge: {normalized_edge_id}")
        for edge in edges:
            if isinstance(edge, dict) and str(edge.get("id") or "") == normalized_edge_id:
                history = edge.get("history")
                event_count = len(history) if isinstance(history, list) else 0
                timeline = self._edge_timeline(history if isinstance(history, list) else [])
                return {
                    "schemaVersion": 1,
                    "source": self.memory_path,
                    "edge": edge,
                    "eventCount": event_count,
                    "timeline": timeline,
                    "reviewSummary": self._review_summary(timeline),
                    "nodes": graph.get("nodes", []),
                }
        raise FileNotFoundError(f"missing relationship edge: {normalized_edge_id}")

    def update_relationship_event(
        self,
        root: Path,
        event_id: str,
        *,
        relationship_type: str = "",
        status: str,
        pressure: str = "",
        unresolved_emotion: str = "",
        evidence: list[str] | None = None,
    ) -> dict[str, object]:
        normalized_event_id = event_id.strip()
        if not normalized_event_id:
            raise ValueError("缺少关系事件编号。")
        memory = self._read_memory(root)
        relationships = memory.get("relationships")
        if not isinstance(relationships, list):
            relationships = []
            memory["relationships"] = relationships
        target: dict[str, Any] | None = None
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            if str(relationship.get("id") or "") == normalized_event_id:
                target = relationship
                break
        if target is None:
            raise FileNotFoundError(f"missing relationship event: {normalized_event_id}")
        clean_type = relationship_type.strip()
        if clean_type:
            target["type"] = clean_type
        clean_status = status.strip()
        if not clean_status:
            raise ValueError("关系状态不能为空。")
        target["status"] = clean_status
        target["pressure"] = pressure.strip()
        target["unresolvedEmotion"] = unresolved_emotion.strip()
        if evidence is not None:
            target["evidence"] = [item.strip() for item in evidence if item.strip()]
        target["reviewStatus"] = "reviewed"
        self._write_memory(root, memory)
        graph = self.build_graph(root)
        return {
            "schemaVersion": 1,
            "eventId": normalized_event_id,
            "updatedEvent": dict(target),
            "edge": self._find_edge_for_event(graph, normalized_event_id),
            "graph": graph,
        }

    def _read_memory(self, root: Path) -> dict[str, Any]:
        if not self.project_service.file_exists(root, self.memory_path):
            return {"schemaVersion": 1, "relationships": []}
        data = json.loads(self.project_service.read_text(root, self.memory_path))
        if not isinstance(data, dict):
            raise ValueError(f"关系记忆格式必须是对象：{self.memory_path}")
        return data

    def _write_memory(self, root: Path, memory: dict[str, Any]) -> None:
        self.project_service.write_text(
            root,
            self.memory_path,
            json.dumps(memory, ensure_ascii=False, indent=2) + "\n",
        )

    def _find_edge_for_event(
        self,
        graph: dict[str, object],
        event_id: str,
    ) -> dict[str, object]:
        edges = graph.get("edges")
        if not isinstance(edges, list):
            return {}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            history = edge.get("history")
            if not isinstance(history, list):
                continue
            for event in history:
                if isinstance(event, dict) and str(event.get("id") or "") == event_id:
                    return edge
        return {}

    def _edge_key(self, relationship: dict[str, Any]) -> tuple[str, str, str]:
        from_character = self._clean_id(relationship.get("fromCharacterId"), "unknown")
        to_character = self._clean_id(relationship.get("toCharacterId"), "unknown")
        relationship_type = self._clean_id(relationship.get("type"), "other")
        return from_character, to_character, relationship_type

    def _event(self, relationship: dict[str, Any], index: int) -> dict[str, object]:
        return {
            "id": str(relationship.get("id") or f"relationship_{index + 1:03d}"),
            "status": str(relationship.get("status") or ""),
            "pressure": str(relationship.get("pressure") or ""),
            "unresolvedEmotion": str(relationship.get("unresolvedEmotion") or ""),
            "quantifiedScore": self._float_value(relationship.get("quantifiedScore"), 5.0),
            "chapterId": str(relationship.get("chapterId") or ""),
            "source": str(relationship.get("source") or self.memory_path),
            "evidence": self._string_list(relationship.get("evidence")),
            "sequenceIndex": index,
            "transition": "",
            "transitionSignals": [],
            "scoreDelta": 0.0,
        }

    def _annotate_transitions(self, history: list[dict[str, object]]) -> None:
        previous: dict[str, object] | None = None
        for event in history:
            signals = self._transition_signals(event)
            event["transitionSignals"] = signals
            if previous is None:
                event["transition"] = "established"
                event["scoreDelta"] = 0.0
            elif self._same_relationship_state(previous, event):
                event["transition"] = "maintained"
                event["scoreDelta"] = self._score_delta(previous, event)
            elif self._has_explicit_transition(event):
                event["transition"] = "explicit-shift"
                event["scoreDelta"] = self._score_delta(previous, event)
            else:
                event["transition"] = "shifted"
                event["scoreDelta"] = self._score_delta(previous, event)
            previous = event

    def _same_relationship_state(
        self,
        previous: dict[str, object],
        current: dict[str, object],
    ) -> bool:
        keys = ("status", "pressure", "unresolvedEmotion")
        return all(str(previous.get(key) or "") == str(current.get(key) or "") for key in keys)

    def _has_explicit_transition(self, event: dict[str, object]) -> bool:
        text = self._event_text(event)
        return any(marker in text for marker in self.transition_markers)

    def _transition_signals(self, event: dict[str, object]) -> list[str]:
        text = self._event_text(event)
        signals = [
            signal
            for signal, terms in self.signal_terms.items()
            if any(term in text for term in terms)
        ]
        if self._has_explicit_transition(event):
            signals.insert(0, "explicit-transition")
        return sorted(set(signals), key=signals.index)

    def _event_text(self, event: dict[str, object]) -> str:
        return " ".join(
            str(event.get(key) or "")
            for key in ("status", "pressure", "unresolvedEmotion")
        )

    def _edge_timeline(self, history: list[dict[str, object]]) -> list[dict[str, object]]:
        timeline: list[dict[str, object]] = []
        for event in history:
            signals = self._string_list(event.get("transitionSignals"))
            transition = str(event.get("transition") or "")
            score_delta = float(event.get("scoreDelta") or 0.0)
            jump_needs_review = abs(score_delta) > 3.0
            needs_review = (
                transition == "shifted" and "explicit-transition" not in signals
            ) or jump_needs_review
            timeline.append(
                {
                    "eventId": str(event.get("id") or ""),
                    "chapterId": str(event.get("chapterId") or ""),
                    "transition": transition,
                    "signals": signals,
                    "quantifiedScore": float(event.get("quantifiedScore") or 5.0),
                    "scoreDelta": score_delta,
                    "statusPreview": self._preview(str(event.get("status") or "")),
                    "pressurePreview": self._preview(str(event.get("pressure") or "")),
                    "unresolvedEmotionPreview": self._preview(
                        str(event.get("unresolvedEmotion") or "")
                    ),
                    "needsReview": needs_review,
                    "reviewReason": (
                        "关系评分变化过快"
                        if jump_needs_review
                        else
                        "关系状态发生变化，但缺少明确的转折依据"
                        if needs_review
                        else ""
                    ),
                }
            )
        return timeline

    def _review_summary(self, timeline: list[dict[str, object]]) -> dict[str, object]:
        review_items = [item for item in timeline if item.get("needsReview")]
        transition_counts: dict[str, int] = {}
        for item in timeline:
            transition = str(item.get("transition") or "unknown")
            transition_counts[transition] = transition_counts.get(transition, 0) + 1
        return {
            "eventCount": len(timeline),
            "needsReviewCount": len(review_items),
            "reviewEventIds": [str(item.get("eventId") or "") for item in review_items],
            "transitionCounts": transition_counts,
        }

    def _score_delta(self, previous: dict[str, object], current: dict[str, object]) -> float:
        return round(
            self._float_value(current.get("quantifiedScore"), 5.0)
            - self._float_value(previous.get("quantifiedScore"), 5.0),
            2,
        )

    def _float_value(self, value: object, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _preview(self, value: str, limit: int = 48) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}..."

    def _is_later_event(self, event: dict[str, object], edge: dict[str, object]) -> bool:
        latest = str(edge.get("latestChapterId") or "")
        current = str(event.get("chapterId") or "")
        if not latest:
            return True
        return self._chapter_order(current) >= self._chapter_order(latest)

    def _nodes_from_edges(self, edges: list[dict[str, object]]) -> list[dict[str, object]]:
        node_ids = sorted(
            {
                str(edge.get("fromCharacterId") or "")
                for edge in edges
                if str(edge.get("fromCharacterId") or "")
            }
            | {
                str(edge.get("toCharacterId") or "")
                for edge in edges
                if str(edge.get("toCharacterId") or "")
            }
        )
        return [{"id": node_id, "label": node_id} for node_id in node_ids]

    def _chapter_order(self, chapter_id: str) -> int:
        value = chapter_id.strip()
        if value.isdigit():
            return int(value)
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else 0

    def _edge_id(self, edge_key: tuple[str, str, str]) -> str:
        return "__".join(edge_key)

    def _clean_id(self, value: object, fallback: str) -> str:
        text = str(value or "").strip()
        return text or fallback

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]
