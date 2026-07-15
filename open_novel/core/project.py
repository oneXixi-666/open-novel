from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from uuid import uuid4

from open_novel.core.models import NovelMetadata, NovelProject, TimelineEvent, TimelineEventsMemory
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.workspace_storage import ProjectDocumentStore
from open_novel.security.path_guard import PathGuard


class ProjectService:
    required_dirs = [
        "characters",
        "chapters",
        "drafts",
        "exports",
        "knowledge",
        "knowledge/chunks",
        "knowledge/sources",
        "memory",
        "models",
        "models/adapters",
        "notes",
        "patches",
        "reviews",
        "runs",
        "story",
        "story/arc-contracts",
        "story/branches",
        "story/chapter-briefs",
        "story/context-packs",
        "story/ideation-sessions",
    ]

    starter_files = {
        "bible.md": "# Story Bible\n\n",
        "style.md": "# Style Guide\n\n",
        "rules.md": "# Writing Rules\n\n",
        "outline.md": "# Outline\n\n",
        "timeline.md": "# Timeline\n\n",
        "story/style-profile.json": StyleProfileService.default_project_profile_text(),
        "chapters/001.md": "# 001\n\n",
        "notes/ideas.md": "# Ideas\n\n",
        "memory/facts.json": '{\n  "facts": []\n}\n',
        "memory/open-loops.json": '{\n  "schemaVersion": 1,\n  "loops": []\n}\n',
        "memory/character-states.json": '{\n  "schemaVersion": 1,\n  "characters": []\n}\n',
        "memory/character-assets.json": '{\n  "schemaVersion": 1,\n  "assets": []\n}\n',
        "memory/relationship-states.json": ('{\n  "schemaVersion": 1,\n  "relationships": []\n}\n'),
        "memory/timeline-events.json": '{\n  "schemaVersion": 1,\n  "events": []\n}\n',
        "memory/chapter-summaries.json": '{\n  "schemaVersion": 1,\n  "chapters": []\n}\n',
        "memory/promises.json": '{\n  "schemaVersion": 1,\n  "promises": []\n}\n',
        "memory/emotional-arcs.json": '{\n  "schemaVersion": 1,\n  "characters": []\n}\n',
        "memory/writing-lessons.json": '{\n  "schemaVersion": 1,\n  "lessons": []\n}\n',
        "memory/active-prohibitions.json": ('{\n  "schemaVersion": 1,\n  "items": []\n}\n'),
        "memory/writing-formulas.json": '{\n  "schemaVersion": 1,\n  "formulas": []\n}\n',
        "memory/long-term-memory.json": (
            "{\n"
            '  "schemaVersion": 1,\n'
            '  "topics": [],\n'
            '  "entityIndex": [],\n'
            '  "writingGuidance": []\n'
            "}\n"
        ),
    }

    def __init__(self, document_store: ProjectDocumentStore | None = None) -> None:
        self.document_store = document_store or ProjectDocumentStore()

    def create_project(
        self,
        path: Path,
        title: str,
        language: str = "zh-CN",
        *,
        database_only: bool = False,
    ) -> NovelProject:
        root = path.expanduser().resolve()

        metadata = NovelMetadata(title=title, language=language)
        novel_file = root / "novel.json"
        if novel_file.exists() or self.document_store.exists(root, "novel.json"):
            raise ValueError(f"novel.json already exists in {root}")

        if database_only:
            self.document_store.write_text(
                root,
                "novel.json",
                json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            )
            for relative_path, content in self.starter_files.items():
                self.document_store.write_text(root, relative_path, content)
            return NovelProject(root=root, metadata=metadata)

        root.mkdir(parents=True, exist_ok=True)
        novel_file.write_text(
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for dirname in self.required_dirs:
            (root / dirname).mkdir(parents=True, exist_ok=True)
        for relative_path, content in self.starter_files.items():
            target = PathGuard(root).resolve(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        return NovelProject(root=root, metadata=metadata)

    def open_project(self, path: Path) -> NovelProject:
        root = path.expanduser().resolve()
        if self.document_store.is_database_project(root):
            metadata = NovelMetadata.model_validate_json(
                self.document_store.read_text(root, "novel.json")
            )
            return NovelProject(root=root, metadata=metadata)
        metadata_path = root / "novel.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"missing novel.json: {metadata_path}")
        metadata = NovelMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        return NovelProject(root=root, metadata=metadata)

    def clone_project(self, source: Path, target: Path) -> NovelProject:
        source_root = self.open_project(source).root
        target_root = target.expanduser().resolve()
        if target_root.exists():
            raise ValueError(f"target project already exists: {target_root}")
        if self.is_database_project(source_root):
            target_root.mkdir(parents=True)
            for relative_path in self.list_paths(source_root):
                self.write_text(
                    target_root,
                    relative_path,
                    self.read_text(source_root, relative_path),
                )
            return self.open_project(target_root)
        shutil.copytree(source_root, target_root)
        return self.open_project(target_root)

    def import_file_project_to_database(
        self,
        root: Path,
        *,
        remove_source_files: bool = False,
    ) -> NovelProject:
        project_root = root.expanduser().resolve()
        if self.is_database_project(project_root):
            return self.open_project(project_root)
        metadata_path = project_root / "novel.json"
        if not metadata_path.is_file():
            raise FileNotFoundError(f"missing novel.json: {metadata_path}")
        documents = [
            (
                path.relative_to(project_root).as_posix(),
                path.read_text(encoding="utf-8"),
            )
            for path in sorted(project_root.rglob("*"))
            if path.is_file()
        ]
        imported_paths = self.document_store.import_texts(project_root, documents)
        if imported_paths != [relative_path for relative_path, _content in documents]:
            raise RuntimeError(f"project migration verification failed: {project_root}")
        for relative_path, content in documents:
            if self.document_store.read_text(project_root, relative_path) != content:
                raise RuntimeError(
                    f"project migration content mismatch: {project_root / relative_path}"
                )
        project = self.open_project(project_root)
        if remove_source_files:
            shutil.rmtree(project_root)
        return project

    def list_files(self, root: Path) -> list[str]:
        project_root = root.expanduser().resolve()
        if self.is_database_project(project_root):
            return self.document_store.list_paths(project_root)
        ignored = {".git", ".venv", "__pycache__"}
        paths: list[str] = []
        for path in sorted(project_root.rglob("*")):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_file():
                paths.append(path.relative_to(project_root).as_posix())
        return paths

    def list_runs(self, root: Path, limit: int = 20) -> list[dict[str, object]]:
        if self.is_database_project(root):
            records: list[dict[str, object]] = []
            for relative_path in reversed(self.list_paths(root, "runs")):
                if not (
                    relative_path.endswith("/run.json")
                    or (
                        relative_path.startswith("runs/model-comparisons/")
                        and relative_path.endswith(".json")
                    )
                ):
                    continue
                try:
                    data = json.loads(self.read_text(root, relative_path))
                except json.JSONDecodeError:
                    continue
                data.setdefault("runId", Path(relative_path).parent.name)
                data["path"] = relative_path
                records.append(data)
            records.sort(
                key=lambda item: str(
                    item.get("createdAt") or item.get("updatedAt") or item.get("path") or ""
                ),
                reverse=True,
            )
            return records[:limit]
        runs_dir = PathGuard(root).resolve("runs")
        if not runs_dir.exists():
            return []

        records: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        for run_file in sorted(runs_dir.glob("*/run.json"), reverse=True):
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            relative_path = run_file.relative_to(PathGuard(root).root).as_posix()
            data["path"] = relative_path
            records.append(data)
            seen_paths.add(relative_path)
        for run_file in sorted(runs_dir.glob("model-comparisons/*.json"), reverse=True):
            relative_path = run_file.relative_to(PathGuard(root).root).as_posix()
            if relative_path in seen_paths:
                continue
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            data.setdefault("runId", run_file.stem)
            data.setdefault("kind", "model-comparison")
            data["path"] = relative_path
            records.append(data)
            seen_paths.add(relative_path)
        records.sort(
            key=lambda item: str(
                item.get("createdAt") or item.get("updatedAt") or item.get("path") or ""
            ),
            reverse=True,
        )
        return records[:limit]

    def get_run(self, root: Path, run_id: str) -> dict[str, object]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
            raise ValueError("invalid run id")
        if self.is_database_project(root):
            relative_path = f"runs/{run_id}/run.json"
            data = json.loads(self.read_text(root, relative_path))
            data["path"] = relative_path
            data["prompt"] = self.read_text_if_exists(root, f"runs/{run_id}/prompt.md")
            data["output"] = self.read_text_if_exists(root, f"runs/{run_id}/output.md")
            return data
        run_dir = PathGuard(root).resolve(f"runs/{run_id}")
        run_file = run_dir / "run.json"
        if not run_file.is_file():
            raise FileNotFoundError(f"missing run: {run_id}")
        data = json.loads(run_file.read_text(encoding="utf-8"))
        data["path"] = run_file.relative_to(PathGuard(root).root).as_posix()
        prompt_file = run_dir / "prompt.md"
        output_file = run_dir / "output.md"
        data["prompt"] = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        data["output"] = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
        return data

    def read_text(self, root: Path, relative_path: str) -> str:
        if self.is_database_project(root):
            return self.document_store.read_text(root, relative_path)
        path = PathGuard(root).resolve(relative_path)
        return path.read_text(encoding="utf-8")

    def write_text(self, root: Path, relative_path: str, content: str) -> None:
        if self.is_database_project(root):
            self.document_store.write_text(root, relative_path, content)
            return
        path = PathGuard(root).resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def next_chapter_id(self, root: Path) -> str:
        if self.is_database_project(root):
            existing = [
                int(match.group(1))
                for relative_path in self.list_paths(root, "chapters")
                if (match := re.fullmatch(r"chapters/(\d+)\.md", relative_path))
            ]
            return f"{(max(existing) if existing else 0) + 1:03d}"
        chapters_dir = PathGuard(root).resolve("chapters")
        existing: list[int] = []
        for path in chapters_dir.glob("*.md"):
            match = re.match(r"(\d+)", path.stem)
            if match:
                existing.append(int(match.group(1)))
        return f"{(max(existing) if existing else 0) + 1:03d}"

    def normalize_chapter_id(self, chapter_id: str) -> str:
        return self._normalize_chapter_id(chapter_id)

    def create_chapter(self, root: Path, chapter_id: str | None, title: str | None = None) -> str:
        normalized_id = self._normalize_chapter_id(chapter_id or self.next_chapter_id(root))
        relative_path = f"chapters/{normalized_id}.md"
        if self.file_exists(root, relative_path):
            raise ValueError(f"chapter already exists: {relative_path}")
        heading = title.strip() if title else normalized_id
        self.write_text(root, relative_path, f"# {heading}\n\n")
        return relative_path

    def accept_draft(
        self,
        root: Path,
        draft_path: str,
        chapter_id: str | None = None,
    ) -> str:
        if not draft_path.startswith("drafts/"):
            raise ValueError("only drafts/ files can be accepted into chapters")
        if not self.file_exists(root, draft_path):
            raise FileNotFoundError(f"missing draft: {draft_path}")

        target_id = self._normalize_chapter_id(
            chapter_id or self._stem_without_generated(Path(draft_path))
        )
        target_path = f"chapters/{target_id}.md"
        self.write_text(root, target_path, self.read_text(root, draft_path))
        return target_path

    def chapter_path_for_draft(self, draft_path: str) -> str:
        if not draft_path.startswith("drafts/"):
            raise ValueError("draft path must start with drafts/")
        draft_name = Path(draft_path).name
        chapter_id = (
            draft_name.removesuffix(".generated.md")
            .removesuffix(".polished.md")
            .removesuffix(".md")
        )
        target_id = self._normalize_chapter_id(chapter_id)
        return f"chapters/{target_id}.md"

    def list_characters(self, root: Path) -> list[str]:
        if self.is_database_project(root):
            return [
                path
                for path in self.list_paths(root, "characters")
                if path.endswith(".md")
            ]
        characters_dir = PathGuard(root).resolve("characters")
        if not characters_dir.exists():
            return []
        return sorted(
            path.relative_to(PathGuard(root).root).as_posix()
            for path in characters_dir.glob("*.md")
            if path.is_file()
        )

    def create_character(self, root: Path, character_id: str, name: str | None = None) -> str:
        normalized_id = self._normalize_slug(character_id, "character id")
        relative_path = f"characters/{normalized_id}.md"
        if self.file_exists(root, relative_path):
            raise ValueError(f"character already exists: {relative_path}")
        display_name = name.strip() if name else normalized_id
        self.write_text(root, relative_path, self._character_template(display_name))
        return relative_path

    def read_timeline_events(self, root: Path) -> TimelineEventsMemory:
        if not self.file_exists(root, "memory/timeline-events.json"):
            return TimelineEventsMemory()
        return TimelineEventsMemory.model_validate_json(
            self.read_text(root, "memory/timeline-events.json")
        )

    def write_timeline_events(self, root: Path, memory: TimelineEventsMemory) -> None:
        self.write_text(
            root,
            "memory/timeline-events.json",
            json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def sync_timeline_events_from_markdown(self, root: Path) -> TimelineEventsMemory:
        markdown = self.read_text(root, "timeline.md")
        events = self._timeline_events_from_markdown(markdown)
        existing = self.read_timeline_events(root)
        memory = TimelineEventsMemory(events=self._merge_timeline_events(events, existing.events))
        self.write_timeline_events(root, memory)
        self._rebuild_all_context_packs_after_memory_change(root)
        return memory

    def _merge_timeline_events(
        self,
        markdown_events: list[TimelineEvent],
        existing_events: list[TimelineEvent],
    ) -> list[TimelineEvent]:
        existing_by_id = {event.id: event for event in existing_events}
        used_existing_ids: set[str] = set()
        merged: list[TimelineEvent] = []

        for event in markdown_events:
            existing = existing_by_id.get(event.id)
            if existing is None:
                existing = self._find_existing_timeline_event(event, existing_events)
            if existing is None:
                merged.append(event)
                continue

            used_existing_ids.add(existing.id)
            existing_data = existing.model_dump(mode="json")
            event_data = event.model_dump(mode="json")
            data = {**existing_data, **event_data}
            if not event.entities and existing.entities:
                data["entities"] = existing.entities
            merged.append(TimelineEvent.model_validate(data))

        for event in existing_events:
            if event.id in used_existing_ids:
                continue
            if event.source == "timeline.md":
                continue
            merged.append(event)
        return merged

    def _find_existing_timeline_event(
        self,
        event: TimelineEvent,
        existing_events: list[TimelineEvent],
    ) -> TimelineEvent | None:
        for existing in existing_events:
            if existing.source != "timeline.md":
                continue
            if existing.summary == event.summary:
                return existing
            if existing.label == event.label and existing.time == event.time:
                return existing
        return None

    def _rebuild_all_context_packs_after_memory_change(self, root: Path) -> None:
        from open_novel.core.context_pack import ContextPackService
        from open_novel.core.story_guidance import StoryGuidanceService

        context_pack_service = ContextPackService(self, StoryGuidanceService(self))
        contract_paths = [
            path
            for path in self.list_paths(root, "story/chapter-briefs")
            if path.endswith(".json")
        ]
        for relative_path in contract_paths:
            try:
                context_pack_service.build_context_pack(root, Path(relative_path).stem)
            except (FileNotFoundError, ValueError):
                continue

    def is_database_project(self, root: Path) -> bool:
        return self.document_store.is_database_project(root.expanduser().resolve())

    def project_exists(self, root: Path) -> bool:
        resolved = root.expanduser().resolve()
        return self.document_store.is_database_project(resolved) or (
            resolved / "novel.json"
        ).is_file()

    def file_exists(self, root: Path, relative_path: str) -> bool:
        if self.is_database_project(root):
            return self.document_store.exists(root, relative_path)
        return PathGuard(root).resolve(relative_path).is_file()

    def read_text_if_exists(self, root: Path, relative_path: str) -> str:
        if not self.file_exists(root, relative_path):
            return ""
        return self.read_text(root, relative_path)

    def delete_text(self, root: Path, relative_path: str) -> None:
        if self.is_database_project(root):
            self.document_store.delete(root, relative_path)
            return
        path = PathGuard(root).resolve(relative_path)
        if path.exists():
            path.unlink()

    def list_paths(self, root: Path, prefix: str = "") -> list[str]:
        if self.is_database_project(root):
            return self.document_store.list_paths(root, prefix)
        base = PathGuard(root).resolve(prefix) if prefix else PathGuard(root).root
        if not base.exists():
            return []
        if base.is_file():
            return [base.relative_to(PathGuard(root).root).as_posix()]
        return sorted(
            path.relative_to(PathGuard(root).root).as_posix()
            for path in base.rglob("*")
            if path.is_file()
        )

    def modified_at(self, root: Path, relative_path: str) -> str:
        if self.is_database_project(root):
            return self.document_store.updated_at(root, relative_path)
        path = PathGuard(root).resolve(relative_path)
        return str(path.stat().st_mtime_ns) if path.is_file() else ""

    def _normalize_chapter_id(self, chapter_id: str) -> str:
        value = chapter_id.strip()
        if not value:
            raise ValueError("chapter id is required")
        if value.isdigit():
            return f"{int(value):03d}"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("chapter id may only contain letters, numbers, hyphen, and underscore")
        return value

    def _stem_without_generated(self, path: Path) -> str:
        return path.stem.removesuffix(".generated").removesuffix(".polished")

    def _normalize_slug(self, value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
            raise ValueError(f"{label} may only contain letters, numbers, hyphen, and underscore")
        return normalized

    def _character_template(self, name: str) -> str:
        return (
            f"# {name}\n\n"
            "- 身份：\n"
            "- 外貌：\n"
            "- 目标：\n"
            "- 恐惧：\n"
            "- 秘密：\n"
            "- 能力：\n"
            "- 关系：\n"
            "- 成长弧：\n"
            "- 语言习惯：\n"
            "- 禁止写法：\n"
        )

    def _timeline_events_from_markdown(self, markdown: str) -> list[TimelineEvent]:
        events: list[TimelineEvent] = []
        for line_number, line in enumerate(markdown.splitlines(), start=1):
            item = self._parse_timeline_line(line)
            if item is None:
                continue
            order = len(events) + 1
            events.append(
                TimelineEvent(
                    id=f"event_{order:03d}",
                    order=order,
                    label=item["label"],
                    time=item["time"],
                    chapterId=item["chapter_id"],
                    evidence=[f"timeline.md#line:{line_number}"],
                    summary=item["summary"],
                )
            )
        return events

    def _parse_timeline_line(self, line: str) -> dict[str, str | None] | None:
        match = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<text>.+?)\s*$", line)
        if match is None:
            return None
        text = match.group("text").strip()
        if not text:
            return None

        chapter_id: str | None = None
        chapter_match = re.search(
            r"(?:chapter|chap|ch|第)\s*[:：]?\s*(?P<id>\d{1,4})(?:\s*章)?",
            text,
            flags=re.IGNORECASE,
        )
        if chapter_match:
            chapter_id = f"{int(chapter_match.group('id')):03d}"

        time = ""
        label = text
        delimiter_match = re.match(r"^(?P<time>[^:：\-]+?)\s*[:：\-]\s*(?P<label>.+)$", text)
        if delimiter_match:
            time = delimiter_match.group("time").strip()
            label = delimiter_match.group("label").strip()

        return {
            "label": label,
            "time": time,
            "chapter_id": chapter_id,
            "line": text,
            "summary": text,
        }
