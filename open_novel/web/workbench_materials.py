from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService
from open_novel.core.workbench_repository import WorkbenchRepository


class WorkbenchMaterialService:
    store_path = "memory/workbench-materials.json"

    def __init__(
        self,
        project_service: ProjectService,
        repository: WorkbenchRepository | None = None,
    ) -> None:
        self.project_service = project_service
        self.repository = repository or WorkbenchRepository()

    def read_store(self, root: Path) -> list[dict[str, Any]]:
        stored = self.repository.list_materials(root)
        if stored or self.repository.list_materials(root, include_deleted=True):
            return stored
        data = self._read_json(root, self.store_path)
        materials = data.get("materials") if isinstance(data, dict) else None
        if not isinstance(materials, list):
            return []
        self.repository.replace_materials(root, materials)
        return materials

    def write_store(self, root: Path, materials: list[dict[str, Any]]) -> None:
        self.repository.replace_materials(root, materials)
        self.project_service.write_text(
            root,
            self.store_path,
            json.dumps({"schemaVersion": 1, "materials": materials}, ensure_ascii=False, indent=2)
            + "\n",
        )

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
