from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from open_novel.core.models import utc_now


def default_workspace_db_path() -> Path:
    configured_db = os.environ.get("OPEN_NOVEL_DB_PATH")
    if configured_db:
        return Path(configured_db).expanduser().resolve()
    configured_registry = os.environ.get("OPEN_NOVEL_REGISTRY_PATH")
    if configured_registry:
        return Path(configured_registry).expanduser().resolve()
    return (Path.cwd() / ".open-novel" / "workspace.sqlite3").resolve()


class ProjectDocumentStore:
    """Store database-backed project documents without materializing project files."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or default_workspace_db_path()).resolve()
        self._ensure_schema()

    def is_database_project(self, root: Path) -> bool:
        return self.exists(root, "novel.json")

    def exists(self, root: Path, relative_path: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM workbench_project_documents
                WHERE root = ? AND relative_path = ?
                """,
                (root.resolve().as_posix(), self._normalize_path(relative_path)),
            ).fetchone()
        return row is not None

    def read_text(self, root: Path, relative_path: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content
                FROM workbench_project_documents
                WHERE root = ? AND relative_path = ?
                """,
                (root.resolve().as_posix(), self._normalize_path(relative_path)),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"missing project document: {relative_path}")
        return str(row["content"] or "")

    def write_text(self, root: Path, relative_path: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_project_documents (
                    root, relative_path, content, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(root, relative_path) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (
                    root.resolve().as_posix(),
                    self._normalize_path(relative_path),
                    content,
                    utc_now().isoformat(),
                ),
            )

    def import_texts(
        self,
        root: Path,
        documents: Iterable[tuple[str, str]],
    ) -> list[str]:
        normalized_root = root.resolve().as_posix()
        imported: list[str] = []
        now = utc_now().isoformat()
        with self._connect() as conn:
            for relative_path, content in documents:
                normalized_path = self._normalize_path(relative_path)
                conn.execute(
                    """
                    INSERT INTO workbench_project_documents (
                        root, relative_path, content, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(root, relative_path) DO UPDATE SET
                        content = excluded.content,
                        updated_at = excluded.updated_at
                    """,
                    (normalized_root, normalized_path, content, now),
                )
                imported.append(normalized_path)
        return imported

    def delete(self, root: Path, relative_path: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM workbench_project_documents
                WHERE root = ? AND relative_path = ?
                """,
                (root.resolve().as_posix(), self._normalize_path(relative_path)),
            )

    def list_paths(self, root: Path, prefix: str = "") -> list[str]:
        normalized_prefix = self._normalize_prefix(prefix)
        query = """
            SELECT relative_path
            FROM workbench_project_documents
            WHERE root = ?
        """
        params: list[str] = [root.resolve().as_posix()]
        if normalized_prefix:
            query += " AND relative_path LIKE ?"
            params.append(f"{normalized_prefix}%")
        query += " ORDER BY relative_path ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [str(row["relative_path"]) for row in rows]

    def updated_at(self, root: Path, relative_path: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT updated_at
                FROM workbench_project_documents
                WHERE root = ? AND relative_path = ?
                """,
                (root.resolve().as_posix(), self._normalize_path(relative_path)),
            ).fetchone()
        return str(row["updated_at"] or "") if row else ""

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_project_documents (
                    root TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, relative_path)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workbench_project_documents_root
                ON workbench_project_documents(root, relative_path)
                """
            )

    def _normalize_path(self, relative_path: str) -> str:
        normalized = Path(relative_path).as_posix().lstrip("/")
        if not normalized or normalized == "." or ".." in Path(normalized).parts:
            raise ValueError("invalid project document path")
        return normalized

    def _normalize_prefix(self, prefix: str) -> str:
        normalized = Path(prefix).as_posix().lstrip("/")
        if normalized in {"", "."}:
            return ""
        if ".." in Path(normalized).parts:
            raise ValueError("invalid project document prefix")
        return normalized.rstrip("/") + "/"
