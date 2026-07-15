from __future__ import annotations

from pathlib import Path

import pytest

from open_novel.security.path_guard import PathGuard


def test_path_guard_allows_relative_path(tmp_path: Path) -> None:
    resolved = PathGuard(tmp_path).resolve("chapters/001.md")

    assert resolved == tmp_path / "chapters" / "001.md"


def test_path_guard_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        PathGuard(tmp_path).resolve("../outside.md")


def test_path_guard_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        PathGuard(tmp_path).resolve("/tmp/outside.md")


def test_path_guard_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "secret.md").write_text("nope", encoding="utf-8")
    (project / "linked").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes"):
        PathGuard(project).resolve("linked/secret.md")
