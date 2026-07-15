from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_assets import WritingAssetService


def _project(tmp_path: Path) -> Path:
    root = ProjectService().create_project(tmp_path / "demo", title="Demo").root
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            focus="主角进入港区寻找信标。",
            goal="确认信标来源。",
            conflict="守卫封锁港区。",
            turn="信标突然回应。",
            outcome="主角找到新入口。",
            hook="入口后传来姐姐的声音。",
            emotionalBeat="主角从克制转为动摇。",
        ),
    )
    ProjectService().write_text(
        root,
        "memory/writing-formulas.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "formulas": [
                    {
                        "id": "ending_hook_grounded",
                        "title": "钩子从结果里长出来",
                        "guidance": "章末问题必须由本章结果引出。",
                        "status": "suggested",
                        "evidenceChapters": ["001"],
                        "sourceAnalysis": "runs/analysis.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    return root


def test_writing_assets_share_enabled_rules_with_context_and_gate(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assets = WritingAssetService()
    assets.set_formula_status(root, "ending_hook_grounded", "active")
    context = ContextPackService(writing_assets=assets)
    pack = context.build_context_pack(root, "001")

    item = next(item for item in pack.included if item.source == "story/style-profile.json")
    effective = item.data["effectiveWritingAssets"]
    assert effective["formulas"][0]["id"] == "ending_hook_grounded"
    assert effective["sources"] == [
        "story/style-profile.json",
        "memory/writing-formulas.json",
        "memory/writing-lessons.json",
    ]

    assets.set_formula_status(root, "ending_hook_grounded", "retired")
    updated = context.build_context_pack(root, "001")
    updated_item = next(
        item for item in updated.included if item.source == "story/style-profile.json"
    )

    assert "effectiveWritingAssets" not in updated_item.data
