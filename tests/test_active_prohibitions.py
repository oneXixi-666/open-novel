from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from open_novel.core.book_assets import BookAssetService
from open_novel.core.chapter_drafting import ChapterDraftService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.generation_artifacts import GenerationArtifactService, GenerationRoute
from open_novel.core.models import SceneContract
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.workbench_repository import WorkbenchRepository
from open_novel.core.writing_model import WritingModelService


def _ready_project(root: Path) -> Path:
    project = ProjectService().create_project(root, title="永久规则测试")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="主角销毁唯一钥匙。",
            goal="主角阻止敌人打开密门。",
            conflict="敌人争夺钥匙。",
            turn="钥匙被熔毁。",
            outcome="唯一钥匙彻底消失。",
            hook="敌人开始寻找替代路线。",
            emotionalBeat="主角从迟疑转为坚定。",
            relationshipBeat="敌人从轻视转为敌视。",
            internalNeed="主角要亲手终结旧日错误。",
            woundOrFear="主角害怕再次纵容敌人。",
            stakes="失败会让密门被打开。",
            cost="主角也失去进入密门的机会。",
            subtext="主角用沉默承认没有退路。",
            aftertaste="胜利同时封死另一条选择。",
            mustInclude=["钥匙"],
            mustAvoid=["钥匙恢复"],
            readerPromises=["密门真相"],
        ),
    )
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n唯一钥匙被熔毁。")
    return project.root


