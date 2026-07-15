from __future__ import annotations

from pathlib import Path

from open_novel.core.skills import SkillLoader, default_skills_dir


def test_skill_loader_loads_builtin_skill() -> None:
    loader = SkillLoader(Path("skills"))

    skills = loader.list_skills()
    ids = {skill.id for skill in skills}

    assert "chapter-writer" in ids
    assert loader.load_prompt("chapter-writer").strip()


def test_default_skill_loader_falls_back_to_packaged_skills(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    loader = SkillLoader()
    ids = {skill.id for skill in loader.list_skills()}

    assert default_skills_dir().name == "builtin_skills"
    assert "chapter-writer" in ids
    assert "Chapter Writer" in loader.load_prompt("chapter-writer")
