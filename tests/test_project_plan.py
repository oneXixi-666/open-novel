from __future__ import annotations

from pathlib import Path

from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.workspace_registry import WorkspaceRegistryService


def test_project_plan_summarizes_chapters_and_words(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="计划测试")
    service = ProjectPlanService()
    service.write_plan(
        project.root,
        target_chapter_count=10,
        target_words_per_chapter=1000,
        platform="番茄小说",
        cadence="日更",
    )
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n她推开门。")
    ProjectService().write_text(project.root, "chapters/002.md", "# 第二章\n\n")

    summary = service.summarize(project.root)

    assert summary.plan.targetChapterCount == 10
    assert summary.plan.targetWordsPerChapter == 1000
    assert summary.completedChapterCount == 1
    assert summary.acceptedWordCount == 4
    assert summary.chapterProgressPercent == 10
    assert summary.nextChapterId == "003"


def test_workspace_registry_lists_multiple_projects(tmp_path: Path) -> None:
    first = ProjectService().create_project(tmp_path / "first", title="第一本")
    second = ProjectService().create_project(tmp_path / "second", title="第二本")
    registry = WorkspaceRegistryService(registry_path=tmp_path / "projects.json")

    registry.register_project(first.root)
    registry.register_project(second.root)
    projects = registry.list_projects()

    assert [item["title"] for item in projects[:2]] == ["第二本", "第一本"]
    assert projects[0]["plan"]["plan"]["targetChapterCount"] == 100
