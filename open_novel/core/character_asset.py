from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from open_novel.core.project import ProjectService
from open_novel.core.text_support import important_terms, text_supports_claim


class CharacterAsset(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    characterId: str = ""
    kind: str = "general"
    summary: str = ""
    status: Literal["active", "dormant", "retired"] = "active"
    evidence: list[str] = Field(default_factory=list)
    lastUsedChapter: str = ""
    cooldown: int = 0
    tags: list[str] = Field(default_factory=list)
    importance: Literal["low", "medium", "high", "critical"] = "medium"


class CharacterAssetsMemory(BaseModel):
    schemaVersion: int = 1
    assets: list[CharacterAsset] = Field(default_factory=list)


class CharacterAssetService:
    memory_path = "memory/character-assets.json"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_memory(self, root: Path) -> CharacterAssetsMemory:
        if not self.project_service.file_exists(root, self.memory_path):
            return CharacterAssetsMemory()
        return CharacterAssetsMemory.model_validate_json(
            self.project_service.read_text(root, self.memory_path)
        )

    def write_memory(self, root: Path, memory: CharacterAssetsMemory) -> None:
        self.project_service.write_text(
            root,
            self.memory_path,
            json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def select_for_context(
        self,
        root: Path,
        chapter_id: str,
        contract_data: dict[str, Any],
        keywords: set[str],
        limit: int = 6,
    ) -> dict[str, Any]:
        memory = self.read_memory(root)
        if not memory.assets:
            return {"schemaVersion": memory.schemaVersion, "assets": []}

        contract_terms = self._contract_terms(contract_data) | keywords
        decorated: list[tuple[int, int, CharacterAsset]] = []
        for index, asset in enumerate(memory.assets):
            score, reasons = self._score_asset(asset, chapter_id, contract_data, contract_terms)
            if score <= 0:
                continue
            decorated.append((score, index, asset.model_copy(update={
                "_contextPriority": {"score": score, "reasons": reasons},
            })))
        decorated.sort(key=lambda item: (-item[0], item[1]))
        return {
            "schemaVersion": memory.schemaVersion,
            "assets": [
                asset.model_dump(mode="json")
                for _, _, asset in decorated[: max(0, limit)]
            ],
        }

    def _score_asset(
        self,
        asset: CharacterAsset,
        chapter_id: str,
        contract_data: dict[str, Any],
        terms: set[str],
    ) -> tuple[int, list[str]]:
        if asset.status == "retired":
            return 0, []

        text = json.dumps(asset.model_dump(mode="json"), ensure_ascii=False)
        reasons: list[str] = []
        score = 0

        if asset.status == "active":
            score += 20
            reasons.append("active_asset")
        elif asset.status == "dormant":
            score += 6
            reasons.append("dormant_asset")

        if asset.importance == "critical":
            score += 45
            reasons.append("importance_critical")
        elif asset.importance == "high":
            score += 30
            reasons.append("importance_high")
        elif asset.importance == "medium":
            score += 12
            reasons.append("importance_medium")

        contract_characters = self._contract_characters(contract_data)
        if asset.characterId and asset.characterId in contract_characters:
            score += 50
            reasons.append("contract_character")

        if asset.lastUsedChapter == chapter_id:
            score -= 20
            reasons.append("used_this_chapter")
        elif self._chapter_distance(asset.lastUsedChapter, chapter_id) == 1:
            score += 12
            reasons.append("recent_previous_chapter")

        if asset.cooldown > 0:
            score -= min(30, asset.cooldown * 10)
            reasons.append("cooldown")

        keyword_hits = sorted(term for term in terms if self._term_matches(text, term))
        if keyword_hits:
            score += min(30, len(keyword_hits) * 5)
            reasons.append("keyword_match")

        if score <= 0:
            return 0, []
        return score, reasons or ["matched"]

    def _contract_terms(self, contract_data: dict[str, Any]) -> set[str]:
        terms: set[str] = set()
        for value in contract_data.values():
            if isinstance(value, str):
                terms.update(important_terms(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        terms.update(important_terms(item))
        return {term for term in terms if len(term) >= 2}

    def _contract_characters(self, contract_data: dict[str, Any]) -> set[str]:
        values = {
            str(contract_data.get("pov") or "").strip(),
            str(contract_data.get("characterId") or "").strip(),
        }
        for key in ("focus", "goal", "conflict", "emotionalBeat", "relationshipBeat"):
            raw = contract_data.get(key)
            if isinstance(raw, str):
                values.update(important_terms(raw))
        return {value for value in values if value}

    def _term_matches(self, text: str, term: str) -> bool:
        return bool(term and (term in text or text_supports_claim(text, term)))

    def _chapter_distance(self, asset_chapter: str, current_chapter: str) -> int | None:
        if not asset_chapter.isdigit() or not current_chapter.isdigit():
            return None
        return int(current_chapter) - int(asset_chapter)
