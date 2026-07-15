from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.continuity import ContinuityService
from open_novel.core.local_training import LocalTrainingService
from open_novel.core.memory_distillation import MemoryDistillationService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_quality import WritingQualityService

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-c", "from open_novel.cli import app; app()"]


def run_command(args: list[str], *, cwd: Path = ROOT) -> None:
    print(f"$ {shlex.join(args)}", flush=True)
    completed = subprocess.run(args, cwd=cwd, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_cli(*args: str, cwd: Path = ROOT) -> None:
    run_command([*CLI, *args], cwd=cwd)


def build_project(root: Path) -> None:
    project = ProjectService().create_project(root, title="Final Acceptance Novel")
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "林澈曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n"
        "- 第1章：山门测试引发异常\n"
        "- 第2章：玉牌指向后山禁地\n"
        "- 第3章：林澈潜入禁地入口\n"
        "- 第4章：封印回声暴露线索\n"
        "- 第5章：追兵逼近，新的势力现身\n",
    )

    contracts = [
        SceneContract(
            chapterId="001",
            title="山门测试",
            focus="林澈在山门测试中证明异常潜力。",
            goal="林澈想通过山门测试。",
            conflict="旧敌和执事阻挠。",
            turn="测试石显出禁忌纹路。",
            outcome="林澈通过测试但被长老盯上。",
            hook="长老封锁消息并暗中关注林澈。",
            emotionalBeat="林澈从压抑转为震惊和警惕。",
            relationshipBeat="旧敌从轻蔑转为忌惮。",
            internalNeed="林澈想证明自己不是任人踩踏的废物。",
            woundOrFear="林澈害怕再次被当众否定。",
            stakes="如果失败，他会失去进入宗门和追查真相的机会。",
            cost="他证明潜力的同时暴露异常，被长老盯上。",
            subtext="林澈嘴上冷静，实际是在保护最后一点尊严。",
            aftertaste="读者应感到爽快，同时意识到更大危险来了。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["测试石"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭", "禁忌传承谜题"],
        ),
        SceneContract(
            chapterId="002",
            title="玉牌夜探",
            focus="林澈顺着裂开玉牌追查禁地线索。",
            goal="林澈想确认玉牌为什么会指向后山。",
            conflict="执事和旧敌都在暗中试探他。",
            turn="玉牌背面的纹路在月光下显形。",
            outcome="林澈确认后山禁地和测试石有关。",
            hook="有人在黑暗里跟上了他。",
            emotionalBeat="林澈从震惊转为戒备。",
            relationshipBeat="旧敌从忌惮转为盯防。",
            internalNeed="林澈想证明自己不只是被动挨打。",
            woundOrFear="林澈害怕再次被别人替他决定命运。",
            stakes="如果他退缩，禁地线索会被别人抢先。",
            cost="他追查真相的动作暴露了自己的好奇心。",
            subtext="林澈嘴上不问，实际上已经把退路关掉了。",
            aftertaste="读者应感到真相更近一步，同时危险也更近一步。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["玉牌"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭", "禁忌传承谜题"],
        ),
        SceneContract(
            chapterId="003",
            title="潜入禁地",
            focus="林澈潜入后山禁地，撞上第一道封印。",
            goal="林澈想看清禁地里面到底藏着什么。",
            conflict="禁地封印和巡夜弟子同时逼近。",
            turn="封印对测试石纹路产生共鸣。",
            outcome="林澈暂时跨过入口，但代价是灵力失衡。",
            hook="封印后面传来第二道心跳声。",
            emotionalBeat="林澈从戒备转为压迫感。",
            relationshipBeat="旧敌从盯防转为惊疑。",
            internalNeed="林澈想证明自己有资格追到真相最后一层。",
            woundOrFear="林澈害怕自己只是更大棋局里的一颗棋子。",
            stakes="如果被发现，他会失去继续追查和自保的机会。",
            cost="他强行破入禁地，身体先一步付出代价。",
            subtext="林澈没有退，因为他知道退一步就再也回不去了。",
            aftertaste="读者应感到秘密门槛被推开，但还看不清全貌。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["禁地"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭", "禁忌传承谜题"],
        ),
        SceneContract(
            chapterId="004",
            title="封印回声",
            focus="林澈在禁地深处破解封印回声。",
            goal="林澈想弄清封印为什么会对他响应。",
            conflict="封印反噬和巡守压力同时升高。",
            turn="封印回声暴露了上代人的遗留线索。",
            outcome="林澈拿到关键线索，却被反噬震退。",
            hook="追兵已经逼到禁地外。",
            emotionalBeat="林澈从压迫转为紧绷。",
            relationshipBeat="旧敌从试探转为确认威胁。",
            internalNeed="林澈想证明自己不是只会逃命的废物。",
            woundOrFear="林澈害怕自己再次在众目睽睽下败北。",
            stakes="如果他停在这里，线索会断，危险也会追上来。",
            cost="他拿到线索的同时，身体和行踪都被反噬暴露。",
            subtext="林澈不说疼，但他每一步都比上一章更重。",
            aftertaste="读者应感到答案临近，同时局势进一步恶化。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["封印"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭", "禁忌传承谜题"],
        ),
        SceneContract(
            chapterId="005",
            title="追兵逼近",
            focus="林澈在追兵逼近时保住了线索。",
            goal="林澈想带着真相从禁地脱身。",
            conflict="追兵、旧敌和封印余波一起压来。",
            turn="真正盯上他的不是执事，而是更深的势力。",
            outcome="林澈暂时脱身，但新的威胁已经成形。",
            hook="更大的危险在禁地外等着他。",
            emotionalBeat="林澈从紧绷转为更深的警惕。",
            relationshipBeat="旧敌从忌惮转为被迫站队。",
            internalNeed="林澈想证明自己可以把命运夺回来。",
            woundOrFear="林澈害怕自己保护不了已经握住的线索。",
            stakes="如果他失败，禁忌传承线索会被彻底夺走。",
            cost="他活着出来，却把自己推到了更大的风口上。",
            subtext="林澈表面沉住气，心里已经把下一轮对局算到了最坏。",
            aftertaste="读者应感到阶段性胜利成立，但长线危机刚刚加码。",
            logicDependencies=["林澈曾被视为残缺灵根"],
            mustInclude=["传承"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭", "禁忌传承谜题"],
        ),
    ]

    story = StoryGuidanceService()
    for contract in contracts:
        story.write_scene_contract(project.root, contract)
        run_cli(
            "skill",
            "run",
            "--project",
            str(project.root),
            "chapter-writer",
            "--chapter-id",
            contract.chapterId,
            "--chapter-title",
            contract.title,
        )
        run_cli(
            "project",
            "accept-draft",
            "--project",
            str(project.root),
            f"drafts/{contract.chapterId}.generated.md",
            "--chapter-id",
            contract.chapterId,
        )
        run_cli(
            "project",
            "review-chapter",
            "--project",
            str(project.root),
            "--chapter-id",
            contract.chapterId,
        )
        run_cli(
            "project",
            "accept-canon-patch",
            "--project",
            str(project.root),
            "--chapter-id",
            contract.chapterId,
        )
        run_cli(
            "project",
            "apply-canon-patch",
            "--project",
            str(project.root),
            "--chapter-id",
            contract.chapterId,
        )


