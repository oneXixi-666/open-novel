from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService
from open_novel.core.workspace_registry import WorkspaceRegistryService


class ProjectBackupService:
    manifest_name = "open-novel-backup.json"
    registry_name = "workbench-registry.json"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        registry_path: Path | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.registry_path = (
            registry_path or WorkspaceRegistryService.default_registry_path()
        ).resolve()

    def create(self, root: Path, output: Path) -> dict[str, Any]:
        project = self.project_service.open_project(root)
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        files = [path for path in sorted(project.root.rglob("*")) if path.is_file()]
        registry = self._registry_rows(project.root)
        manifest = {
            "schemaVersion": 1,
            "createdAt": datetime.now(UTC).isoformat(),
            "projectRoot": project.root.as_posix(),
            "title": project.metadata.title,
            "fileCount": len(files),
            "registryTableCount": len(registry),
            "files": {
                path.relative_to(project.root).as_posix(): self._hash(path) for path in files
            },
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, f"project/{path.relative_to(project.root).as_posix()}")
            archive.writestr(
                self.registry_name,
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            )
            archive.writestr(
                self.manifest_name,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        return {**manifest, "backupPath": output.as_posix()}

    def verify(self, backup: Path) -> dict[str, Any]:
        backup = backup.expanduser().resolve()
        with zipfile.ZipFile(backup) as archive:
            manifest = json.loads(archive.read(self.manifest_name))
            expected = manifest.get("files") if isinstance(manifest, dict) else None
            if not isinstance(expected, dict):
                raise ValueError("备份清单格式无效。")
            for relative_path, digest in expected.items():
                data = archive.read(f"project/{relative_path}")
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f"备份文件校验失败：{relative_path}")
            json.loads(archive.read(self.registry_name))
        return {
            "status": "passed",
            "backupPath": backup.as_posix(),
            "fileCount": len(expected),
            "projectRoot": str(manifest.get("projectRoot") or ""),
        }

    def restore(
        self, backup: Path, destination: Path, *, overwrite: bool = False
    ) -> dict[str, Any]:
        verified = self.verify(backup)
        destination = destination.expanduser().resolve()
        if destination.exists() and any(destination.iterdir()) and not overwrite:
            raise FileExistsError("恢复目录非空；确认覆盖后才能继续。")
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup.expanduser().resolve()) as archive:
            manifest = json.loads(archive.read(self.manifest_name))
            for relative_path in manifest["files"]:
                target = (destination / relative_path).resolve()
                if destination not in target.parents:
                    raise ValueError("备份包含越界路径。")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(f"project/{relative_path}"))
            registry = json.loads(archive.read(self.registry_name))
        self._restore_registry(
            registry,
            old_root=str(manifest.get("projectRoot") or verified["projectRoot"]),
            new_root=destination.as_posix(),
        )
        self.project_service.open_project(destination)
        return {
            "status": "restored",
            "projectRoot": destination.as_posix(),
            "fileCount": verified["fileCount"],
        }

    def _registry_rows(self, root: Path) -> dict[str, list[dict[str, Any]]]:
        if not self.registry_path.is_file():
            return {}
        result: dict[str, list[dict[str, Any]]] = {}
        with sqlite3.connect(self.registry_path) as connection:
            connection.row_factory = sqlite3.Row
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                columns = [
                    str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
                ]
                if "root" not in columns:
                    continue
                rows = connection.execute(
                    f'SELECT * FROM "{table}" WHERE root = ?', (root.as_posix(),)
                ).fetchall()
                if rows:
                    result[table] = [dict(row) for row in rows]
        return result

    def _restore_registry(
        self,
        data: Any,
        *,
        old_root: str,
        new_root: str,
    ) -> None:
        if not isinstance(data, dict) or not self.registry_path.is_file():
            return
        with sqlite3.connect(self.registry_path) as connection:
            existing_tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table, rows in data.items():
                if table not in existing_tables or not isinstance(rows, list):
                    continue
                for raw in rows:
                    if not isinstance(raw, dict) or not raw:
                        continue
                    row = {
                        key: self._remap_root(value, old_root, new_root)
                        for key, value in raw.items()
                    }
                    columns = list(row)
                    placeholders = ", ".join("?" for _ in columns)
                    names = ", ".join(f'"{column}"' for column in columns)
                    connection.execute(
                        f'INSERT OR REPLACE INTO "{table}" ({names}) VALUES ({placeholders})',
                        [row[column] for column in columns],
                    )

    def _remap_root(self, value: Any, old_root: str, new_root: str) -> Any:
        if isinstance(value, str):
            return value.replace(old_root, new_root)
        return value

    def _hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
