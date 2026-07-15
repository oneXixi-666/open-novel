from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.testclient import TestClient

from open_novel.core.ai_runtime import AIRuntimeService
from open_novel.core.chapter_progress import calculate_chapter_progress
from open_novel.core.context_pack import ContextPackService
from open_novel.core.generation_artifacts import GenerationArtifactService, GenerationRoute
from open_novel.core.jobs import JobController
from open_novel.core.models import (
    ChapterGateReport,
    SceneContract,
    SkillRunResult,
    TrainingReadinessItem,
    TrainingReadinessReport,
)
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.workbench_repository import WorkbenchRepository
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.core.writing_model import WritingModelService
from open_novel.server import app
from open_novel.web.routes_workbench import AgentAssistRequest, WorkbenchPresenter
from open_novel.web.workbench_calibration import WorkbenchCalibrationService
from open_novel.web.workbench_generation import WorkbenchGenerationService
from open_novel.web.workbench_training import WorkbenchTrainingService
from tests.test_local_training import create_training_ready_project


def _client_with_project(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    project = ProjectService().create_project(tmp_path / "demo", title="异声追猎")
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章 暗室回声\n\n林澈听见墙后传来三秒一次的呼吸声。\n",
    )
    ProjectService().write_text(
        project.root,
        "memory/long-term-memory.json",
        """{
  "schemaVersion": 1,
  "topics": [
    {
      "id": "topic-lin",
      "summary": "林澈习惯用声音判断风险。",
      "sourceChapters": ["001"]
    }
  ],
  "entityIndex": [
    {"entityId": "lin", "name": "林澈", "topicIds": ["topic-lin"]}
  ],
  "writingGuidance": []
}
""",
    )
    WorkspaceRegistryService().register_project(project.root)
    return TestClient(app), project


def _configure_ai_account(
    client: TestClient,
    *,
    name: str = "受控写作账号",
    protocol: str = "responses",
) -> str:
    created = client.post(
        "/api/ai/accounts",
        json={
            "name": name,
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "test-key",
            "model": "controlled-model",
            "protocol": protocol,
            "maxContextTokens": 128000,
            "enabled": True,
        },
    )
    assert created.status_code == 200
    account_id = created.json()["account"]["id"]
    bound = client.put(
        "/api/ai/roles",
        json={
            "writingAccountId": account_id,
            "reviewAccountId": account_id,
        },
    )
    assert bound.status_code == 200
    return account_id


def _write_ready_contract(root) -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId="001",
            title="第一章",
            focus="林澈追查异声来源",
            goal="找到呼吸声来源",
            conflict="门禁和未知规则阻挡",
            turn="磁带暴露了更大的问题",
            outcome="林澈拿到关键磁带",
            hook="更大的谜团浮出水面",
            emotionalBeat="不安升级",
            relationshipBeat="同伴从怀疑转为有限信任。",
            internalNeed="林澈需要证明自己的判断不是幻觉。",
            woundOrFear="林澈害怕再次被当成污染源。",
            stakes="失败会让关键证据和同伴记忆同时消失。",
            cost="追查会暴露林澈的位置。",
            subtext="林澈表面冷静，实际在压住恐惧。",
            aftertaste="真相更近，但危险已经认出了他。",
            mustInclude=["磁带"],
            mustAvoid=["提前揭示最终真相"],
            readerPromises=["声音谜案", "记忆代价"],
        ),
    )


def _write_post_review_ready_story(root) -> None:
    _write_ready_contract(root)
    ProjectService().write_text(
        root,
        "chapters/001.md",
        (
            "# 第一章\n\n"
            "测试台前，主角第一次证明了自己的异常潜力。"
            "他通过测试，却也被长老盯上。长老随即封锁消息。"
            "主角先是压抑，随后变得警惕。废柴逆袭的期待被建立。"
            "他想证明自己不是任人踩踏的废物，也害怕再次被当众否定。"
            "如果失败，主角会失去进入宗门的机会。"
            "主角证明潜力的同时暴露异常，被长老盯上。"
            "主角嘴上冷静，实际是在保护最后一点尊严。"
            "读者应感到爽快，同时意识到更大危险来了。"
        ),
    )


def _write_ready_architecture_and_blueprint(root) -> None:
    ProjectService().write_text(
        root,
        "story/workbench-architecture.json",
        json.dumps({"schemaVersion": 1, "serialHook": "异声继续逼近。"}, ensure_ascii=False),
    )
    ProjectService().write_text(
        root,
        "story/chapter-blueprint.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "chapters": [
                    {
                        "chapterId": f"{index:03d}",
                        "title": f"第{index}章",
                        "goal": "追查异声",
                        "conflict": "阻力升级",
                        "turn": "证据反转",
                        "hook": "危险逼近",
                    }
                    for index in range(1, 11)
                ],
            },
            ensure_ascii=False,
        ),
    )


