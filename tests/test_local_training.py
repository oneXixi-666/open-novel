from __future__ import annotations

import json
import sys
from pathlib import Path
from threading import Event

from open_novel.core.local_training import LocalTrainingService
from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService


def create_training_ready_project(root: Path) -> Path:
    project = ProjectService().create_project(root, title="Demo")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "林澈曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "importance": "high",
                        "confidence": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
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
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
            runId="local_training_ready",
        )
    )
    ProjectService().accept_draft(project.root, "drafts/001.generated.md", chapter_id="001")
    return project.root


def test_local_training_plan_exports_dataset_and_command(tmp_path: Path) -> None:
    root = create_training_ready_project(tmp_path / "demo")

    plan = LocalTrainingService().plan_local_tuning(
        root,
        base_model="local-model",
        min_examples=1,
        train_command="trainer --data {dataset_rel} --out {output_dir} --model {base_model}",
    )

    assert plan.status == "ready"
    assert plan.eligibleCount == 1
    assert plan.datasetPath == "exports/writing-training.jsonl"
    assert plan.command == [
        "trainer",
        "--data",
        "exports/writing-training.jsonl",
        "--out",
        "models/adapters/latest",
        "--model",
        "local-model",
    ]
    assert (root / "exports" / "local-tuning-plan.json").exists()
    assert (root / "exports" / "writing-training.jsonl").exists()


def test_local_training_run_executes_explicit_local_command(tmp_path: Path) -> None:
    root = create_training_ready_project(tmp_path / "demo")
    command = (
        "python -c \"from pathlib import Path; "
        "Path('{output_dir}').mkdir(parents=True, exist_ok=True); "
        "Path('{output_dir}/done.txt').write_text('ok')\""
    )

    run = LocalTrainingService().run_local_tuning(
        root,
        min_examples=1,
        train_command=command,
        timeout_seconds=30,
    )

    assert run.status == "completed"
    assert run.exitCode == 0
    assert (root / "models" / "adapters" / "latest" / "done.txt").read_text() == "ok"
    assert (root / "runs" / "local-tuning-run.json").exists()


def test_local_training_run_registers_writing_model_profile(tmp_path: Path) -> None:
    root = create_training_ready_project(tmp_path / "demo")
    train_command = (
        f"{sys.executable} -c \"from pathlib import Path; "
        "Path('{{output_dir}}').mkdir(parents=True, exist_ok=True); "
        "Path('{{output_dir}}/adapter.txt').write_text('trained')\""
    )
    inference_command = (
        f"{sys.executable} -c \"from pathlib import Path; "
        "Path(r'{{output_file}}').write_text('# 训练模型章\\n\\n测试石前，林澈咬牙做出选择。'); "
        "print(Path(r'{{output_file}}').read_text())\""
    )

    run = LocalTrainingService().run_local_tuning(
        root,
        base_model="local-base",
        model_profile_id="tomato-trained",
        inference_command_template=inference_command,
        min_examples=1,
        train_command=train_command,
        timeout_seconds=30,
    )

    registry = json.loads((root / "models" / "writing-models.json").read_text(encoding="utf-8"))

    assert run.status == "completed"
    assert run.modelProfileId == "tomato-trained"
    assert registry["defaultProfileId"] == ""
    assert registry["profiles"][0]["baseModel"] == "local-base"
    assert registry["profiles"][0]["adapterPath"] == "models/adapters/latest"
    assert "五章模型对比" in run.message


def test_local_training_run_skips_without_command(tmp_path: Path) -> None:
    root = create_training_ready_project(tmp_path / "demo")

    run = LocalTrainingService().run_local_tuning(root, min_examples=1)

    assert run.status == "skipped"
    assert "缺少本地训练命令" in run.message


def test_local_training_run_cancels_running_command(tmp_path: Path) -> None:
    root = create_training_ready_project(tmp_path / "demo")
    cancel = Event()
    command = (
        f"{sys.executable} -c \"import time; from pathlib import Path; "
        "time.sleep(5); Path('{{output_dir}}').mkdir(parents=True, exist_ok=True); "
        "Path('{{output_dir}}/should_not_exist.txt').write_text('late')\""
    )
    cancel.set()

    run = LocalTrainingService().run_local_tuning(
        root,
        min_examples=1,
        train_command=command,
        timeout_seconds=30,
        cancel_check=cancel.is_set,
    )

    assert run.status == "cancelled"
    assert run.message == "本地微调任务已取消。"
    assert not (root / "models" / "adapters" / "latest" / "should_not_exist.txt").exists()
