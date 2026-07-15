from __future__ import annotations

from pathlib import Path

from open_novel.core.models import ActiveProhibitionsMemory
from open_novel.core.project import ProjectService
from open_novel.core.workbench_repository import WorkbenchRepository


class ActiveProhibitionService:
    memory_path = "memory/active-prohibitions.json"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        repository: WorkbenchRepository | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.repository = repository or WorkbenchRepository()

    def collect(self, root: Path) -> list[dict[str, object]]:
        from open_novel.core.book_assets import BookAssetService

        items: list[dict[str, object]] = []
        seen: set[str] = set()
        book_assets = BookAssetService(self.repository, self.project_service)
        for material in self.repository.list_materials(root):
            if str(material.get("type") or "") != "设定":
                continue
            for index, rule in enumerate(book_assets.hard_rules_for_material(material)):
                forbidden = str(rule.get("forbidden") or "").strip()
                if not forbidden or forbidden in seen:
                    continue
                seen.add(forbidden)
                items.append(
                    {
                        "id": f"material-{material.get('id', 'rule')}-{index + 1}",
                        "rule": str(rule.get("rule") or ""),
                        "forbidden": forbidden,
                        "source": "workbench-material",
                        "evidence": [str(item) for item in material.get("related", [])],
                    }
                )

        if not self.project_service.file_exists(root, self.memory_path):
            return items
        memory = ActiveProhibitionsMemory.model_validate_json(
            self.project_service.read_text(root, self.memory_path)
        )
        for entry in memory.items:
            forbidden = entry.forbidden.strip()
            if not forbidden or forbidden in seen:
                continue
            seen.add(forbidden)
            items.append(entry.model_dump(mode="json"))
        return items

    def format_for_prompt(self, root: Path) -> str:
        items = self.collect(root)
        if not items:
            return "（当前没有需要遵守的永久禁止项）"
        return "\n".join(f"- {item['rule']}（禁止再出现：{item['forbidden']}）" for item in items)