def _chapter_similarity(left: str, right: str) -> float:
    def ngrams(text: str) -> set[str]:
        compact = "".join(text.split())
        return {compact[index : index + 4] for index in range(max(0, len(compact) - 3))}

    left_tokens = ngrams(left)
    right_tokens = ngrams(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _install_controlled_generation_executor(monkeypatch) -> None:
    monkeypatch.setattr(
        GenerationArtifactService,
        "resolve_route",
        lambda self, root, selected_model_id: GenerationRoute("codex-cli", None, "Codex CLI"),
    )

    def controlled_run(self, request):
        chapter_id = request.variables.get("chapterId", "001")
        run_id = request.runId or f"controlled-{request.skillId}-{chapter_id}"
        run_relative_dir = f"runs/{run_id}"
        run_dir = Path(tempfile.mkdtemp(prefix=f"open-novel-test-{run_id}-"))
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.md"
        prompt_path.write_text("controlled test prompt\n", encoding="utf-8")
        self.project_service.write_text(
            request.projectRoot,
            f"{run_relative_dir}/prompt.md",
            "controlled test prompt\n",
        )
        if request.skillId == "book-direction-generator":
            output = json.dumps(
                {
                    "recommendedOptionId": "direction-2",
                    "options": [
                        {
                            "id": f"direction-{index}",
                            "title": f"方向 {index}",
                            "genrePositioning": f"都市悬疑分支 {index}",
                            "protagonistDesire": f"查清第 {index} 条异声线索",
                            "centralConflict": f"线索与代价冲突 {index}",
                            "serialHook": f"每章推进不同的谜面 {index}",
                            "targetReaderExperience": f"紧张和发现感 {index}",
                            "risks": [f"节奏风险 {index}"],
                            "recommendation": f"推荐依据 {index}",
                        }
                        for index in range(1, 4)
                    ],
                },
                ensure_ascii=False,
            )
        elif request.skillId == "book-architecture-builder":
            selected = json.loads(request.variables["selectedDirection"])
            output = json.dumps(
                {
                    "directionTitle": selected["title"],
                    "genrePositioning": selected["genrePositioning"],
                    "coreSellingPoints": ["声音谜案", "选择代价"],
                    "protagonistGoal": selected["protagonistDesire"],
                    "centralConflict": selected["centralConflict"],
                    "storyEngine": "每次追查都改变人物关系并打开下一层谜面",
                    "escalationPath": "个人异声、旧案关联、城市真相逐层升级",
                    "longTermHooks": [selected["serialHook"], "主角过去为何与异声同步"],
                    "targetReaderExperience": selected["targetReaderExperience"],
                    "risks": selected["risks"],
                    "recommendation": selected["recommendation"],
                },
                ensure_ascii=False,
            )
        elif request.skillId in {"long-form-planner", "long-form-replanner"}:
            long_form_payload = {
                "bookPlan": {
                    "mainline": "主角沿声音谜案追查城市真相",
                    "endingDirection": "主角让居民共同决定城市规则",
                    "longTermOpposition": "真相公开与城市稳定持续冲突",
                    "corePromises": ["声音来源", "城市选择"],
                },
                "volumes": [
                    {
                        "volumeId": f"volume-{volume_index:03d}",
                        "title": f"第 {volume_index} 卷",
                        "chapterRange": ("001-010" if volume_index == 1 else "011-020"),
                        "goal": f"完成第 {volume_index} 卷目标",
                        "mainConflict": f"第 {volume_index} 卷核心冲突",
                        "payoffs": [f"兑现承诺 {volume_index}"],
                        "endingChange": f"第 {volume_index} 卷末局势改变",
                        "failureCondition": f"第 {volume_index} 卷失败代价",
                        "beatSegments": [
                            {
                                "segmentId": (
                                    f"volume-{volume_index:03d}-segment-{segment_index:02d}"
                                ),
                                "title": f"节奏段 {segment_index}",
                                "chapterRange": (
                                    f"{1 + (volume_index - 1) * 10:03d}-"
                                    f"{5 + (volume_index - 1) * 10:03d}"
                                    if segment_index == 1
                                    else f"{6 + (volume_index - 1) * 10:03d}-"
                                    f"{10 + (volume_index - 1) * 10:03d}"
                                ),
                                "purpose": f"推进卷目标 {segment_index}",
                                "pressure": f"升级压力 {segment_index}",
                                "payoff": f"阶段兑现 {segment_index}",
                                "density": "升级" if segment_index == 1 else "兑现",
                            }
                            for segment_index in range(1, 3)
                        ],
                    }
                    for volume_index in range(1, 3)
                ],
            }
            if request.skillId == "long-form-replanner":
                long_form_payload["chapterAdjustments"] = [
                    {
                        "chapterId": f"{index:03d}",
                        "segmentId": "volume-001-segment-01"
                        if index <= 5
                        else "volume-001-segment-02",
                        "goal": f"重规划目标 {index}",
                        "hook": f"重规划钩子 {index}",
                        "promiseProgression": f"重规划承诺推进 {index}",
                        "logicDependencies": [] if index == 1 else [f"承接第 {index - 1} 章"],
                    }
                    for index in range(1, 11)
                ]
            output = json.dumps(long_form_payload, ensure_ascii=False)
        elif request.skillId in {"chapter-blueprint-builder", "chapter-blueprint-repairer"}:
            count = int(request.variables["chapterCount"])
            output = json.dumps(
                {
                    "chapters": [
                        {
                            "title": f"第 {index} 章线索 {index}",
                            "goal": f"确认第 {index} 条独立线索",
                            "conflict": f"阻力 {index} 改变调查方向",
                            "turn": f"证据 {index} 指向意外对象",
                            "outcome": f"获得阶段结果 {index}",
                            "hook": f"新危险 {index} 在结尾出现",
                            "characterChange": f"主角完成变化 {index}",
                            "promiseProgression": f"长线承诺推进 {index}",
                            "logicDependencies": []
                            if index == 1
                            else [f"承接第 {index - 1} 章结果"],
                        }
                        for index in range(1, count + 1)
                    ]
                },
                ensure_ascii=False,
            )
        elif request.skillId == "generation-scene-contract-builder":
            output = json.dumps(
                {
                    "title": f"第 {int(chapter_id)} 章",
                    "pov": "沈砚，第三人称限知",
                    "focus": f"追查线索 {chapter_id}",
                    "goal": f"确认线索 {chapter_id} 的来源",
                    "conflict": f"阻力迫使主角为线索 {chapter_id} 付出代价",
                    "turn": f"证据 {chapter_id} 指向主角过去",
                    "outcome": f"主角取得证据 {chapter_id}",
                    "hook": f"下一条危险在 {chapter_id} 章末出现",
                    "emotionalBeat": "警惕转为坚定",
                    "relationshipBeat": "同伴给予有限信任",
                    "internalNeed": "证明自己的判断可靠",
                    "woundOrFear": "害怕再次被否定",
                    "stakes": "失败会失去证据",
                    "cost": "主角暴露行踪",
                    "subtext": "冷静外表掩盖恐惧",
                    "aftertaste": "获得答案同时看见更大危险",
                    "mustInclude": [f"证据 {chapter_id}"],
                    "mustAvoid": ["提前揭示最终真相"],
                    "readerPromises": ["声音谜案", "记忆代价"],
                },
                ensure_ascii=False,
            )
        elif request.skillId == "line-editor":
            source = self.project_service.read_text(
                request.projectRoot,
                request.variables["sourcePath"],
            )
            output = source + "\n修复后，人物行动与本章合同重新对齐，关键代价也得到明确呈现。\n"
        else:
            body = " ".join(
                f"线索{chapter_id}动作{index}带来独立阻力与选择"
                for index in range(1, 660 + int(chapter_id))
            )
            contract_path = f"story/chapter-briefs/{chapter_id}.json"
            contract_evidence = (
                json.dumps(
                    json.loads(self.project_service.read_text(request.projectRoot, contract_path)),
                    ensure_ascii=False,
                )
                if self.project_service.file_exists(request.projectRoot, contract_path)
                else ""
            )
            output = (
                f"# 第 {int(chapter_id)} 章\n\n{body}\n"
                f"{contract_evidence}\n结尾时，新危险改变了下一章的调查方向。\n"
            )
        output_path = run_dir / "output.md"
        output_path.write_text(output, encoding="utf-8")
        self.project_service.write_text(
            request.projectRoot,
            f"{run_relative_dir}/output.md",
            output,
        )
        if request.skillId == "chapter-writer":
            self.project_service.write_text(
                request.projectRoot,
                f"drafts/{chapter_id}.generated.md",
                output,
            )
        run_record = json.dumps(
            {"runId": run_id, "skillId": request.skillId, "agentId": "codex-cli"}
        )
        (run_dir / "run.json").write_text(run_record, encoding="utf-8")
        self.project_service.write_text(
            request.projectRoot,
            f"{run_relative_dir}/run.json",
            run_record,
        )
        return SkillRunResult(
            runId=run_id,
            skillId=request.skillId,
            agentId="codex-cli",
            runDir=run_dir,
            promptPath=prompt_path,
            outputPath=f"{run_relative_dir}/output.md",
            outputText=output,
        )

    monkeypatch.setattr(SkillRunner, "run", controlled_run)


def _install_passing_generation_gate(monkeypatch) -> None:
    from open_novel.core.chapter_gate import ChapterGateService

    def passing_gate(self, root, chapter_id, **kwargs):
        return ChapterGateReport(
            chapterId=chapter_id,
            status="pass",
            score=92,
            recommendedNextAction="可以接收正文。",
        )

    monkeypatch.setattr(
        ChapterGateService,
        "check_chapter",
        passing_gate,
    )


def test_workbench_workspace_returns_react_contract(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    ProjectService().write_text(
        project.root,
        "story/arc-contracts/arc_001.json",
        json.dumps(
            {
                "arcId": "arc_001",
                "title": "异声追猎篇",
                "chapterRange": "001-003",
                "arcGoal": "追查墙后异声来源",
                "emotionalArc": "从不安到主动追猎",
                "status": "in_progress",
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [{"characterId": "lin", "name": "林澈", "status": "警惕"}],
            },
            ensure_ascii=False,
        ),
    )

    response = client.get("/api/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["books"][0]["id"] == project.root.as_posix()
    assert data["books"][0]["title"] == "异声追猎"
    assert data["books"][0]["platform"]
    assert data["books"][0]["styleProfileId"]
    assert data["books"][0]["styleProfileLabel"]
    assert data["creationOptions"]["platformStyles"]
    assert data["creationOptions"]["genres"]
    assert data["creationOptions"]["platformLabels"]["generic"] == "跨平台"
    assert any(
        item["id"] == "generic-web-serial" and item["status"] == "active"
        for item in data["creationOptions"]["platformStyles"]
    )
    assert all(
        item["status"] in {"active", "candidate"}
        for item in data["creationOptions"]["platformStyles"]
    )
    assert all(
        not any(character.isascii() and character.isalpha() for character in item["label"])
        and not any(
            character.isascii() and character.isalpha() for character in item["summary"]
        )
        and all(
            not any(character.isascii() and character.isalpha() for character in genre)
            for genre in item["genres"]
        )
        for item in data["creationOptions"]["platformStyles"]
    )
    assert all(
        "后端" not in item["summary"]
        and "后台" not in item["summary"]
        and "等待后续" not in item["summary"]
        for item in data["creationOptions"]["platformStyles"]
    )
    assert any(item["label"] == "科幻冒险" for item in data["creationOptions"]["genres"])
    assert data["books"][0]["chapters"][0]["id"] == "001"
    assert "plotPoints" in data["books"][0]["chapters"][0]
    assert data["books"][0]["chapters"][0]["content"].startswith("林澈听见")
    assert data["books"][0]["writingPlan"] == {
        "targetChapterCount": 100,
        "targetWordsPerChapter": 2500,
        "targetChaptersPerPlot": 10,
    }
    assert any(
        material["type"] == "人物" and material["title"] == "林澈" for material in data["materials"]
    )
    assert data["reviews"][0]["bookId"] == project.root.as_posix()
    model_ids = {model["id"] for model in data["models"]}
    assert "codex-cli" in model_ids
    assert "local-dry-run" not in model_ids
    assert data["books"][0]["currentModelId"] == ""
    assert data["books"][0]["qualitySummary"]["completedChapterCount"] >= 0
    assert data["books"][0]["qualitySummary"]["targetChapterCount"] >= 0
    assert "averageQualityScore" in data["books"][0]["qualitySummary"]
    assert "recentAverageQualityScore" in data["books"][0]["qualitySummary"]
    assert "trainingEligibleCount" in data["books"][0]["qualitySummary"]
    assert "lastTrainingRunAt" in data["books"][0]["qualitySummary"]
    assert "coherenceScore" in data["books"][0]["qualitySummary"]
    assert isinstance(data["books"][0]["qualitySummary"]["tensionPoints"], list)
    assert data["books"][0]["arcs"][0]["arcId"] == "arc_001"
    assert data["books"][0]["arcs"][0]["progress"] > 0
    assert data["books"][0]["memoryInspection"]["characters"][0]["name"] == "林澈"
    assert data["books"][0]["memoryInspection"]["arcs"][0]["arcId"] == "arc_001"
    first_model = data["models"][0]
    assert first_model["source"] in {"builtin", "project"}
    assert first_model["sourceLabel"]
    assert first_model["statusNote"]
    assert {action["key"] for action in first_model["actions"]} >= {"validate", "apply"}
    model_text = json.dumps(data["models"], ensure_ascii=False)
    assert "后端" not in model_text


def test_workbench_workspace_recalculates_stale_chapter_progress(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()
    chapter = presenter._chapter_for_file(
        project.root,
        project.root / "chapters" / "001.md",
    )
    chapter["status"] = "草稿"
    chapter["progress"] = 58
    chapter["targetWordCount"] = 3000
    WorkbenchRepository().upsert_chapter(project.root, chapter)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    response_chapter = response.json()["books"][0]["chapters"][0]
    expected_progress = calculate_chapter_progress(
        "草稿",
        int(chapter["wordCount"]),
        presenter.plan_service.summarize(project.root).plan.targetWordsPerChapter,
    )
    assert response_chapter["progress"] == expected_progress
    assert response_chapter["progress"] != 58
    assert response_chapter["targetWordCount"] == 2500
    stored_chapter = WorkbenchRepository().list_chapters(project.root)[0]
    assert stored_chapter["progress"] == expected_progress
    assert stored_chapter["targetWordCount"] == 2500


def test_workbench_exposes_optimization_v2_service_routes(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n"
        "林澈握紧磁带，选择继续追查墙后的呼吸声。旧敌冷笑着拦住去路。"
        "门禁规则忽然变了，他必须立刻判断风险。门外忽然传来一道声音。\n",
    )
    ProjectService().write_text(
        project.root,
        "knowledge/sources/world.md",
        "# 异声规则\n\n墙后呼吸声每三秒出现一次，磁带可以记录异常频率。\n",
    )
    book_id = quote(project.root.as_posix(), safe="")

    plot_response = client.post(
        f"/api/books/{book_id}/chapters/001/plot-directions",
        json={"userIntent": "强化磁带线索"},
    )
    assert plot_response.status_code == 200
    options = plot_response.json()["report"]["options"]
    assert len(options) == 3

    apply_response = client.post(
        f"/api/books/{book_id}/chapters/001/plot-directions/apply",
        json={"optionId": options[0]["id"]},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["contract"]["focus"]

    rebuild_response = client.post(f"/api/books/{book_id}/knowledge/rebuild")
    assert rebuild_response.status_code == 200
    assert rebuild_response.json()["chunkCount"] == 1

    search_response = client.get(f"/api/books/{book_id}/knowledge/search?q=磁带&limit=3")
    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["source"] == "knowledge/sources/world.md"
    assert search_response.json()["results"][0]["matchReasons"]

    polish_without_account = client.post(
        f"/api/books/{book_id}/chapters/001/polish",
        json={"preferTrainedModel": False},
    )
    assert polish_without_account.status_code == 503
    assert "写作角色" in polish_without_account.json()["detail"]

    _configure_ai_account(client)

    async def fake_polish_upstream(self, account, prompt):
        assert "原文" in prompt
        yield "token", {"text": "# 第一章\n\n润色后的章节正文。"}
        yield "usage", {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28}

    monkeypatch.setattr(AIRuntimeService, "_upstream_events", fake_polish_upstream)
    polish_response = client.post(
        f"/api/books/{book_id}/chapters/001/polish",
        json={"instruction": "减少解释，强化雨夜压力。"},
    )
    assert polish_response.status_code == 200
    assert polish_response.json()["candidateText"].endswith("润色后的章节正文。")
    assert polish_response.json()["usage"]["totalTokens"] == 28

    ideation_response = client.post(
        f"/api/books/{book_id}/ideation",
        json={"title": "下一章方向", "focus": "磁带", "seed": "下一章继续追查磁带。"},
    )
    assert ideation_response.status_code == 200
    session_id = ideation_response.json()["session"]["sessionId"]

    turn_response = client.post(
        f"/api/books/{book_id}/ideation/{session_id}/turns",
        json={"content": "增加旧敌误导。"},
    )
    assert turn_response.status_code == 200
    assert len(turn_response.json()["session"]["turns"]) == 2

    analysis_response = client.post(
        f"/api/books/{book_id}/analysis",
        json={"startChapterId": "001", "endChapterId": "001"},
    )
    assert analysis_response.status_code == 200
    analysis_report = analysis_response.json()["report"]
    assert analysis_report["path"]

    formula_response = client.post(
        f"/api/books/{book_id}/analysis/promote-formulas",
        json={"reportPath": analysis_report["path"]},
    )
    assert formula_response.status_code == 200
    assert "formulas" in formula_response.json()["memory"]
    formulas = formula_response.json()["memory"]["formulas"]
    if not formulas:
        formulas = [
            {
                "id": "ending_hook_grounded",
                "title": "钩子从结果里长出来",
                "guidance": "章末问题由本章结果引出。",
                "status": "suggested",
                "evidenceChapters": ["001"],
            }
        ]
        ProjectService().write_text(
            project.root,
            "memory/writing-formulas.json",
            json.dumps({"schemaVersion": 1, "formulas": formulas}, ensure_ascii=False),
        )
    formula_id = formulas[0]["id"]
    writing_assets = client.get(f"/api/books/{book_id}/writing-assets")
    enabled_formula = client.put(
        f"/api/books/{book_id}/writing-assets/formulas/{formula_id}",
        json={"formulaId": formula_id, "status": "active"},
    )
    assert writing_assets.status_code == 200
    assert enabled_formula.status_code == 200
    assert enabled_formula.json()["effective"]["formulas"][0]["id"] == formula_id

    sequence_response = client.post(
        f"/api/books/{book_id}/sequence-evaluation",
        json={"startChapterId": "001", "endChapterId": "001"},
    )
    assert sequence_response.status_code == 200
    assert sequence_response.json()["report"]["chapters"][0]["chapterId"] == "001"

    revision_response = client.post(
        f"/api/books/{book_id}/revision-plan",
        json={"startChapterId": "001", "endChapterId": "001"},
    )
    assert revision_response.status_code == 200
    assert "recommendedNextAction" in revision_response.json()["plan"]

    prepare_response = client.post(
        f"/api/books/{book_id}/chapters/001/prepare",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )
    assert prepare_response.status_code == 200
    assert "buildDurationMs" in prepare_response.json()["contextPack"]


def test_plot_directions_requires_prepared_chapter_contract(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    book_id = quote(project.root.as_posix(), safe="")

    response = client.post(
        f"/api/books/{book_id}/chapters/001/plot-directions",
        json={"userIntent": "强化冲突"},
    )

    assert response.status_code == 409
    assert "准备本章" in response.json()["detail"]


def test_next_chapter_is_blocked_until_latest_chapter_is_completed(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()
    book_id = quote(project.root.as_posix(), safe="")

    for status in ("待写", "草稿", "审阅"):
        presenter._write_chapter_status(project.root, "001", status)  # noqa: SLF001
        response = client.post(f"/api/books/{book_id}/chapters/next")

        assert response.status_code == 409
        assert "尚未正式完稿" in response.json()["detail"]

    presenter._write_chapter_status(project.root, "001", "完成")  # noqa: SLF001
    response = client.post(f"/api/books/{book_id}/chapters/next")

    assert response.status_code == 200
    assert response.json()["chapter"]["id"] == "002"


def test_workbench_materials_mark_overdue_promises(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    ProjectService().write_text(
        project.root,
        "chapters/011.md",
        "# 第十一章\n\n林澈继续追查。\n",
    )
    ProjectService().write_text(
        project.root,
        "memory/promises.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise_identity",
                        "text": "三章内揭开身世之谜",
                        "expectedPayoffWindow": "chapter:005-010",
                        "status": "open",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    data = client.get("/api/workspace").json()
    promise = next(item for item in data["materials"] if item["id"] == "promise-promise_identity")

    assert promise["dueStatus"] == "overdue"
    assert promise["details"]["到期状态"] == "已过期"


def test_workbench_workspace_normalizes_stale_numeric_chapter_title(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    assert client.get("/api/workspace").status_code == 200
    with sqlite3.connect(tmp_path / "workspace.sqlite3") as conn:
        conn.execute(
            """
            UPDATE workbench_chapters
            SET title = '001 001'
            WHERE root = ? AND chapter_id = '001'
            """,
            (project.root.as_posix(),),
        )

    response = client.get("/api/workspace")

    assert response.status_code == 200
    chapter = response.json()["books"][0]["chapters"][0]
    assert chapter["title"] == "第1章 待命名章节"


def test_workbench_next_action_reflects_running_job(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    JobController()._create(  # noqa: SLF001
        project.root,
        kind="chapter-draft",
        title="生成章节候选",
        detail="正在整理上下文。",
    )

    response = client.get("/api/workspace")

    assert response.status_code == 200
    next_action = response.json()["books"][0]["nextAction"]
    assert "正在整理上下文" in next_action
    assert "后台" not in next_action


def test_workbench_next_action_reflects_pending_reviews(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert run_response.status_code == 200
    response = client.get("/api/workspace")
    assert response.status_code == 200
    assert "待确认审稿" in response.json()["books"][0]["nextAction"]


def test_workbench_next_action_reflects_completed_chapter(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    accept_response = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/accept",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "force": True,
        },
    )

    assert accept_response.status_code == 200
    response = client.get("/api/workspace")
    assert response.status_code == 200
    assert "可以开始下一章" in response.json()["books"][0]["nextAction"]


def test_workbench_create_book_uses_role_account_instead_of_legacy_model_selection(
    tmp_path, monkeypatch
) -> None:
    client, _project = _client_with_project(tmp_path, monkeypatch)

    response = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "新书测试",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "一句话简介",
                "firstChapterTitle": "第一章",
                "seed": "开场灵感",
            },
            "existingBookCount": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["book"]["currentModelId"] == ""


def test_workbench_guided_create_requires_model_before_writing_project(
    tmp_path, monkeypatch
) -> None:
    client, _project = _client_with_project(tmp_path, monkeypatch)
    before = {item["root"] for item in WorkspaceRegistryService().list_projects()}

    response = client.post(
        "/api/books",
        json={
            "draft": {"title": "保留在表单中的新书", "genre": "都市悬疑"},
            "existingBookCount": 1,
            "defaultModelId": "",
            "startGeneration": True,
        },
    )

    assert response.status_code == 409
    assert "写作角色" in response.json()["detail"]
    assert {item["root"] for item in WorkspaceRegistryService().list_projects()} == before


def test_workbench_guided_create_starts_direction_candidate_with_selected_setup(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, _project = _client_with_project(tmp_path, monkeypatch)
    _configure_ai_account(client)

    response = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "连续创建测试",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "创建后直接审阅方向。",
                "firstChapterTitle": "第一章",
                "seed": "雨夜录音发出警告。",
            },
            "existingBookCount": 1,
            "interventionMode": "deep_control",
            "batchTarget": 3,
            "targetChapterCount": 120,
            "targetWordsPerChapter": 3200,
            "targetChaptersPerPlot": 12,
            "startGeneration": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    state = data["generationState"]
    assert state["status"] == "waiting_confirm"
    assert state["activeArtifactType"] == "book_direction"
    assert state["interventionMode"] == "deep_control"
    assert state["batchTarget"] == 3
    assert data["book"]["currentModelId"] == ""
    created_root = Path(data["book"]["id"])
    project_service = ProjectService()
    plan = json.loads(project_service.read_text(created_root, "story/project-plan.json"))
    assert not (created_root / "story" / "project-plan.json").exists()
    assert plan["targetChapterCount"] == 120
    assert plan["targetWordsPerChapter"] == 3200
    assert plan["targetChaptersPerPlot"] == 12
    assert data["book"]["writingPlan"] == {
        "targetChapterCount": 120,
        "targetWordsPerChapter": 3200,
        "targetChaptersPerPlot": 12,
    }


def test_workbench_updates_project_plan_and_unbinds_current_model(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    WritingModelService().register_profile(
        project.root,
        "default-writing-model",
        command_template=f"{sys.executable} {{prompt_file}} {{output_file}}",
        label="默认写作模型",
        set_default=True,
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")

    applied = client.put(
        f"/api/books/{encoded_book_id}/model",
        json={"bookId": project.root.as_posix(), "modelId": "codex-cli"},
    )
    updated = client.put(
        f"/api/books/{encoded_book_id}/plan",
        json={
            "bookId": project.root.as_posix(),
            "targetChapterCount": 180,
            "targetWordsPerChapter": 3600,
            "targetChaptersPerPlot": 14,
        },
    )
    unbound = client.put(
        f"/api/books/{encoded_book_id}/model",
        json={"bookId": project.root.as_posix(), "modelId": ""},
    )
    workspace = client.get("/api/workspace").json()
    current_book = next(
        item for item in workspace["books"] if item["id"] == project.root.as_posix()
    )

    assert applied.status_code == 200
    assert applied.json()["modelId"] == "codex-cli"
    assert updated.status_code == 200
    assert updated.json()["plan"]["targetChapterCount"] == 180
    assert updated.json()["plan"]["targetWordsPerChapter"] == 3600
    assert updated.json()["plan"]["targetChaptersPerPlot"] == 14
    assert updated.json()["book"]["writingPlan"] == {
        "targetChapterCount": 180,
        "targetWordsPerChapter": 3600,
        "targetChaptersPerPlot": 14,
    }
    assert unbound.status_code == 200
    assert unbound.json()["modelId"] == ""
    assert current_book["currentModelId"] == ""
    assert current_book["writingPlan"] == {
        "targetChapterCount": 180,
        "targetWordsPerChapter": 3600,
        "targetChaptersPerPlot": 14,
    }
    selection = json.loads(
        ProjectService().read_text(project.root, "models/workbench-selection.json")
    )
    assert selection == {"modelId": ""}


def test_workbench_generation_state_endpoints_persist_author_control(tmp_path, monkeypatch) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    _write_ready_architecture_and_blueprint(project.root)
    ProjectService().write_text(
        project.root,
        "memory/workbench-chapter-states.json",
        json.dumps({"schemaVersion": 1, "chapters": {"001": "待写"}}, ensure_ascii=False),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")

    listing = client.get("/api/workspace")
    initial = client.get(f"/api/books/{encoded_book_id}/generation")
    mode = client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": project.root.as_posix(),
            "interventionMode": "chapter_confirm",
            "batchTarget": 2,
        },
    )
    paused = client.post(
        f"/api/books/{encoded_book_id}/generation/pause",
        json={"bookId": project.root.as_posix()},
    )
    paused_continue = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    resumed = client.post(
        f"/api/books/{encoded_book_id}/generation/resume",
        json={"bookId": project.root.as_posix()},
    )
    continued = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    drafted = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": project.root.as_posix()},
    )
    takeover = client.post(
        f"/api/books/{encoded_book_id}/generation/takeover",
        json={"bookId": project.root.as_posix(), "target": "review"},
    )
    export_check = client.post(
        f"/api/books/{encoded_book_id}/exports/check",
        json={"bookId": project.root.as_posix(), "kind": "正文", "range": "全书"},
    )

    assert listing.status_code == 200
    assert listing.json()["generationStates"][0]["bookId"] == project.root.as_posix()
    assert initial.status_code == 200
    assert initial.json()["generationState"]["stage"] == "contract"
    assert mode.status_code == 200
    assert mode.json()["generationState"]["interventionMode"] == "chapter_confirm"
    assert mode.json()["generationState"]["batchTarget"] == 2
    assert paused.status_code == 200
    assert paused.json()["generationState"]["status"] == "paused"
    assert paused_continue.status_code == 200
    assert paused_continue.json()["generationState"]["status"] == "paused"
    assert resumed.status_code == 200
    assert resumed.json()["generationState"]["status"] == "idle"
    assert continued.status_code == 200
    continued_state = continued.json()["generationState"]
    assert continued_state["stage"] == "context"
    assert continued_state["status"] == "idle"
    assert drafted.status_code == 200
    assert drafted.json()["generationState"]["stage"] == "draft"
    assert drafted.json()["generationState"]["status"] == "waiting_confirm"
    assert drafted.json()["activeChapter"]["status"] == "审阅"
    assert confirmed.status_code == 200
    assert confirmed.json()["generationState"]["stage"] == "gate"
    assert confirmed.json()["activeChapter"]["status"] == "草稿"
    assert "线索001动作1" in confirmed.json()["activeChapter"]["content"]
    assert takeover.status_code == 200
    assert takeover.json()["target"] == "review"
    assert export_check.status_code == 200
    readiness = export_check.json()["readiness"]
    assert readiness["ready"] is False
    assert any("暂停" in risk for risk in readiness["risks"])
    state_file = json.loads(
        ProjectService().read_text(
            project.root,
            "memory/workbench-generation-state.json",
        )
    )
    assert state_file["state"]["status"] == "paused"


def test_workbench_new_book_starts_from_architecture_then_blueprint(tmp_path, monkeypatch) -> None:
    _install_controlled_generation_executor(monkeypatch)
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    client = TestClient(app)

    created = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "架构启动验证",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "异声把主角拖回旧案。",
                "firstChapterTitle": "",
                "seed": "",
            },
            "existingBookCount": 0,
            "defaultModelId": "codex-cli",
        },
    )

    assert created.status_code == 200
    book_id = created.json()["book"]["id"]
    encoded_book_id = quote(book_id, safe="")
    assert created.json()["chapter"]["title"] != "001 001"

    initial = client.get(f"/api/books/{encoded_book_id}/generation")
    architecture = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )
    project_service = ProjectService()
    architecture_candidate = "story/generation-candidates/book-directions.json"
    assert project_service.file_exists(Path(book_id), architecture_candidate)
    assert not (Path(book_id) / architecture_candidate).exists()
    assert not (Path(book_id) / "story" / "workbench-architecture.json").exists()
    architecture_confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": book_id, "optionId": "direction-2"},
    )
    planning = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )

    assert initial.status_code == 200
    assert initial.json()["generationState"]["stage"] == "architecture"
    assert "作品架构" in initial.json()["generationState"]["nextAction"]
    assert architecture.status_code == 200
    assert architecture.json()["generationState"]["stage"] == "architecture"
    assert architecture.json()["generationState"]["status"] == "waiting_confirm"
    assert len(architecture.json()["generationState"]["candidateOptions"]) == 3
    assert architecture_confirmed.status_code == 200
    assert architecture_confirmed.json()["generationState"]["stage"] == "blueprint"
    architecture_data = json.loads(
        project_service.read_text(Path(book_id), "story/workbench-architecture.json")
    )
    assert architecture_data["directionId"] == "direction-2"
    assert architecture_data["storyEngine"]
    assert architecture_data["longTermHooks"]
    architecture_candidate = json.loads(
        project_service.read_text(
            Path(book_id),
            "story/generation-candidates/book-architecture.json",
        )
    )
    assert architecture_candidate["status"] == "accepted"
    assert architecture_candidate["sourceAgentId"] == "codex-cli"
    assert planning.status_code == 200
    assert planning.json()["generationState"]["stage"] == "blueprint"
    assert planning.json()["generationState"]["status"] == "waiting_confirm"
    assert planning.json()["generationState"]["activeArtifactType"] == "long_form_plan"
    planning_confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": book_id},
    )
    assert planning_confirmed.status_code == 200
    long_form_plan = json.loads(
        project_service.read_text(Path(book_id), "story/long-form-plan.json")
    )
    assert len(long_form_plan["volumes"]) == 2
    assert all(len(volume["beatSegments"]) >= 2 for volume in long_form_plan["volumes"])
    blueprint = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )
    assert blueprint.status_code == 200
    assert blueprint.json()["generationState"]["stage"] == "blueprint"
    assert blueprint.json()["generationState"]["status"] == "waiting_confirm"
    blueprint_file = "story/chapter-blueprint.json"
    assert not project_service.file_exists(Path(book_id), blueprint_file)
    assert project_service.file_exists(
        Path(book_id), "story/generation-candidates/chapter-blueprint.json"
    )
    blueprint_confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": book_id},
    )
    assert blueprint_confirmed.status_code == 200
    blueprint_data = json.loads(project_service.read_text(Path(book_id), blueprint_file))
    assert len(blueprint_data["chapters"]) == 10
    assert blueprint_confirmed.json()["generationState"]["stage"] == "contract"
    brief = json.loads(
        project_service.read_text(Path(book_id), "story/chapter-briefs/001.blueprint.json")
    )
    assert brief["goal"]


def test_fresh_workspace_bootstraps_database_starter_demo_without_project_files(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.delenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", raising=False)
    assert not db_path.exists()
    client = TestClient(app)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    books = response.json()["books"]
    assert len(books) == 1
    assert books[0]["title"] == "示例作品"
    assert [(chapter["id"], chapter["status"]) for chapter in books[0]["chapters"]] == [
        ("001", "草稿")
    ]
    root = Path(books[0]["id"])
    service = ProjectService()
    assert not root.exists()
    assert service.is_database_project(root)
    assert service.file_exists(root, "novel.json")
    assert service.file_exists(root, "chapters/001.md")
    assert db_path.is_file()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM ai_accounts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_secrets").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_role_bindings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM model_templates").fetchone()[0] == 14
    model_library = client.get("/api/model-library")
    assert model_library.status_code == 200
    assert {item["label"] for item in model_library.json()["categories"]} >= {
        "玄幻",
        "都市",
        "悬疑",
    }
    assert {item["name"] for item in model_library.json()["templates"]} >= {
        "东方玄幻升级流",
        "本格悬疑推理",
    }
    style_labels = {
        item["label"] for item in response.json()["creationOptions"]["platformStyles"]
    }
    assert "通用网文连载" in style_labels


def test_existing_empty_workspace_database_is_not_seeded_or_replaced(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    WorkspaceRegistryService(db_path)
    client = TestClient(app)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    assert response.json()["books"] == []
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workspace_projects").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM workbench_project_documents").fetchone()[0]
            == 0
        )


