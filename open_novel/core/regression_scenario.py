from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import StyleProfileService


class RegressionScenarioService:
    fanqie_xuanhuan_upgrade = "fanqie-xuanhuan-upgrade"
    resource_package = "open_novel.builtin_regression_scenarios"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        style_profile_service: StyleProfileService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.style_profile_service = style_profile_service or StyleProfileService(
            self.project_service
        )

    def seed(
        self,
        root: Path,
        *,
        start_chapter_id: str = "001",
        chapter_count: int = 5,
        scenario: str = fanqie_xuanhuan_upgrade,
    ) -> dict[str, object]:
        scenario = (scenario or "").strip()
        if scenario != self.fanqie_xuanhuan_upgrade:
            raise ValueError(f"unsupported regression scenario: {scenario}")
        project = self.project_service.open_project(root)
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        if not start.isdigit():
            raise ValueError("start chapter id must be numeric")
        count = max(1, min(chapter_count, 10))
        start_number = int(start)
        data = self._load_scenario(scenario)
        max_count = int(data.get("maxChapterCount") or 10)
        count = max(1, min(chapter_count, max_count))

        self._write_memory(project.root, data, start)
        self.style_profile_service.write_project_profile_from_builtin(
            project.root,
            str(data.get("styleProfileId") or scenario),
        )
        contract_paths: list[str] = []
        for offset in range(count):
            chapter_number = start_number + offset
            contract = self._scenario_contract(data, chapter_number, offset)
            self.story_guidance.write_scene_contract(project.root, contract)
            contract_paths.append(self.story_guidance.contract_path(contract.chapterId))
        report = {
            "schemaVersion": 1,
            "scenario": scenario,
            "startChapterId": start,
            "chapterCount": count,
            "styleProfile": StyleProfileService.default_profile_path,
            "contracts": contract_paths,
            "memory": ["memory/facts.json", "memory/open-loops.json", "memory/promises.json"],
        }
        self.project_service.write_text(
            project.root,
            "runs/regression-scenario.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _load_scenario(self, scenario: str) -> dict[str, Any]:
        resource_name = f"{scenario}.json"
        try:
            text = resources.files(self.resource_package).joinpath(resource_name).read_text(
                encoding="utf-8"
            )
        except FileNotFoundError as exc:
            raise ValueError(f"unsupported regression scenario: {scenario}") from exc
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"invalid regression scenario resource: {scenario}")
        if str(data.get("id") or "") != scenario:
            raise ValueError(f"regression scenario id mismatch: {scenario}")
        return data

    def _write_memory(self, root: Path, data: dict[str, Any], start: str) -> None:
        memory = data.get("memory")
        if not isinstance(memory, dict):
            return
        for path, payload in memory.items():
            if not isinstance(path, str):
                continue
            formatted = self._format_placeholders(payload, start=start)
            self.project_service.write_text(
                root,
                path,
                json.dumps(formatted, ensure_ascii=False, indent=2) + "\n",
            )

    def _scenario_contract(
        self,
        data: dict[str, Any],
        chapter_number: int,
        offset: int,
    ) -> SceneContract:
        chapter_id = f"{chapter_number:03d}"
        contracts = data.get("contracts")
        if not isinstance(contracts, list) or not contracts:
            raise ValueError("regression scenario has no contracts")
        defaults = data.get("contractDefaults")
        if not isinstance(defaults, dict):
            defaults = {}
        contract_data = contracts[offset % len(contracts)]
        if not isinstance(contract_data, dict):
            raise ValueError("regression scenario contract must be an object")
        merged = {**defaults, **contract_data}
        merged = self._format_placeholders(
            merged,
            start=f"{chapter_number:03d}",
            chapter_id=chapter_id,
            chapter_number=str(chapter_number),
        )
        title = str(merged.get("title") or f"Chapter {chapter_id}")
        merged["chapterId"] = chapter_id
        merged["title"] = f"第{chapter_number}章 {title}"
        return SceneContract.model_validate(merged)

    def _format_placeholders(self, value: Any, **replacements: str) -> Any:
        if isinstance(value, str):
            return value.format(**replacements)
        if isinstance(value, list):
            return [self._format_placeholders(item, **replacements) for item in value]
        if isinstance(value, dict):
            return {
                key: self._format_placeholders(item, **replacements)
                for key, item in value.items()
            }
        return value
