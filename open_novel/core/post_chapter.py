from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from open_novel.core.chapter_pipeline import ChapterPipelineService
from open_novel.core.character_state import anchors_for_state
from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import (
    CanonPatch,
    CanonPatchOperation,
    ChapterReviewItem,
    PostChapterReview,
)
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.text_support import cjk_fragments, important_terms, text_supports_claim
from open_novel.core.writing_learning import WritingLearningService


class PostChapterService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        context_pack_service: ContextPackService | None = None,
        writing_learning_service: WritingLearningService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.context_pack_service = context_pack_service or ContextPackService(
            self.project_service,
            self.story_guidance,
        )
        self.writing_learning_service = writing_learning_service or WritingLearningService(
            self.project_service
        )

    def review_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"reviews/{normalized}.review.json"

    def patch_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"patches/{normalized}.canon-patch.json"

    def build_review(self, root: Path, chapter_id: str) -> PostChapterReview:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        chapter_path = f"chapters/{normalized}.md"
        chapter_text = self.project_service.read_text(root, chapter_path)
        contract = self.story_guidance.read_scene_contract(root, normalized)
        self.context_pack_service.build_context_pack(root, normalized)

        summary = self._chapter_summary(chapter_text, contract.focus)
        items = [
            ChapterReviewItem(
                id=f"review_{normalized}_summary",
                kind="summary",
                text=summary,
                evidence=[chapter_path],
                payload={"chapterId": normalized, "summary": summary},
            )
        ]
        items.extend(
            self._items_from_contract(normalized, chapter_path, chapter_text, contract.model_dump())
        )
        items.extend(
            self._risk_items_from_contract(
                normalized,
                chapter_path,
                chapter_text,
                contract.model_dump(),
            )
        )
        items.extend(self._close_items_from_memory(root, normalized, chapter_path, chapter_text))

        review = PostChapterReview(
            chapterId=normalized,
            source=chapter_path,
            summary=summary,
            items=items,
        )
        self._write_json(root, self.review_path(normalized), review.model_dump(mode="json"))
        ChapterPipelineService(self.project_service).update_step(
            root,
            normalized,
            "post_review",
            artifact=self.review_path(normalized),
            message="章后审稿已生成",
        )
        self.writing_learning_service.learn_from_review(root, normalized, review.items)
        self.context_pack_service.build_context_pack(root, normalized)
        return review

    def read_review(self, root: Path, chapter_id: str) -> PostChapterReview:
        return PostChapterReview.model_validate_json(
            self._read_text(root, self.review_path(chapter_id))
        )

    def propose_canon_patch(self, root: Path, chapter_id: str) -> CanonPatch:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        review = self.read_review(root, normalized)
        operations: list[CanonPatchOperation] = []
        for item in review.items:
            operation = self._operation_for_review_item(normalized, item)
            if operation is not None:
                if self._should_auto_accept_operation(operation):
                    operation.status = "accepted"
                operations.append(operation)
        patch = CanonPatch(
            chapterId=normalized,
            sourceReview=self.review_path(normalized),
            operations=operations,
        )
        self._write_json(root, self.patch_path(normalized), patch.model_dump(mode="json"))
        ChapterPipelineService(self.project_service).update_step(
            root,
            normalized,
            "canon_patch",
            artifact=self.patch_path(normalized),
            message="长期记忆建议已生成",
        )
        return patch

    def add_world_rule_review_item(
        self,
        root: Path,
        chapter_id: str,
        *,
        rule_id: str,
        rule: str,
        forbidden: str,
        evidence: list[str],
    ) -> PostChapterReview:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        values = {
            "rule_id": rule_id.strip(),
            "rule": rule.strip(),
            "forbidden": forbidden.strip(),
        }
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise ValueError("永久禁止项缺少 " + "、".join(missing))
        review = self.read_review(root, normalized)
        item = ChapterReviewItem(
            id=f"review_{normalized}_world_rule_{values['rule_id']}",
            kind="world_rule",
            text=values["rule"],
            evidence=[str(item) for item in evidence if str(item).strip()],
            payload={
                "id": values["rule_id"],
                "rule": values["rule"],
                "forbidden": values["forbidden"],
                "source": f"chapters/{normalized}.md",
                "chapterId": normalized,
                "evidence": [str(item) for item in evidence if str(item).strip()],
                "confidence": 1,
            },
        )
        review.items = [entry for entry in review.items if entry.id != item.id]
        review.items.append(item)
        self._write_json(root, self.review_path(normalized), review.model_dump(mode="json"))
        return review

    def read_canon_patch(self, root: Path, chapter_id: str) -> CanonPatch:
        return CanonPatch.model_validate_json(self._read_text(root, self.patch_path(chapter_id)))

    def accept_canon_patch(
        self,
        root: Path,
        chapter_id: str,
        operation_ids: list[str] | None = None,
    ) -> CanonPatch:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        patch = self.read_canon_patch(root, normalized)
        selected = set(operation_ids or [])
        for operation in patch.operations:
            if operation.status != "proposed":
                continue
            if operation.action == "defer":
                continue
            if selected and operation.id not in selected:
                continue
            operation.status = "accepted"
        self._write_json(root, self.patch_path(normalized), patch.model_dump(mode="json"))
        return patch

    def update_canon_patch_operations(
        self,
        root: Path,
        chapter_id: str,
        operation_ids: list[str],
        status: Literal["accepted", "rejected", "deferred"],
    ) -> CanonPatch:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        if not operation_ids:
            raise ValueError("operation_ids is required")
        patch = self.read_canon_patch(root, normalized)
        selected = set(operation_ids)
        matched = False
        for operation in patch.operations:
            if operation.id not in selected:
                continue
            matched = True
            if operation.status == "applied":
                raise ValueError(f"cannot change applied canon patch operation: {operation.id}")
            if status == "accepted" and operation.action == "defer":
                operation.status = "rejected"
                continue
            operation.status = status
        if not matched:
            raise FileNotFoundError("canon patch operation not found")
        self._write_json(root, self.patch_path(normalized), patch.model_dump(mode="json"))
        return patch

    def apply_canon_patch(self, root: Path, chapter_id: str) -> CanonPatch:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        patch = self.read_canon_patch(root, normalized)
        for operation in patch.operations:
            if operation.status != "accepted":
                continue
            self._apply_operation(root, operation)
            operation.status = "applied"
        self._write_json(root, self.patch_path(normalized), patch.model_dump(mode="json"))
        self._rebuild_context_pack_if_possible(root, normalized)
        next_chapter = f"{int(normalized) + 1:03d}" if normalized.isdigit() else normalized
        self._rebuild_context_pack_if_possible(root, next_chapter)
        return patch

    def build_review_and_patch(self, root: Path, chapter_id: str) -> CanonPatch:
        self.build_review(root, chapter_id)
        return self.propose_canon_patch(root, chapter_id)

    def _items_from_contract(
        self,
        chapter_id: str,
        chapter_path: str,
        chapter_text: str,
        contract: dict[str, Any],
    ) -> list[ChapterReviewItem]:
        items: list[ChapterReviewItem] = []
        if contract.get("outcome"):
            supported = self._text_supports(chapter_text, contract["outcome"])
            outcome_evidence = [chapter_path, f"story/chapter-briefs/{chapter_id}.json#outcome"]
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_fact_outcome",
                    kind="fact",
                    text=str(contract["outcome"]),
                    evidence=outcome_evidence,
                    payload={
                        "id": f"fact_{chapter_id}_outcome",
                        "type": "chapter_outcome",
                        "source": chapter_path,
                        "validFrom": f"chapter:{chapter_id}",
                        "text": contract["outcome"],
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_timeline_outcome",
                    kind="timeline_event",
                    text=str(contract["outcome"]),
                    evidence=outcome_evidence,
                    payload={
                        "id": f"event_{chapter_id}_outcome",
                        "order": self._event_order(chapter_id),
                        "label": contract["outcome"],
                        "chapterId": chapter_id,
                        "source": chapter_path,
                        "evidence": outcome_evidence,
                        "summary": contract["outcome"],
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
        if contract.get("hook"):
            supported = self._text_supports(chapter_text, contract["hook"])
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_open_loop_hook",
                    kind="open_loop",
                    text=str(contract["hook"]),
                    evidence=[chapter_path, f"story/chapter-briefs/{chapter_id}.json#hook"],
                    payload={
                        "id": f"loop_{chapter_id}_hook",
                        "kind": "hook",
                        "introducedAt": f"chapter:{chapter_id}",
                        "text": contract["hook"],
                        "expectedPayoffWindow": self._default_payoff_window(chapter_id),
                        "status": "open",
                        "priority": "medium",
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
        if contract.get("emotionalBeat"):
            supported = self._text_supports(chapter_text, contract["emotionalBeat"])
            relationship_beat = str(contract.get("relationshipBeat", ""))
            relationship_supported = bool(
                relationship_beat and self._text_supports(chapter_text, relationship_beat)
            )
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_emotional_beat",
                    kind="emotional_beat",
                    text=str(contract["emotionalBeat"]),
                    evidence=[
                        chapter_path,
                        f"story/chapter-briefs/{chapter_id}.json#emotionalBeat",
                    ],
                    payload={
                        "chapterId": chapter_id,
                        "beat": contract["emotionalBeat"],
                        "relationshipShift": relationship_beat if relationship_supported else "",
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_character_state",
                    kind="character_state",
                    text=str(contract["emotionalBeat"]),
                    evidence=[
                        chapter_path,
                        f"story/chapter-briefs/{chapter_id}.json#emotionalBeat",
                        f"story/chapter-briefs/{chapter_id}.json#relationshipBeat",
                    ],
                    payload={
                        "characterId": self._pov_character_id(contract),
                        "state": {
                            "chapterId": chapter_id,
                            "externalGoal": contract.get("goal", ""),
                            "emotion": contract["emotionalBeat"],
                            "relationshipChanges": [relationship_beat]
                            if relationship_supported
                            else [],
                            "source": chapter_path,
                            "evidence": [
                                chapter_path,
                                f"story/chapter-briefs/{chapter_id}.json#emotionalBeat",
                            ],
                        },
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
            if relationship_supported:
                items.append(
                    ChapterReviewItem(
                        id=f"review_{chapter_id}_relationship_state",
                        kind="relationship_state",
                        text=relationship_beat,
                        evidence=[
                            chapter_path,
                            f"story/chapter-briefs/{chapter_id}.json#relationshipBeat",
                        ],
                        payload=self._relationship_state_payload(
                            chapter_id,
                            chapter_path,
                            contract,
                            relationship_beat,
                        ),
                    )
                )
        for index, promise in enumerate(contract.get("readerPromises", []), start=1):
            supported = self._text_supports(chapter_text, str(promise))
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_promise_{index:02d}",
                    kind="promise_update",
                    text=str(promise),
                    evidence=[
                        chapter_path,
                        f"story/chapter-briefs/{chapter_id}.json#readerPromises",
                    ],
                    payload={
                        "id": f"promise_{chapter_id}_{index:02d}",
                        "type": "reader_promise",
                        "readerQuestion": promise,
                        "introducedAt": f"chapter:{chapter_id}",
                        "expectedPayoffWindow": self._default_payoff_window(chapter_id),
                        "status": "open",
                        "confidence": 1 if supported else 0.4,
                    },
                )
            )
        return items

    def _risk_items_from_contract(
        self,
        chapter_id: str,
        chapter_path: str,
        chapter_text: str,
        contract: dict[str, Any],
    ) -> list[ChapterReviewItem]:
        items: list[ChapterReviewItem] = []
        scalar_fields = [
            ("focus", "high", "本章重点没有被正文明确支撑。"),
            ("outcome", "high", "本章结果没有被正文明确支撑。"),
            ("hook", "high", "结尾钩子没有被正文明确支撑。"),
            ("emotionalBeat", "high", "本章情绪节拍没有被正文明确支撑。"),
            ("relationshipBeat", "medium", "关系变化没有被正文明确支撑。"),
            ("internalNeed", "medium", "人物内在需求没有被正文明确支撑。"),
            ("woundOrFear", "medium", "人物旧伤或恐惧没有被正文明确支撑。"),
            ("stakes", "high", "失败代价没有被正文明确支撑。"),
            ("cost", "high", "行动代价没有被正文明确支撑。"),
            ("subtext", "medium", "潜台词没有被正文明确支撑。"),
            ("aftertaste", "medium", "章节余味没有被正文明确支撑。"),
        ]
        for field, severity, message in scalar_fields:
            value = str(contract.get(field) or "")
            if not value or self._text_supports(chapter_text, value):
                continue
            items.append(
                self._continuity_risk_item(
                    chapter_id,
                    chapter_path,
                    field,
                    message,
                    value,
                    severity,
                )
            )

        for index, required in enumerate(contract.get("mustInclude", []), start=1):
            value = str(required)
            if not value or self._text_supports(chapter_text, value):
                continue
            items.append(
                self._continuity_risk_item(
                    chapter_id,
                    chapter_path,
                    f"mustInclude_{index:02d}",
                    "正文缺少必须包含内容。",
                    value,
                    "high",
                )
            )

        for index, forbidden in enumerate(contract.get("mustAvoid", []), start=1):
            value = str(forbidden)
            if not value or value not in chapter_text:
                continue
            items.append(
                self._continuity_risk_item(
                    chapter_id,
                    chapter_path,
                    f"mustAvoid_{index:02d}",
                    "正文触碰了禁止事项。",
                    value,
                    "blocker",
                )
            )

        for index, promise in enumerate(contract.get("readerPromises", []), start=1):
            value = str(promise)
            if not value or self._text_supports(chapter_text, value):
                continue
            items.append(
                self._continuity_risk_item(
                    chapter_id,
                    chapter_path,
                    f"readerPromises_{index:02d}",
                    "读者承诺没有被正文明确推进或建立。",
                    value,
                    "medium",
                )
            )
        return items

    def _continuity_risk_item(
        self,
        chapter_id: str,
        chapter_path: str,
        field: str,
        message: str,
        expected: str,
        severity: str,
    ) -> ChapterReviewItem:
        return ChapterReviewItem(
            id=f"review_{chapter_id}_risk_{field}",
            kind="continuity_risk",
            text=f"{message} 预期：{expected}",
            evidence=[chapter_path, f"story/chapter-briefs/{chapter_id}.json#{field}"],
            payload={
                "type": "contract_support_risk",
                "field": field,
                "severity": severity,
                "expected": expected,
                "confidence": 1,
            },
        )

    def _relationship_state_payload(
        self,
        chapter_id: str,
        chapter_path: str,
        contract: dict[str, Any],
        relationship_beat: str,
    ) -> dict[str, Any]:
        pov = self._pov_character_id(contract)
        counterpart = self._relationship_counterpart(relationship_beat, pov)
        relationship_type = self._relationship_type(relationship_beat)
        relationship_id = self._relationship_id(pov, counterpart, relationship_type)
        score = self._relationship_score(relationship_beat)
        return {
            "id": relationship_id,
            "fromCharacterId": pov,
            "toCharacterId": counterpart,
            "type": relationship_type,
            "quantifiedScore": score,
            "status": relationship_beat,
            "pressure": str(contract.get("conflict") or contract.get("stakes") or ""),
            "unresolvedEmotion": str(
                contract.get("subtext")
                or contract.get("woundOrFear")
                or contract.get("emotionalBeat")
                or ""
            ),
            "chapterId": chapter_id,
            "source": chapter_path,
            "evidence": [
                chapter_path,
                f"story/chapter-briefs/{chapter_id}.json#relationshipBeat",
            ],
        }

    def _pov_character_id(self, contract: dict[str, Any]) -> str:
        pov = str(contract.get("pov") or "unknown")
        normalized = re.sub(
            r"(?:第一|第二|第三)人称|有限视角|限知|全知|主视角|视角|POV",
            "",
            pov,
            flags=re.IGNORECASE,
        ).strip(" ，,。:：-_/")
        return normalized or "unknown"

    def _relationship_score(self, relationship_beat: str) -> float:
        text = relationship_beat
        score = 5.0
        positive = {
            "信任": 7.0,
            "亲近": 8.0,
            "保护": 7.5,
            "和解": 7.0,
            "敬": 6.5,
            "战友": 8.0,
        }
        negative = {
            "敌视": 2.0,
            "敌对": 2.0,
            "恨": 1.5,
            "怀疑": 4.0,
            "警惕": 4.0,
            "误会": 3.5,
            "背叛": 1.0,
            "恐惧": 3.0,
            "忌惮": 4.5,
        }
        for marker, value in positive.items():
            if marker in text:
                score = max(score, value)
        for marker, value in negative.items():
            if marker in text:
                score = min(score, value)
        if "有限" in text or "试探" in text:
            score = min(score, 6.5)
        return score

    def _relationship_counterpart(self, relationship_beat: str, pov: str) -> str:
        candidates = [
            "旧敌",
            "长老",
            "师父",
            "师兄",
            "师姐",
            "同伴",
            "母亲",
            "父亲",
            "妹妹",
            "姐姐",
            "恋人",
            "对手",
        ]
        for candidate in candidates:
            if candidate and candidate != pov and candidate in relationship_beat:
                return candidate
        return "unknown"

    def _relationship_type(self, relationship_beat: str) -> str:
        markers = [
            ("信任", "trust"),
            ("债", "debt"),
            ("欠", "debt"),
            ("怕", "fear"),
            ("恐惧", "fear"),
            ("误会", "misunderstanding"),
            ("误解", "misunderstanding"),
            ("护", "protection"),
            ("保护", "protection"),
            ("怀疑", "suspicion"),
            ("警惕", "suspicion"),
            ("忌惮", "respect"),
            ("敬", "respect"),
            ("敌", "rivalry"),
            ("敌视", "hostility"),
            ("恨", "hostility"),
        ]
        for marker, relationship_type in markers:
            if marker in relationship_beat:
                return relationship_type
        return "other"

    def _relationship_id(
        self,
        from_character_id: str,
        to_character_id: str,
        relationship_type: str,
    ) -> str:
        parts = [from_character_id or "unknown", to_character_id or "unknown", relationship_type]
        return "rel_" + "_".join(self._slug(part) for part in parts)

    def _slug(self, value: str) -> str:
        slug = "".join(char if char.isalnum() else "_" for char in value.strip())
        slug = "_".join(part for part in slug.split("_") if part)
        return slug.lower() or "unknown"

    def _operation_for_review_item(
        self,
        chapter_id: str,
        item: ChapterReviewItem,
    ) -> CanonPatchOperation | None:
        target_by_kind = {
            "summary": "memory/chapter-summaries.json",
            "fact": "memory/facts.json",
            "timeline_event": "memory/timeline-events.json",
            "character_state": "memory/character-states.json",
            "relationship_state": "memory/relationship-states.json",
            "open_loop": "memory/open-loops.json",
            "promise_update": "memory/promises.json",
            "emotional_beat": "memory/emotional-arcs.json",
            "world_rule": "memory/active-prohibitions.json",
        }
        target = target_by_kind.get(item.kind)
        if target is None:
            return None
        action = str(item.payload.get("_action") or "add")
        if action not in {"add", "update", "close", "defer"}:
            action = "defer"
        if action != "defer" and float(item.payload.get("confidence", 1)) < 0.8:
            action = "defer"
        payload = {key: value for key, value in item.payload.items() if key != "_action"}
        return CanonPatchOperation(
            id=f"op_{item.id}",
            action=action,
            target=target,
            source=f"reviews/{chapter_id}.review.json#{item.id}",
            evidence=item.evidence,
            payload=payload,
        )

    def _should_auto_accept_operation(self, operation: CanonPatchOperation) -> bool:
        confidence = float(operation.payload.get("confidence", 1))
        if (
            operation.action == "add"
            and operation.target == "memory/chapter-summaries.json"
            and confidence >= 0.95
        ):
            return True
        if (
            operation.action == "close"
            and operation.target == "memory/promises.json"
            and confidence >= 0.9
            and self._payload_has_payoff_evidence(operation.payload)
        ):
            return True
        return False

    def _payload_has_payoff_evidence(self, payload: dict[str, Any]) -> bool:
        text = json.dumps(payload, ensure_ascii=False)
        return any(marker in text for marker in ("兑现", "揭开", "揭晓", "完成", "解决", "真相"))

    def _apply_operation(self, root: Path, operation: CanonPatchOperation) -> None:
        data = self._read_json(root, operation.target)
        if operation.action == "add" and operation.target in {
            "memory/open-loops.json",
            "memory/promises.json",
        }:
            payload = {**operation.payload, "_operationId": operation.id}
            key = "loops" if operation.target == "memory/open-loops.json" else "promises"
            self._upsert_progress_item(data, key, payload)
            self._write_json(root, operation.target, data)
            return
        if self._operation_already_applied(data, operation.id):
            return
        payload = {**operation.payload, "_operationId": operation.id}
        if operation.target == "memory/chapter-summaries.json":
            self._append_to_list(data, "chapters", payload)
        elif operation.target == "memory/facts.json":
            self._append_to_list(data, "facts", payload)
        elif operation.target == "memory/timeline-events.json":
            self._append_to_list(data, "events", payload)
        elif operation.target == "memory/character-states.json":
            self._append_character_state(data, payload)
        elif operation.target == "memory/relationship-states.json":
            self._append_relationship_state(data, payload)
        elif operation.target == "memory/open-loops.json":
            if operation.action == "close":
                self._close_list_item(data, "loops", payload)
            elif operation.action == "update":
                self._update_list_item(data, "loops", payload)
            else:
                self._append_to_list(data, "loops", payload)
        elif operation.target == "memory/promises.json":
            if operation.action == "close":
                self._close_list_item(data, "promises", payload)
            elif operation.action == "update":
                self._update_list_item(data, "promises", payload)
            else:
                self._append_to_list(data, "promises", payload)
        elif operation.target == "memory/emotional-arcs.json":
            self._append_emotional_beat(data, payload)
        elif operation.target == "memory/active-prohibitions.json":
            required = ["id", "rule", "forbidden"]
            if any(not str(payload.get(field) or "").strip() for field in required):
                raise ValueError("active prohibition requires id, rule and forbidden")
            self._upsert_by_id(data, "items", payload)
        else:
            raise ValueError(f"unsupported canon patch target: {operation.target}")
        self._write_json(root, operation.target, data)

    def _append_to_list(self, data: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
        values = data.setdefault(key, [])
        if not isinstance(values, list):
            raise ValueError(f"memory key is not a list: {key}")
        values.append(payload)

    def _upsert_by_id(self, data: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
        values = data.setdefault(key, [])
        if not isinstance(values, list):
            raise ValueError(f"memory key is not a list: {key}")
        item_id = str(payload.get("id") or "")
        for index, item in enumerate(values):
            if isinstance(item, dict) and str(item.get("id") or "") == item_id:
                values[index] = payload
                return
        values.append(payload)

    def _upsert_progress_item(
        self,
        data: dict[str, Any],
        key: str,
        payload: dict[str, Any],
    ) -> None:
        values = data.setdefault(key, [])
        if not isinstance(values, list):
            raise ValueError(f"memory key is not a list: {key}")
        item_id = str(payload.get("id") or "")
        if not item_id:
            raise ValueError(f"{key} add operation payload requires id")
        matches = [
            (index, value)
            for index, value in enumerate(values)
            if isinstance(value, dict) and value.get("id") == item_id
        ]
        if not matches:
            values.append(payload)
            return

        terminal = next(
            (
                value
                for _, value in matches
                if value.get("status") in {"partial", "closed", "paid_off"}
            ),
            matches[0][1],
        )
        preserved = {
            field: terminal[field]
            for field in (
                "status",
                "payoffAt",
                "closedBy",
                "lastTouchedAt",
                "lastTouchedBy",
                "_operationId",
            )
            if field in terminal
        }
        first_index = matches[0][0]
        values[first_index] = {**terminal, **payload, **preserved}
        for index, _ in reversed(matches[1:]):
            values.pop(index)

    def _close_list_item(self, data: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
        item = self._find_list_item(data, key, payload, "close")
        if item.get("status") in {"closed", "paid_off"}:
            item.setdefault("_operationId", payload.get("_operationId"))
            return
        item["status"] = str(payload.get("status") or "closed")
        item["payoffAt"] = payload.get("payoffAt")
        item["closedBy"] = payload.get("source")
        item["_operationId"] = payload.get("_operationId")

    def _update_list_item(self, data: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
        item = self._find_list_item(data, key, payload, "update")
        if item.get("status") in {"closed", "paid_off"}:
            item.setdefault("_operationId", payload.get("_operationId"))
            return
        item["status"] = str(payload.get("status") or item.get("status") or "partial")
        item["lastTouchedAt"] = payload.get("lastTouchedAt")
        item["lastTouchedBy"] = payload.get("source")
        item["_operationId"] = payload.get("_operationId")

    def _find_list_item(
        self,
        data: dict[str, Any],
        key: str,
        payload: dict[str, Any],
        action: str,
    ) -> dict[str, Any]:
        values = data.setdefault(key, [])
        if not isinstance(values, list):
            raise ValueError(f"memory key is not a list: {key}")
        item_id = str(payload.get("id") or "")
        if not item_id:
            raise ValueError(f"{action} operation payload requires id")
        item = next(
            (value for value in values if isinstance(value, dict) and value.get("id") == item_id),
            None,
        )
        if item is None:
            raise ValueError(f"cannot {action} missing memory item: {item_id}")
        return item

    def _append_emotional_beat(self, data: dict[str, Any], payload: dict[str, Any]) -> None:
        characters = data.setdefault("characters", [])
        if not isinstance(characters, list):
            raise ValueError("memory emotional-arcs characters is not a list")
        character_id = str(payload.get("characterId") or "unknown")
        character = next(
            (
                item
                for item in characters
                if isinstance(item, dict) and item.get("characterId") == character_id
            ),
            None,
        )
        if character is None:
            character = {"characterId": character_id, "beats": []}
            characters.append(character)
        beats = character.setdefault("beats", [])
        if not isinstance(beats, list):
            raise ValueError("memory emotional-arcs beats is not a list")
        beats.append(payload)

    def _append_character_state(self, data: dict[str, Any], payload: dict[str, Any]) -> None:
        characters = data.setdefault("characters", [])
        if not isinstance(characters, list):
            raise ValueError("memory character-states characters is not a list")
        character_id = str(payload.get("characterId") or "unknown")
        character = next(
            (
                item
                for item in characters
                if isinstance(item, dict) and item.get("characterId") == character_id
            ),
            None,
        )
        if character is None:
            character = {"characterId": character_id, "states": []}
            characters.append(character)
        states = character.setdefault("states", [])
        if not isinstance(states, list):
            raise ValueError("memory character-states states is not a list")
        state = payload.get("state")
        if not isinstance(state, dict):
            raise ValueError("memory character-state payload state is not an object")
        state_with_anchors = {**state}
        state_with_anchors.setdefault("continuityAnchors", anchors_for_state(state_with_anchors))
        states.append({**state_with_anchors, "_operationId": payload.get("_operationId")})

    def _append_relationship_state(self, data: dict[str, Any], payload: dict[str, Any]) -> None:
        relationships = data.setdefault("relationships", [])
        if not isinstance(relationships, list):
            raise ValueError("memory relationship-states relationships is not a list")
        relationship_id = str(payload.get("id") or "")
        if not relationship_id:
            raise ValueError("relationship-state payload requires id")
        existing = next(
            (
                item
                for item in relationships
                if isinstance(item, dict) and item.get("id") == relationship_id
            ),
            None,
        )
        history_item = {
            "chapterId": payload.get("chapterId", ""),
            "status": payload.get("status", ""),
            "pressure": payload.get("pressure", ""),
            "unresolvedEmotion": payload.get("unresolvedEmotion", ""),
            "score": payload.get("quantifiedScore", 5.0),
            "source": payload.get("source", ""),
            "evidence": payload.get("evidence", []),
        }
        if existing is None:
            relationships.append(
                {
                    **payload,
                    "history": [history_item],
                    "_operationId": payload.get("_operationId"),
                }
            )
            return
        for key in (
            "type",
            "quantifiedScore",
            "status",
            "pressure",
            "unresolvedEmotion",
            "chapterId",
            "source",
            "evidence",
        ):
            if payload.get(key) not in (None, "", []):
                existing[key] = payload[key]
        history = existing.setdefault("history", [])
        if not isinstance(history, list):
            raise ValueError("memory relationship-states history is not a list")
        previous_score = (
            float(history[-1].get("score") or payload.get("quantifiedScore") or 5.0)
            if history
            else float(payload.get("quantifiedScore") or 5.0)
        )
        history_item["delta"] = round(float(history_item["score"] or 5.0) - previous_score, 2)
        history.append(history_item)
        existing["_operationId"] = payload.get("_operationId")

    def _operation_already_applied(self, data: Any, operation_id: str) -> bool:
        return self._contains_operation_id(data, operation_id)

    def _contains_operation_id(self, value: Any, operation_id: str) -> bool:
        if isinstance(value, dict):
            if value.get("_operationId") == operation_id:
                return True
            return any(self._contains_operation_id(item, operation_id) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_operation_id(item, operation_id) for item in value)
        return False

    def _close_items_from_memory(
        self,
        root: Path,
        chapter_id: str,
        chapter_path: str,
        chapter_text: str,
    ) -> list[ChapterReviewItem]:
        items: list[ChapterReviewItem] = []
        items.extend(
            self._close_items_for_memory_file(
                root,
                chapter_id,
                chapter_path,
                chapter_text,
                "memory/promises.json",
                "promises",
                "promise_update",
                ("readerQuestion", "text"),
            )
        )
        items.extend(
            self._close_items_for_memory_file(
                root,
                chapter_id,
                chapter_path,
                chapter_text,
                "memory/open-loops.json",
                "loops",
                "open_loop",
                ("text", "readerQuestion"),
            )
        )
        return items

    def _close_items_for_memory_file(
        self,
        root: Path,
        chapter_id: str,
        chapter_path: str,
        chapter_text: str,
        relative_path: str,
        list_key: str,
        kind: Literal["promise_update", "open_loop"],
        text_keys: tuple[str, ...],
    ) -> list[ChapterReviewItem]:
        data = self._read_json(root, relative_path)
        values = data.get(list_key)
        if not isinstance(values, list):
            return []
        items: list[ChapterReviewItem] = []
        for value in values:
            if not isinstance(value, dict) or value.get("status") not in (None, "open", "partial"):
                continue
            text = " ".join(str(value.get(key, "")) for key in text_keys if value.get(key))
            if not text or not self._memory_item_touched(chapter_text, text):
                continue
            item_id = str(value.get("id") or "")
            if not item_id:
                continue
            action = "close" if self._text_resolves_item(chapter_text) else "update"
            status = "paid_off" if action == "close" else "partial"
            payload: dict[str, object] = {
                "_action": action,
                "id": item_id,
                "status": status,
                "source": chapter_path,
                "confidence": 1,
            }
            if action == "close":
                payload["payoffAt"] = f"chapter:{chapter_id}"
            else:
                payload["lastTouchedAt"] = f"chapter:{chapter_id}"
            items.append(
                ChapterReviewItem(
                    id=f"review_{chapter_id}_{action}_{item_id}",
                    kind=kind,
                    text=(
                        f"关闭已兑现记忆项：{text}"
                        if action == "close"
                        else f"标记已触碰记忆项：{text}"
                    ),
                    evidence=[chapter_path, f"{relative_path}#{item_id}"],
                    payload=payload,
                )
            )
        return items

    def _text_resolves_item(self, chapter_text: str) -> bool:
        resolve_terms = [
            "兑现",
            "回收",
            "揭开",
            "揭晓",
            "真相",
            "查清",
            "确认",
            "解决",
            "打破",
            "答案",
        ]
        return any(term in chapter_text for term in resolve_terms)

    def _memory_item_touched(self, chapter_text: str, item_text: str) -> bool:
        if self._text_supports(chapter_text, item_text):
            return True
        fragments = self._chinese_fragments(item_text)
        return bool(fragments and any(fragment in chapter_text for fragment in fragments))

    def _chinese_fragments(self, text: str) -> list[str]:
        fragments = cjk_fragments(text)
        windows: list[str] = []
        for fragment in fragments:
            windows.append(fragment)
            windows.extend(fragment[index : index + 2] for index in range(len(fragment) - 1))
        return windows

    def _chapter_summary(self, chapter_text: str, fallback: str) -> str:
        lines = [
            line.strip()
            for line in chapter_text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if lines:
            return lines[0][:240]
        return fallback[:240] if fallback else "本章已被接受为正文。"

    def _text_supports(self, chapter_text: str, claim: str) -> bool:
        return text_supports_claim(chapter_text, claim)

    def _important_terms(self, text: str) -> list[str]:
        return important_terms(text)

    def _event_order(self, chapter_id: str) -> int:
        return int(chapter_id) if chapter_id.isdigit() else 0

    def _default_payoff_window(self, chapter_id: str) -> str:
        if not chapter_id.isdigit():
            return ""
        start = int(chapter_id) + 3
        end = int(chapter_id) + 8
        return f"chapter:{start:03d}-{end:03d}"

    def _read_text(self, root: Path, relative_path: str) -> str:
        return self.project_service.read_text(root, relative_path)

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {"schemaVersion": 1}
        return json.loads(self.project_service.read_text(root, relative_path))

    def _write_json(self, root: Path, relative_path: str, data: dict[str, Any]) -> None:
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        )

    def _rebuild_context_pack_if_possible(self, root: Path, chapter_id: str) -> None:
        try:
            self.context_pack_service.build_context_pack(root, chapter_id)
        except FileNotFoundError:
            return
