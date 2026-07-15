from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.beginner_guidance import BeginnerGuidanceService, BeginnerProjectInput
from open_novel.core.story_guidance import StoryGuidanceService


def _beginner_request(root: Path) -> BeginnerProjectInput:
    return BeginnerProjectInput(
        path=root,
        title="新手项目",
        idea="一个不会写小说的人，用一次选择开始改变命运。",
        genre="都市成长",
        targetReaders="喜欢成长、反击和情绪代价的读者",
        protagonistName="许开",
        protagonistDesire="想证明自己能独立解决问题。",
        protagonistWound="害怕自己永远只能依赖别人。",
        opponent="掌握资源的上级和旧关系压力",
        worldRule="每次获得机会都要付出关系或名誉代价。",
        longMystery="许开当年失败的真正原因是什么。",
        corePromise="主角会一步步夺回选择权。",
        volumeGoal="第一卷让主角完成第一次公开反击。",
        chapterCount=5,
    )


def test_beginner_guidance_creates_writable_project_foundation(tmp_path: Path) -> None:
    result = BeginnerGuidanceService().create_guided_project(
        _beginner_request(tmp_path / "guided")
    )

    root = result.root
    metadata = json.loads((root / "novel.json").read_text(encoding="utf-8"))
    promises = json.loads((root / "memory" / "promises.json").read_text(encoding="utf-8"))
    protagonist = (root / "characters" / "protagonist.md").read_text(encoding="utf-8")

    assert result.chapterCount == 5
    assert result.nextRoute.endswith("chapterId=001")
    assert metadata["title"] == "新手项目"
    assert metadata["targetReaders"] == "喜欢成长、反击和情绪代价的读者"
    assert "一个不会写小说的人" in (root / "bible.md").read_text(encoding="utf-8")
    assert "许开" in protagonist
    assert promises["promises"][0]["text"] == "主角会一步步夺回选择权。"

    guidance = StoryGuidanceService()
    for index in range(1, 6):
        chapter_id = f"{index:03d}"
        assert (root / "story" / "chapter-briefs" / f"{chapter_id}.json").exists()
        assert guidance.check_readiness(root, chapter_id).status in {"pass", "warn"}
        assert (root / "story" / "context-packs" / f"{chapter_id}.json").exists()
