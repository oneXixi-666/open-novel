from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from open_novel.core.editorial_profile import EditorialProfileService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


def write_contract(root: Path) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="林澈在山门测试中证明异常潜力。",
            goal="林澈想通过山门测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="林澈从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            internalNeed="林澈想证明自己不是任人踩踏的废物。",
            woundOrFear="林澈害怕再次被当众否定。",
            stakes="如果失败，林澈会失去进入宗门和追查测试石异常的机会。",
            cost="林澈证明潜力的同时暴露异常，被长老盯上。",
            subtext="林澈嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            mustInclude=["测试石"],
            readerPromises=["废柴逆袭"],
        ),
    )


def test_editorial_prompt_presets_are_listed_and_validated(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = EditorialProfileService()

    presets = service.list_prompt_presets()
    preset_ids = {preset.id for preset in presets}

    assert "generic-humanity" in preset_ids
    assert "continuity-editor" in preset_ids
    assert "emotion-line-editor" in preset_ids
    assert "platform-genre-commercial-editor" in preset_ids
    assert all(any("\u4e00" <= char <= "\u9fff" for char in preset.label) for preset in presets)
    assert service.get_prompt_preset("platform-genre-commercial-editor").rubric
    with pytest.raises(ValueError):
        service.register_profile(
            project.root,
            profile_id="bad-editor",
            prompt_preset="unknown-editor",
        )


def test_editorial_profile_registry_persists_in_database_project(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    root = tmp_path / "database-book"
    project_service = ProjectService()
    project_service.create_project(root, title="数据库审稿配置", database_only=True)
    service = EditorialProfileService(project_service)

    service.register_profile(
        root,
        profile_id="continuity-reviewer",
        label="连续性审稿",
        prompt_preset="continuity-editor",
        set_default=True,
    )
    reloaded = EditorialProfileService(ProjectService()).read_registry(root)

    assert reloaded.defaultProfileId == "continuity-reviewer"
    assert any(profile.label == "连续性审稿" for profile in reloaded.profiles)
    assert not root.exists()


def test_editorial_review_flags_flat_emotion_and_missing_cost(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "林澈参加测试。他感到十分愤怒，也很害怕。规则很多，据说很多年前就是如此。"
        "最后他通过了测试，大家都很震惊。",
    )

    report = EditorialReviewService().review_chapter(project.root, "001")

    issue_types = {issue.type for issue in report.issues}
    assert "emotion_told_not_felt" in issue_types
    assert "abstract_human_core" in issue_types
    assert "payoff_without_cost" in issue_types
    assert report.status in {"warn", "block"}
    assert (project.root / "runs" / "editorial-review-001.json").exists()


def test_editorial_review_learns_bounded_writing_lessons(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "林澈参加测试。他感到十分愤怒，也很害怕。最后他通过了测试，大家都很震惊。",
    )

    EditorialReviewService().review_chapter(project.root, "001")
    EditorialReviewService().review_chapter(project.root, "001")

    memory = json.loads(
        (project.root / "memory" / "writing-lessons.json").read_text(encoding="utf-8")
    )
    emotion_lesson = next(
        lesson
        for lesson in memory["lessons"]
        if lesson["id"] == "lesson_emotion_emotion_told_not_felt"
    )

    assert emotion_lesson["category"] == "emotion"
    assert emotion_lesson["failureCount"] == 2
    assert "动作" in emotion_lesson["lesson"]
    assert "emotion_told_not_felt" in emotion_lesson["appliesTo"]


def test_editorial_review_rewards_concrete_human_core(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "测试石前，林澈握紧指尖，胸口那口压抑的气几乎顶到喉咙。\n\n"
        "旧敌冷笑着拦在前方：“你这种残缺灵根，也配站上去？”\n\n"
        "林澈没有解释，也没有求饶。他选择踏上石阶，把掌心按在测试石上。\n\n"
        "下一刻，测试石忽然异动，暗纹从石心亮起。旧敌先一步变了脸色，长老也抬眼盯住他。\n\n"
        "如果失败，林澈会失去进入宗门和追查测试石异常的机会；可退下去，他就又一次被当众否定。\n\n"
        "他咬牙把最后一缕灵力推入暗纹。林澈证明潜力的同时暴露异常，被长老盯上。\n\n"
        "林澈嘴上冷静，实际是在保护最后一点尊严。旧敌想再说什么，却在长老的目光下沉默。\n\n"
        "门外忽然送来一枚裂开的玉牌。读者应感到爽快，同时意识到更大危险来了。\n",
    )

    report = EditorialReviewService().review_chapter(project.root, "001")

    assert report.score >= 70
    assert report.strengths
    assert "emotion_told_not_felt" not in {issue.type for issue in report.issues}


def test_editorial_review_command_backend_writes_validated_report(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "prompt = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "report = {\n"
        "  'reviewer': 'fake-llm-editor',\n"
        "  'issues': [{\n"
        "    'type': 'motivation_not_personal',\n"
        "    'severity': 'high',\n"
        "    'dimension': 'character',\n"
        "    'evidence': [prompt['source']],\n"
        "    'message': '人物动机还停留在剧情功能，没有私人伤口。',\n"
        "    'suggestions': ['把通过测试和旧伤、尊严或关系代价绑在一起。'],\n"
        "  }],\n"
        "  'strengths': ['外部事件清楚。'],\n"
        "}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    report = EditorialReviewService().review_chapter(
        project.root,
        "001",
        backend="command",
        command_template=f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
    )

    stored = json.loads(
        (project.root / "runs" / "editorial-review-001.json").read_text(encoding="utf-8")
    )
    assert report.reviewer == "fake-llm-editor"
    assert report.status == "warn"
    assert report.score == 82
    assert report.metrics["backend"] == "command"
    assert report.metrics["styleProfileId"] == "project-style"
    assert report.issues[0].type == "motivation_not_personal"
    assert stored["reviewer"] == "fake-llm-editor"


def test_database_editorial_command_keeps_run_artifacts_out_of_project_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    service = ProjectService()
    project = service.create_project(
        tmp_path / "database-demo",
        title="Database Demo",
        database_only=True,
    )
    write_contract(project.root)
    service.write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = tmp_path / "editor.py"
    script.write_text(
        "import json, sys\n"
        "report = {'reviewer': 'database-editor', 'score': 88, 'status': 'pass'}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    report = EditorialReviewService(service).review_chapter(
        project.root,
        "001",
        backend="command",
        command_template=f"{sys.executable} {script} {{prompt_file}} {{output_file}}",
    )

    assert report.reviewer == "database-editor"
    assert not project.root.exists()
    assert service.file_exists(
        project.root,
        "runs/editorial-review-001-command/prompt.json",
    )
    assert service.file_exists(
        project.root,
        "runs/editorial-review-001-command/output.json",
    )
    assert service.file_exists(project.root, "runs/editorial-review-001.json")


def test_editorial_review_command_prompt_includes_style_profile_override(
    tmp_path: Path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "story/style-profile.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "project-suspense",
                "extends": "generic-web-serial",
                "platform": "custom-platform",
                "genres": ["悬疑"],
                "editorialFocus": ["线索公平", "情绪压迫"],
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "prompt = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "assert prompt['styleProfile']['id'] == 'project-suspense'\n"
        "assert prompt['styleProfile']['platform'] == 'custom-platform'\n"
        "assert prompt['styleProfile']['genres'] == ['悬疑']\n"
        "report = {'reviewer': 'style-aware-editor', 'score': 88, 'status': 'pass'}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )

    report = EditorialReviewService().review_chapter(
        project.root,
        "001",
        backend="command",
        command_template=f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
    )

    assert report.reviewer == "style-aware-editor"
    assert report.metrics["styleProfileId"] == "project-suspense"
    assert report.metrics["styleProfilePath"] == "story/style-profile.json"


def test_editorial_review_uses_registered_profile(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "prompt = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "report = {'reviewer': prompt['promptPreset'], 'score': 77, 'status': 'warn'}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    EditorialProfileService().register_profile(
        project.root,
        profile_id="suspense-editor",
        backend="command",
        command_template=f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
        prompt_preset="continuity-editor",
        set_default=True,
    )

    report = EditorialReviewService().review_chapter(
        project.root,
        "001",
        profile_id="suspense-editor",
    )

    assert report.reviewer == "continuity-editor"
    assert report.metrics["profileId"] == "suspense-editor"
    assert report.metrics["promptPreset"] == "continuity-editor"