def assert_final_state(project_root: Path) -> None:
    project_service = ProjectService()
    sequence = ChapterSequenceEvaluationService().evaluate(project_root, "001", "005")
    if sequence.status != "pass":
        raise SystemExit(f"sequence evaluation failed: {sequence.status}")
    if sequence.minQualityScore < 70 or sequence.minGateScore < 70:
        raise SystemExit("five-chapter quality baseline is too low")

    memory_validation = MemoryValidationService().validate_project(project_root)
    if memory_validation.status == "block":
        raise SystemExit("memory validation blocked final acceptance")

    writing_training = project_root / "exports" / "writing-training.jsonl"
    if not writing_training.exists():
        raise SystemExit("writing training jsonl missing")
    training_lines = [
        line for line in writing_training.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(training_lines) != 1:
        raise SystemExit(f"expected 1 deduplicated training example, got {len(training_lines)}")

    readiness = LocalTrainingService().export_service.training_readiness(project_root)
    if readiness.eligibleCount != 1:
        raise SystemExit(
            f"expected 1 eligible training example after deduplication, "
            f"got {readiness.eligibleCount}"
        )

    distill = MemoryDistillationService().distill_project(
        project_root,
        "005",
        hot_window_chapters=3,
        max_topics=40,
    )
    if distill.topicCount <= 0:
        raise SystemExit("memory distillation produced no topics")

    run_cli(
        "project",
        "build-context",
        "--project",
        str(project_root),
        "--chapter-id",
        "005",
    )
    context_pack = json.loads(
        project_service.read_text(project_root, "story/context-packs/005.json")
    )
    included_sources = {item["source"] for item in context_pack.get("included", [])}
    if "memory/long-term-memory.json" not in included_sources:
        raise SystemExit("long-term memory was not included in the refreshed context pack")

    local_training = LocalTrainingService()
    train_command = (
        f'{sys.executable} -c "from pathlib import Path; '
        "Path(r'{output_dir}').mkdir(parents=True, exist_ok=True); "
        "Path(r'{output_dir}/adapter.txt').write_text('smoke-trained', encoding='utf-8')\""
    )
    inference_template = (
        f'{sys.executable} -c "from pathlib import Path; '
        "Path(r'{output_file}').write_text("
        "Path(r'{prompt_file}').read_text(encoding='utf-8')[:4000], "
        "encoding='utf-8'); "
        "print(Path(r'{output_file}').read_text(encoding='utf-8'))\""
    )
    plan = local_training.plan_local_tuning(
        project_root,
        min_examples=1,
        train_command=train_command,
        inference_command_template=inference_template,
        model_profile_id="final-smoke",
        output_dir="models/adapters/final-smoke",
    )
    if plan.status not in {"ready", "warn"}:
        raise SystemExit(f"unexpected training plan status: {plan.status}")

    run = local_training.run_local_tuning(
        project_root,
        min_examples=1,
        train_command=train_command,
        inference_command_template=inference_template,
        model_profile_id="final-smoke",
        output_dir="models/adapters/final-smoke",
        force=True,
    )
    if run.status != "completed":
        raise SystemExit(f"dummy local training did not complete: {run.status}")

    registry = json.loads(project_service.read_text(project_root, "models/writing-models.json"))
    profiles = registry.get("profiles", [])
    if not any(
        isinstance(profile, dict) and profile.get("id") == "final-smoke" for profile in profiles
    ):
        raise SystemExit("local model profile was not registered")

    gate = ChapterGateService().check_chapter(
        project_root,
        "005",
        draft_path="drafts/005.generated.md",
    )
    quality = WritingQualityService().evaluate_chapter(
        project_root,
        "005",
        draft_path="drafts/005.generated.md",
    )
    continuity = ContinuityService().check_draft(
        project_root,
        "005",
        draft_path="drafts/005.generated.md",
    )
    print(
        f"final chapter gate={gate.status}/{gate.score}, "
        f"quality={quality.score}, continuity={continuity.score}"
    )


def main() -> None:
    run_cli("agent", "detect")
    run_cli("skill", "list")

    with tempfile.TemporaryDirectory(prefix="open-novel-final-acceptance-") as tmpdir:
        project_root = Path(tmpdir) / "final-acceptance-novel"
        build_project(project_root)
        run_cli("project", "sync-timeline", "--project", str(project_root))
        run_cli("project", "validate-memory", "--project", str(project_root))
        run_cli(
            "project",
            "evaluate-sequence",
            "--project",
            str(project_root),
            "--start-chapter",
            "001",
            "--end-chapter",
            "005",
        )
        run_cli("export", "training-readiness", "--project", str(project_root))
        run_cli("export", "training-data", "--project", str(project_root))
        assert_final_state(project_root)

    run_command([sys.executable, "-m", "pytest", "-q"], cwd=ROOT)
    run_command([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT)
    print("FINAL_ACCEPTANCE: PASS")


if __name__ == "__main__":
    main()