def test_workbench_generation_candidate_versions_select_and_safe_rollback(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    client = TestClient(app)
    created = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "候选版本验证",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "候选必须可以比较和返回。",
                "firstChapterTitle": "第一章",
                "seed": "雨夜录音出现未来警告。",
            },
            "existingBookCount": 0,
            "defaultModelId": "codex-cli",
        },
    )
    book_id = created.json()["book"]["id"]
    root = Path(book_id)
    path = f"/api/books/{quote(book_id, safe='')}/generation"

    first = client.post(f"{path}/continue", json={"bookId": book_id})
    first_artifact = first.json()["generationState"]["artifact"]
    assert first_artifact["candidateId"] == "book_direction-v1"
    assert len(first_artifact["versions"]) == 1
    waiting_continue = client.post(
        f"{path}/continue",
        json={"bookId": book_id, "requestId": "must-confirm-direction"},
    )
    assert waiting_continue.status_code == 200
    assert (
        waiting_continue.json()["generationState"]["artifact"]["candidateId"] == "book_direction-v1"
    )
    project_service = ProjectService()
    current_path = "story/generation-candidates/book-directions.json"
    legacy_candidate = json.loads(project_service.read_text(root, current_path))
    legacy_candidate.pop("candidateId")
    legacy_candidate.pop("version")
    project_service.write_text(root, current_path, json.dumps(legacy_candidate, ensure_ascii=False))
    migrated = client.get(path)
    assert migrated.json()["generationState"]["artifact"]["candidateId"] == "book_direction-v1"

    regenerated = client.post(
        f"{path}/candidates/regenerate",
        json={"bookId": book_id, "requestId": "direction-v2"},
    )
    regenerated_artifact = regenerated.json()["generationState"]["artifact"]
    assert regenerated.status_code == 200
    assert regenerated_artifact["candidateId"] == "book_direction-v2"
    assert [item["version"] for item in regenerated_artifact["versions"]] == [2, 1]
    archived_path = (
        "story/generation-candidates/versions/book-directions/book_direction-v1.json"
    )
    assert project_service.file_exists(root, archived_path)
    assert not (root / archived_path).exists()
    duplicate_regenerated = client.post(
        f"{path}/candidates/regenerate",
        json={"bookId": book_id, "requestId": "direction-v2"},
    )
    assert duplicate_regenerated.status_code == 200
    assert len(duplicate_regenerated.json()["generationState"]["artifact"]["versions"]) == 2

    selected = client.put(
        f"{path}/candidates/current",
        json={
            "bookId": book_id,
            "candidateId": "book_direction-v1",
            "requestId": "select-direction-v1",
        },
    )
    assert selected.status_code == 200
    assert selected.json()["generationState"]["artifact"]["candidateId"] == "book_direction-v1"
    assert not (root / "story" / "workbench-architecture.json").exists()
    duplicate_selected = client.put(
        f"{path}/candidates/current",
        json={
            "bookId": book_id,
            "candidateId": "book_direction-v1",
            "requestId": "select-direction-v1",
        },
    )
    assert duplicate_selected.status_code == 200
    assert (
        duplicate_selected.json()["generationState"]["artifact"]["candidateId"]
        == "book_direction-v1"
    )

    confirmed = client.post(
        f"{path}/confirm",
        json={
            "bookId": book_id,
            "optionId": "direction-2",
            "requestId": "confirm-direction-v1",
        },
    )
    assert confirmed.status_code == 200
    architecture = json.loads(
        project_service.read_text(root, "story/workbench-architecture.json")
    )
    assert architecture["directionId"] == "direction-2"
    duplicate_confirmed = client.post(
        f"{path}/confirm",
        json={
            "bookId": book_id,
            "optionId": "direction-2",
            "requestId": "confirm-direction-v1",
        },
    )
    assert duplicate_confirmed.status_code == 200
    assert duplicate_confirmed.json()["generationState"]["stage"] == "blueprint"

    planning = client.post(f"{path}/continue", json={"bookId": book_id})
    assert planning.json()["generationState"]["activeArtifactType"] == "long_form_plan"
    rolled_back = client.post(
        f"{path}/candidates/rollback",
        json={"bookId": book_id, "requestId": "rollback-long-form-v1"},
    )
    assert rolled_back.status_code == 200
    rollback_state = rolled_back.json()["generationState"]
    assert rollback_state["stage"] == "architecture"
    assert rollback_state["activeArtifactType"] == "book_direction"
    assert rollback_state["status"] == "waiting_confirm"
    assert not project_service.file_exists(root, "story/workbench-architecture.json")
    duplicate_rollback = client.post(
        f"{path}/candidates/rollback",
        json={"bookId": book_id, "requestId": "rollback-long-form-v1"},
    )
    assert duplicate_rollback.status_code == 200
    assert duplicate_rollback.json()["generationState"]["stage"] == "architecture"
    with TestClient(app) as restarted_client:
        refreshed = restarted_client.get(path)
    assert refreshed.json()["generationState"]["artifact"]["candidateId"] == "book_direction-v1"


def test_workbench_generation_structure_rollback_blocks_after_finalized_chapter(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    ProjectService().write_text(
        project.root,
        "story/workbench-architecture.json",
        json.dumps({"schemaVersion": 2, "serialHook": "城市真相持续逼近。"}),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")
    generated = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    assert generated.json()["generationState"]["activeArtifactType"] == "long_form_plan"

    blocked = client.post(
        f"/api/books/{encoded_book_id}/generation/candidates/rollback",
        json={"bookId": project.root.as_posix()},
    )

    assert blocked.status_code == 409
    assert "定稿章节" in blocked.json()["detail"]
    assert (project.root / "story" / "workbench-architecture.json").is_file()


def test_workbench_generation_blocks_without_real_model_and_preserves_stage(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    monkeypatch.delenv("OPEN_NOVEL_WORKBENCH_AGENT_ID", raising=False)
    client = TestClient(app)
    created = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "模型阻断验证",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "未配置模型不能伪造成功。",
                "firstChapterTitle": "",
                "seed": "",
            },
            "existingBookCount": 0,
            "defaultModelId": "",
        },
    )
    book_id = created.json()["book"]["id"]
    encoded_book_id = quote(book_id, safe="")

    response = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )

    assert response.status_code == 200
    state = response.json()["generationState"]
    assert state["stage"] == "architecture"
    assert state["status"] == "blocked"
    assert state["canRetry"] is False
    assert "模型" in state["blockers"][0]
    assert not (Path(book_id) / "story" / "workbench-architecture.json").exists()
    assert not (Path(book_id) / "story" / "generation-candidates").exists()


def test_workbench_long_form_plan_replans_future_without_overwriting_finalized_chapter(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "story/workbench-architecture.json",
        json.dumps({"schemaVersion": 2, "serialHook": "城市真相持续逼近。"}),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")

    generated = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": project.root.as_posix()},
    )
    plan_response = client.get(f"/api/books/{encoded_book_id}/long-form-plan")

    assert generated.status_code == 200
    assert generated.json()["generationState"]["activeArtifactType"] == "long_form_plan"
    assert confirmed.status_code == 200
    plan = plan_response.json()["plan"]
    assert len(plan["volumes"]) == 2
    assert all(len(volume["beatSegments"]) >= 2 for volume in plan["volumes"])

    original_chapter = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    volume_id = plan["currentVolumeId"]
    updated = client.put(
        f"/api/books/{encoded_book_id}/long-form-plan/volumes/{volume_id}",
        json={
            "bookId": project.root.as_posix(),
            "volumeId": volume_id,
            "goal": "作者改为让主角优先保护居民共同决策权。",
        },
    )
    replanned = client.post(
        f"/api/books/{encoded_book_id}/long-form-plan/replan",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )

    assert updated.status_code == 200
    assert replanned.status_code == 200
    assert replanned.json()["deviation"]["significant"] is True
    assert replanned.json()["candidate"]["status"] == "candidate"
    accepted_before_confirm = json.loads(
        (project.root / "story" / "long-form-plan.json").read_text(encoding="utf-8")
    )
    assert accepted_before_confirm["volumes"][0]["goal"] == "作者改为让主角优先保护居民共同决策权。"

    replan_confirmed = client.post(
        f"/api/books/{encoded_book_id}/long-form-plan/replan/confirm",
        json={"bookId": project.root.as_posix()},
    )
    assert replan_confirmed.status_code == 200
    assert (project.root / "chapters" / "001.md").read_text(encoding="utf-8") == original_chapter

    contract = (
        StoryGuidanceService()
        .read_scene_contract(project.root, "001")
        .model_copy(update={"chapterId": "004", "title": "第四章"})
    )
    StoryGuidanceService().write_scene_contract(project.root, contract)
    context = ContextPackService().build_context_pack(project.root, "004")
    contract_item = next(
        item for item in context.included if item.source == "story/chapter-briefs/004.json"
    )
    assert contract_item.data["arcContext"]["arcId"] == "volume-001"
    assert contract_item.data["arcContext"]["currentMilestones"] == []


