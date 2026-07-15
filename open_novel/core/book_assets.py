from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService
from open_novel.core.text_support import important_terms, text_supports_claim
from open_novel.core.workbench_repository import WorkbenchRepository


class BookAssetService:
    context_source = "workspace/book-assets"
    world_types = {"设定", "地点", "势力"}

    def __init__(
        self,
        repository: WorkbenchRepository | None = None,
        project_service: ProjectService | None = None,
    ) -> None:
        self.repository = repository or WorkbenchRepository()
        self.project_service = project_service or ProjectService()

    def select_for_context(
        self,
        root: Path,
        chapter_id: str,
        contract_data: dict[str, Any],
        keywords: set[str],
        limit: int = 12,
    ) -> dict[str, Any]:
        terms = self._terms(contract_data) | keywords
        materials = self.repository.list_materials(root)
        world: list[tuple[int, int, dict[str, Any]]] = []
        characters: list[tuple[int, int, dict[str, Any]]] = []
        for index, material in enumerate(materials):
            material_type = str(material.get("type") or "")
            if material_type not in self.world_types and material_type != "人物":
                continue
            score, reasons = self._score(material, terms)
            if material_type == "设定" and self._hard_rules(material):
                score += 80
                reasons.append("hard_world_rule")
            if score <= 0:
                continue
            selected = {
                **material,
                "evidence": self._evidence(material),
                "_contextPriority": {"score": min(100, score), "reasons": reasons},
            }
            if material_type in self.world_types:
                selected["hardRules"] = self._hard_rules(material)
                world.append((score, index, selected))
            else:
                selected.update(self._character_state(root, material, chapter_id))
                characters.append((score, index, selected))
        from open_novel.core.active_prohibitions import ActiveProhibitionService

        world.sort(key=lambda item: (-item[0], item[1]))
        capacity = max(0, limit)
        retained_world = world[: max(0, capacity - 1)]
        already_covered = {
            str(rule.get("forbidden") or "")
            for _, _, selected in retained_world
            for rule in selected.get("hardRules", [])
            if str(rule.get("forbidden") or "")
        }
        prohibitions = ActiveProhibitionService(
            self.project_service,
            self.repository,
        ).collect(root)
        aggregate_prohibitions = [
            prohibition
            for prohibition in prohibitions
            if prohibition["forbidden"] not in already_covered
        ]
        if aggregate_prohibitions:
            retained_world.append(
                (
                    100,
                    -1,
                    {
                        "id": "active-prohibitions",
                        "title": "永久禁止项（已确认）",
                        "hardRules": [
                            {
                                "rule": prohibition["rule"],
                                "forbidden": prohibition["forbidden"],
                            }
                            for prohibition in aggregate_prohibitions
                        ],
                        "evidence": list(
                            dict.fromkeys(
                                evidence
                                for prohibition in aggregate_prohibitions
                                for evidence in prohibition.get("evidence", [])
                            )
                        ),
                        "_contextPriority": {
                            "score": 100,
                            "reasons": ["active_prohibition"],
                        },
                    },
                )
            )
        else:
            retained_world = world[:capacity]
        retained_world.sort(key=lambda item: (-item[0], item[1]))
        characters.sort(key=lambda item: (-item[0], item[1]))
        return {
            "schemaVersion": 1,
            "worldAssets": [item for _, _, item in retained_world[:capacity]],
            "characterRoster": [item for _, _, item in characters[:limit]],
        }

    def hard_rule_violations(self, context_data: Any, draft: str) -> list[dict[str, str]]:
        if not isinstance(context_data, dict):
            return []
        violations: list[dict[str, str]] = []
        for asset in context_data.get("worldAssets", []):
            if not isinstance(asset, dict):
                continue
            for rule in asset.get("hardRules", []):
                if not isinstance(rule, dict):
                    continue
                forbidden = str(rule.get("forbidden") or "").strip()
                if forbidden and forbidden in draft:
                    violations.append(
                        {
                            "assetId": str(asset.get("id") or ""),
                            "title": str(asset.get("title") or "世界规则"),
                            "rule": str(rule.get("rule") or ""),
                            "forbidden": forbidden,
                        }
                    )
        return violations

    def _score(self, material: dict[str, Any], terms: set[str]) -> tuple[int, list[str]]:
        text = json.dumps(material, ensure_ascii=False)
        score = max(0, min(30, int(material.get("confidence") or 0) // 4))
        reasons = ["confirmed_book_asset"]
        hits = [
            term for term in terms if term and (term in text or text_supports_claim(text, term))
        ]
        if hits:
            score += min(60, len(hits) * 10)
            reasons.append("contract_keyword_match")
        return score, reasons

    def _hard_rules(self, material: dict[str, Any]) -> list[dict[str, str]]:
        details = material.get("details") if isinstance(material.get("details"), dict) else {}
        values = [str(details.get(key) or "") for key in ("规则", "限制", "代价")]
        values.extend([str(material.get("summary") or ""), str(material.get("influence") or "")])
        rules: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            for sentence in re.split(r"[。；;\n]+", value):
                text = sentence.strip()
                match = re.search(r"(?:禁止|不得|不能|不允许)[:：]?\s*([^，,。；;]+)", text)
                if match is None:
                    continue
                forbidden = match.group(1).strip()
                if forbidden and forbidden not in seen:
                    seen.add(forbidden)
                    rules.append({"rule": text, "forbidden": forbidden})
        return rules

    def hard_rules_for_material(self, material: dict[str, Any]) -> list[dict[str, str]]:
        return self._hard_rules(material)

    def _terms(self, data: dict[str, Any]) -> set[str]:
        return {
            term for term in important_terms(json.dumps(data, ensure_ascii=False)) if len(term) >= 2
        }

    def _evidence(self, material: dict[str, Any]) -> list[str]:
        related = material.get("related") if isinstance(material.get("related"), list) else []
        return [str(item) for item in related if str(item).strip()]

    def _character_state(
        self, root: Path, material: dict[str, Any], chapter_id: str
    ) -> dict[str, Any]:
        names = {str(material.get("id") or ""), str(material.get("title") or "")}
        states = self._matching_entries(root, "memory/character-states.json", "characters", names)
        relationships = self._matching_entries(
            root, "memory/relationship-states.json", "relationships", names
        )
        return {
            "currentStates": self._before_chapter(states, chapter_id),
            "relationships": self._before_chapter(relationships, chapter_id),
        }

    def _matching_entries(
        self, root: Path, relative_path: str, key: str, names: set[str]
    ) -> list[dict[str, Any]]:
        if not self.project_service.file_exists(root, relative_path):
            return []
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return []
        values = data.get(key) if isinstance(data, dict) else []
        return (
            [
                item
                for item in values
                if isinstance(item, dict)
                and any(name and name in json.dumps(item, ensure_ascii=False) for name in names)
            ]
            if isinstance(values, list)
            else []
        )

    def _before_chapter(
        self, values: list[dict[str, Any]], chapter_id: str
    ) -> list[dict[str, Any]]:
        current = self._chapter_order(chapter_id)
        if current is None:
            return values[-3:]
        eligible = [
            item
            for item in values
            if (order := self._chapter_order(str(item.get("chapterId") or ""))) is None
            or order < current
        ]
        return eligible[-3:]

    def _chapter_order(self, value: str) -> int | None:
        match = re.search(r"(\d+)", value)
        return int(match.group(1)) if match else None
