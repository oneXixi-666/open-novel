from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from open_novel.core.models import NovelProject, utc_now
from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.workspace_storage import default_workspace_db_path


class WorkspaceRegistryService:
    """Persist the creator's workspace bookshelf in a local SQLite database."""

    def __init__(
        self,
        registry_path: Path | None = None,
        project_service: ProjectService | None = None,
        plan_service: ProjectPlanService | None = None,
    ) -> None:
        self.db_path = registry_path or self.default_registry_path()
        self.registry_path = self.db_path
        self.project_service = project_service or ProjectService()
        self.plan_service = plan_service or ProjectPlanService(self.project_service)
        self._migrate_legacy_json_if_needed()
        self._ensure_schema()

    @staticmethod
    def default_registry_path() -> Path:
        return default_workspace_db_path()

    @staticmethod
    def is_initialized(registry_path: Path | None = None) -> bool:
        db_path = registry_path or WorkspaceRegistryService.default_registry_path()
        if not db_path.is_file():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'workspace_projects'
                    """
                ).fetchone()
        except sqlite3.DatabaseError:
            return False
        return row is not None

    def register_project(self, root: Path) -> dict[str, Any]:
        project = self.project_service.open_project(root)
        now = utc_now().isoformat()
        existing = self._project_row(project.root.as_posix())
        created_at = (
            str(existing["created_at"])
            if existing is not None and existing["created_at"]
            else project.metadata.createdAt.isoformat()
        )
        record = self._record_from_project(
            project,
            created_at=created_at,
            last_opened_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_projects (
                    root, title, language, genre_json, target_readers,
                    created_at, updated_at, last_opened_at, available, plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root) DO UPDATE SET
                    title = excluded.title,
                    language = excluded.language,
                    genre_json = excluded.genre_json,
                    target_readers = excluded.target_readers,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at,
                    available = excluded.available,
                    plan_json = excluded.plan_json
                """,
                self._record_params(record),
            )
        return record

    def list_projects(self) -> list[dict[str, Any]]:
        return self.list_project_page(page=1, per_page=500)["items"]

    def list_project_page(self, *, page: int = 1, per_page: int = 8) -> dict[str, Any]:
        page = max(1, int(page or 1))
        per_page = max(1, min(int(per_page or 8), 48))
        offset = (page - 1) * per_page
        with self._connect() as conn:
            total = int(
                conn.execute("SELECT COUNT(*) FROM workspace_projects").fetchone()[0]
            )
            rows = conn.execute(
                """
                SELECT * FROM workspace_projects
                ORDER BY last_opened_at DESC, updated_at DESC, title ASC
                LIMIT ? OFFSET ?
                """,
                (per_page, offset),
            ).fetchall()
        items = [self._fresh_record_from_row(row) for row in rows]
        page_count = max(1, (total + per_page - 1) // per_page)
        return {
            "items": items,
            "page": page,
            "perPage": per_page,
            "total": total,
            "pageCount": page_count,
            "hasPrevious": page > 1,
            "hasNext": page < page_count,
            "previousPage": max(1, page - 1),
            "nextPage": min(page_count, page + 1),
        }

    def _fresh_record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        root = Path(str(row["root"]))
        try:
            if (root / "novel.json").is_file() and not self.project_service.is_database_project(
                root
            ):
                self.project_service.import_file_project_to_database(
                    root,
                    remove_source_files=True,
                )
            project = self.project_service.open_project(root)
        except (FileNotFoundError, ValueError):
            record = self._record_from_row(row)
            record["available"] = False
            self._save_record(record)
            return record
        record = self._record_from_project(
            project,
            created_at=str(row["created_at"] or project.metadata.createdAt.isoformat()),
            last_opened_at=str(row["last_opened_at"] or row["updated_at"] or ""),
        )
        self._save_record(record)
        return record

    def _record_from_project(
        self,
        project: NovelProject,
        *,
        created_at: str = "",
        last_opened_at: str = "",
    ) -> dict[str, Any]:
        summary = self.plan_service.summarize(project.root)
        return {
            "root": project.root.as_posix(),
            "title": project.metadata.title,
            "language": project.metadata.language,
            "genre": project.metadata.genre,
            "targetReaders": project.metadata.targetReaders,
            "createdAt": created_at or project.metadata.createdAt.isoformat(),
            "updatedAt": project.metadata.updatedAt.isoformat(),
            "lastOpenedAt": last_opened_at or utc_now().isoformat(),
            "available": True,
            "plan": summary.model_dump(mode="json"),
        }

    def _record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "root": str(row["root"]),
            "title": str(row["title"] or ""),
            "language": str(row["language"] or "zh-CN"),
            "genre": self._loads_list(str(row["genre_json"] or "[]")),
            "targetReaders": str(row["target_readers"] or ""),
            "createdAt": str(row["created_at"] or ""),
            "updatedAt": str(row["updated_at"] or ""),
            "lastOpenedAt": str(row["last_opened_at"] or ""),
            "available": bool(row["available"]),
            "plan": self._loads_dict(str(row["plan_json"] or "{}")),
        }

    def _save_record(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspace_projects (
                    root, title, language, genre_json, target_readers,
                    created_at, updated_at, last_opened_at, available, plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root) DO UPDATE SET
                    title = excluded.title,
                    language = excluded.language,
                    genre_json = excluded.genre_json,
                    target_readers = excluded.target_readers,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    last_opened_at = excluded.last_opened_at,
                    available = excluded.available,
                    plan_json = excluded.plan_json
                """,
                self._record_params(record),
            )

    def _record_params(self, record: dict[str, Any]) -> tuple[Any, ...]:
        return (
            str(record["root"]),
            str(record.get("title") or ""),
            str(record.get("language") or "zh-CN"),
            json.dumps(record.get("genre") or [], ensure_ascii=False),
            str(record.get("targetReaders") or ""),
            str(record.get("createdAt") or ""),
            str(record.get("updatedAt") or ""),
            str(record.get("lastOpenedAt") or ""),
            1 if record.get("available", True) else 0,
            json.dumps(record.get("plan") or {}, ensure_ascii=False),
        )

    def _project_row(self, root: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM workspace_projects WHERE root = ?",
                (root,),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspace_projects (
                    root TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'zh-CN',
                    genre_json TEXT NOT NULL DEFAULT '[]',
                    target_readers TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT NOT NULL,
                    available INTEGER NOT NULL DEFAULT 1,
                    plan_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workspace_projects_last_opened
                ON workspace_projects(last_opened_at DESC)
                """
            )
            if version < 1:
                conn.execute("PRAGMA user_version = 1")

    def _migrate_legacy_json_if_needed(self) -> None:
        if not self.db_path.is_file():
            legacy = self.db_path.with_name("projects.json")
            if self.db_path.name != "projects.json" and legacy.is_file():
                self._migrate_legacy_json(legacy)
            return
        try:
            prefix = self.db_path.read_bytes()[:1]
        except OSError:
            return
        if prefix not in {b"{", b"["}:
            return
        legacy = self.db_path.with_suffix(self.db_path.suffix + ".legacy-json")
        self.db_path.replace(legacy)
        self._migrate_legacy_json(legacy)

    def _migrate_legacy_json(self, legacy_path: Path) -> None:
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        projects = data.get("projects") if isinstance(data, dict) else None
        if not isinstance(projects, list):
            return
        self._ensure_schema()
        for item in projects:
            if not isinstance(item, dict):
                continue
            root = str(item.get("root") or "").strip()
            if not root:
                continue
            try:
                project = self.project_service.open_project(Path(root))
            except (FileNotFoundError, ValueError):
                record = {
                    "root": root,
                    "title": str(item.get("title") or Path(root).name),
                    "language": str(item.get("language") or "zh-CN"),
                    "genre": item.get("genre") if isinstance(item.get("genre"), list) else [],
                    "targetReaders": str(item.get("targetReaders") or ""),
                    "createdAt": str(item.get("createdAt") or utc_now().isoformat()),
                    "updatedAt": str(item.get("updatedAt") or utc_now().isoformat()),
                    "lastOpenedAt": str(item.get("lastOpenedAt") or utc_now().isoformat()),
                    "available": False,
                    "plan": item.get("plan") if isinstance(item.get("plan"), dict) else {},
                }
            else:
                record = self._record_from_project(
                    project,
                    created_at=str(item.get("createdAt") or project.metadata.createdAt.isoformat()),
                    last_opened_at=str(item.get("lastOpenedAt") or ""),
                )
            self._save_record(record)

    def _loads_list(self, text: str) -> list[Any]:
        try:
            value = json.loads(text)
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    def _loads_dict(self, text: str) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