def test_workbench_generation_requires_assigned_writing_account(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    WritingModelService().register_profile(
        project.root,
        "missing-command-model",
        command_template="definitely-missing-open-novel-command {prompt_file}",
    )
    ProjectService().write_text(
        project.root,
        "models/workbench-selection.json",
        json.dumps({"modelId": "missing-command-model"}),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )

    assert response.status_code == 200
    state = response.json()["generationState"]
    assert state["status"] == "blocked"
    assert "写作角色" in state["blockers"][0]
    assert not (project.root / "story" / "generation-candidates").exists()


def test_workbench_generation_full_auto_advances_ten_chapters_with_sqlite_registry(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    _install_passing_generation_gate(monkeypatch)
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    client = TestClient(app)

    created = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "十章推进验证",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "声音线索牵出记忆代价。",
                "firstChapterTitle": "第一章 旧区回声",
                "seed": "主角在旧区听见三秒一次的异常广播。",
            },
            "existingBookCount": 0,
            "defaultModelId": "codex-cli",
        },
    )

    assert created.status_code == 200
    book_id = created.json()["book"]["id"]
    encoded_book_id = quote(book_id, safe="")
    project_service = ProjectService()

    mode = client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": book_id,
            "interventionMode": "full_auto",
            "batchTarget": 10,
        },
    )
    continued = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )

    assert mode.status_code == 200
    assert continued.status_code == 200
    state = continued.json()["generationState"]
    assert state["interventionMode"] == "full_auto"
    assert state["stage"] == "next_chapter"
    assert state["status"] == "completed"
    assert state["batchDone"] == 10

    workspace = client.get("/api/workspace")
    assert workspace.status_code == 200
    book = next(item for item in workspace.json()["books"] if item["id"] == book_id)
    completed_chapters = [chapter for chapter in book["chapters"] if chapter["status"] == "完成"]
    assert len(completed_chapters) >= 10
    assert all(chapter["wordCount"] > 100 for chapter in completed_chapters[:10]), [
        (chapter["id"], chapter["wordCount"]) for chapter in completed_chapters[:10]
    ]
    word_counts = [chapter["wordCount"] for chapter in completed_chapters[:10]]
    assert min(word_counts) >= 600
    assert len(set(word_counts)) >= 3
    assert all("城市旧区" not in str(chapter["content"]) for chapter in completed_chapters[:10])
    completed_chapter_ids = {str(chapter["id"]) for chapter in completed_chapters[:10]}

    training_readiness_response = client.post(
        "/api/models/training/readiness",
        params={"bookId": book_id},
    )
    assert training_readiness_response.status_code == 200
    training_readiness = training_readiness_response.json()
    assert training_readiness["status"] == "block"
    assert training_readiness["eligibleCount"] == 0
    assert training_readiness["skippedCount"] == 10
    assert training_readiness["minRecommendedExamples"] == 50
    assert all(item["eligible"] is False for item in training_readiness["items"])
    readiness_report = json.loads(
        project_service.read_text(Path(book_id), "exports/training-readiness.json")
    )
    readiness_chapter_ids = {item["chapterId"] for item in readiness_report["items"]}
    eligible_chapter_ids = {
        item["chapterId"] for item in readiness_report["items"] if item["eligible"]
    }
    assert readiness_chapter_ids == completed_chapter_ids
    assert eligible_chapter_ids == set()

    training_check = client.post(
        f"/api/books/{encoded_book_id}/exports/check",
        json={"bookId": book_id, "kind": "训练数据", "range": "全书"},
    )
    assert training_check.status_code == 200
    training_export_readiness = training_check.json()["readiness"]
    assert training_export_readiness["kind"] == "训练数据"
    assert training_export_readiness["ready"] is False
    assert "可用样本 0 章" in training_export_readiness["checks"]
    assert "跳过 10 章" in training_export_readiness["risks"]
    assert "当前没有可用于训练的数据样本" in training_export_readiness["risks"]

    training_export = client.post(
        f"/api/books/{encoded_book_id}/exports",
        json={"bookId": book_id, "kind": "训练数据", "range": "全书"},
    )
    assert training_export.status_code == 200
    assert training_export.json()["resultName"] == "writing-training.jsonl"
    training_records = [
        json.loads(line)
        for line in project_service.read_text(
            Path(book_id), "exports/writing-training.jsonl"
        ).splitlines()
        if line.strip()
    ]
    assert {record["metadata"]["chapterId"] for record in training_records} == eligible_chapter_ids

    manuscript_check = client.post(
        f"/api/books/{encoded_book_id}/exports/check",
        json={"bookId": book_id, "kind": "正文", "range": "全书"},
    )
    assert manuscript_check.status_code == 200
    manuscript_readiness = manuscript_check.json()["readiness"]
    assert manuscript_readiness["kind"] == "正文"
    assert manuscript_readiness["ready"] is False
    assert "生成状态：下一章准备" in manuscript_readiness["checks"]
    assert not any("生成流程" in risk for risk in manuscript_readiness["risks"])
    assert not any("不是完成状态" in risk for risk in manuscript_readiness["risks"])
    assert manuscript_readiness["risks"] == ["仍有 1 条未确认审稿项"]

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT root, title FROM workspace_projects WHERE root = ?",
            (book_id,),
        ).fetchall()
        db_completed = conn.execute(
            """
            SELECT COUNT(*) FROM workbench_chapters
            WHERE root = ? AND status = '完成'
            """,
            (book_id,),
        ).fetchone()[0]
        db_contracts = conn.execute(
            "SELECT COUNT(*) FROM workbench_scene_contracts WHERE root = ?",
            (book_id,),
        ).fetchone()[0]
        db_context_packs = conn.execute(
            "SELECT COUNT(*) FROM workbench_context_packs WHERE root = ?",
            (book_id,),
        ).fetchone()[0]
        db_state = json.loads(
            conn.execute(
                "SELECT state_json FROM workbench_generation_states WHERE root = ?",
                (book_id,),
            ).fetchone()[0]
        )
        coverage = WorkbenchRepository(db_path).coverage_counts(Path(book_id))
        conn.execute(
            "DELETE FROM workbench_chapters WHERE root = ? AND chapter_id = '010'",
            (book_id,),
        )
    project_service.delete_text(Path(book_id), "story/chapter-briefs/010.json")
    assert rows == [(book_id, "十章推进验证")]
    assert db_completed == 10
    assert db_contracts >= 10
    assert db_context_packs >= 10
    assert db_state["batchDone"] == 10
    assert coverage["chapters"] >= 10
    assert coverage["sceneContracts"] >= 10
    assert coverage["contextPacks"] >= 10
    assert coverage["hasGenerationState"] is True
    run_agents = {
        json.loads(project_service.read_text(Path(book_id), relative_path))["agentId"]
        for relative_path in project_service.list_paths(Path(book_id), "runs")
        if relative_path.endswith("/run.json")
    }
    assert run_agents == {"codex-cli"}
    facts = json.loads(project_service.read_text(Path(book_id), "memory/facts.json"))
    characters = json.loads(
        project_service.read_text(Path(book_id), "memory/character-states.json")
    )
    relationships = json.loads(
        project_service.read_text(Path(book_id), "memory/relationship-states.json")
    )
    promises = json.loads(project_service.read_text(Path(book_id), "memory/promises.json"))
    assert len(facts["facts"]) >= 10
    assert characters["characters"][0]["characterId"] == "沈砚"
    assert relationships["relationships"]
    assert promises["promises"]
    project_root = Path(book_id)
    assert not project_root.exists() or not any(path.is_file() for path in project_root.rglob("*"))

    after_delete = client.get("/api/workspace")
    assert after_delete.status_code == 200
    book_after_delete = next(item for item in after_delete.json()["books"] if item["id"] == book_id)
    assert len(book_after_delete["chapters"]) == 9
    assert all(chapter["id"] != "010" for chapter in book_after_delete["chapters"])

    prepare = client.post(
        f"/api/books/{encoded_book_id}/chapters/010/prepare",
        json={"bookId": book_id, "chapterId": "010"},
    )
    assert prepare.status_code == 200
    assert project_service.file_exists(Path(book_id), "story/chapter-briefs/010.json")


def test_workbench_generation_full_auto_stops_at_author_step_limit(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    client = TestClient(app)
    created = client.post(
        "/api/books",
        json={
            "draft": {
                "title": "自动推进熔断验证",
                "platform": "generic",
                "styleProfileId": "generic-web-serial",
                "styleProfileLabel": "通用网文连载",
                "genre": "都市悬疑",
                "tagline": "自动推进必须按作者上限停止。",
                "firstChapterTitle": "第一章",
                "seed": "旧录音在雨夜重启。",
            },
            "defaultModelId": "codex-cli",
        },
    )
    book_id = created.json()["book"]["id"]
    encoded_book_id = quote(book_id, safe="")

    mode = client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": book_id,
            "interventionMode": "full_auto",
            "batchTarget": 10,
            "autoStepLimit": 2,
        },
    )
    continued = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": book_id},
    )
    confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": book_id},
    )

    assert mode.status_code == 200
    state = continued.json()["generationState"]
    assert state["status"] == "waiting_confirm"
    assert state["activeArtifactType"] == "auto_step_limit"
    assert state["autoStepLimit"] == 2
    assert state["autoStepsUsed"] == 2
    assert "步数上限" in state["lastResult"]
    confirmed_state = confirmed.json()["generationState"]
    assert confirmed_state["status"] == "idle"
    assert confirmed_state["autoStepsUsed"] == 0


def test_workbench_full_auto_blocks_repeated_low_quality_chapter(tmp_path, monkeypatch) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    repeated_body = (
        "旧区广播站里，主角握紧录音笔，胸口发冷。"
        "值守人冷笑着拦住他，主角选择继续追查异常广播。"
        "下一刻，广播忽然异动，新的名单在屏幕上出现。"
        "主角没有退，他把录音笔贴近门缝，听见三秒一次的呼吸。"
        "同伴低声问他还要不要继续，主角只说必须确认线索来源。"
        "门禁变红以后，值守人逼他删掉证据，主角反而把名单拍了下来。"
        "广播里忽然念出主角的名字，关键证据反指向他自己的过去。"
        "同伴看见他手指发抖，终于从怀疑转为有限信任。"
        "如果失败，证据会被删除，同伴也会失去关键记忆。"
        "推进目标的代价是主角暴露行踪并失去一段私人记忆。"
        "主角嘴上冷静，停顿和回避泄露出恐惧。"
        "主角想证明自己的判断不是幻觉，也害怕再次被当成污染源。"
        "到天亮前，主角拿到第二条证据，但暴露新的危险。"
        "本章推进都市悬疑、声音线索和记忆代价。"
        "结尾留下危险、不安和继续追查的期待。"
        "新的名单在结尾出现，下一章危险逼近。"
    )
    ProjectService().write_text(project.root, "chapters/001.md", f"# 第一章\n\n{repeated_body}")
    ProjectService().write_text(project.root, "chapters/002.md", "# 第二章\n\n")
    ProjectService().write_text(
        project.root,
        "drafts/002.generated.md",
        f"# 第二章\n\n{repeated_body}",
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="002",
            title="第二章",
            focus="主角继续追查异常广播。",
            goal="主角必须确认第二条异常线索的来源。",
            conflict="档案封锁、陌生阻力和记忆代价同时逼近主角。",
            turn="关键证据忽然反指向主角自己的过去。",
            outcome="主角拿到第二条证据，但暴露新的危险。",
            hook="新的名单在结尾出现，下一章危险逼近。",
            emotionalBeat="主角从警惕走向压抑后的坚定。",
            relationshipBeat="同伴从怀疑转为有限信任，但裂痕仍然存在。",
            internalNeed="主角想证明自己的判断不是幻觉。",
            woundOrFear="主角害怕再次被当成污染源。",
            stakes="如果失败，证据会被删除，同伴也会失去关键记忆。",
            cost="推进目标的代价是主角暴露行踪并失去一段私人记忆。",
            subtext="主角嘴上冷静，停顿和回避泄露出恐惧。",
            aftertaste="结尾留下危险、不安和继续追查的期待。",
            mustInclude=["第二条异常线索", "记忆代价", "新的名单"],
            mustAvoid=["提前揭示最终真相"],
            readerPromises=["都市悬疑", "声音线索", "记忆代价"],
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/workbench-chapter-states.json",
        json.dumps(
            {"schemaVersion": 1, "chapters": {"001": "完成", "002": "审阅"}},
            ensure_ascii=False,
        ),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")
    mode = client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": project.root.as_posix(),
            "interventionMode": "full_auto",
            "batchTarget": 2,
        },
    )
    continued = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )

    assert mode.status_code == 200
    assert continued.status_code == 200
    state = continued.json()["generationState"]
    assert state["status"] == "blocked"
    assert state["stage"] == "gate"
    assert state["batchDone"] == 0
    assert state["retryCount"] == 2
    assert (project.root / "drafts" / "history" / "002.before-repair-1.md").exists()
    assert (project.root / "drafts" / "history" / "002.before-repair-2.md").exists()
    assert any("相似" in blocker or "重复" in blocker for blocker in state["blockers"])


def test_workbench_gate_retry_creates_confirmable_repair_candidate(tmp_path, monkeypatch) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    _write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n" + "当前正文存在阻断。" * 80,
    )
    presenter = WorkbenchPresenter()
    presenter._write_chapter_status(project.root, "001", "审阅")

    def controlled_gate(self, root, chapter_id):
        text = ProjectService().read_text(root, f"drafts/{chapter_id}.generated.md")
        if "修复后" in text:
            return {"gate": {"status": "pass", "score": 90, "issues": []}, "display": "检查通过"}
        return {
            "gate": {
                "status": "block",
                "score": 40,
                "issues": [{"severity": "blocker", "message": "当前正文存在阻断。"}],
            },
            "display": "检查阻断",
        }

    monkeypatch.setattr(WorkbenchGenerationService, "_check_gate", controlled_gate)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": project.root.as_posix(),
            "interventionMode": "stage_confirm",
            "batchTarget": 1,
        },
    )

    blocked = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    repair = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )
    draft_before_confirm = (project.root / "drafts" / "001.generated.md").read_text(
        encoding="utf-8"
    )
    confirmed = client.post(
        f"/api/books/{encoded_book_id}/generation/confirm",
        json={"bookId": project.root.as_posix()},
    )
    rechecked = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )

    assert blocked.json()["generationState"]["status"] == "blocked"
    assert blocked.json()["generationState"]["canRetry"] is True
    assert repair.json()["generationState"]["status"] == "waiting_confirm"
    assert repair.json()["generationState"]["activeArtifactType"] == "chapter_repair"
    assert (project.root / "drafts" / "001.repair-1.candidate.md").exists()
    assert "修复后" not in draft_before_confirm
    assert confirmed.json()["generationState"]["stage"] == "gate"
    assert "修复后" in (project.root / "drafts" / "001.generated.md").read_text(encoding="utf-8")
    assert (project.root / "drafts" / "history" / "001.before-repair-1.md").exists()
    assert rechecked.json()["generationState"]["stage"] == "accept"
    assert rechecked.json()["generationState"]["status"] == "waiting_confirm"


def test_workbench_memory_failure_preserves_finalized_chapter_and_progress(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()
    presenter._write_chapter_status(project.root, "001", "完成")
    state = presenter._generation_state_payload(
        project.root,
        stage="memory",
        status="idle",
        batch_target=3,
        batch_done=0,
        active_chapter_id="001",
        next_action="应用记忆更新。",
        last_result="正文已定稿。",
    )
    presenter._write_generation_state(project.root, state)

    def fail_memory(self, root, chapter_id, mode):
        raise RuntimeError("internal path and secret must not leak")

    monkeypatch.setattr(WorkbenchGenerationService, "_apply_accepted_memory", fail_memory)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    response = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )

    result = response.json()["generationState"]
    assert response.status_code == 200
    assert result["stage"] == "memory"
    assert result["status"] == "blocked"
    assert result["batchDone"] == 0
    assert result["canRetry"] is True, json.dumps(result, ensure_ascii=False)
    assert "internal path" not in json.dumps(response.json(), ensure_ascii=False)
    assert presenter._stored_chapter_status(project.root, "001") == "完成"


def test_workbench_regeneration_archives_previous_draft(tmp_path, monkeypatch) -> None:
    _install_controlled_generation_executor(monkeypatch)
    _install_passing_generation_gate(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    _write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n作者保留的上一版候选。\n",
    )
    presenter = WorkbenchPresenter()
    presenter._write_chapter_status(project.root, "001", "待写")
    encoded_book_id = quote(project.root.as_posix(), safe="")
    client.put(
        f"/api/books/{encoded_book_id}/generation/mode",
        json={
            "bookId": project.root.as_posix(),
            "interventionMode": "chapter_confirm",
            "batchTarget": 1,
        },
    )

    response = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json={"bookId": project.root.as_posix()},
    )

    archived = project.root / "drafts" / "history" / "001.before-generation-1.md"
    assert response.status_code == 200
    assert response.json()["generationState"]["stage"] == "draft"
    assert archived.exists()
    assert "作者保留的上一版候选" in archived.read_text(encoding="utf-8")


def test_workbench_generation_continue_is_idempotent_across_presenter_restart(
    tmp_path, monkeypatch
) -> None:
    _install_controlled_generation_executor(monkeypatch)
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_architecture_and_blueprint(project.root)
    _write_ready_contract(project.root)
    WorkbenchPresenter()._write_chapter_status(project.root, "001", "待写")
    encoded_book_id = quote(project.root.as_posix(), safe="")
    payload = {"bookId": project.root.as_posix(), "requestId": "continue-001"}

    first = client.post(
        f"/api/books/{encoded_book_id}/generation/continue",
        json=payload,
    )
    restarted = WorkbenchPresenter()
    repeated = restarted.continue_generation(
        project.root.as_posix(),
        request_id="continue-001",
    )

    assert first.status_code == 200
    assert first.json()["generationState"]["stage"] == "context"
    assert repeated["generationState"]["stage"] == "context"
    assert restarted._read_generation_state(project.root)["lastContinueRequestId"] == "continue-001"
    assert not (project.root / "drafts" / "001.generated.md").exists()


