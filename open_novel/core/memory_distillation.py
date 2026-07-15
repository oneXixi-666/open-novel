from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_novel.core.models import MemoryDistillationReport
from open_novel.core.project import ProjectService
from open_novel.core.text_support import important_terms
from open_novel.security.path_guard import PathGuard


class MemoryDistillationService:
    output_path = "memory/long-term-memory.json"
    report_path = "runs/memory-distillation.json"
    source_files = [
        "memory/chapter-summaries.json",
        "memory/facts.json",
        "memory/promises.json",
        "memory/open-loops.json",
        "memory/character-states.json",
        "memory/emotional-arcs.json",
        "memory/writing-lessons.json",
    ]

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def distill_project(
        self,
        root: Path,
        current_chapter_id: str,
        hot_window_chapters: int = 5,
        max_topics: int = 120,
    ) -> MemoryDistillationReport:
        normalized = self.project_service.normalize_chapter_id(current_chapter_id)
        current_order = self._chapter_order(normalized)
        hot_window_chapters = max(1, hot_window_chapters)
        max_topics = max(1, max_topics)

        memory = {
            "schemaVersion": 1,
            "generatedForChapter": normalized,
            "hotWindowChapters": hot_window_chapters,
            "topics": [],
            "entityIndex": [],
            "writingGuidance": [],
        }
        raw = {source: self._read_json(root, source) for source in self.source_files}
        topics: list[dict[str, Any]] = []
        topics.extend(
            self._chapter_arc_topics(
                raw["memory/chapter-summaries.json"],
                current_order,
                hot_window_chapters,
            )
        )
        topics.extend(
            self._list_topics(
                raw["memory/facts.json"],
                "facts",
                "fact",
                "memory/facts.json",
                current_order,
                hot_window_chapters,
            )
        )
        topics.extend(
            self._list_topics(
                raw["memory/promises.json"],
                "promises",
                "promise",
                "memory/promises.json",
                current_order,
                hot_window_chapters,
            )
        )
        topics.extend(
            self._list_topics(
                raw["memory/open-loops.json"],
                "loops",
                "open_loop",
                "memory/open-loops.json",
                current_order,
                hot_window_chapters,
            )
        )
        topics.extend(
            self._character_topics(
                raw["memory/character-states.json"],
                "states",
                "character_state",
                "memory/character-states.json",
                current_order,
                hot_window_chapters,
            )
        )
        topics.extend(
            self._character_topics(
                raw["memory/emotional-arcs.json"],
                "beats",
                "emotional_arc",
                "memory/emotional-arcs.json",
                current_order,
                hot_window_chapters,
            )
        )
        topics = self._dedupe_topics(topics)
        topics.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("id", ""))))
        memory["topics"] = topics[:max_topics]
        memory["entityIndex"] = self._entity_index(memory["topics"])
        memory["writingGuidance"] = self._writing_guidance(raw["memory/writing-lessons.json"])

        self.project_service.write_text(
            root,
            self.output_path,
            json.dumps(memory, ensure_ascii=False, indent=2) + "\n",
        )
        report = MemoryDistillationReport(
            currentChapterId=normalized,
            hotWindowChapters=hot_window_chapters,
            sourceFiles=self.source_files,
            topicCount=len(memory["topics"]),
            entityCount=len(memory["entityIndex"]),
            writingGuidanceCount=len(memory["writingGuidance"]),
            outputPath=self.output_path,
            recommendedNextAction=self._recommended_next_action(len(memory["topics"])),
        )
        self.project_service.write_text(
            root,
            self.report_path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _chapter_arc_topics(
        self,
        data: Any,
        current_order: int | None,
        hot_window: int,
    ) -> list[dict[str, Any]]:
        chapters = data.get("chapters") if isinstance(data, dict) else None
        if not isinstance(chapters, list):
            return []
        cold = [
            chapter
            for chapter in chapters
            if isinstance(chapter, dict)
            and self._is_cold_chapter(chapter, current_order, hot_window)
        ]
        groups: dict[int, list[dict[str, Any]]] = {}
        for chapter in cold:
            order = self._item_order(chapter) or 0
            groups.setdefault(order // 10, []).append(chapter)

        topics: list[dict[str, Any]] = []
        for group_id, items in sorted(groups.items()):
            items.sort(key=lambda item: self._item_order(item) or 0)
            summaries = []
            orders = []
            for item in items:
                order = self._item_order(item)
                if order is not None:
                    orders.append(order)
                summary = str(item.get("summary") or item.get("text") or "").strip()
                if summary:
                    label = str(item.get("chapterId") or item.get("id") or "")
                    summaries.append(f"{label}: {summary}")
            if not summaries:
                continue
            summary_text = self._clip("；".join(summaries), 900)
            topics.append(
                self._topic(
                    topic_id=f"arc_{group_id:03d}",
                    kind="chapter_arc",
                    title=self._chapter_range_title(orders),
                    summary=summary_text,
                    source="memory/chapter-summaries.json",
                    priority=40 + min(len(items), 10),
                )
            )
        return topics

    def _list_topics(
        self,
        data: Any,
        list_key: str,
        kind: str,
        source: str,
        current_order: int | None,
        hot_window: int,
    ) -> list[dict[str, Any]]:
        values = data.get(list_key) if isinstance(data, dict) else None
        if not isinstance(values, list):
            return []
        topics: list[dict[str, Any]] = []
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            if not self._should_distill_item(item, current_order, hot_window):
                continue
            text = self._item_text(item)
            if not text:
                continue
            item_id = str(item.get("id") or f"{kind}_{index:03d}")
            topics.append(
                self._topic(
                    topic_id=f"{kind}_{self._slug(item_id)}",
                    kind=kind,
                    title=item_id,
                    summary=self._clip(text, 500),
                    source=source,
                    priority=self._priority(item),
                    status=str(item.get("status") or ""),
                    chapterRef=self._chapter_ref(item),
                )
            )
        return topics

    def _character_topics(
        self,
        data: Any,
        list_key: str,
        kind: str,
        source: str,
        current_order: int | None,
        hot_window: int,
    ) -> list[dict[str, Any]]:
        characters = data.get("characters") if isinstance(data, dict) else None
        if not isinstance(characters, list):
            return []
        topics: list[dict[str, Any]] = []
        for character in characters:
            if not isinstance(character, dict):
                continue
            entries = character.get(list_key)
            if not isinstance(entries, list):
                continue
            cold_entries = [
                entry
                for entry in entries
                if isinstance(entry, dict)
                and self._is_cold_chapter(entry, current_order, hot_window)
            ]
            if not cold_entries:
                continue
            latest = max(cold_entries, key=lambda entry: self._item_order(entry) or -1)
            name = str(character.get("name") or character.get("characterId") or "角色")
            text = self._item_text(latest)
            if not text:
                continue
            topics.append(
                self._topic(
                    topic_id=f"{kind}_{self._slug(str(character.get('characterId') or name))}",
                    kind=kind,
                    title=f"{name} 的长期状态",
                    summary=self._clip(text, 500),
                    source=source,
                    priority=65,
                    chapterRef=self._chapter_ref(latest),
                )
            )
        return topics

    def _writing_guidance(self, data: Any) -> list[dict[str, Any]]:
        lessons = data.get("lessons") if isinstance(data, dict) else None
        if not isinstance(lessons, list):
            return []
        active = [
            lesson
            for lesson in lessons
            if isinstance(lesson, dict) and lesson.get("status") != "retired"
        ]
        active.sort(key=lambda item: (-self._priority(item), str(item.get("id", ""))))
        guidance = []
        for lesson in active[:12]:
            guidance.append(
                {
                    "id": str(lesson.get("id") or ""),
                    "category": str(lesson.get("category") or "style"),
                    "lesson": str(lesson.get("lesson") or ""),
                    "failureCount": int(lesson.get("failureCount") or 0),
                }
            )
        return guidance

    def _topic(
        self,
        topic_id: str,
        kind: str,
        title: str,
        summary: str,
        source: str,
        priority: int,
        **extra: Any,
    ) -> dict[str, Any]:
        keywords = sorted(important_terms(" ".join([title, summary])))[:16]
        topic = {
            "id": topic_id,
            "kind": kind,
            "title": title,
            "summary": summary,
            "keywords": keywords,
            "source": source,
            "priority": priority,
            "importance": "long_term",
        }
        topic.update({key: value for key, value in extra.items() if value})
        return topic

    def _entity_index(self, topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        entities: dict[str, set[str]] = {}
        for topic in topics:
            for keyword in topic.get("keywords", []):
                if not isinstance(keyword, str) or len(keyword) < 2:
                    continue
                entities.setdefault(keyword, set()).add(str(topic.get("id") or ""))
        return [
            {"name": name, "topicIds": sorted(topic_ids)[:12]}
            for name, topic_ids in sorted(
                entities.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )[:80]
        ]

    def _read_json(self, root: Path, relative_path: str) -> Any:
        path = PathGuard(root).resolve(relative_path)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _should_distill_item(
        self,
        item: dict[str, Any],
        current_order: int | None,
        hot_window: int,
    ) -> bool:
        status = str(item.get("status") or "")
        if status in {"open", "partial"}:
            return False
        if str(item.get("importance") or "") in {"high", "critical"}:
            return True
        return self._is_cold_chapter(item, current_order, hot_window)

    def _is_cold_chapter(
        self,
        item: dict[str, Any],
        current_order: int | None,
        hot_window: int,
    ) -> bool:
        order = self._item_order(item)
        if current_order is None or order is None:
            return True
        return order <= current_order - hot_window

    def _item_text(self, item: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in (
            "summary",
            "text",
            "label",
            "readerQuestion",
            "emotion",
            "externalGoal",
            "emotionBefore",
            "emotionAfter",
            "trigger",
        ):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        for key in ("relationshipChanges", "evidence"):
            value = item.get(key)
            if isinstance(value, list):
                parts.extend(str(part).strip() for part in value if str(part).strip())
        return "；".join(dict.fromkeys(parts))

    def _priority(self, item: dict[str, Any]) -> int:
        severity = {"blocker": 90, "high": 70, "medium": 50, "low": 25}.get(
            str(item.get("severity") or ""),
            0,
        )
        importance = {"critical": 95, "high": 75, "medium": 45, "low": 20}.get(
            str(item.get("importance") or ""),
            0,
        )
        status = {"paid_off": 55, "closed": 50, "resolved": 50}.get(
            str(item.get("status") or ""),
            0,
        )
        failures = int(item.get("failureCount") or 0) * 4
        return max(35, severity, importance, status) + failures

    def _chapter_ref(self, item: dict[str, Any]) -> str:
        for key in ("chapterId", "validFrom", "introducedAt", "payoffAt", "lastTouchedAt"):
            value = item.get(key)
            if value:
                return str(value)
        return ""

    def _item_order(self, item: dict[str, Any]) -> int | None:
        for key in ("chapterId", "validFrom", "introducedAt", "payoffAt", "lastTouchedAt"):
            value = item.get(key)
            if value:
                order = self._chapter_order_from_text(str(value))
                if order is not None:
                    return order
        return None

    def _chapter_order(self, chapter_id: str) -> int | None:
        return int(chapter_id) if chapter_id.isdigit() else None

    def _chapter_order_from_text(self, value: str) -> int | None:
        match = re.search(r"(?P<chapter>\d{1,4})", value)
        return int(match.group("chapter")) if match else None

    def _chapter_range_title(self, orders: list[int]) -> str:
        if not orders:
            return "旧章节剧情压缩"
        return f"第 {min(orders):03d}-{max(orders):03d} 章剧情压缩"

    def _dedupe_topics(self, topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for topic in topics:
            topic_id = str(topic.get("id") or "")
            if topic_id in seen:
                continue
            seen.add(topic_id)
            result.append(topic)
        return result

    def _recommended_next_action(self, topic_count: int) -> str:
        if topic_count == 0:
            return "keep-writing-until-cold-memory-exists"
        return "use-long-term-memory-in-context-pack-and-run-sequence-evaluation"

    def _clip(self, value: str, limit: int) -> str:
        return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"

    def _slug(self, value: str) -> str:
        slug = "".join(char if char.isalnum() else "_" for char in value.strip())
        slug = "_".join(part for part in slug.split("_") if part)
        return slug.lower() or "item"
