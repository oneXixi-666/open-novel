from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import (
    CharacterStatesMemory,
    MemoryRepairOperation,
    MemoryRepairProposal,
    MemoryValidationIssue,
    MemoryValidationReport,
    RelationshipStatesMemory,
    TimelineEventsMemory,
)
from open_novel.core.project import ProjectService


class MemoryValidationService:
    report_path = "runs/memory-validation.json"
    repair_report_path = "runs/memory-repair-proposal.json"
    model_schemas: dict[str, type[BaseModel]] = {
        "memory/timeline-events.json": TimelineEventsMemory,
        "memory/character-states.json": CharacterStatesMemory,
        "memory/relationship-states.json": RelationshipStatesMemory,
    }
    list_schemas = {
        "memory/facts.json": "facts",
        "memory/open-loops.json": "loops",
        "memory/chapter-summaries.json": "chapters",
        "memory/promises.json": "promises",
        "memory/emotional-arcs.json": "characters",
        "memory/writing-lessons.json": "lessons",
    }
    text_fields = {
        "memory/facts.json": ("text", "summary"),
        "memory/open-loops.json": ("text", "readerQuestion"),
        "memory/chapter-summaries.json": ("summary", "text"),
        "memory/promises.json": ("readerQuestion", "text"),
        "memory/writing-lessons.json": ("lesson",),
    }

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()
        self.context_pack_service = ContextPackService(self.project_service)

    def validate_project(self, root: Path) -> MemoryValidationReport:
        issues: list[MemoryValidationIssue] = []
        for relative_path, model in self.model_schemas.items():
            issues.extend(self._validate_model_file(root, relative_path, model))
        for relative_path, list_key in self.list_schemas.items():
            issues.extend(self._validate_list_file(root, relative_path, list_key))

        report = MemoryValidationReport(
            status=self._status(issues),
            score=self._score(issues),
            issues=issues,
        )
        self.project_service.write_text(
            root,
            self.report_path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def propose_repair(self, root: Path) -> MemoryRepairProposal:
        report = self.validate_project(root)
        operations = [
            operation
            for issue in report.issues
            if (operation := self._repair_operation_for_issue(issue)) is not None
        ]
        proposal = MemoryRepairProposal(
            sourceReport=self.report_path,
            operations=operations,
        )
        self.project_service.write_text(
            root,
            self.repair_report_path,
            json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return proposal

    def apply_safe_repairs(self, root: Path) -> MemoryRepairProposal:
        proposal = self.propose_repair(root)
        for operation in proposal.operations:
            if operation.action == "create_file":
                self._apply_create_file(root, operation)
            elif operation.action == "add_missing_list":
                self._apply_add_missing_list(root, operation)
            else:
                operation.status = "skipped"
                operation.message = "manual_fix operations require human review."
        self.project_service.write_text(
            root,
            self.repair_report_path,
            json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self.validate_project(root)
        self._rebuild_context_packs_after_memory_changes(root)
        return proposal

    def _validate_model_file(
        self,
        root: Path,
        relative_path: str,
        model: type[BaseModel],
    ) -> list[MemoryValidationIssue]:
        data, issue = self._read_json(root, relative_path)
        if issue is not None:
            return [issue]
        try:
            model.model_validate(data)
        except ValidationError as error:
            return [
                MemoryValidationIssue(
                    severity="blocker",
                    path=relative_path,
                    type="schema_error",
                    message=f"记忆文件结构不符合预期：{error.errors()[0]['msg']}",
                    evidence=[relative_path],
                )
            ]
        return self._validate_model_semantics(relative_path, data)

    def _validate_list_file(
        self,
        root: Path,
        relative_path: str,
        list_key: str,
    ) -> list[MemoryValidationIssue]:
        data, issue = self._read_json(root, relative_path)
        if issue is not None:
            return [issue]
        if not isinstance(data, dict):
            return [
                MemoryValidationIssue(
                    severity="blocker",
                    path=relative_path,
                    type="schema_error",
                    message="记忆文件顶层必须是 JSON object。",
                    evidence=[relative_path],
                )
            ]
        values = data.get(list_key)
        if not isinstance(values, list):
            return [
                MemoryValidationIssue(
                    severity="high",
                    path=relative_path,
                    type="missing_list",
                    message=f"记忆文件缺少列表字段：{list_key}",
                    evidence=[f"{relative_path}#{list_key}"],
                )
            ]
        if relative_path == "memory/emotional-arcs.json":
            return self._validate_emotional_arcs(relative_path, values)
        return self._validate_flat_list_items(relative_path, list_key, values)

    def _validate_model_semantics(
        self,
        relative_path: str,
        data: Any,
    ) -> list[MemoryValidationIssue]:
        if not isinstance(data, dict):
            return []
        if relative_path == "memory/timeline-events.json":
            events = data.get("events")
            if isinstance(events, list):
                return self._validate_timeline_events(relative_path, events)
        if relative_path == "memory/character-states.json":
            characters = data.get("characters")
            if isinstance(characters, list):
                return self._validate_character_states(relative_path, characters)
        if relative_path == "memory/relationship-states.json":
            relationships = data.get("relationships")
            if isinstance(relationships, list):
                return self._validate_relationship_states(relative_path, relationships)
        return []

    def _validate_timeline_events(
        self,
        relative_path: str,
        events: list[Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        issues.extend(self._duplicate_id_issues(relative_path, "events", events))
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                issues.append(self._item_schema_issue(relative_path, "events", index))
                continue
            item_ref = self._item_ref(relative_path, "events", event, index)
            if not str(event.get("label") or event.get("summary") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_text",
                        message="时间线事件缺少 label 或 summary，后续章节无法可靠引用。",
                        evidence=[item_ref],
                    )
                )
            order = event.get("order")
            if not isinstance(order, int) or order < 1:
                issues.append(
                    MemoryValidationIssue(
                        severity="medium",
                        path=relative_path,
                        type="invalid_order",
                        message="时间线事件 order 必须是从 1 开始的整数。",
                        evidence=[f"{item_ref}#order"],
                    )
                )
            issues.extend(self._field_format_issues(relative_path, item_ref, event))
        return issues

    def _validate_relationship_states(
        self,
        relative_path: str,
        relationships: list[Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        issues.extend(self._duplicate_id_issues(relative_path, "relationships", relationships))
        for index, relationship in enumerate(relationships):
            if not isinstance(relationship, dict):
                issues.append(self._item_schema_issue(relative_path, "relationships", index))
                continue
            item_ref = self._item_ref(relative_path, "relationships", relationship, index)
            if not str(relationship.get("fromCharacterId") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_from_character",
                        message="关系状态缺少 fromCharacterId，后续关系承接无法归属。",
                        evidence=[f"{item_ref}#fromCharacterId"],
                    )
                )
            if not str(relationship.get("toCharacterId") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="medium",
                        path=relative_path,
                        type="missing_to_character",
                        message="关系状态缺少 toCharacterId，后续关系压力会变得模糊。",
                        evidence=[f"{item_ref}#toCharacterId"],
                    )
                )
            if not str(relationship.get("status") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_relationship_status",
                        message="关系状态缺少 status，无法判断关系是否延续、反转或缓和。",
                        evidence=[f"{item_ref}#status"],
                    )
                )
            issues.extend(self._field_format_issues(relative_path, item_ref, relationship))
        return issues

    def _validate_character_states(
        self,
        relative_path: str,
        characters: list[Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        issues.extend(
            self._duplicate_id_issues(relative_path, "characters", characters, "characterId")
        )
        for char_index, character in enumerate(characters):
            if not isinstance(character, dict):
                issues.append(self._item_schema_issue(relative_path, "characters", char_index))
                continue
            character_ref = self._item_ref(
                relative_path,
                "characters",
                character,
                char_index,
                id_key="characterId",
            )
            if not str(character.get("characterId") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_id",
                        message="人物状态缺少 characterId，情绪和关系连续性无法归属。",
                        evidence=[character_ref],
                    )
                )
            states = character.get("states")
            if not isinstance(states, list):
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_list",
                        message="人物状态记录缺少 states 列表。",
                        evidence=[f"{character_ref}#states"],
                    )
                )
                continue
            for state_index, state in enumerate(states):
                if not isinstance(state, dict):
                    issues.append(
                        self._item_schema_issue(
                            relative_path,
                            f"{character_ref}/states",
                            state_index,
                        )
                    )
                    continue
                state_ref = f"{character_ref}/states/{state_index}"
                if not str(state.get("emotion") or "").strip():
                    issues.append(
                        MemoryValidationIssue(
                            severity="high",
                            path=relative_path,
                            type="missing_emotion",
                            message="人物状态缺少 emotion，下一章很容易丢失情感承接。",
                            evidence=[f"{state_ref}#emotion"],
                        )
                    )
                issues.extend(self._field_format_issues(relative_path, state_ref, state))
        return issues

    def _validate_flat_list_items(
        self,
        relative_path: str,
        list_key: str,
        values: list[Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        issues.extend(self._duplicate_id_issues(relative_path, list_key, values))
        text_fields = self.text_fields.get(relative_path, ())
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                issues.append(self._item_schema_issue(relative_path, list_key, index))
                continue
            item_ref = self._item_ref(relative_path, list_key, value, index)
            if text_fields and not self._has_any_text(value, text_fields):
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_text",
                        message="记忆条目缺少可供写作引用的文本字段。",
                        evidence=[item_ref],
                    )
                )
            issues.extend(self._field_format_issues(relative_path, item_ref, value))
        return issues

    def _validate_emotional_arcs(
        self,
        relative_path: str,
        characters: list[Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        issues.extend(
            self._duplicate_id_issues(relative_path, "characters", characters, "characterId")
        )
        for char_index, character in enumerate(characters):
            if not isinstance(character, dict):
                issues.append(self._item_schema_issue(relative_path, "characters", char_index))
                continue
            character_ref = self._item_ref(
                relative_path,
                "characters",
                character,
                char_index,
                id_key="characterId",
            )
            if not str(character.get("characterId") or "").strip():
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_id",
                        message="情绪弧缺少 characterId，情绪节拍无法归属到人物。",
                        evidence=[character_ref],
                    )
                )
            beats = character.get("beats")
            if not isinstance(beats, list):
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="missing_list",
                        message="情绪弧人物记录缺少 beats 列表。",
                        evidence=[f"{character_ref}#beats"],
                    )
                )
                continue
            for beat_index, beat in enumerate(beats):
                if not isinstance(beat, dict):
                    issues.append(
                        self._item_schema_issue(relative_path, f"{character_ref}/beats", beat_index)
                    )
                    continue
                beat_ref = f"{character_ref}/beats/{beat_index}"
                if not self._has_any_text(beat, ("beat", "emotion", "text")):
                    issues.append(
                        MemoryValidationIssue(
                            severity="high",
                            path=relative_path,
                            type="missing_emotional_beat",
                            message="情绪节拍缺少 beat/emotion/text，后续无法承接情感变化。",
                            evidence=[beat_ref],
                        )
                    )
                issues.extend(self._field_format_issues(relative_path, beat_ref, beat))
        return issues

    def _duplicate_id_issues(
        self,
        relative_path: str,
        list_key: str,
        values: list[Any],
        id_key: str = "id",
    ) -> list[MemoryValidationIssue]:
        seen: dict[str, str] = {}
        issues: list[MemoryValidationIssue] = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            item_id = str(value.get(id_key) or "").strip()
            if not item_id:
                continue
            item_ref = self._item_ref(relative_path, list_key, value, index, id_key=id_key)
            if item_id in seen:
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="duplicate_id",
                        message=f"记忆条目 ID 重复：{item_id}",
                        evidence=[seen[item_id], item_ref],
                    )
                )
                continue
            seen[item_id] = item_ref
        return issues

    def _field_format_issues(
        self,
        relative_path: str,
        item_ref: str,
        value: dict[str, Any],
    ) -> list[MemoryValidationIssue]:
        issues: list[MemoryValidationIssue] = []
        for field in ("chapterId", "validFrom", "introducedAt", "payoffAt", "lastTouchedAt"):
            raw = value.get(field)
            if raw is None or str(raw).strip() == "":
                continue
            if not self._is_chapter_ref(str(raw)):
                issues.append(
                    MemoryValidationIssue(
                        severity="medium",
                        path=relative_path,
                        type="invalid_chapter_ref",
                        message=f"章节引用格式不清晰：{field}={raw}",
                        evidence=[f"{item_ref}#{field}"],
                    )
                )
        payoff_window = value.get("expectedPayoffWindow")
        if payoff_window is not None and str(payoff_window).strip():
            if not self._is_payoff_window(str(payoff_window)):
                issues.append(
                    MemoryValidationIssue(
                        severity="high",
                        path=relative_path,
                        type="invalid_payoff_window",
                        message="兑现窗口必须使用 chapter:NNN-NNN 且起点不能晚于终点。",
                        evidence=[f"{item_ref}#expectedPayoffWindow"],
                    )
                )
        confidence = value.get("confidence")
        if confidence is not None and not self._is_confidence(confidence):
            issues.append(
                MemoryValidationIssue(
                    severity="medium",
                    path=relative_path,
                    type="invalid_confidence",
                    message="confidence 必须是 0 到 1 之间的数字。",
                    evidence=[f"{item_ref}#confidence"],
                )
            )
        evidence = value.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            issues.append(
                MemoryValidationIssue(
                    severity="medium",
                    path=relative_path,
                    type="invalid_evidence",
                    message="evidence 必须是列表，方便后续追溯记忆来源。",
                    evidence=[f"{item_ref}#evidence"],
                )
            )
        return issues

    def _item_schema_issue(
        self,
        relative_path: str,
        list_key: str,
        index: int,
    ) -> MemoryValidationIssue:
        return MemoryValidationIssue(
            severity="high",
            path=relative_path,
            type="item_schema_error",
            message="记忆列表条目必须是 JSON object。",
            evidence=[f"{relative_path}#{list_key}/{index}"],
        )

    def _item_ref(
        self,
        relative_path: str,
        list_key: str,
        value: dict[str, Any],
        index: int,
        id_key: str = "id",
    ) -> str:
        item_id = str(value.get(id_key) or "").strip()
        return f"{relative_path}#{item_id}" if item_id else f"{relative_path}#{list_key}/{index}"

    def _has_any_text(self, value: dict[str, Any], fields: tuple[str, ...]) -> bool:
        return any(str(value.get(field) or "").strip() for field in fields)

    def _is_chapter_ref(self, value: str) -> bool:
        stripped = value.strip()
        return bool(
            re.fullmatch(r"[A-Za-z0-9_-]+", stripped)
            or re.fullmatch(r"chapter:[A-Za-z0-9_-]+", stripped)
        )

    def _is_payoff_window(self, value: str) -> bool:
        match = re.fullmatch(r"chapter:(?P<start>\d{1,4})-(?P<end>\d{1,4})", value.strip())
        return bool(match and int(match.group("start")) <= int(match.group("end")))

    def _is_confidence(self, value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return 0 <= number <= 1

    def _read_json(
        self,
        root: Path,
        relative_path: str,
    ) -> tuple[Any, MemoryValidationIssue | None]:
        if not self.project_service.file_exists(root, relative_path):
            return None, MemoryValidationIssue(
                severity="medium",
                path=relative_path,
                type="missing_file",
                message="缺少标准记忆文件。",
                evidence=[relative_path],
            )
        try:
            return json.loads(self.project_service.read_text(root, relative_path)), None
        except json.JSONDecodeError as error:
            return None, MemoryValidationIssue(
                severity="blocker",
                path=relative_path,
                type="invalid_json",
                message=f"记忆文件不是有效 JSON：line {error.lineno}, column {error.colno}",
                evidence=[relative_path],
            )

    def _status(self, issues: list[MemoryValidationIssue]) -> str:
        if any(issue.severity == "blocker" for issue in issues):
            return "block"
        if self._score(issues) < 60:
            return "block"
        if issues:
            return "warn"
        return "pass"

    def _score(self, issues: list[MemoryValidationIssue]) -> int:
        penalty = {
            "blocker": 35,
            "high": 18,
            "medium": 9,
            "low": 3,
        }
        return max(0, 100 - sum(penalty[issue.severity] for issue in issues))

    def _repair_operation_for_issue(
        self,
        issue: MemoryValidationIssue,
    ) -> MemoryRepairOperation | None:
        if issue.type == "missing_file":
            starter = self._starter_json(issue.path)
            return MemoryRepairOperation(
                id=self._operation_id(issue),
                action="create_file",
                target=issue.path,
                source=f"{self.report_path}#{issue.path}",
                reason="创建缺失的标准记忆文件。",
                payload={"content": starter},
            )
        if issue.type == "missing_list":
            list_key = self.list_schemas.get(issue.path)
            if list_key is None:
                return None
            return MemoryRepairOperation(
                id=self._operation_id(issue),
                action="add_missing_list",
                target=issue.path,
                source=f"{self.report_path}#{issue.path}",
                reason=f"补充缺失的顶层列表字段：{list_key}",
                payload={"field": list_key, "value": []},
            )
        if issue.type in {
            "invalid_json",
            "schema_error",
            "item_schema_error",
            "duplicate_id",
            "missing_text",
            "missing_id",
            "missing_emotion",
            "missing_emotional_beat",
            "invalid_order",
            "invalid_chapter_ref",
            "invalid_payoff_window",
            "invalid_confidence",
            "invalid_evidence",
        }:
            return MemoryRepairOperation(
                id=self._operation_id(issue),
                action="manual_fix",
                target=issue.path,
                source=f"{self.report_path}#{issue.path}",
                reason="需要人工修复，避免自动覆盖可能仍有价值的记忆内容。",
                payload={
                    "issueType": issue.type,
                    "message": issue.message,
                    "starterContent": self._starter_json(issue.path),
                },
            )
        return None

    def _starter_json(self, relative_path: str) -> object:
        starter = ProjectService.starter_files.get(relative_path)
        if starter is None:
            return {}
        try:
            return json.loads(starter)
        except json.JSONDecodeError:
            return {}

    def _operation_id(self, issue: MemoryValidationIssue) -> str:
        normalized_path = (
            issue.path.replace("/", "_").replace(".", "_").replace("-", "_").strip("_")
        )
        return f"repair_{normalized_path}_{issue.type}"

    def _apply_create_file(self, root: Path, operation: MemoryRepairOperation) -> None:
        if self.project_service.file_exists(root, operation.target):
            operation.status = "skipped"
            operation.message = "target already exists."
            return
        content = operation.payload.get("content")
        self.project_service.write_text(
            root,
            operation.target,
            json.dumps(content if isinstance(content, dict) else {}, ensure_ascii=False, indent=2)
            + "\n",
        )
        operation.status = "applied"
        operation.message = "created missing memory file."

    def _apply_add_missing_list(self, root: Path, operation: MemoryRepairOperation) -> None:
        field = operation.payload.get("field")
        if not isinstance(field, str) or not field:
            operation.status = "skipped"
            operation.message = "missing list field name."
            return
        data, issue = self._read_json(root, operation.target)
        if issue is not None or not isinstance(data, dict):
            operation.status = "skipped"
            operation.message = "target is not a valid JSON object."
            return
        if isinstance(data.get(field), list):
            operation.status = "skipped"
            operation.message = "list field already exists."
            return
        data[field] = []
        self.project_service.write_text(
            root,
            operation.target,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        )
        operation.status = "applied"
        operation.message = f"added missing list field: {field}."

    def _rebuild_context_packs_after_memory_changes(self, root: Path) -> None:
        contract_paths = [
            path
            for path in self.project_service.list_paths(root, "story/chapter-briefs")
            if path.endswith(".json")
        ]
        for contract_path in contract_paths:
            chapter_id = Path(contract_path).stem
            try:
                self.context_pack_service.build_context_pack(root, chapter_id)
            except (FileNotFoundError, ValueError):
                continue