def test_workbench_generation_continue_claims_duplicate_request_atomically(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    entered = Event()
    release = Event()
    calls = 0

    def controlled_advance(self, root, *, mode, batch_target, batch_done):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        current = self.presenter._read_generation_state(root)
        return (
            self._state(
                root,
                current,
                stage="context",
                status="idle",
                next_action="继续。",
                last_result="已推进。",
            ),
            "已推进。",
            True,
        )

    monkeypatch.setattr(WorkbenchGenerationService, "advance_once", controlled_advance)
    request_id = "concurrent-continue-001"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            WorkbenchPresenter().continue_generation,
            project.root.as_posix(),
            request_id,
        )
        assert entered.wait(timeout=5)
        repeated = executor.submit(
            WorkbenchPresenter().continue_generation,
            project.root.as_posix(),
            request_id,
        ).result(timeout=5)
        release.set()
        completed = first.result(timeout=5)

    assert calls == 1
    assert completed["generationState"]["stage"] == "context"
    assert repeated["authorMessage"] == "该生成请求已处理，已返回当前状态。"
    assert (
        WorkbenchPresenter()._read_generation_state(project.root)["lastContinueRequestId"]
        == request_id
    )


def test_workbench_gate_checks_author_saved_draft_before_stale_generated_candidate(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    generated = project.root / "drafts" / "001.generated.md"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("# 第一章\n\n旧候选。\n", encoding="utf-8")
    author_text = "# 第一章\n\n" + "作者已保存的新正文包含完整行动、冲突、转折和结果。" * 180
    encoded_book_id = quote(project.root.as_posix(), safe="")

    saved = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/draft",
        json={"bookId": project.root.as_posix(), "chapterId": "001", "nextContent": author_text},
    )
    checked = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/gate",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )

    assert saved.status_code == 200
    assert checked.status_code == 200
    quality = json.loads(
        (project.root / "runs" / "writing-quality-001.json").read_text(encoding="utf-8")
    )
    assert quality["source"] == "chapters/001.md"
    assert quality["metrics"]["characters"] > 1000


