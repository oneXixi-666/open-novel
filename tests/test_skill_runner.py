from __future__ import annotations

import json
import sys
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import CliRunResult, SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillLoader, SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_model import WritingModelService


def test_default_skill_loader_falls_back_to_packaged_p0_skills() -> None:
    loader = SkillLoader()

    manifest = loader.load_manifest("book-direction-generator")

    assert manifest.id == "book-direction-generator"
    assert "recommendedOptionId" in loader.load_prompt(manifest.id)


def test_skill_runner_writes_chapter_draft(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章 测试",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            internalNeed="主角想证明自己不是任人踩踏的废物。",
            woundOrFear="主角害怕再次被当众否定。",
            stakes="如果失败，他会失去进入宗门的机会。",
            cost="他证明潜力的同时暴露异常，被长老盯上。",
            subtext="主角嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/active-prohibitions.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "items": [
                    {
                        "id": "sealed-door",
                        "rule": "封印门已经永久消失。",
                        "forbidden": "重新打开封印门",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章 测试"},
        )
    )

    assert result.outputPath == "drafts/001.generated.md"
    draft = (project.root / result.outputPath).read_text(encoding="utf-8")
    assert (project.root / result.outputPath).exists()
    assert (project.root / "story" / "context-packs" / "001.json").exists()
    assert (result.runDir / "prompt.md").exists()
    assert "重新打开封印门" in result.promptPath.read_text(encoding="utf-8")
    assert "第一章 测试" in draft
    assert "任人踩踏" in draft
    assert "失去进入宗门" in draft
    assert "更大危险" in draft


def test_chapter_writer_prompt_includes_writing_lessons(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章 测试",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        '{"schemaVersion": 1, "lessons": [{"id": "lesson_emotion", "category": "emotion",'
        ' "lesson": "情绪节拍要用动作落地。", "severity": "high", "status": "active"}]}',
    )

    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章 测试"},
        )
    )

    prompt = result.promptPath.read_text(encoding="utf-8")
    assert "memory/writing-lessons.json" in prompt
    assert "情绪节拍要用动作落地" in prompt


def test_line_editor_writes_reviewable_polished_draft(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n他感觉非常紧张，然后说道：“我要继续。”\n",
    )

    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="line-editor",
            variables={
                "sourcePath": "chapters/001.md",
                "sourceText": ProjectService().read_text(project.root, "chapters/001.md"),
                "targetName": "001",
                "instruction": "保持剧情不变，提升节奏。",
            },
        )
    )

    polished = (project.root / "drafts" / "001.polished.md").read_text(encoding="utf-8")

    assert result.outputPath == "drafts/001.polished.md"
    assert "（润色稿）" in polished
    assert "随即" in polished
    assert "他察觉" in polished
    assert not (project.root / "chapters" / "001.md").read_text(encoding="utf-8").startswith(
        "# 第一章（润色稿）"
    )


def test_chapter_writer_can_use_registered_local_model_profile(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章 本地模型",
            focus="林澈在测试石前证明异常潜力。",
            goal="林澈想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过但被长老盯上。",
            hook="玉牌指向禁地。",
            emotionalBeat="林澈从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    command_template = (
        f"{sys.executable} -c \"from pathlib import Path; "
        "Path(r'{{output_file}}').write_text("
        "'# 第一章 本地模型\\n\\n测试石前，林澈咬牙选择按上掌心。\\n\\n"
        "旧敌冷笑着阻挠，下一刻测试石忽然异动，废柴逆袭的惊呼炸开。\\n\\n"
        "林澈从压抑转为警惕，旧敌开始忌惮。门外却有人送来玉牌：今夜禁地见。'"
        "); print(Path(r'{{output_file}}').read_text())\""
    )
    WritingModelService().register_profile(
        project.root,
        profile_id="tomato-trained",
        base_model="local-base",
        adapter_path="models/adapters/latest",
        command_template=command_template,
    )

    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章 本地模型"},
            agentId="local-model",
            modelProfile="tomato-trained",
            runId="local_model_writer",
        )
    )

    run_record = json.loads((result.runDir / "run.json").read_text(encoding="utf-8"))

    assert result.modelProfile == "tomato-trained"
    assert result.outputPath == "drafts/001.generated.md"
    assert "测试石前" in (project.root / "drafts" / "001.generated.md").read_text(
        encoding="utf-8"
    )
    assert run_record["agentId"] == "local-model"
    assert run_record["modelProfile"] == "tomato-trained"


