from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from open_novel.core.models import WritingLessonsMemory
from open_novel.core.project import ProjectService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.writing_formula import WritingFormulaMemory, WritingFormulaService


class WritingAssetService:
    context_source = "story/effective-writing-assets"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def effective_assets(self, root: Path) -> dict[str, Any]:
        profile = StyleProfileService(self.project_service).read_project_profile(root)
        formulas = [
            item.model_dump(mode="json")
            for item in self._formulas(root).formulas
            if item.status == "active"
        ]
        lessons = [
            item.model_dump(mode="json")
            for item in self._lessons(root).lessons
            if item.status == "active"
        ]
        anti_ai_rules = [
            "避免连续使用相同句式、机械连接词和成组排比。",
            "情绪必须落到动作、对白、身体反应或选择，不能只贴标签。",
            "生成、Gate 和修复都以当前生效写法资产为准。",
        ]
        return {
            "schemaVersion": 1,
            "styleProfile": {
                "id": profile.id,
                "label": profile.label,
                "source": StyleProfileService.default_profile_path,
            },
            "formulas": formulas,
            "lessons": lessons,
            "antiAiRules": anti_ai_rules,
            "sources": [
                StyleProfileService.default_profile_path,
                WritingFormulaService.memory_path,
                "memory/writing-lessons.json",
            ],
        }

    def list_assets(self, root: Path) -> dict[str, Any]:
        memory = self._formulas(root)
        return {
            "effective": self.effective_assets(root),
            "formulas": [item.model_dump(mode="json") for item in memory.formulas],
        }

    def set_formula_status(
        self,
        root: Path,
        formula_id: str,
        status: Literal["active", "retired"],
    ) -> dict[str, Any]:
        memory = self._formulas(root)
        formula = next((item for item in memory.formulas if item.id == formula_id), None)
        if formula is None:
            raise FileNotFoundError(f"missing writing formula: {formula_id}")
        formula.status = status
        self.project_service.write_text(
            root,
            WritingFormulaService.memory_path,
            json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return self.list_assets(root)

    def _formulas(self, root: Path) -> WritingFormulaMemory:
        if not self.project_service.file_exists(root, WritingFormulaService.memory_path):
            return WritingFormulaMemory()
        try:
            return WritingFormulaMemory.model_validate_json(
                self.project_service.read_text(root, WritingFormulaService.memory_path)
            )
        except ValueError:
            return WritingFormulaMemory()

    def _lessons(self, root: Path) -> WritingLessonsMemory:
        relative_path = "memory/writing-lessons.json"
        if not self.project_service.file_exists(root, relative_path):
            return WritingLessonsMemory()
        try:
            return WritingLessonsMemory.model_validate_json(
                self.project_service.read_text(root, relative_path)
            )
        except (ValueError, json.JSONDecodeError):
            return WritingLessonsMemory()