def test_workbench_validate_model_returns_author_facing_result(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    local_response = client.post(
        "/api/models/local-dry-run/validate",
        json={"modelId": "local-dry-run"},
    )
    codex_response = client.post(
        "/api/models/codex-cli/validate",
        json={"modelId": "codex-cli"},
    )

    assert local_response.status_code == 200
    local_data = local_response.json()
    assert local_data["modelId"] == "local-dry-run"
    assert local_data["status"] == "待验证"
    assert local_data["coverage"] == 0
    assert local_data["checks"]
    assert local_data["warnings"]
    assert "recommendedNextAction" in local_data

    assert codex_response.status_code == 200
    codex_data = codex_response.json()
    assert codex_data["modelId"] == "codex-cli"
    assert codex_data["status"] in {"可使用", "待验证"}
    assert "checks" in codex_data
    assert "warnings" in codex_data


def test_workbench_validate_project_model_checks_command_and_paths(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    writer = WritingModelService()
    ProjectService().write_text(project.root, "models/adapters/valid/weights.bin", "ok")
    writer.register_profile(
        project.root,
        "valid-model",
        label="可用模型",
        base_model="base",
        adapter_path="models/adapters/valid",
        command_template="python3 -c \"print('ok')\"",
        set_default=True,
    )
    writer.register_profile(
        project.root,
        "broken-model",
        label="不可用模型",
        base_model="",
        adapter_path="models/adapters/missing",
        command_template="missing-command --prompt {prompt_file} --output {output_file}",
        set_default=False,
    )

    valid_response = client.post(
        "/api/models/valid-model/validate",
        json={"modelId": "valid-model"},
    )
    broken_response = client.post(
        "/api/models/broken-model/validate",
        json={"modelId": "broken-model"},
    )

    assert valid_response.status_code == 200
    valid_data = valid_response.json()
    assert valid_data["status"] == "可使用"
    assert any("命令入口可解析" in item for item in valid_data["checks"])
    assert any("已找到 adapter 路径" in item for item in valid_data["checks"])
    assert valid_data["warnings"] == []

    assert broken_response.status_code == 200
    broken_data = broken_response.json()
    assert broken_data["status"] == "待验证"
    assert broken_data["coverage"] < valid_data["coverage"]
    assert any("adapter path 当前不存在" in item for item in broken_data["warnings"])
    assert any("执行入口不存在" in item for item in broken_data["warnings"])


def test_workbench_model_training_readiness_returns_author_summary(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    response = client.post("/api/models/training/readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ready", "warn", "block"}
    assert "eligibleCount" in data
    assert data["checks"]
    assert data["maturity"]
    assert isinstance(data["items"], list)
    if data["items"]:
        assert "actionSuggestion" in data["items"][0]
    assert "recommendedNextAction" in data


def test_workbench_calibration_annotates_analyzes_and_applies_thresholds(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)

    annotate = client.post(
        "/api/calibration/annotate",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "label": "acceptable",
            "note": "边界样本",
        },
    )
    assert annotate.status_code == 200
    assert annotate.json()["annotation"]["label"] == "acceptable"

    analysis = client.get(
        "/api/calibration/analysis",
        params={"bookId": project.root.as_posix()},
    )
    assert analysis.status_code == 200
    analysis_data = analysis.json()
    assert analysis_data["sampleCount"] == 1
    assert analysis_data["currentThresholds"]["min_chars_blocker"] == 360
    assert analysis_data["scoreDistribution"]
    assert "suggestedThresholds" in analysis_data
    assert analysis_data["thresholdEligible"] is False
    assert "至少需要 10 个" in analysis_data["thresholdBlockers"][0]

    repair = client.post(
        "/api/calibration/annotate",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "label": "repair",
            "note": "需要修复但不阻断",
        },
    )
    assert repair.status_code == 200
    assert repair.json()["annotation"]["label"] == "repair"

    blocked_apply = client.post(
        "/api/calibration/apply",
        json={"bookId": project.root.as_posix(), "min_chars_blocker": 120},
    )
    assert blocked_apply.status_code == 409
    assert "至少需要 10 个" in blocked_apply.json()["detail"]

    eligible_rows = [
        {"chapterId": f"{index:03d}", "label": label, "score": score, "metrics": {}}
        for index, (label, score) in enumerate(
            [
                ("acceptable", 90),
                ("acceptable", 88),
                ("acceptable", 86),
                ("acceptable", 84),
                ("repair", 55),
                ("repair", 50),
                ("repair", 45),
                ("block", 20),
                ("block", 15),
                ("block", 10),
            ],
            start=1,
        )
    ]
    monkeypatch.setattr(
        WorkbenchCalibrationService,
        "_annotated_quality_rows",
        lambda self, root, thresholds: eligible_rows,
    )

    apply = client.post(
        "/api/calibration/apply",
        json={
            "bookId": project.root.as_posix(),
            "min_chars_blocker": 120,
            "min_chars_medium": 180,
            "max_chars_medium": 9000,
            "similarity_blocker": 0.86,
            "similarity_high": 0.72,
            "choice_marker_min": 1,
            "conflict_marker_min": 1,
            "emotion_marker_min": 1,
            "exposition_marker_max": 4,
            "min_recommended_examples": 10,
            "regression_gate_tolerance": 3,
        },
    )
    assert apply.status_code == 200
    applied_data = apply.json()
    assert applied_data["currentThresholds"]["min_chars_blocker"] == 120
    assert "affectedChapterCount" in applied_data
    metadata = json.loads((project.root / "novel.json").read_text(encoding="utf-8"))
    assert metadata["qualityThresholds"]["min_chars_blocker"] == 120
    assert metadata["qualityThresholds"]["regression_gate_tolerance"] == 3

    history = client.get(
        "/api/calibration/history",
        params={"bookId": project.root.as_posix()},
    )
    assert history.status_code == 200
    assert history.json()["items"]

    revert = client.post(
        "/api/calibration/revert",
        json={
            "bookId": project.root.as_posix(),
            "appliedAt": history.json()["items"][0]["appliedAt"],
        },
    )
    assert revert.status_code == 200
    reverted_metadata = json.loads((project.root / "novel.json").read_text(encoding="utf-8"))
    assert reverted_metadata["qualityThresholds"].get("min_chars_blocker", 360) == 360


def test_workbench_calibration_rescore_all_updates_repository(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    repository = WorkbenchRepository()
    repository.upsert_chapter(
        project.root,
        {
            "id": "001",
            "title": "第一章",
            "status": "完成",
            "wordCount": 0,
            "progress": 100,
            "summary": "",
            "content": (project.root / "chapters" / "001.md").read_text(encoding="utf-8"),
        },
    )

    response = client.post(
        "/api/calibration/rescore-all",
        json={"bookId": project.root.as_posix()},
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    JobController().wait_for_job(job_id, timeout=5)

    job = JobController().get_job(project.root, job_id)
    assert job.status == "completed"
    assert int(job.result["rescoredCount"]) == 1
    chapter = repository.list_chapters(project.root)[0]
    assert chapter["qualityScore"] >= 0
    assert chapter["gateStatus"] in {"pass", "warn", "block"}


def test_model_training_readiness_returns_all_preview_items(tmp_path) -> None:
    root = ProjectService().create_project(tmp_path / "demo", title="Demo").root
    items = [
        TrainingReadinessItem(
            chapterId=f"{index:03d}",
            eligible=True,
            qualityScore=88,
            gateStatus="pass",
            gateScore=100,
        )
        for index in range(1, 10)
    ]

    class ExportServiceStub:
        def training_readiness(self, _root):
            return TrainingReadinessReport(
                status="warn",
                eligibleCount=len(items),
                skippedCount=0,
                minRecommendedExamples=10,
                items=items,
                recommendedNextAction="继续积累样本。",
            )

    class PresenterStub:
        export_service = ExportServiceStub()

        def _target_root(self, _book_id):
            return root

    response = WorkbenchTrainingService(PresenterStub()).model_training_readiness(root.as_posix())

    assert len(response["items"]) == 9


def test_workbench_quality_distribution_and_training_preview(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)

    distribution = client.get(
        "/api/models/quality-distribution",
        params={"bookId": project.root.as_posix()},
    )
    assert distribution.status_code == 200
    distribution_data = distribution.json()
    assert distribution_data["bookId"] == project.root.as_posix()
    assert distribution_data["items"]
    assert {"chapterId", "score", "similarity", "gateStatus", "eligible", "label"} <= set(
        distribution_data["items"][0]
    )

    readiness = client.get(
        "/api/export/training-readiness",
        params={"bookId": project.root.as_posix()},
    )
    assert readiness.status_code == 200
    readiness_data = readiness.json()
    assert readiness_data["kind"] == "训练数据"
    assert "trainingPreview" in readiness_data
    assert readiness_data["trainingPreview"]["items"]

    selected = client.post(
        f"/api/books/{quote(project.root.as_posix(), safe='')}/exports",
        json={
            "bookId": project.root.as_posix(),
            "kind": "训练数据",
            "range": "全书",
            "trainingChapterIds": ["001"],
        },
    )
    assert selected.status_code == 200
    records = [
        json.loads(line)
        for line in (project.root / "exports" / "writing-training.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert {record["metadata"]["chapterId"] for record in records} == {"001"}


def test_workbench_model_training_run_queues_local_training_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    root = create_training_ready_project(tmp_path / "demo")
    WorkspaceRegistryService().register_project(root)
    client = TestClient(app)
    monkeypatch.setenv(
        "OPEN_NOVEL_TRAIN_COMMAND",
        (
            f'{sys.executable} -c "from pathlib import Path; '
            "Path('{output_dir}').mkdir(parents=True, exist_ok=True)\""
        ),
    )

    response = client.post(
        "/api/models/training/run",
        json={
            "backend": "custom",
            "modelProfileId": "latest-trained",
            "outputDir": "models/adapters/latest",
            "minExamples": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["job"]["title"] == "本地模型训练"
    assert data["job"]["status"] in {"等待中", "运行中"}
    assert data["training"]["modelProfileId"] == "latest-trained"
    assert "summary" in data
    jobs = client.get(f"/api/books/{quote(root.as_posix(), safe='')}/jobs").json()
    assert any(job["title"] == "本地模型训练" for job in jobs["jobs"])


def test_workbench_model_training_run_blocks_when_below_required_examples(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    root = create_training_ready_project(tmp_path / "demo")
    WorkspaceRegistryService().register_project(root)
    client = TestClient(app)
    monkeypatch.setenv(
        "OPEN_NOVEL_TRAIN_COMMAND",
        (
            f'{sys.executable} -c "from pathlib import Path; '
            "Path('{output_dir}').mkdir(parents=True, exist_ok=True)\""
        ),
    )

    response = client.post(
        "/api/models/training/run",
        json={
            "backend": "custom",
            "modelProfileId": "latest-trained",
            "outputDir": "models/adapters/latest",
            "minExamples": 20,
        },
    )

    assert response.status_code == 400
    assert "训练样本不足" in response.json()["detail"]


def test_workbench_model_training_run_blocks_without_examples(tmp_path, monkeypatch) -> None:
    client, _project = _client_with_project(tmp_path, monkeypatch)

    response = client.post(
        "/api/models/training/run",
        json={
            "backend": "custom",
            "modelProfileId": "latest-trained",
        },
    )

    assert response.status_code == 400
    assert "训练样本不足" in response.json()["detail"]


def test_workbench_model_compare_returns_author_summary(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_post_review_ready_story(project.root)
    writer = WritingModelService()
    python_exec = sys.executable
    writer.register_profile(
        project.root,
        "base-model",
        label="基础模型",
        base_model="base",
        adapter_path="models/adapters/base",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text('# base\\n\\n主角通过测试，但仍被盯上。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于当前书稳定续写。",
        set_default=True,
    )
    writer.register_profile(
        project.root,
        "tuned-model",
        label="增强模型",
        base_model="base",
        adapter_path="models/adapters/tuned",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text("
            "'# tuned\\n\\n主角通过测试，旧敌也开始忌惮他的异常。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于增强角色压迫感。",
        set_default=False,
    )

    response = client.post(
        "/api/models/compare",
        json={
            "baseProfileId": "base-model",
            "tunedProfileId": "tuned-model",
            "includeReferenceAgent": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["baseProfileId"] == "base-model"
    assert data["baseProfileLabel"] == "基础模型"
    assert data["tunedProfileId"] == "tuned-model"
    assert data["tunedProfileLabel"] == "增强模型"
    assert data["comparisonId"]
    assert isinstance(data["regressionPassed"], bool)
    assert "averageGate" in data["scoreSummary"]["base"]
    assert "averageGate" in data["scoreSummary"]["tuned"]
    assert data["chapterCount"] == 5
    assert data["promotionDecision"]
    assert isinstance(data["promotionReasons"], list)
    assert "recommendedNextAction" in data
    assert len(data["candidates"]) >= 2
    assert {item["id"] for item in data["candidates"]} >= {"base-model", "tuned-model"}
    assert all("qualityScore" in item for item in data["candidates"])


def test_workbench_writing_models_list_create_and_set_default(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    create_response = client.post(
        "/api/models/writing",
        json={
            "bookId": project.root.as_posix(),
            "profileId": "suspense-v2",
            "label": "悬疑二代",
            "baseModel": "local-base",
            "adapterPath": "models/adapters/suspense-v2",
            "commandTemplate": "python writer.py --profile suspense-v2",
            "setDefault": True,
            "notes": "强调压迫感与动作线索。",
        },
    )

    assert create_response.status_code == 200
    create_data = create_response.json()
    assert create_data["profile"]["id"] == "suspense-v2"
    assert create_data["defaultProfileId"] == "suspense-v2"

    list_response = client.get("/api/models/writing", params={"bookId": project.root.as_posix()})
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert list_data["bookId"] == project.root.as_posix()
    assert list_data["defaultProfileId"] == "suspense-v2"
    assert any(profile["label"] == "悬疑二代" for profile in list_data["profiles"])

    client.post(
        "/api/models/writing",
        json={
            "bookId": project.root.as_posix(),
            "profileId": "dialogue-v1",
            "label": "对白强化",
            "baseModel": "local-base",
            "adapterPath": "models/adapters/dialogue-v1",
            "commandTemplate": "python writer.py --profile dialogue-v1",
        },
    )
    default_response = client.patch(
        "/api/models/writing/default",
        json={"bookId": project.root.as_posix(), "profileId": "dialogue-v1"},
    )

    assert default_response.status_code == 200
    assert default_response.json()["defaultProfileId"] == "dialogue-v1"
    refreshed = client.get("/api/models/writing", params={"bookId": project.root.as_posix()}).json()
    assert refreshed["defaultProfileId"] == "dialogue-v1"
    default_profile = next(
        profile for profile in refreshed["profiles"] if profile["id"] == "dialogue-v1"
    )
    assert default_profile["isDefault"] is True


def test_workbench_blocks_trained_model_default_without_comparison(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    WritingModelService().register_profile(
        project.root,
        profile_id="trained-v1",
        base_model="local-base",
        adapter_path="models/adapters/trained-v1",
        command_template="python writer.py --profile trained-v1",
        training_run_path="runs/local-tuning-run.json",
        set_default=False,
    )

    response = client.patch(
        "/api/models/writing/default",
        json={"bookId": project.root.as_posix(), "profileId": "trained-v1"},
    )

    assert response.status_code == 400
    assert "多章节模型对比" in response.json()["detail"]
    apply_response = client.put(
        f"/api/books/{quote(project.root.as_posix(), safe='')}/model",
        json={"bookId": project.root.as_posix(), "modelId": "trained-v1"},
    )
    workspace = client.get("/api/workspace").json()
    trained_model = next(model for model in workspace["models"] if model["id"] == "trained-v1")

    assert apply_response.status_code == 400
    assert "多章节模型对比" in apply_response.json()["detail"]
    assert trained_model["status"] == "待验证"
    assert {action["key"] for action in trained_model["actions"]} == {"validate"}
    assert "五章模型对比" in trained_model["recommendedNextAction"]


def test_workbench_style_profiles_list_and_apply_for_current_book(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    listing = client.get("/api/models/style-profiles", params={"bookId": project.root.as_posix()})
    apply = client.post(
        "/api/models/style-profiles/apply",
        json={
            "bookId": project.root.as_posix(),
            "profileId": "urban-emotion-suspense",
        },
    )

    assert listing.status_code == 200
    listing_data = listing.json()
    assert listing_data["bookId"] == project.root.as_posix()
    assert "profiles" in listing_data
    assert "plannedSlots" in listing_data
    assert "coverageCatalog" in listing_data
    assert "templatePacks" in listing_data
    assert "creationOptions" in listing_data
    assert any(profile["id"] == "urban-emotion-suspense" for profile in listing_data["profiles"])
    assert any(slot["id"] == "qidian-sci-fi-tech" for slot in listing_data["plannedSlots"])

    assert apply.status_code == 200
    apply_data = apply.json()
    assert apply_data["bookId"] == project.root.as_posix()
    assert apply_data["profileId"] == "urban-emotion-suspense"
    assert apply_data["styleProfileId"] == "urban-emotion-suspense"
    assert "summary" in apply_data

    workspace = client.get("/api/workspace").json()
    assert workspace["books"][0]["styleProfileId"] == "urban-emotion-suspense"
    assert workspace["books"][0]["styleProfileLabel"] == "都市情绪悬疑"


def test_workbench_library_relationships_topic_and_timeline_facades(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "characters": [
                    {"characterId": "lin-che", "name": "作者命名主角", "states": []},
                    {"characterId": "old-rival", "name": "作者命名对手", "states": []},
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    ProjectService().write_text(
        project.root,
        "memory/relationship-states.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "relationships": [
                    {
                        "id": "rel_linche_rival",
                        "fromCharacterId": "lin-che",
                        "toCharacterId": "old-rival",
                        "type": "rivalry",
                        "status": "旧敌从轻蔑转为忌惮。",
                        "pressure": "测试石异象打破旧认知。",
                        "unresolvedEmotion": "旧敌不愿承认林澈已经构成威胁。",
                        "quantifiedScore": 2.0,
                        "chapterId": "001",
                        "source": "chapters/001.md",
                        "evidence": ["旧敌的笑僵在嘴边"],
                    },
                    {
                        "id": "rel_linche_rival_002",
                        "fromCharacterId": "lin-che",
                        "toCharacterId": "old-rival",
                        "type": "rivalry",
                        "status": "旧敌突然变成亲密战友。",
                        "pressure": "并肩行动。",
                        "unresolvedEmotion": "信任。",
                        "quantifiedScore": 8.0,
                        "chapterId": "002",
                        "source": "chapters/002.md",
                        "evidence": ["旧敌忽然护住林澈"],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n- chapter 2: 主角抵达旧都\n",
    )

    relationships = client.get(f"/api/books/{encoded_book_id}/library/relationships")
    assert relationships.status_code == 200
    relationships_data = relationships.json()
    assert relationships_data["edgeCount"] == 1
    assert relationships_data["edges"][0]["fromLabel"] == "作者命名主角"

    edge_detail = client.get(
        f"/api/books/{encoded_book_id}/library/relationships/lin-che__old-rival__rivalry"
    )
    assert edge_detail.status_code == 200
    assert edge_detail.json()["edge"]["toLabel"] == "作者命名对手"
    assert edge_detail.json()["timeline"][0]["status"]
    assert edge_detail.json()["timeline"][1]["needsReview"] is True
    assert edge_detail.json()["timeline"][1]["scoreDelta"] == 6.0
    latest_event_id = edge_detail.json()["timeline"][1]["eventId"]

    updated_relationship = client.post(
        f"/api/books/{encoded_book_id}/library/relationship-events/{latest_event_id}",
        json={
            "bookId": project.root.as_posix(),
            "type": "亦敌亦友",
            "status": "双方暂时合作，但仍互相提防。",
            "pressure": "共同目标压过旧有敌意。",
            "unresolvedEmotion": "都不愿先承认信任。",
            "evidence": ["旧敌忽然护住林澈"],
        },
    )
    assert updated_relationship.status_code == 200
    assert updated_relationship.json()["edge"]["type"] == "亦敌亦友"
    assert updated_relationship.json()["edge"]["status"] == "双方暂时合作，但仍互相提防。"
    refreshed_relationships = client.get(
        f"/api/books/{encoded_book_id}/library/relationships"
    ).json()
    assert refreshed_relationships["edges"][0]["type"] == "亦敌亦友"

    topic = client.get(
        f"/api/books/{encoded_book_id}/library/topics/topic-lin",
        params={"chapterId": "001"},
    )
    assert topic.status_code == 200
    topic_data = topic.json()
    assert topic_data["topicId"] == "topic-lin"
    assert "relatedEntities" in topic_data
    assert "contextStatus" in topic_data

    sync_response = client.post(f"/api/books/{encoded_book_id}/library/timeline/sync")
    assert sync_response.status_code == 200
    assert sync_response.json()["eventCount"] == 1

    timeline = client.get(f"/api/books/{encoded_book_id}/library/timeline")
    assert timeline.status_code == 200
    assert timeline.json()["events"][0]["chapterId"] == "002"


def test_workbench_editorial_models_list_create_and_set_default(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    create_response = client.post(
        "/api/models/editorial",
        json={
            "bookId": project.root.as_posix(),
            "profileId": "suspense-editor",
            "backend": "local",
            "label": "悬疑审稿",
            "reviewer": "local-editor-v2",
            "promptPreset": "continuity-editor",
            "styleProfilePath": "story/style-profile.json",
            "rubric": ["检查线索公平", "检查关系状态"],
            "setDefault": True,
            "notes": "偏重线索公平和长线连续性。",
        },
    )

    assert create_response.status_code == 200
    create_data = create_response.json()
    assert create_data["profile"]["id"] == "suspense-editor"
    assert create_data["defaultProfileId"] == "suspense-editor"

    list_response = client.get("/api/models/editorial", params={"bookId": project.root.as_posix()})
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert list_data["bookId"] == project.root.as_posix()
    assert list_data["defaultProfileId"] == "suspense-editor"
    assert any(profile["label"] == "悬疑审稿" for profile in list_data["profiles"])
    assert any(preset["id"] == "continuity-editor" for preset in list_data["promptPresets"])

    second_response = client.post(
        "/api/models/editorial",
        json={
            "bookId": project.root.as_posix(),
            "profileId": "emotion-editor",
            "backend": "local",
            "label": "情绪线审稿",
            "promptPreset": "emotion-line-editor",
        },
    )
    assert second_response.status_code == 200

    default_response = client.patch(
        "/api/models/editorial/default",
        json={"bookId": project.root.as_posix(), "profileId": "emotion-editor"},
    )
    assert default_response.status_code == 200
    assert default_response.json()["defaultProfileId"] == "emotion-editor"


def test_workbench_promote_model_compare_sets_default_profile(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_post_review_ready_story(project.root)
    writer = WritingModelService()
    python_exec = sys.executable
    writer.register_profile(
        project.root,
        "base-model",
        label="基础模型",
        base_model="base",
        adapter_path="models/adapters/base",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text('# base\\n\\n主角通过测试，但仍被盯上。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于当前书稳定续写。",
        set_default=True,
    )
    writer.register_profile(
        project.root,
        "tuned-model",
        label="增强模型",
        base_model="base",
        adapter_path="models/adapters/tuned",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text("
            "'# tuned\\n\\n主角通过测试，旧敌也开始忌惮他的异常。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于增强角色压迫感。",
        set_default=False,
    )

    compare_response = client.post(
        "/api/models/compare",
        json={
            "bookId": project.root.as_posix(),
            "baseProfileId": "base-model",
            "tunedProfileId": "tuned-model",
            "includeReferenceAgent": False,
        },
    )
    assert compare_response.status_code == 200
    report_path = f"runs/model-comparisons/{compare_response.json()['comparisonId']}.json"

    raw = ProjectService().read_text(project.root, report_path)
    report_data = compare_response.json()
    if report_data["bestCandidateId"] != "tuned-model" or not report_data["safeToSetDefault"]:
        report_json = json.loads(raw)
        summary = report_json["summary"]
        summary["bestCandidateId"] = "tuned-model"
        summary["bestCandidateLabel"] = "增强模型"
        summary["bestStatus"] = "pass"
        summary["promotionDecision"] = "promote-tuned-profile"
        summary["promotionReasons"] = ["measured-improvement-over-base"]
        summary["safeToSetDefault"] = True
        report_json["tunedProfileId"] = "tuned-model"
        ProjectService().write_text(
            project.root,
            report_path,
            json.dumps(report_json, ensure_ascii=False, indent=2) + "\n",
        )

    promote_response = client.post(
        "/api/models/compare/promote",
        json={
            "bookId": project.root.as_posix(),
            "comparisonReportPath": report_path,
        },
    )

    assert promote_response.status_code == 200
    assert promote_response.json()["defaultProfileId"] == "tuned-model"
    refreshed = client.get("/api/models/writing", params={"bookId": project.root.as_posix()}).json()
    assert refreshed["defaultProfileId"] == "tuned-model"


def test_workbench_material_mutations_persist_to_project(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    create = client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "faction-archive",
            "bookId": project.root.as_posix(),
            "type": "势力",
            "title": "档案修正会",
            "summary": "删除异常声音相关证据的组织。",
            "influence": "给下一章制造外部阻力。",
            "related": ["门禁记录"],
            "confidence": 70,
            "details": {"目标": "抹掉证据", "资源": "城市档案", "弱点": "必须接触原始媒介"},
        },
    )

    assert create.status_code == 200
    assert create.json()["material"]["title"] == "档案修正会"

    update = client.put(
        f"/api/books/{encoded_book_id}/materials/faction-archive",
        json={
            "id": "faction-archive",
            "bookId": project.root.as_posix(),
            "type": "势力",
            "title": "档案修正会",
            "summary": "删除异常声音相关证据的隐秘组织。",
            "influence": "迫使主角从调查转为被追踪。",
            "related": ["门禁记录"],
            "confidence": 82,
            "details": {"目标": "抹掉证据", "资源": "城市档案", "弱点": "必须接触原始媒介"},
        },
    )
    workspace = client.get("/api/workspace").json()

    assert update.status_code == 200
    stored = next(
        material for material in workspace["materials"] if material["id"] == "faction-archive"
    )
    assert stored["confidence"] == 82
    assert stored["influence"] == "迫使主角从调查转为被追踪。"


def test_workbench_material_create_generates_id_when_missing(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "",
            "bookId": "frontend-temporary-book",
            "type": "地点",
            "title": "地下录音棚",
            "summary": "墙体潮湿、回声异常的封闭空间。",
            "influence": "给当前章节制造空间压力和声音误导。",
            "related": ["当前章节", "林澈"],
            "confidence": 84,
        },
    )
    workspace = client.get("/api/workspace").json()

    assert response.status_code == 200
    material = response.json()["material"]
    assert material["bookId"] == project.root.as_posix()
    assert material["id"].startswith("material-")
    assert material["id"] in {item["id"] for item in workspace["materials"]}


def test_workbench_materials_read_from_sqlite_when_file_missing(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "sqlite-material",
            "bookId": project.root.as_posix(),
            "type": "人物",
            "title": "林澈",
            "summary": "用声音判断风险的人。",
            "influence": "影响章节判断和审稿风险。",
            "related": ["001"],
            "confidence": 88,
        },
    )
    (project.root / "memory" / "workbench-materials.json").unlink()

    workspace = client.get("/api/workspace").json()
    material_ids = {item["id"] for item in workspace["materials"]}
    coverage = WorkbenchRepository().coverage_counts(project.root)

    assert response.status_code == 200
    assert "sqlite-material" in material_ids
    assert coverage["materials"] == 1


def test_workbench_material_delete_cleans_material_store_and_chapter_links(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "studio-basement",
            "bookId": project.root.as_posix(),
            "type": "地点",
            "title": "地下录音棚",
            "summary": "墙体潮湿、回声异常的封闭空间。",
            "influence": "给当前章节制造空间压力和声音误导。",
            "related": ["当前章节", "林澈"],
            "confidence": 84,
        },
    )
    client.post(
        f"/api/books/{encoded_book_id}/chapters/001/materials/link",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "materialIds": ["studio-basement"],
            "mode": "replace",
        },
    )

    response = client.delete(f"/api/books/{encoded_book_id}/materials/studio-basement")

    assert response.status_code == 200
    data = response.json()
    assert data["removed"] is True
    assert data["materialId"] == "studio-basement"
    assert data["affectedChapters"][0]["id"] == "001"
    assert "studio-basement" not in data["affectedChapters"][0]["linkedMaterialIds"]

    workspace = client.get("/api/workspace").json()
    assert all(item["id"] != "studio-basement" for item in workspace["materials"])
    assert "studio-basement" not in workspace["books"][0]["chapters"][0]["linkedMaterialIds"]


def test_workbench_chapter_and_review_mutations_return_updated_chapter(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    draft = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/draft",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "nextContent": "AI 候选正文。",
        },
    )
    repair = client.post(
        f"/api/books/{encoded_book_id}/reviews/review-001/repair",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "reviewId": "review-001",
            "repairText": "补一处主角误判。",
        },
    )
    accept = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/accept",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "force": True,
        },
    )

    assert draft.status_code == 200
    draft_chapter = draft.json()["chapter"]
    assert draft_chapter["id"] == "001"
    assert draft_chapter["status"] == "草稿"
    assert draft_chapter["content"] == "AI 候选正文。"

    assert repair.status_code == 200
    repair_chapter = repair.json()["chapter"]
    assert repair.json()["reviewId"] == "review-001"
    assert repair_chapter["id"] == "001"
    assert repair_chapter["status"] == "草稿"
    assert "补一处主角误判。" in repair_chapter["content"]

    assert accept.status_code == 200
    accept_chapter = accept.json()["chapter"]
    assert accept_chapter["id"] == "001"
    assert accept_chapter["status"] == "完成"
    assert accept_chapter["progress"] == 100
    assert accept.json()["gate"]["status"] in {"pass", "warn", "block"}
    assert "recommendedNextAction" in accept.json()["gate"]
    assert all("textSnippet" in issue for issue in accept.json()["gate"]["issues"])
    assert all("suggestionHint" in issue for issue in accept.json()["gate"]["issues"])
    assert "patchPath" in accept.json()

    chapter_text = (project.root / "chapters" / "001.md").read_text(encoding="utf-8")
    assert "AI 候选正文。" in chapter_text
    assert "补一处主角误判。" in chapter_text
    workspace = client.get("/api/workspace").json()
    assert workspace["books"][0]["chapters"][0]["status"] == "完成"


def test_workbench_accept_blocks_on_gate_without_force(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    blocked = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/accept",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["gate"]["status"] == "block"
    assert all("textSnippet" in issue for issue in blocked.json()["detail"]["gate"]["issues"])
    assert all("suggestionHint" in issue for issue in blocked.json()["detail"]["gate"]["issues"])
    assert "message" in blocked.json()["detail"]
    assert blocked.json()["detail"]["recovery"]["blocked"] is True
    assert blocked.json()["detail"]["recovery"]["steps"]
    assert blocked.json()["detail"]["recovery"]["recommendedNextAction"]
    workspace_after_block = client.get("/api/workspace").json()
    assert workspace_after_block["books"][0]["chapters"][0]["status"] == "审阅"

    forced = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/accept",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "force": True,
        },
    )

    assert forced.status_code == 200
    assert forced.json()["chapter"]["status"] == "完成"


def test_workbench_gate_and_review_run_mark_chapter_under_review(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    draft = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/draft",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "nextContent": "一版待审阅正文。",
        },
    )
    assert draft.status_code == 200
    assert draft.json()["chapter"]["status"] == "草稿"

    gate = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/gate",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    assert gate.status_code == 200
    assert gate.json()["gate"]["status"] in {"pass", "warn", "block"}
    workspace_after_gate = client.get("/api/workspace").json()
    assert workspace_after_gate["books"][0]["chapters"][0]["status"] == "审阅"

    reviews = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    assert reviews.status_code == 200
    workspace_after_reviews = client.get("/api/workspace").json()
    assert workspace_after_reviews["books"][0]["chapters"][0]["status"] == "审阅"


def test_workbench_chapter_planning_persists_to_brief(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.put(
        f"/api/books/{encoded_book_id}/chapters/001/planning",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "tasks": ["确认异声来源", "让主角主动做错一次判断"],
            "plotPoints": ["墙后呼吸声反向误导主角", "旧录音带出现第二个时间戳"],
        },
    )

    assert response.status_code == 200
    chapter = response.json()["chapter"]
    assert chapter["tasks"] == ["确认异声来源", "让主角主动做错一次判断"]
    assert chapter["plotPoints"] == ["墙后呼吸声反向误导主角", "旧录音带出现第二个时间戳"]

    brief = (project.root / "story" / "chapter-briefs" / "001.json").read_text(encoding="utf-8")
    assert "workbenchTasks" in brief
    assert "旧录音带出现第二个时间戳" in brief

    workspace = client.get("/api/workspace").json()
    stored_chapter = workspace["books"][0]["chapters"][0]
    assert stored_chapter["tasks"] == ["确认异声来源", "让主角主动做错一次判断"]
    assert stored_chapter["plotPoints"] == ["墙后呼吸声反向误导主角", "旧录音带出现第二个时间戳"]


def test_workbench_link_chapter_materials_persists_to_brief(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "studio-basement",
            "bookId": project.root.as_posix(),
            "type": "地点",
            "title": "地下录音棚",
            "summary": "墙体潮湿、回声异常的封闭空间。",
            "influence": "给当前章节制造空间压力和声音误导。",
            "related": ["当前章节", "林澈"],
            "confidence": 84,
        },
    )
    client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "archive-group",
            "bookId": project.root.as_posix(),
            "type": "势力",
            "title": "档案修正会",
            "summary": "会清理异常声音证据的组织。",
            "influence": "让主角面对被提前处理过的现场。",
            "related": ["当前章节", "门禁记录"],
            "confidence": 80,
        },
    )

    response = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/materials/link",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "materialIds": ["studio-basement", "archive-group"],
            "mode": "replace",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "已更新本章资料提示。"
    assert {item["id"] for item in data["linkedMaterials"]} == {"studio-basement", "archive-group"}
    assert data["chapter"]["linkedMaterialIds"] == ["studio-basement", "archive-group"]
    assert "地下录音棚" in data["chapter"]["plotPoints"]
    brief = (project.root / "story" / "chapter-briefs" / "001.json").read_text(encoding="utf-8")
    assert '"linkedMaterials"' in brief
    assert '"location": "地下录音棚"' in brief
    workspace = client.get("/api/workspace").json()
    stored_chapter = workspace["books"][0]["chapters"][0]
    assert stored_chapter["linkedMaterialIds"] == ["studio-basement", "archive-group"]


def test_workbench_chapter_materials_returns_related_ranked_results(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "studio-basement",
            "bookId": project.root.as_posix(),
            "type": "地点",
            "title": "地下录音棚",
            "summary": "墙体潮湿、回声异常的封闭空间。",
            "influence": "给当前章节制造空间压力和声音误导。",
            "related": ["当前章节", "林澈"],
            "confidence": 84,
        },
    )
    client.post(
        f"/api/books/{encoded_book_id}/materials",
        json={
            "id": "unused-dock",
            "bookId": project.root.as_posix(),
            "type": "地点",
            "title": "旧泊位",
            "summary": "与当前章节无关的远端地点。",
            "influence": "只影响后续章节。",
            "related": ["失踪舰队"],
            "confidence": 70,
        },
    )
    client.post(
        f"/api/books/{encoded_book_id}/chapters/001/materials/link",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "materialIds": ["studio-basement"],
            "mode": "replace",
        },
    )

    related_response = client.get(
        f"/api/books/{encoded_book_id}/chapters/001/materials",
        params={"type": "地点", "scope": "related"},
    )
    all_response = client.get(
        f"/api/books/{encoded_book_id}/chapters/001/materials",
        params={"type": "地点", "scope": "all"},
    )

    assert related_response.status_code == 200
    related_data = related_response.json()
    assert related_data["scope"] == "related"
    assert related_data["materials"]
    assert related_data["materials"][0]["id"] == "studio-basement"
    assert all(item["id"] != "unused-dock" for item in related_data["materials"])

    assert all_response.status_code == 200
    all_data = all_response.json()
    assert {item["id"] for item in all_data["materials"]} >= {"studio-basement", "unused-dock"}


def test_workbench_prepare_and_gate_return_author_facing_reports(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    prepare = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/prepare",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    gate = client.post(
        f"/api/books/{encoded_book_id}/chapters/001/gate",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert prepare.status_code == 200
    prepare_data = prepare.json()
    assert prepare_data["bookId"] == project.root.as_posix()
    assert prepare_data["chapterId"] == "001"
    assert prepare_data["readiness"]["status"] == "block"
    assert prepare_data["readiness"]["issues"]
    assert "display" in prepare_data
    assert prepare_data["contextPack"]["status"] == "skipped"
    assert "tokenBudget" in prepare_data["contextPack"]
    assert "items" in prepare_data["contextPack"]

    assert gate.status_code == 200
    gate_data = gate.json()
    assert gate_data["bookId"] == project.root.as_posix()
    assert gate_data["chapterId"] == "001"
    assert gate_data["gate"]["status"] in {"block", "warn", "pass"}
    assert gate_data["gate"]["issues"]
    assert "display" in gate_data
    assert all("message" in issue for issue in gate_data["gate"]["issues"])
    assert all("textSnippet" in issue for issue in gate_data["gate"]["issues"])
    assert all("suggestionHint" in issue for issue in gate_data["gate"]["issues"])


def test_workbench_writing_panels_return_real_memory_and_contract_data(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    ProjectService().write_text(
        project.root,
        "memory/writing-lessons.json",
        json.dumps(
            {
                "lessons": [
                    {
                        "id": "lesson-001",
                        "category": "节奏",
                        "lesson": "阻断揭示前先补一拍感官压力。",
                        "severity": "medium",
                        "sourceChapters": ["001"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/character-states.json",
        json.dumps(
            {
                "characters": [
                    {
                        "characterId": "lin",
                        "name": "林澈",
                        "states": [
                            {
                                "chapterId": "001",
                                "emotionalState": "警惕",
                                "goal": "找到墙后呼吸声来源",
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "memory/relationship-states.json",
        json.dumps(
            {
                "relationships": [
                    {
                        "from": "lin",
                        "to": "noise",
                        "quantifiedScore": 72,
                        "status": "危险牵引",
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )

    lessons = client.get(f"/api/books/{encoded_book_id}/writing-lessons")
    characters = client.get(f"/api/books/{encoded_book_id}/chapters/001/characters/snapshot")
    contract = client.get(f"/api/books/{encoded_book_id}/chapters/001/contract")
    updated = client.put(
        f"/api/books/{encoded_book_id}/chapters/001/contract",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
            "fields": {
                "internalNeed": "确认自己不是幻听。",
                "stakes": "若判断错误，主角会暴露追查意图。",
            },
        },
    )

    assert lessons.status_code == 200
    assert lessons.json()["groups"][0]["category"] == "节奏"
    assert lessons.json()["groups"][0]["lessons"][0]["lesson"] == "阻断揭示前先补一拍感官压力。"
    assert characters.status_code == 200
    assert characters.json()["characters"][0]["emotion"] == "警惕"
    assert characters.json()["characters"][0]["relationshipScore"] == 72
    assert contract.status_code == 200
    assert contract.json()["contract"]["chapterId"] == "001"
    assert updated.status_code == 200
    assert updated.json()["contract"]["internalNeed"] == "确认自己不是幻听。"
    assert updated.json()["contract"]["stakes"] == "若判断错误，主角会暴露追查意图。"


def test_workbench_agent_assist_stream_returns_sse_tokens(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _configure_ai_account(client)

    async def fake_upstream(self, account, prompt):
        yield "token", {"text": "受控账号返回的候选。"}
        yield "usage", {
            "input_tokens": 8,
            "output_tokens": 4,
            "total_tokens": 12,
        }

    monkeypatch.setattr(AIRuntimeService, "_upstream_events", fake_upstream)

    with client.stream(
        "POST",
        "/api/agent/assist/stream",
        json={
            "bookId": project.root.as_posix(),
            "scope": "chapter",
            "action": "续写",
            "chapterId": "001",
            "input": "继续写主角追查异声。",
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: status" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "data:" in body


def test_workbench_gate_recovery_returns_author_steps(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.get(f"/api/books/{encoded_book_id}/chapters/001/gate/recovery")

    assert response.status_code == 200
    data = response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["chapterId"] == "001"
    assert "steps" in data
    assert "recommendedNextAction" in data


def test_workbench_run_reviews_returns_review_inbox(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["chapterId"] == "001"
    assert data["reviews"]
    assert all(review["bookId"] == project.root.as_posix() for review in data["reviews"])
    assert all(review["chapterId"] == "001" for review in data["reviews"])
    assert any("接收门禁" in review["title"] for review in data["reviews"])
    assert (project.root / "runs" / "chapter-gate-001.json").exists()
    inbox = client.get(f"/api/books/{encoded_book_id}/reviews")
    assert inbox.status_code == 200
    assert inbox.json()["chapterId"] == "001"
    assert inbox.json()["reviews"] == data["reviews"]


def test_workbench_book_reviews_fallback_to_workspace_review(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.get(f"/api/books/{encoded_book_id}/reviews")

    assert response.status_code == 200
    data = response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["reviews"]
    assert data["reviews"][0]["id"] == "review-001"
    assert data["chapterId"] == "001"


def test_workbench_review_status_patch_persists(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.patch(
        f"/api/books/{encoded_book_id}/reviews/review-001",
        json={
            "bookId": project.root.as_posix(),
            "reviewId": "review-001",
            "status": "已确认",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["review"]["id"] == "review-001"
    assert data["review"]["status"] == "已确认"
    workspace = client.get("/api/workspace").json()
    review = next(item for item in workspace["reviews"] if item["id"] == "review-001")
    assert review["status"] == "已确认"
    assert ProjectService().file_exists(
        project.root,
        "memory/workbench-review-states.json",
    )


def test_workbench_review_status_applies_to_rerun_reviews(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    review_id = run_response.json()["reviews"][0]["id"]

    patch_response = client.patch(
        f"/api/books/{encoded_book_id}/reviews/{quote(review_id, safe='')}",
        json={
            "bookId": project.root.as_posix(),
            "reviewId": review_id,
            "status": "处理中",
        },
    )
    rerun_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert patch_response.status_code == 200
    rerun_review = next(
        item for item in rerun_response.json()["reviews"] if item["id"] == review_id
    )
    assert rerun_review["status"] == "处理中"
    inbox_response = client.get(f"/api/books/{encoded_book_id}/reviews")
    inbox_review = next(
        item for item in inbox_response.json()["reviews"] if item["id"] == review_id
    )
    assert inbox_review["status"] == "处理中"


def test_workbench_review_inbox_and_states_read_from_sqlite_when_files_missing(
    tmp_path,
    monkeypatch,
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    review_id = run_response.json()["reviews"][0]["id"]
    patch_response = client.patch(
        f"/api/books/{encoded_book_id}/reviews/{quote(review_id, safe='')}",
        json={
            "bookId": project.root.as_posix(),
            "reviewId": review_id,
            "status": "处理中",
        },
    )
    (project.root / "memory" / "workbench-review-inbox.json").unlink()
    (project.root / "memory" / "workbench-review-states.json").unlink()

    inbox_response = client.get(f"/api/books/{encoded_book_id}/reviews")
    inbox_review = next(
        item for item in inbox_response.json()["reviews"] if item["id"] == review_id
    )
    coverage = WorkbenchRepository().coverage_counts(project.root)

    assert run_response.status_code == 200
    assert patch_response.status_code == 200
    assert inbox_review["status"] == "处理中"
    assert coverage["reviewInbox"] >= 1
    assert coverage["reviewStates"] >= 1


def test_workbench_workspace_uses_latest_review_inbox(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert run_response.status_code == 200
    workspace = client.get("/api/workspace")
    assert workspace.status_code == 200
    workspace_reviews = [
        item for item in workspace.json()["reviews"] if item["bookId"] == project.root.as_posix()
    ]
    assert workspace_reviews == run_response.json()["reviews"]


def test_workbench_book_workspace_uses_latest_review_inbox(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert run_response.status_code == 200
    workspace = client.get(f"/api/books/{encoded_book_id}/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["reviews"] == run_response.json()["reviews"]


def test_workbench_chapter_memory_updates_list_and_apply(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_post_review_ready_story(project.root)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    list_response = client.get(f"/api/books/{encoded_book_id}/chapters/001/memory-updates")

    assert list_response.status_code == 200
    data = list_response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["chapterId"] == "001"
    assert data["memoryUpdates"]
    summary_update = next(
        item for item in data["memoryUpdates"] if item["targetLabel"] == "章节摘要"
    )
    assert summary_update["status"] == "accepted"
    assert all(
        item["status"] == "proposed"
        for item in data["memoryUpdates"]
        if item["targetLabel"] != "章节摘要"
    )
    assert {item["targetLabel"] for item in data["memoryUpdates"]} >= {
        "章节摘要",
        "事实",
        "时间线",
        "人物状态",
        "伏笔与未解问题",
        "情绪轨迹",
    }

    apply_response = client.post(
        f"/api/books/{encoded_book_id}/memory-updates/{summary_update['id']}/apply",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["bookId"] == project.root.as_posix()
    assert applied["chapterId"] == "001"
    assert applied["memoryUpdate"]["id"] == summary_update["id"]
    assert applied["memoryUpdate"]["status"] == "applied"
    assert applied["memoryUpdate"]["statusLabel"] == "已应用"
    assert applied["memoryUpdate"]["title"] in applied["summary"]
    (project.root / "reviews" / "001.review.json").unlink()
    (project.root / "patches" / "001.canon-patch.json").unlink()
    refreshed_from_sqlite = client.get(f"/api/books/{encoded_book_id}/chapters/001/memory-updates")
    refreshed_update = next(
        item
        for item in refreshed_from_sqlite.json()["memoryUpdates"]
        if item["id"] == summary_update["id"]
    )
    coverage = WorkbenchRepository().coverage_counts(project.root)

    assert refreshed_from_sqlite.status_code == 200
    assert refreshed_update["status"] == "applied"
    assert coverage["memoryUpdates"] >= 1
    target_file = {
        "章节摘要": "chapter-summaries.json",
        "读者承诺": "promises.json",
        "事实": "facts.json",
        "时间线": "timeline-events.json",
        "人物状态": "character-states.json",
        "关系状态": "relationship-states.json",
        "伏笔与未解问题": "open-loops.json",
        "情绪轨迹": "emotional-arcs.json",
    }[applied["memoryUpdate"]["targetLabel"]]
    assert (project.root / "memory" / target_file).exists()


def test_workbench_chapter_memory_updates_returns_empty_before_review_artifacts(
    tmp_path, monkeypatch
) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.get(
        f"/api/books/{encoded_book_id}/chapters/099/memory-updates"
    )

    assert response.status_code == 200
    assert response.json() == {
        "bookId": project.root.as_posix(),
        "chapterId": "099",
        "memoryUpdates": [],
    }


def test_workbench_deferred_memory_update_cannot_apply(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")
    encoded_book_id = quote(project.root.as_posix(), safe="")

    list_response = client.get(f"/api/books/{encoded_book_id}/chapters/001/memory-updates")
    deferred_update = next(
        item
        for item in list_response.json()["memoryUpdates"]
        if item["id"] == "op_review_001_fact_outcome"
    )
    assert deferred_update["canApply"] is False
    assert deferred_update["action"] == "defer"
    assert deferred_update["statusLabel"] == "需人工确认"
    assert "后端" not in deferred_update["blockedReason"]
    assert "后台" not in deferred_update["blockedReason"]

    apply_response = client.post(
        f"/api/books/{encoded_book_id}/memory-updates/op_review_001_fact_outcome/apply",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )

    assert apply_response.status_code == 409
    assert "人工确认" in apply_response.json()["detail"]


def test_workbench_export_check_and_generate_outputs(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    check_response = client.post(
        f"/api/books/{encoded_book_id}/exports/check",
        json={
            "bookId": project.root.as_posix(),
            "kind": "正文",
            "range": "全书",
        },
    )
    generate_response = client.post(
        f"/api/books/{encoded_book_id}/exports",
        json={
            "bookId": project.root.as_posix(),
            "kind": "正文",
            "range": "全书",
        },
    )

    assert check_response.status_code == 200
    assert check_response.json()["readiness"]["kind"] == "正文"
    assert check_response.json()["readiness"]["chapterIds"] == ["001"]
    assert generate_response.status_code == 200
    assert generate_response.json()["resultName"] == "manuscript.txt"
    assert (project.root / "exports" / "manuscript.txt").exists()


def test_workbench_export_report_and_material_package(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    material = {
        "id": "mat-export",
        "bookId": project.root.as_posix(),
        "type": "人物",
        "title": "林澈",
        "summary": "用声音判断风险的人。",
        "influence": "影响审稿报告和资料包。",
        "related": ["001"],
        "confidence": 82,
    }
    client.post(f"/api/books/{encoded_book_id}/materials", json=material)

    report_response = client.post(
        f"/api/books/{encoded_book_id}/exports",
        json={
            "bookId": project.root.as_posix(),
            "kind": "审稿报告",
            "range": "全书",
        },
    )
    package_response = client.post(
        f"/api/books/{encoded_book_id}/exports",
        json={
            "bookId": project.root.as_posix(),
            "kind": "资料包",
            "range": "全书",
        },
    )

    assert report_response.status_code == 200
    assert package_response.status_code == 200
    assert (project.root / "exports" / "review-report.md").exists()
    assert (project.root / "exports" / "material-package.zip").exists()


def test_workbench_export_report_uses_latest_review_inbox(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    assert run_response.status_code == 200
    latest_titles = [item["title"] for item in run_response.json()["reviews"]]

    report_response = client.post(
        f"/api/books/{encoded_book_id}/exports",
        json={
            "bookId": project.root.as_posix(),
            "kind": "审稿报告",
            "range": "全书",
        },
    )

    assert report_response.status_code == 200
    report_text = (project.root / "exports" / "review-report.md").read_text(encoding="utf-8")
    assert latest_titles
    assert all(title in report_text for title in latest_titles)


def test_workbench_export_check_uses_latest_review_inbox(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    run_response = client.post(
        f"/api/books/{encoded_book_id}/reviews/run",
        json={
            "bookId": project.root.as_posix(),
            "chapterId": "001",
        },
    )
    assert run_response.status_code == 200
    latest_reviews = run_response.json()["reviews"]
    expected_open_reviews = sum(1 for item in latest_reviews if item["status"] != "已确认")

    check_response = client.post(
        f"/api/books/{encoded_book_id}/exports/check",
        json={
            "bookId": project.root.as_posix(),
            "kind": "正文",
            "range": "全书",
        },
    )

    assert check_response.status_code == 200
    readiness = check_response.json()["readiness"]
    assert f"未确认审稿 {expected_open_reviews} 条" in readiness["checks"]


def test_workbench_workspace_includes_jobs_and_runs(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    JobController()._create(  # noqa: SLF001
        project.root,
        kind="local-training",
        title="训练检查",
        detail="等待训练样本。",
    )
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        (
            '{"runId": "run_001", "skillId": "chapter-writer", '
            '"status": "completed", "summary": "已生成候选。"}'
        ),
    )

    response = client.get("/api/workspace")

    assert response.status_code == 200
    data = response.json()
    assert data["jobs"][0]["bookId"] == project.root.as_posix()
    assert data["jobs"][0]["status"] == "等待中"
    assert data["runs"][0]["id"] == "run_001"
    assert data["runs"][0]["kind"] == "生成"

    ProjectService().delete_text(project.root, "runs/run_001/run.json")
    runs_response = client.get(f"/api/books/{quote(project.root.as_posix(), safe='')}/runs")
    coverage = WorkbenchRepository().coverage_counts(project.root)

    assert runs_response.status_code == 200
    assert any(item["id"] == "run_001" for item in runs_response.json()["runs"])
    assert coverage["runs"] >= 1


def test_workbench_workspace_includes_exports_for_all_books(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    second_project = ProjectService().create_project(tmp_path / "demo-2", title="第二本书")
    WorkspaceRegistryService().register_project(second_project.root)

    response = client.get("/api/workspace")

    assert response.status_code == 200
    exports = response.json()["exports"]
    assert any(item["bookId"] == project.root.as_posix() for item in exports)
    assert any(item["bookId"] == second_project.root.as_posix() for item in exports)


def test_workbench_book_workspace_returns_single_book_scope(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    second_project = ProjectService().create_project(tmp_path / "demo-2", title="第二本书")
    WorkspaceRegistryService().register_project(second_project.root)
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        (
            '{"runId": "run_001", "skillId": "chapter-writer", '
            '"status": "completed", "summary": "已生成一章。"}'
        ),
    )
    ProjectService().write_text(
        second_project.root,
        "runs/run_002/run.json",
        (
            '{"runId": "run_002", "skillId": "chapter-writer", '
            '"status": "completed", "summary": "第二本书运行记录。"}'
        ),
    )
    encoded_book_id = quote(project.root.as_posix(), safe="")

    response = client.get(f"/api/books/{encoded_book_id}/workspace")

    assert response.status_code == 200
    data = response.json()
    assert len(data["books"]) == 1
    assert data["books"][0]["id"] == project.root.as_posix()
    assert all(item["bookId"] == project.root.as_posix() for item in data["materials"])
    assert all(item["bookId"] == project.root.as_posix() for item in data["reviews"])
    assert all(item["bookId"] == project.root.as_posix() for item in data["jobs"])
    assert all(item["bookId"] == project.root.as_posix() for item in data["runs"])
    assert data["creationOptions"]["platformStyles"]


def test_workbench_jobs_cancel_and_retry_return_summaries(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="local-training",
        title="训练检查",
        detail="等待训练样本。",
    )

    list_response = client.get(f"/api/books/{encoded_book_id}/jobs")
    cancel_response = client.post(f"/api/books/{encoded_book_id}/jobs/{queued.jobId}/cancel")
    retry_response = client.post(f"/api/books/{encoded_book_id}/jobs/{queued.jobId}/retry")

    assert list_response.status_code == 200
    assert list_response.json()["jobs"][0]["id"] == queued.jobId
    assert cancel_response.status_code == 200
    assert cancel_response.json()["job"]["status"] == "失败"
    assert retry_response.status_code == 200
    assert retry_response.json()["job"]["id"] != queued.jobId
    assert retry_response.json()["job"]["title"] == "训练检查"
    assert retry_response.json()["job"]["status"] == "等待中"
    assert "后台" not in retry_response.json()["job"]["result"]
    assert "后续" not in retry_response.json()["job"]["result"]


def test_workbench_job_detail_and_events_return_author_summaries(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    job = JobController()._create(  # noqa: SLF001
        project.root,
        kind="chapter-draft",
        title="生成章节候选",
        detail="准备上下文。",
    )

    detail_response = client.get(f"/api/books/{encoded_book_id}/jobs/{job.jobId}")
    events_response = client.get(f"/api/books/{encoded_book_id}/jobs/{job.jobId}/events")

    assert detail_response.status_code == 200
    assert detail_response.json()["job"]["id"] == job.jobId
    assert detail_response.json()["detail"]["events"]
    assert "logs" not in detail_response.json()["detail"]
    assert "retryOfJobId" not in detail_response.json()["detail"]
    assert events_response.status_code == 200
    assert events_response.json()["events"]


def test_workbench_runs_endpoint_returns_summaries(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    ProjectService().write_text(
        project.root,
        "runs/run_review/run.json",
        (
            '{"runId": "run_review", "skillId": "editorial-review", '
            '"status": "warning", "summary": "有审稿提醒。"}'
        ),
    )

    response = client.get(f"/api/books/{encoded_book_id}/runs")

    assert response.status_code == 200
    data = response.json()
    assert data["bookId"] == project.root.as_posix()
    assert data["runs"][0]["id"] == "run_review"
    assert data["runs"][0]["status"] == "警告"
    assert data["runs"][0]["kind"] == "审稿"


def test_workbench_runs_include_model_comparison_summary(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    _write_post_review_ready_story(project.root)
    writer = WritingModelService()
    python_exec = sys.executable
    writer.register_profile(
        project.root,
        "base-model",
        label="基础模型",
        base_model="base",
        adapter_path="models/adapters/base",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text('# base\\n\\n主角通过测试，但仍被盯上。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于当前书稳定续写。",
        set_default=True,
    )
    writer.register_profile(
        project.root,
        "tuned-model",
        label="增强模型",
        base_model="base",
        adapter_path="models/adapters/tuned",
        command_template=(
            f'{python_exec} -c "from pathlib import Path; '
            "Path(r'{output_file}').write_text("
            "'# tuned\\n\\n主角通过测试，旧敌也开始忌惮他的异常。'); "
            "print(Path(r'{output_file}').read_text())\""
        ),
        notes="用于增强角色压迫感。",
        set_default=False,
    )

    compare_response = client.post(
        "/api/models/compare",
        json={
            "bookId": project.root.as_posix(),
            "baseProfileId": "base-model",
            "tunedProfileId": "tuned-model",
            "includeReferenceAgent": False,
        },
    )
    assert compare_response.status_code == 200

    response = client.get(f"/api/books/{encoded_book_id}/runs")

    assert response.status_code == 200
    data = response.json()
    model_run = next(
        (item for item in data["runs"] if item["id"] == compare_response.json()["comparisonId"]),
        None,
    )
    assert model_run is not None
    assert model_run["kind"] == "模型"
    assert model_run["title"].startswith("模型对比")
    assert "最佳候选" in model_run["summary"]


def test_workbench_diff_endpoint_returns_author_summary(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章 暗室回声\n\nDraft",
    )

    response = client.get(f"/api/books/{encoded_book_id}/diff")

    assert response.status_code == 200
    data = response.json()
    assert data["chapterId"] == "001"
    assert data["changed"] is True
    assert "+Draft" in data["diff"]
    assert "新增" in data["summary"]


def test_workbench_diagnostics_endpoint_returns_author_items(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    encoded_book_id = quote(project.root.as_posix(), safe="")
    _write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "提前揭秘")
    assert client.get("/api/workspace").status_code == 200

    response = client.get(f"/api/books/{encoded_book_id}/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert data["chapterId"] == "001"
    assert data["items"]
    assert any("数据真源" in item for item in data["items"])
    assert any("兼容文件" in item for item in data["items"])
    assert "summary" in data


def test_workbench_maintenance_actions_return_author_summary(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _write_ready_contract(project.root)
    encoded_book_id = quote(project.root.as_posix(), safe="")

    context_response = client.post(
        f"/api/books/{encoded_book_id}/maintenance/rebuild-context-pack",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )
    diagnostics_response = client.post(
        f"/api/books/{encoded_book_id}/maintenance/refresh-diagnostics",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )
    reviews_response = client.post(
        f"/api/books/{encoded_book_id}/maintenance/rebuild-review-inbox",
        json={"bookId": project.root.as_posix(), "chapterId": "001"},
    )

    assert context_response.status_code == 200
    assert context_response.json()["action"] == "rebuild-context-pack"
    assert context_response.json()["items"]
    assert "上下文包" in context_response.json()["summary"]

    assert diagnostics_response.status_code == 200
    assert diagnostics_response.json()["action"] == "refresh-diagnostics"
    assert diagnostics_response.json()["items"]

    assert reviews_response.status_code == 200
    assert reviews_response.json()["action"] == "rebuild-review-inbox"
    assert "审稿 inbox" in reviews_response.json()["summary"]
    assert (project.root / "memory" / "workbench-review-inbox.json").exists()


def test_workbench_agent_assist_requires_assigned_role_account(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)

    response = client.post(
        "/api/agent/assist",
        json={
            "bookId": project.root.as_posix(),
            "scope": "material",
            "action": "新建资料",
            "input": "一个控制城市档案的组织",
            "materialType": "势力",
        },
    )

    assert response.status_code == 503
    assert "写作角色" in response.json()["detail"]


def test_workbench_local_chapter_assist_is_not_used_as_ai_fallback(tmp_path, monkeypatch) -> None:
    _client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()

    try:
        asyncio.run(
            presenter.agent_assist(
                AgentAssistRequest(
                    bookId=project.root.as_posix(),
                    scope="chapter",
                    action="续写",
                    input="章节：第一章\n任务：找到呼吸声来源",
                    chapterId="001",
                )
            )
        )
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("local-dry-run must not generate AI candidates")


def test_workbench_local_book_assist_is_not_used_as_ai_fallback(tmp_path, monkeypatch) -> None:
    _client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()

    try:
        asyncio.run(
            presenter.agent_assist(
                AgentAssistRequest(
                    bookId=project.root.as_posix(),
                    scope="book",
                    action="生成新书初始设定",
                    input="平台风格：通用网文连载\n题材：都市悬疑\n请生成作品标题、简介、首章标题和开场灵感。",
                )
            )
        )
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("local-dry-run must not generate AI candidates")


def test_workbench_local_review_assist_is_not_used_as_ai_fallback(tmp_path, monkeypatch) -> None:
    _client, project = _client_with_project(tmp_path, monkeypatch)
    presenter = WorkbenchPresenter()

    try:
        asyncio.run(
            presenter.agent_assist(
                AgentAssistRequest(
                    bookId=project.root.as_posix(),
                    scope="review",
                    action="生成修复方案",
                    input="审稿项：第 001 章审稿建议\n建议：减少集中解释",
                    reviewId="review-001",
                )
            )
        )
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("local-dry-run must not generate AI candidates")


def test_workbench_agent_assist_uses_assigned_api_account(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    _configure_ai_account(client, protocol="chat_completions")

    async def fake_upstream(self, account, prompt):
        assert account.protocol == "chat_completions"
        assert "不要返回 JSON" in prompt
        yield "token", {"text": "API 账号生成的候选建议"}
        yield "usage", {
            "prompt_tokens": 12,
            "completion_tokens": 6,
            "total_tokens": 18,
        }

    monkeypatch.setattr(AIRuntimeService, "_upstream_events", fake_upstream)

    response = client.post(
        "/api/agent/assist",
        json={
            "bookId": project.root.as_posix(),
            "scope": "chapter",
            "action": "续写",
            "input": "补强暗室冲突",
            "chapterId": "001",
        },
    )
    assert response.status_code == 200
    result = response.json()

    assert result["content"] == "API 账号生成的候选建议"
    assert result["candidateText"] == "API 账号生成的候选建议"
    assert result["usage"]["totalTokens"] == 18
    assert result["accountName"] == "受控写作账号"


def test_workbench_review_assist_uses_assigned_review_account(tmp_path, monkeypatch) -> None:
    client, project = _client_with_project(tmp_path, monkeypatch)
    writing_response = client.post(
        "/api/ai/accounts",
        json={
            "name": "受控写作账号",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "writing-key",
            "model": "writing-model",
            "protocol": "responses",
            "maxContextTokens": 128000,
            "enabled": True,
        },
    )
    review_response = client.post(
        "/api/ai/accounts",
        json={
            "name": "受控审核账号",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "review-key",
            "model": "review-model",
            "protocol": "chat_completions",
            "maxContextTokens": 128000,
            "enabled": True,
        },
    )
    writing_id = writing_response.json()["account"]["id"]
    review_id = review_response.json()["account"]["id"]
    bound = client.put(
        "/api/ai/roles",
        json={
            "writingAccountId": writing_id,
            "reviewAccountId": review_id,
        },
    )

    async def fake_upstream(self, account, prompt):
        assert account.name == "受控审核账号"
        assert account.model == "review-model"
        assert account.protocol == "chat_completions"
        assert "审稿项" in prompt
        yield "token", {"text": "审核账号生成的修复方案"}
        yield "usage", {
            "prompt_tokens": 16,
            "completion_tokens": 7,
            "total_tokens": 23,
        }

    monkeypatch.setattr(AIRuntimeService, "_upstream_events", fake_upstream)

    response = client.post(
        "/api/agent/assist",
        json={
            "bookId": project.root.as_posix(),
            "scope": "review",
            "action": "生成修复方案",
            "input": "审稿项：减少集中解释",
            "reviewId": "review-001",
        },
    )
    usage_events = client.get("/api/ai/settings").json()["usageEvents"]

    assert bound.status_code == 200
    assert response.status_code == 200
    assert response.json()["accountName"] == "受控审核账号"
    assert response.json()["usage"]["totalTokens"] == 23
    assert usage_events[0]["role"] == "review"
    assert usage_events[0]["accountId"] == review_id
