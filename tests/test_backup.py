from __future__ import annotations

import sqlite3
from pathlib import Path

from open_novel.core.backup import ProjectBackupService
from open_novel.core.project import ProjectService
from open_novel.core.workbench_repository import WorkbenchRepository


def test_project_backup_restores_files_and_workbench_state(tmp_path: Path) -> None:
    registry = tmp_path / "workspace.sqlite3"
    repository = WorkbenchRepository(registry)
    project = ProjectService().create_project(tmp_path / "source", title="Backup Demo")
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n正文。\n")
    repository.write_generation_state(
        project.root,
        {
            "bookId": project.root.as_posix(),
            "stage": "gate",
            "status": "blocked",
            "activeChapterId": "001",
        },
    )
    repository.upsert_material(
        project.root,
        {
            "id": "world-rule",
            "type": "设定",
            "title": "潮汐规则",
            "summary": "退潮后旧城开放。",
            "confidence": 90,
        },
    )
    service = ProjectBackupService(registry_path=registry)
    backup = tmp_path / "backup.onovel.zip"

    created = service.create(project.root, backup)
    verified = service.verify(backup)
    restored = service.restore(backup, tmp_path / "restored")

    restored_root = Path(restored["projectRoot"])
    assert created["fileCount"] == verified["fileCount"]
    assert (restored_root / "chapters/001.md").read_text(encoding="utf-8").endswith("正文。\n")
    restored_state = repository.read_generation_state(restored_root)
    assert restored_state["stage"] == "gate"
    assert restored_state["bookId"] == restored_root.as_posix()
    assert repository.list_materials(restored_root)[0]["id"] == "world-rule"


def test_workbench_repository_migrates_legacy_calibration_labels(tmp_path: Path) -> None:
    registry = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(registry) as connection:
        connection.execute(
            """
            CREATE TABLE calibration_annotations (
                id INTEGER PRIMARY KEY,
                project_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                label TEXT CHECK(label IN ('gold','acceptable','reject')) NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, chapter_id)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO calibration_annotations
                (project_id, chapter_id, label, note, created_at)
            VALUES (?, ?, ?, '', '2026-07-11T00:00:00Z')
            """,
            [
                ("/demo", "001", "gold"),
                ("/demo", "002", "acceptable"),
                ("/demo", "003", "reject"),
            ],
        )

    repository = WorkbenchRepository(registry)

    assert [
        item["label"] for item in repository.list_calibration_annotations(Path("/demo"))
    ] == ["acceptable", "acceptable", "block"]
