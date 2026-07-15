from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService
from open_novel.core.workbench_repository import WorkbenchRepository


class WorkbenchReviewService:
    state_path = "memory/workbench-review-states.json"
    inbox_path = "memory/workbench-review-inbox.json"

    def __init__(
        self,
        project_service: ProjectService,
        repository: WorkbenchRepository | None = None,
    ) -> None:
        self.project_service = project_service
        self.repository = repository or WorkbenchRepository()

    def read_states(self, root: Path) -> dict[str, str]:
        stored_states = self.repository.read_review_states(root)
        if stored_states:
            return {
                review_id: status
                for review_id, status in stored_states.items()
                if status in {"待处理", "处理中", "已确认"}
            }
        data = self._read_json(root, self.state_path)
        reviews = data.get("reviews") if isinstance(data, dict) else None
        if not isinstance(reviews, dict):
            return {}
        states = {
            str(review_id): status
            for review_id, status in reviews.items()
            if status in {"待处理", "处理中", "已确认"}
        }
        if states:
            self.repository.write_review_states(root, states)
        return states

    def write_states(self, root: Path, states: dict[str, str]) -> None:
        self.repository.write_review_states(root, states)
        self.project_service.write_text(
            root,
            self.state_path,
            json.dumps({"schemaVersion": 1, "reviews": states}, ensure_ascii=False, indent=2)
            + "\n",
        )

    def read_inbox(self, root: Path) -> tuple[str, list[dict[str, Any]]]:
        stored_chapter_id, stored_reviews = self.repository.read_review_inbox(root)
        if stored_reviews:
            return stored_chapter_id, stored_reviews
        data = self._read_json(root, self.inbox_path)
        chapter_id = str(data.get("chapterId") or "").strip() if isinstance(data, dict) else ""
        reviews = data.get("reviews") if isinstance(data, dict) else None
        if not isinstance(reviews, list):
            return chapter_id, []
        inbox_reviews = [
            item
            for item in reviews
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        if inbox_reviews:
            self.repository.replace_review_inbox(root, chapter_id, inbox_reviews)
        return chapter_id, inbox_reviews

    def write_inbox(self, root: Path, chapter_id: str, reviews: list[dict[str, Any]]) -> None:
        self.repository.replace_review_inbox(root, chapter_id, reviews)
        self.project_service.write_text(
            root,
            self.inbox_path,
            json.dumps(
                {
                    "schemaVersion": 1,
                    "chapterId": chapter_id,
                    "reviews": reviews,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def apply_states(self, root: Path, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
        states = self.read_states(root)
        if not states:
            return reviews
        return [
            {**review, "status": states.get(str(review.get("id")), review.get("status", "待处理"))}
            for review in reviews
        ]

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