def test_chapter_writer_cancels_registered_local_model_profile(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章 本地模型",
            focus="林澈在测试石前证明异常潜力。",
            goal="林澈想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="林澈通过但被长老盯上。",
            hook="玉牌指向禁地。",
            emotionalBeat="林澈从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    command_template = (
        f"{sys.executable} -c \"import time; from pathlib import Path; "
        "time.sleep(5); Path(r'{{output_file}}').write_text('late')\""
    )
    WritingModelService().register_profile(
        project.root,
        profile_id="tomato-trained",
        command_template=command_template,
        timeout_seconds=30,
    )

    try:
        SkillRunner().run(
            SkillRunRequest(
                projectRoot=project.root,
                skillId="chapter-writer",
                variables={"chapterId": "001", "chapterTitle": "第一章 本地模型"},
                agentId="local-model",
                modelProfile="tomato-trained",
            ),
            cancel_check=lambda: True,
        )
    except RuntimeError as exc:
        assert "local model cancelled" in str(exc)
    else:
        raise AssertionError("local model command should be cancelled")

    assert not (project.root / "drafts" / "001.generated.md").exists()


def test_chapter_writer_blocks_without_ready_contract(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    try:
        SkillRunner().run(
            SkillRunRequest(
                projectRoot=project.root,
                skillId="chapter-writer",
                variables={"chapterId": "001", "chapterTitle": "第一章 测试"},
            )
        )
    except ValueError as exc:
        assert "chapter is not ready for drafting" in str(exc)
    else:
        raise AssertionError("chapter-writer should require a ready scene contract")


def test_chapter_writer_refreshes_stale_context_pack(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    service = StoryGuidanceService()
    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一版",
            focus="旧重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ContextPackService().build_context_pack(project.root, "001")

    service.write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第二版",
            focus="新重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被长老盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )

    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章 测试"},
        )
    )

    context_pack = ContextPackService().read_context_pack(project.root, "001")
    assert context_pack.included[0].data["title"] == "第二版"


def test_skill_runner_rejects_agent_not_allowed_by_manifest(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "dry-only"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps(
            {
                "id": "dry-only",
                "name": "Dry Only",
                "description": "Only local dry-run is allowed.",
                "inputs": [],
                "outputs": [],
                "writePolicy": "read-only",
                "allowedAgents": ["local-dry-run"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "prompt.md").write_text("Hello", encoding="utf-8")

    try:
        SkillRunner(skills_dir=skills_dir).run(
            SkillRunRequest(
                projectRoot=project.root,
                skillId="dry-only",
                agentId="api",
            )
        )
    except ValueError as exc:
        assert "is not allowed" in str(exc)
    else:
        raise AssertionError("SkillRunner should reject undeclared agents")


class FakeSecretCliAgentService:
    async def run_prompt(
        self,
        agent_id: str,
        prompt: str,
        cwd: Path,
        writable: bool = False,
    ) -> CliRunResult:
        return CliRunResult(
            command=["fake-agent", "--api-key", "sk-commandsecret12345"],
            cwd=cwd,
            exitCode=0,
            stdout="generated with Bearer stdoutsecret12345 and token=stdouttoken12345",
            stderr="password: stderrsecret12345",
            timedOut=False,
        )


def test_skill_runner_redacts_run_logs(tmp_path: Path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "secret-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps(
            {
                "id": "secret-check",
                "name": "Secret Check",
                "description": "Exercise run log redaction.",
                "inputs": [],
                "outputs": [],
                "writePolicy": "read-only",
                "allowedAgents": ["fake-cli"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (skill_dir / "prompt.md").write_text("Use api_key={secret}", encoding="utf-8")

    result = SkillRunner(
        skills_dir=skills_dir,
        cli_agent_service=FakeSecretCliAgentService(),
    ).run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="secret-check",
            variables={"secret": "sk-promptsecret12345"},
            agentId="fake-cli",
        )
    )

    run_json = (result.runDir / "run.json").read_text(encoding="utf-8")
    prompt_log = result.promptPath.read_text(encoding="utf-8")
    output_log = (result.runDir / "output.md").read_text(encoding="utf-8")

    for secret in [
        "sk-commandsecret12345",
        "sk-promptsecret12345",
        "stdoutsecret12345",
        "stdouttoken12345",
        "stderrsecret12345",
    ]:
        assert secret not in run_json
        assert secret not in prompt_log
        assert secret not in output_log
    assert "[REDACTED_SECRET]" in run_json
    assert "[REDACTED_SECRET]" in prompt_log
    assert "[REDACTED_SECRET]" in output_log
