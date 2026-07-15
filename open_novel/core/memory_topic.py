from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.context_pack import ContextPackService
from open_novel.core.memory_distillation import MemoryDistillationService
from open_novel.core.project import ProjectService


class MemoryTopicService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        distillation_service: MemoryDistillationService | None = None,
        context_pack_service: ContextPackService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.distillation_service = distillation_service or MemoryDistillationService(
            self.project_service
        )
        self.context_pack_service = context_pack_service or ContextPackService(self.project_service)

    def topic_detail(
        self,
        root: Path,
        topic_id: str,
        chapter_id: str | None = None,
    ) -> dict[str, object]:
        topic_id = (topic_id or "").strip()
        if not topic_id:
            raise ValueError("topic id is required")
        memory = self._read_long_term_memory(root)
        topics = memory.get("topics")
        if not isinstance(topics, list):
            topics = []
        topic = next(
            (
                item
                for item in topics
                if isinstance(item, dict) and str(item.get("id") or "") == topic_id
            ),
            None,
        )
        if topic is None:
            raise FileNotFoundError(f"missing long-term memory topic: {topic_id}")
        related_entities = self._related_entities(memory, topic_id)
        related_topic_ids = sorted(
            {
                related_id
                for entity in related_entities
                for related_id in entity.get("topicIds", [])
                if isinstance(related_id, str) and related_id != topic_id
            }
        )
        related_topics = [
            self._topic_summary(item)
            for item in topics
            if isinstance(item, dict) and str(item.get("id") or "") in related_topic_ids
        ][:12]
        context_status = self._context_status(root, topic_id, chapter_id)
        return {
            "schemaVersion": 1,
            "topicId": topic_id,
            "topic": topic,
            "source": topic.get("source") or self.distillation_service.output_path,
            "chapterRef": topic.get("chapterRef") or "",
            "keywords": self._string_list(topic.get("keywords")),
            "relatedEntities": related_entities,
            "relatedTopics": related_topics,
            "writingGuidance": self._writing_guidance(memory, topic),
            "contextStatus": context_status,
        }

    def _read_long_term_memory(self, root: Path) -> dict[str, Any]:
        relative_path = self.distillation_service.output_path
        if not self.project_service.file_exists(root, relative_path):
            return {"schemaVersion": 1, "topics": [], "entityIndex": [], "writingGuidance": []}
        data = json.loads(self.project_service.read_text(root, relative_path))
        if not isinstance(data, dict):
            raise ValueError("long-term memory must be a JSON object")
        return data

    def _related_entities(
        self,
        memory: dict[str, Any],
        topic_id: str,
    ) -> list[dict[str, object]]:
        entities = memory.get("entityIndex")
        if not isinstance(entities, list):
            return []
        related: list[dict[str, object]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            topic_ids = entity.get("topicIds")
            if not isinstance(topic_ids, list) or topic_id not in topic_ids:
                continue
            related.append(
                {
                    "name": str(entity.get("name") or ""),
                    "topicIds": [str(item) for item in topic_ids if str(item).strip()],
                }
            )
        return related

    def _context_status(
        self,
        root: Path,
        topic_id: str,
        chapter_id: str | None,
    ) -> dict[str, object]:
        if not chapter_id:
            return {"checked": False, "included": False, "path": ""}
        try:
            context_pack = self.context_pack_service.read_context_pack(root, chapter_id)
        except (FileNotFoundError, ValueError):
            return {
                "checked": True,
                "included": False,
                "path": self.context_pack_service.context_pack_path(chapter_id),
            }
        for item in context_pack.included:
            if item.source != self.distillation_service.output_path:
                continue
            data = item.data
            if not isinstance(data, dict):
                continue
            topics = data.get("topics")
            if not isinstance(topics, list):
                continue
            if any(isinstance(topic, dict) and topic.get("id") == topic_id for topic in topics):
                return {"checked": True, "included": True, "path": context_pack.path}
        return {"checked": True, "included": False, "path": context_pack.path}

    def _topic_summary(self, topic: dict[str, Any]) -> dict[str, object]:
        return {
            "id": str(topic.get("id") or ""),
            "kind": str(topic.get("kind") or ""),
            "title": str(topic.get("title") or ""),
            "summary": str(topic.get("summary") or ""),
            "priority": topic.get("priority") or 0,
        }

    def _writing_guidance(
        self,
        memory: dict[str, Any],
        topic: dict[str, Any],
    ) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        guidance_index = 1
        for source in (topic.get("writingGuidance"), memory.get("writingGuidance")):
            if not isinstance(source, list):
                continue
            for item in source:
                if isinstance(item, dict):
                    normalized.append(item)
                elif str(item).strip():
                    normalized.append(
                        {
                            "id": f"topic-guidance-{guidance_index}",
                            "lesson": str(item).strip(),
                        }
                    )
                    guidance_index += 1
        return normalized[:12]

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]
