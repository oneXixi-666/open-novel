from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse


class IssueNavigationService:
    contract_fields_by_type = {
        "focus_drift": "focus",
        "focus_not_supported": "focus",
        "outcome_drift": "outcome",
        "hook_drift": "hook",
        "weak_ending_hook": "hook",
        "emotional_discontinuity": "emotionalBeat",
        "weak_emotional_grounding": "emotionalBeat",
        "emotion_told_not_felt": "emotionalBeat",
        "emotion_lacks_specificity": "emotionalBeat",
        "relationship_discontinuity": "relationshipBeat",
        "relationship_turn_unearned": "relationshipBeat",
        "missing_stakes": "stakes",
        "abstract_human_core": "internalNeed",
        "motivation_not_personal": "internalNeed",
        "missing_cost": "cost",
        "payoff_without_cost": "cost",
        "weak_subtext": "subtext",
        "dialogue_lacks_subtext": "subtext",
        "weak_aftertaste": "aftertaste",
        "ending_lacks_aftertaste": "aftertaste",
        "reader_promise_drift": "readerPromises",
        "reader_promise_not_advanced": "readerPromises",
        "reader_focus_diffuse": "readerPromises",
        "missing_must_include": "mustInclude",
        "violated_must_avoid": "mustAvoid",
        "ungrounded_logic_dependency": "logicDependencies",
    }

    memory_files_by_type = {
        "character_state_contradiction": "memory/character-states.json",
        "relationship_state_contradiction": "memory/relationship-states.json",
        "relationship_transition_needs_review": "memory/relationship-states.json",
        "payoff_due_soon": "memory/promises.json",
        "payoff_overdue": "memory/open-loops.json",
        "timeline_order_conflict": "memory/timeline-events.json",
    }

    def build_navigation(
        self,
        chapter_id: str,
        reports: dict[str, Any],
    ) -> dict[str, object]:
        items: list[dict[str, object]] = []
        for report_name, report in reports.items():
            issues = self._issues_from_report(report)
            for index, issue in enumerate(issues, start=1):
                issue_type = str(issue.get("type") or "")
                evidence = self._string_list(issue.get("evidence"))
                targets = self._targets(chapter_id, issue_type, evidence)
                items.append(
                    {
                        "id": f"{report_name}_{index:03d}_{issue_type or 'issue'}",
                        "report": report_name,
                        "stage": str(issue.get("stage") or report_name),
                        "type": issue_type,
                        "severity": str(issue.get("severity") or ""),
                        "message": str(issue.get("message") or ""),
                        "targets": targets,
                        "primaryTarget": targets[0] if targets else {},
                        "suggestedAction": self._suggested_action(issue_type, targets),
                    }
                )
        return {
            "schemaVersion": 1,
            "chapterId": chapter_id,
            "items": items,
            "count": len(items),
        }

    def _issues_from_report(self, report: Any) -> list[dict[str, Any]]:
        if report is None:
            return []
        if hasattr(report, "model_dump"):
            report = report.model_dump(mode="json")
        if not isinstance(report, dict):
            return []
        issues = report.get("issues")
        if not isinstance(issues, list):
            return []
        return [issue for issue in issues if isinstance(issue, dict)]

    def _targets(
        self,
        chapter_id: str,
        issue_type: str,
        evidence: list[str],
    ) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        for item in evidence:
            parsed = self._target_from_ref(item, chapter_id)
            if parsed:
                targets.append(parsed)
        if not any(target["kind"] == "contract" for target in targets):
            field = self.contract_fields_by_type.get(issue_type)
            if field:
                targets.append(
                    {
                        "kind": "contract",
                        "path": f"story/chapter-briefs/{chapter_id}.json",
                        "field": field,
                        "label": f"章节合同 / {field}",
                    }
                )
        if not any(target["kind"] == "memory" for target in targets):
            memory_path = self.memory_files_by_type.get(issue_type)
            if memory_path:
                targets.append(
                    {
                        "kind": "memory",
                        "path": memory_path,
                        "field": "",
                        "label": memory_path,
                    }
                )
        if not any(target["kind"] == "source" for target in targets):
            targets.insert(
                0,
                {
                    "kind": "source",
                    "path": f"drafts/{chapter_id}.generated.md",
                    "field": "",
                    "label": "草稿来源",
                },
            )
        return self._dedupe_targets(targets)

    def _target_from_ref(self, ref: str, chapter_id: str) -> dict[str, str] | None:
        value = ref.strip()
        if not value:
            return None
        path, _, field = value.partition("#")
        parsed_url = urlparse(path)
        route_path = parsed_url.path
        if path in {"story/chapter-briefs", "story/chapter-briefs.json"}:
            path = f"story/chapter-briefs/{chapter_id}.json"
        if path.startswith("story/chapter-briefs/"):
            return {
                "kind": "contract",
                "path": path,
                "field": field,
                "label": f"章节合同 / {field or path}",
            }
        if path.startswith("memory/"):
            return {
                "kind": "memory",
                "path": path,
                "field": field,
                "label": f"{path}{'#' + field if field else ''}",
            }
        if route_path == "/relationships/edge":
            query = parse_qs(parsed_url.query)
            edge_id = str((query.get("edgeId") or [""])[0])
            return {
                "kind": "relationship-edge",
                "path": "/relationships/edge",
                "field": edge_id,
                "label": f"Relationship History / {edge_id or 'edge'}",
            }
        if path.startswith(("drafts/", "chapters/")):
            return {
                "kind": "source",
                "path": path,
                "field": field,
                "label": f"{path}{'#' + field if field else ''}",
            }
        return None

    def _suggested_action(
        self,
        issue_type: str,
        targets: list[dict[str, str]],
    ) -> str:
        if any(target["kind"] == "contract" for target in targets):
            field = next(
                (target["field"] for target in targets if target["kind"] == "contract"),
                "",
            )
            return f"检查章节合同字段 {field}，再让正文用动作、选择或后果承接。"
        if any(target["kind"] == "memory" for target in targets):
            if issue_type == "relationship_transition_needs_review":
                return "打开关系历史页，补充显式过渡、证据，或修正对应关系事件。"
            return "检查相关记忆文件，确认状态、证据和章节顺序是否需要修正。"
        if issue_type in {"over_exposition", "description_outweighs_drama"}:
            return "压缩说明和静态描写，把文字换成冲突、选择、互动或后果。"
        return "回到正文证据处，补足场景动作、人物选择、关系变化或章尾钩子。"

    def _dedupe_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, str]] = []
        for target in targets:
            key = (target["kind"], target["path"], target["field"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(target)
        return deduped

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]