def _write_prohibition(root: Path) -> None:
    ProjectService().write_text(
        root,
        "memory/active-prohibitions.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "items": [
                    {
                        "id": "destroyed-key",
                        "rule": "唯一钥匙已经彻底熔毁。",
                        "forbidden": "重新取出唯一钥匙",
                        "source": "chapters/001.md",
                        "chapterId": "001",
                        "evidence": ["chapters/001.md"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )


def test_confirmed_world_rule_is_applied_idempotently(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    service = PostChapterService()
    service.build_review(root, "001")
    service.add_world_rule_review_item(
        root,
        "001",
        rule_id="destroyed-key",
        rule="唯一钥匙已经彻底熔毁。",
        forbidden="重新取出唯一钥匙",
        evidence=["chapters/001.md"],
    )
    patch = service.propose_canon_patch(root, "001")
    operation = next(
        item for item in patch.operations if item.target.endswith("active-prohibitions.json")
    )
    service.accept_canon_patch(root, "001", [operation.id])
    service.apply_canon_patch(root, "001")
    service.apply_canon_patch(root, "001")

    memory = json.loads((root / "memory/active-prohibitions.json").read_text(encoding="utf-8"))
    assert len(memory["items"]) == 1
    assert memory["items"][0]["forbidden"] == "重新取出唯一钥匙"


def test_contract_and_draft_receive_active_prohibitions(tmp_path: Path, monkeypatch) -> None:
    root = _ready_project(tmp_path / "demo")
    _write_prohibition(root)
    project_service = ProjectService()
    generation = GenerationArtifactService(
        project_service,
        WritingModelService(project_service),
        SkillRunner(project_service=project_service),
    )
    captured_generation: dict[str, str] = {}

    def fake_run(_root, _route, _skill_id, variables):
        captured_generation.update(variables)
        return SimpleNamespace(
            outputText=json.dumps(
                {
                    "title": "第二章",
                    "pov": "主角",
                    "time": "次日",
                    "location": "密门外",
                    "focus": "主角寻找替代路线。",
                    "goal": "主角要绕开密门。",
                    "conflict": "敌人封锁出口。",
                    "turn": "地道入口出现。",
                    "outcome": "主角进入地道。",
                    "hook": "地道里传来脚步。",
                    "openingHook": "密门失去钥匙。",
                    "emotionalBeat": "主角保持警惕。",
                    "relationshipBeat": "敌人加强封锁。",
                    "internalNeed": "主角要证明仍有选择。",
                    "woundOrFear": "主角害怕困死。",
                    "stakes": "失败就会被抓住。",
                    "cost": "主角暴露地道。",
                    "subtext": "双方都在试探。",
                    "aftertaste": "新路也有危险。",
                    "logicDependencies": [],
                    "mustInclude": ["密门"],
                    "mustAvoid": ["直接开门"],
                    "readerPromises": ["地道来源"],
                },
                ensure_ascii=False,
            ),
            agentId="codex-cli",
            modelProfile=None,
            runId="run-contract",
        )

    monkeypatch.setattr(generation, "_run", fake_run)
    contract, _ = generation.generate_contract(
        root,
        GenerationRoute("codex-cli", None, "Codex"),
        chapter_id="002",
        chapter_intent="寻找替代路线",
    )
    assert "重新取出唯一钥匙" in contract.mustAvoid
    assert "重新取出唯一钥匙" in captured_generation["activeProhibitions"]

    class CapturingRunner:
        def __init__(self) -> None:
            self.request = None

        def run(self, request):
            self.request = request
            return SimpleNamespace(outputText="")

    runner = CapturingRunner()
    drafting = ChapterDraftService(project_service=project_service, skill_runner=runner)
    drafting.draft_chapter(root, "001", prefer_trained_model=False)
    assert "重新取出唯一钥匙" in runner.request.variables["activeProhibitions"]


def test_gate_blocks_active_prohibition_conflict(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    _write_prohibition(root)
    ContextPackService().build_context_pack(root, "001")
    ProjectService().write_text(
        root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角从暗格里重新取出唯一钥匙，打开了密门。",
    )

    report = ChapterGateService().check_chapter(root, "001", include_review=False)

    issue = next(item for item in report.issues if item.type == "world_rule_conflict")
    assert issue.severity == "blocker"
    assert report.status == "block"


def test_gate_keeps_all_active_prohibitions_above_context_limit(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    ProjectService().write_text(
        root,
        "memory/active-prohibitions.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "items": [
                    {
                        "id": f"rule-{index}",
                        "rule": f"规则 {index} 已确认。",
                        "forbidden": f"禁写内容 {index}",
                    }
                    for index in range(15)
                ],
            },
            ensure_ascii=False,
        ),
    )
    ContextPackService().build_context_pack(root, "001")
    ProjectService().write_text(
        root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角触发了禁写内容 14。",
    )

    report = ChapterGateService().check_chapter(root, "001", include_review=False)

    issue = next(item for item in report.issues if item.type == "world_rule_conflict")
    assert issue.severity == "blocker"


def test_material_and_memory_prohibitions_are_reported_once_each(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    repository = WorkbenchRepository(tmp_path / "workbench.sqlite3")
    repository.upsert_material(
        root,
        {
            "id": "world-fire-rule",
            "type": "设定",
            "title": "明火规则",
            "summary": "港区禁止启动明火推进器。",
            "confidence": 98,
            "details": {"规则": "禁止：启动明火推进器"},
        },
    )
    ProjectService().write_text(
        root,
        "memory/active-prohibitions.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "items": [
                    {
                        "id": "closed-gate",
                        "rule": "封闭闸门不得再次开启。",
                        "forbidden": "重新开启封闭闸门",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    book_assets = BookAssetService(repository)
    context_service = ContextPackService(book_assets=book_assets)
    context_pack = context_service.build_context_pack(root, "001")
    ProjectService().write_text(
        root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角启动明火推进器，并重新开启封闭闸门。",
    )

    report = ChapterGateService(
        context_pack_service=context_service,
        book_asset_service=book_assets,
    ).check_chapter(root, "001", include_review=False)

    issues = [item for item in report.issues if item.type == "world_rule_conflict"]
    assert len(issues) == 2
    assets = next(
        item.data
        for item in context_pack.included
        if item.source == BookAssetService.context_source
    )["worldAssets"]
    hard_rule_assets = [item for item in assets if item.get("hardRules")]
    assert len(hard_rule_assets) == 2
    aggregate = next(item for item in hard_rule_assets if item["id"] == "active-prohibitions")
    assert [item["forbidden"] for item in aggregate["hardRules"]] == [
        "重新开启封闭闸门"
    ]


def test_material_prohibitions_over_context_limit_stay_in_aggregate(tmp_path: Path) -> None:
    root = _ready_project(tmp_path / "demo")
    repository = WorkbenchRepository(tmp_path / "workbench.sqlite3")
    for index in range(15):
        repository.upsert_material(
            root,
            {
                "id": f"world-rule-{index:02d}",
                "type": "设定",
                "title": f"规则 {index}",
                "summary": f"禁止：素材禁写内容 {index}",
                "confidence": 90 - index,
                "details": {"规则": f"禁止：素材禁写内容 {index}"},
            },
        )
    assets = BookAssetService(repository).select_for_context(
        root,
        "001",
        {},
        set(),
        limit=12,
    )["worldAssets"]

    forbidden = [
        rule["forbidden"]
        for asset in assets
        for rule in asset.get("hardRules", [])
    ]
    assert len(assets) == 12
    assert len(forbidden) == 15
    assert len(set(forbidden)) == 15
