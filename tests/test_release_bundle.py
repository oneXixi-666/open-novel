from __future__ import annotations

import json
import zipfile
from hashlib import sha256

import pytest

from open_novel import __version__
from scripts.build_release_bundle import (
    build_bundle,
    validate_runtime_modules_are_tracked,
)


def test_release_bundle_contains_manifest_frontend_and_checksum(tmp_path) -> None:
    root = tmp_path / "project"
    output_dir = tmp_path / "dist"
    package_file = root / "open_novel" / "__init__.py"
    frontend_file = root / "frontend" / "dist" / "index.html"
    package_file.parent.mkdir(parents=True)
    frontend_file.parent.mkdir(parents=True)
    package_file.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    frontend_file.write_text("<!doctype html>", encoding="utf-8")

    bundle, checksum_file = build_bundle(
        root=root,
        output_dir=output_dir,
        version=__version__,
        source_files=[package_file],
    )

    prefix = f"open-novel-{__version__}"
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert f"{prefix}/open_novel/__init__.py" in names
        assert f"{prefix}/frontend/dist/index.html" in names
        manifest = json.loads(archive.read(f"{prefix}/update-manifest.json"))
    assert manifest["version"] == __version__
    assert "frontend/dist/index.html" in manifest["files"]
    assert checksum_file.read_text(encoding="ascii").split()[0] == sha256(
        bundle.read_bytes()
    ).hexdigest()


def test_release_bundle_rejects_version_mismatch(tmp_path) -> None:
    frontend_file = tmp_path / "frontend" / "dist" / "index.html"
    frontend_file.parent.mkdir(parents=True)
    frontend_file.write_text("<!doctype html>", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        build_bundle(
            root=tmp_path,
            output_dir=tmp_path / "dist",
            version="9.9.9",
            source_files=[],
        )


def test_release_bundle_excludes_local_data_and_development_outputs(tmp_path) -> None:
    root = tmp_path / "project"
    output_dir = tmp_path / "dist"
    frontend_file = root / "frontend" / "dist" / "index.html"
    frontend_file.parent.mkdir(parents=True)
    frontend_file.write_text("<!doctype html>", encoding="utf-8")
    source_files = [
        root / "open_novel" / "__init__.py",
        root / "output" / "acceptance-report.json",
        root / ".open-novel" / "workspace.sqlite3",
        root / "config" / "workspace.db",
        root / ".env",
        root / "open-novel-ai-secrets.json",
        root / "tests" / "test_private_fixture.py",
        root / "frontend" / ".e2e-runtime" / "workspace.sqlite3",
        root / ".claude" / "settings.local.json",
        root / "scripts" / "stage_d_release_risk_check.py",
    ]
    for path in source_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("local-only", encoding="utf-8")

    bundle, _ = build_bundle(
        root=root,
        output_dir=output_dir,
        version=__version__,
        source_files=source_files,
    )

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    prefix = f"open-novel-{__version__}"
    assert f"{prefix}/open_novel/__init__.py" in names
    assert f"{prefix}/frontend/dist/index.html" in names
    assert not any("/output/" in name for name in names)
    assert not any(name.endswith((".db", ".sqlite", ".sqlite3")) for name in names)
    assert not any("/.env" in name for name in names)
    assert not any(name.endswith("/open-novel-ai-secrets.json") for name in names)
    assert not any("/tests/" in name for name in names)
    assert not any("/.e2e-runtime/" in name for name in names)
    assert not any("/.claude/" in name for name in names)
    assert not any("/stage_d_" in name for name in names)


def test_release_bundle_rejects_untracked_runtime_module(tmp_path) -> None:
    root = tmp_path / "project"
    tracked = root / "open_novel" / "__init__.py"
    untracked = root / "open_novel" / "chapter_progress.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("", encoding="utf-8")
    untracked.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="chapter_progress.py"):
        validate_runtime_modules_are_tracked(root, [tracked])


@pytest.mark.parametrize(
    "content",
    [
        "workspace=/Users/example/private/novel",
        "token=sk-" + "x" * 24,
        "token=ghp_" + "x" * 24,
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_release_bundle_rejects_sensitive_content(tmp_path, content: str) -> None:
    root = tmp_path / "project"
    output_dir = tmp_path / "dist"
    frontend_file = root / "frontend" / "dist" / "index.html"
    frontend_file.parent.mkdir(parents=True)
    frontend_file.write_text("<!doctype html>", encoding="utf-8")
    source_file = root / "open_novel" / "private.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="release bundle contains"):
        build_bundle(
            root=root,
            output_dir=output_dir,
            version=__version__,
            source_files=[source_file],
        )

    assert not (output_dir / f"open-novel-{__version__}.zip").exists()
