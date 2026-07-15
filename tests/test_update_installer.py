from __future__ import annotations

import json
import zipfile
from hashlib import sha256
from pathlib import Path

import pytest

from open_novel.core.update_installer import UpdateInstaller, UpdateInstallError


def _write_package(
    root: Path,
    files: dict[str, bytes],
    *,
    manifest_files: list[str] | None = None,
) -> Path:
    package_path = root / "open-novel-0.2.0.zip"
    prefix = "open-novel-0.2.0"
    with zipfile.ZipFile(package_path, "w") as archive:
        for relative_path, content in files.items():
            archive.writestr(f"{prefix}/{relative_path}", content)
        archive.writestr(
            f"{prefix}/update-manifest.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "version": "0.2.0",
                    "files": manifest_files if manifest_files is not None else list(files),
                },
                ensure_ascii=False,
            ),
        )
    return package_path


def _write_plan(root: Path, install_root: Path, package_path: Path) -> Path:
    plan_path = root / "update-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "prepared",
                "currentVersion": "0.1.0",
                "targetVersion": "0.2.0",
                "installRoot": str(install_root),
                "packagePath": str(package_path),
                "packageSha256": sha256(package_path.read_bytes()).hexdigest(),
                "databasePath": str(root / "workspace.sqlite3"),
                "databaseBackupPath": str(root / "workspace-before-update.sqlite3"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return plan_path


def test_update_installer_applies_and_rolls_back_files(tmp_path) -> None:
    install_root = tmp_path / "application"
    install_root.mkdir()
    existing = install_root / "open_novel" / "__init__.py"
    existing.parent.mkdir()
    existing.write_text('VERSION = "old"\n', encoding="utf-8")
    package_path = _write_package(
        tmp_path,
        {
            "open_novel/__init__.py": b'VERSION = "new"\n',
            "frontend/dist/index.html": b"<html>new</html>",
        },
    )
    plan_path = _write_plan(tmp_path, install_root, package_path)
    installer = UpdateInstaller()

    applied = installer.apply(plan_path)

    assert applied["replacedFileCount"] == 1
    assert applied["createdFileCount"] == 1
    assert existing.read_text(encoding="utf-8") == 'VERSION = "new"\n'
    assert (install_root / "frontend/dist/index.html").read_text() == "<html>new</html>"
    assert json.loads(plan_path.read_text(encoding="utf-8"))["status"] == "applied"

    rolled_back = installer.rollback(plan_path)

    assert rolled_back["restoredFileCount"] == 1
    assert existing.read_text(encoding="utf-8") == 'VERSION = "old"\n'
    assert not (install_root / "frontend/dist/index.html").exists()
    assert json.loads(plan_path.read_text(encoding="utf-8"))["status"] == "rolled_back"


def test_update_installer_rejects_protected_or_traversal_paths(tmp_path) -> None:
    install_root = tmp_path / "application"
    install_root.mkdir()
    package_path = _write_package(
        tmp_path,
        {".git/config": b"blocked"},
    )
    plan_path = _write_plan(tmp_path, install_root, package_path)

    with pytest.raises(UpdateInstallError, match="不允许写入"):
        UpdateInstaller().apply(plan_path)

    assert not (install_root / ".git/config").exists()


def test_update_installer_rejects_checksum_mismatch(tmp_path) -> None:
    install_root = tmp_path / "application"
    install_root.mkdir()
    package_path = _write_package(tmp_path, {"open_novel/app.py": b"new"})
    plan_path = _write_plan(tmp_path, install_root, package_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["packageSha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(UpdateInstallError, match="摘要"):
        UpdateInstaller().apply(plan_path)
