from __future__ import annotations

from pathlib import Path

import pytest

from open_novel.core.project import ProjectService


def test_create_chapter_uses_next_numeric_id(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    path = ProjectService().create_chapter(project.root, chapter_id=None, title="第二章")

    assert path == "chapters/002.md"
    assert (project.root / path).read_text(encoding="utf-8").startswith("# 第二章")


def test_create_chapter_rejects_duplicate(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    with pytest.raises(ValueError, match="already exists"):
        ProjectService().create_chapter(project.root, chapter_id="001", title="Duplicate")


def test_accept_draft_writes_canonical_chapter(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "drafts/002.generated.md", "# Draft\n\nBody")

    path = ProjectService().accept_draft(project.root, "drafts/002.generated.md")

    assert path == "chapters/002.md"
    assert (project.root / "chapters/002.md").read_text(encoding="utf-8") == "# Draft\n\nBody"


def test_accept_draft_rejects_non_draft_source(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    with pytest.raises(ValueError, match="only drafts"):
        ProjectService().accept_draft(project.root, "chapters/001.md")
