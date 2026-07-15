from __future__ import annotations

import json
import sys
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from open_novel.core.context_pack import ContextPackService
from open_novel.core.jobs import JobController
from open_novel.core.models import SceneContract, SkillRunRequest
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.server import app


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(part.strip() for part in parser.parts if part.strip())


def write_ready_contract(root, chapter_id: str = "001") -> None:
    StoryGuidanceService().write_scene_contract(
        root,
        SceneContract(
            chapterId=chapter_id,
            title="第一章",
            focus="主角第一次证明异常潜力。",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            relationshipBeat="旧敌开始忌惮。",
            logicDependencies=["主角曾被视为残缺灵根"],
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )


def wait_for_latest_job(root):
    job = JobController().list_jobs(root)[0]
    JobController().wait_for_job(job.jobId, timeout=5)
    return JobController().get_job(root, job.jobId)


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_skills_endpoint_lists_builtin_skills() -> None:
    client = TestClient(app)

    response = client.get("/skills")

    assert response.status_code == 200
    assert any(skill["id"] == "chapter-writer" for skill in response.json())


def test_agents_detect_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/agents/detect")

    assert response.status_code == 200
    assert {agent["id"] for agent in response.json()} >= {
        "codex-cli",
        "claude-cli",
        "qwen-cli",
    }


def test_skill_run_endpoint_writes_draft(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    client = TestClient(app)

    response = client.post(
        "/projects/skill/run",
        json={
            "projectRoot": str(project.root),
            "skillId": "chapter-writer",
            "variables": {"chapterId": "001", "chapterTitle": "第一章"},
            "agentId": "local-dry-run",
        },
    )

    assert response.status_code == 200
    assert response.json()["outputPath"] == "drafts/001.generated.md"
    assert (project.root / "drafts/001.generated.md").exists()


def test_writing_model_endpoints_register_and_list(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    register = client.post(
        "/projects/models/writing",
        json={
            "root": str(project.root),
            "profileId": "tomato-trained",
            "baseModel": "local-base",
            "adapterPath": "models/adapters/latest",
            "commandTemplate": "python -c \"print('ok')\"",
        },
    )

    assert register.status_code == 200
    assert register.json()["id"] == "tomato-trained"

    listing = client.get("/projects/models/writing", params={"root": str(project.root)})

    assert listing.status_code == 200
    assert listing.json()["defaultProfileId"] == "tomato-trained"
    assert listing.json()["profiles"][0]["adapterPath"] == "models/adapters/latest"


def test_editorial_profile_endpoints_register_and_list(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    register = client.post(
        "/projects/models/editorial",
        json={
            "root": str(project.root),
            "profileId": "suspense-editor",
            "backend": "local",
            "label": "Suspense editor",
            "promptPreset": "continuity-editor",
            "styleProfilePath": "story/style-profile.json",
            "rubric": ["检查线索公平", "检查情绪压迫"],
        },
    )
    listing = client.get("/projects/models/editorial", params={"root": str(project.root)})

    assert register.status_code == 200
    assert register.json()["id"] == "suspense-editor"
    assert register.json()["styleProfilePath"] == "story/style-profile.json"
    assert listing.status_code == 200
    assert listing.json()["defaultProfileId"] == "suspense-editor"
    assert any(
        preset["id"] == "platform-genre-commercial-editor"
        for preset in listing.json()["promptPresets"]
    )
    registered = next(
        profile for profile in listing.json()["profiles"] if profile["id"] == "suspense-editor"
    )
    assert registered["promptPreset"] == "continuity-editor"


def test_style_profile_endpoints_list_and_apply(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    listing = client.get("/projects/style-profiles")
    apply = client.post(
        "/projects/style-profiles/apply",
        json={
            "root": str(project.root),
            "profileId": "fanqie-xuanhuan-upgrade",
        },
    )
    stored = json.loads(
        (project.root / "story" / "style-profile.json").read_text(encoding="utf-8")
    )

    assert listing.status_code == 200
    assert any(
        profile["id"] == "fanqie-xuanhuan-upgrade"
        for profile in listing.json()["profiles"]
    )
    assert any(
        slot["id"] == "qidian-xianxia-longform"
        for slot in listing.json()["plannedSlots"]
    )
    assert any(
        slot["id"] == "douyin-micro-drama-reversal"
        for slot in listing.json()["plannedSlots"]
    )
    assert any(
        item["platform"] == "extension"
        for item in listing.json()["coverageCatalog"]
    )
    assert any(
        item["platform"] == "broad-reserve"
        for item in listing.json()["coverageCatalog"]
    )
    assert any(
        pack["id"] == "builtin-broad-genre-reserve"
        and pack["status"] == "reserved"
        and "douyin-micro-drama-reversal" in pack["plannedProfileIds"]
        for pack in listing.json()["templatePacks"]
    )
    assert listing.json()["maintenancePolicy"]["plannedSlotActivationCriteria"][
        "requiredSampleChapters"
    ] == 5
    assert any(
        profile["id"] == "fanqie-xuanhuan-upgrade"
        and profile["maturity"] == "candidate"
        and profile["promotionCriteria"]["minimumGateScore"] >= 90
        for profile in listing.json()["profiles"]
    )
    assert apply.status_code == 200
    assert apply.json()["extends"] == "fanqie-xuanhuan-upgrade"
    assert stored["extends"] == "fanqie-xuanhuan-upgrade"


def test_style_profile_endpoint_drafts_candidate_from_planned_slot() -> None:
    client = TestClient(app)

    response = client.get("/projects/style-profiles/planned/workplace-business-growth/draft")

    assert response.status_code == 200
    assert response.json()["id"] == "workplace-business-growth"
    assert response.json()["templateStatus"] == "candidate"
    assert response.json()["sourcePlannedSlotId"] == "workplace-business-growth"
    assert response.json()["promotionCriteria"]["requiredSampleChapters"] == 5


def test_style_profile_promotion_endpoint_evaluates_candidate(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "story/candidate-style.json",
        '{"id":"workplace-business-growth","templateStatus":"candidate",'
        '"sourcePlannedSlotId":"workplace-business-growth",'
        '"promotionCriteria":{"requiredSampleChapters":5,'
        '"minimumGateScore":90,"minimumQualityScore":90,'
        '"reviewChecklist":["continuity","humanity","platform-rhythm"]},'
        '"tone":["TODO: fill"],"readerExpectations":["TODO: fill"]}',
    )
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
        )
    )
    client = TestClient(app)

    response = client.post(
        "/projects/style-profiles/promotion/evaluate",
        json={
            "root": str(project.root),
            "candidateProfilePath": "story/candidate-style.json",
            "startChapterId": "001",
            "endChapterId": "001",
        },
    )

    assert response.status_code == 200
    assert response.json()["profileId"] == "workplace-business-growth"
    assert response.json()["status"] == "block"
    assert any(
        issue["type"] == "candidate_contains_todo"
        for issue in response.json()["issues"]
    )


def test_editorial_review_endpoint_uses_registered_profile(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "prompt = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "report = {'reviewer': prompt['styleProfile']['id'], 'score': 83, 'status': 'pass'}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    client = TestClient(app)
    client.post(
        "/projects/models/editorial",
        json={
            "root": str(project.root),
            "profileId": "api-editor",
            "backend": "command",
            "commandTemplate": f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
        },
    )

    response = client.post(
        "/projects/editorial-review/check",
        json={
            "root": str(project.root),
            "chapterId": "001",
            "draftPath": "drafts/001.generated.md",
            "profileId": "api-editor",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "project-style"
    assert response.json()["metrics"]["profileId"] == "api-editor"


def test_skill_run_endpoint_accepts_local_model_profile(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "tomato-trained",
                "profiles": [
                    {
                        "id": "tomato-trained",
                        "label": "Tomato",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "local-base",
                        "adapterPath": "models/adapters/latest",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "Path(r'{output_file}').write_text("
                            "'# API 模型章\\n\\n测试石前，林澈咬牙推进局势。'); "
                            "print(Path(r'{output_file}').read_text())\""
                        ),
                        "timeoutSeconds": 60,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/projects/skill/run",
        json={
            "projectRoot": str(project.root),
            "skillId": "chapter-writer",
            "variables": {"chapterId": "001", "chapterTitle": "第一章"},
            "agentId": "local-model",
            "modelProfile": "tomato-trained",
        },
    )

    assert response.status_code == 200
    assert response.json()["modelProfile"] == "tomato-trained"
    assert "测试石前" in (project.root / "drafts/001.generated.md").read_text(encoding="utf-8")


def test_export_endpoint_writes_txt(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    response = client.post(
        "/projects/export",
        json={"root": str(project.root), "format": "txt"},
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("exports/manuscript.txt")
    assert (project.root / "exports/manuscript.txt").exists()


def test_training_data_export_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n正文。")
    client = TestClient(app)

    response = client.post(
        "/projects/export/training-data",
        json={"root": str(project.root), "format": "jsonl"},
    )

    assert response.status_code == 200
    assert response.json()["path"].endswith("exports/writing-training.jsonl")
    assert (project.root / "exports" / "writing-training.jsonl").exists()


def test_create_chapter_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    response = client.post(
        "/projects/chapter",
        json={"root": str(project.root), "chapterId": "002", "title": "第二章"},
    )

    assert response.status_code == 200
    assert response.json()["path"] == "chapters/002.md"
    assert (project.root / "chapters/002.md").exists()


def test_project_plan_endpoint_updates_and_reports_progress(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n她推开门。")
    client = TestClient(app)

    response = client.post(
        "/projects/plan",
        json={
            "root": str(project.root),
            "targetChapterCount": 20,
            "targetWordsPerChapter": 1500,
            "platform": "番茄小说",
            "cadence": "日更",
        },
    )

    assert response.status_code == 200
    assert response.json()["plan"]["platform"] == "番茄小说"
    assert response.json()["plan"]["targetChapterCount"] == 20
    assert response.json()["completedChapterCount"] == 1
    assert response.json()["acceptedWordCount"] == 4


def test_accept_draft_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/002.generated.md", "# Draft")
    client = TestClient(app)

    response = client.post(
        "/projects/draft/accept",
        json={
            "root": str(project.root),
            "draftPath": "drafts/002.generated.md",
            "chapterId": "001",
            "force": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["path"] == "chapters/001.md"
    assert response.json()["reviewPath"] == "reviews/001.review.json"
    assert response.json()["patchPath"] == "patches/001.canon-patch.json"
    assert response.json()["gateStatus"] == "block"
    assert (project.root / "chapters/001.md").read_text(encoding="utf-8") == "# Draft"


def test_accept_draft_endpoint_blocks_bad_draft_without_force(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "提前揭秘")
    client = TestClient(app)

    response = client.post(
        "/projects/draft/accept",
        json={
            "root": str(project.root),
            "draftPath": "drafts/001.generated.md",
            "chapterId": "001",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["recovery"]["blocked"] is True
    assert response.json()["detail"]["recovery"]["steps"]
    assert response.json()["detail"]["gatePath"] == "runs/chapter-gate-001.json"
    assert not (project.root / "chapters/001.md").read_text(encoding="utf-8") == "提前揭秘"


def test_project_runs_endpoint_lists_run_records(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        '{"runId": "run_001", "skillId": "chapter-writer", "agentId": "local"}',
    )
    client = TestClient(app)

    response = client.get("/projects/runs", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json()[0]["runId"] == "run_001"


def test_project_run_detail_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "runs/run_001/run.json",
        (
            '{"runId": "run_001", "skillId": "chapter-writer", '
            '"agentId": "local", "outputPath": "drafts/007.generated.md"}'
        ),
    )
    ProjectService().write_text(project.root, "runs/run_001/prompt.md", "# Prompt")
    ProjectService().write_text(project.root, "runs/run_001/output.md", "# Output")
    client = TestClient(app)

    response = client.get("/projects/runs/run_001", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json()["prompt"] == "# Prompt"


def test_diff_endpoint_returns_unified_diff(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(project.root, "drafts/001.generated.md", "# 001\n\nDraft")
    client = TestClient(app)

    response = client.post(
        "/projects/diff",
        json={
            "root": str(project.root),
            "leftPath": "chapters/001.md",
            "rightPath": "drafts/001.generated.md",
        },
    )

    assert response.status_code == 200
    assert "+Draft" in response.json()["diff"]


def test_projects_file_save_timeline_refreshes_context_pack(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="旧重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    client = TestClient(app)

    response = client.put(
        "/projects/file",
        params={"root": str(project.root)},
        json={
            "path": "timeline.md",
            "content": "# Timeline\n\n- 第1章：林澈通过山门测试\n- 第2章：长老发现禁忌传承痕迹\n",
        },
    )

    assert response.status_code == 200
    assert [
        event.label for event in ProjectService().read_timeline_events(project.root).events
    ] == ["林澈通过山门测试", "长老发现禁忌传承痕迹"]
    assert (project.root / "story" / "context-packs" / "001.json").exists()


def test_characters_endpoint_lists_characters(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().create_character(project.root, "hero", name="林澈")
    client = TestClient(app)

    response = client.get("/projects/characters", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json() == ["characters/hero.md"]


def test_create_character_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    response = client.post(
        "/projects/characters",
        json={"root": str(project.root), "characterId": "hero", "name": "林澈"},
    )

    assert response.status_code == 200
    assert response.json()["path"] == "characters/hero.md"
    assert (project.root / "characters/hero.md").exists()


def test_timeline_sync_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "timeline.md",
        "# Timeline\n\n- chapter 2: 主角抵达旧都\n",
    )
    client = TestClient(app)

    response = client.post("/projects/timeline/sync", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json()["events"][0]["chapterId"] == "002"
    assert response.json()["events"][0]["label"] == "主角抵达旧都"


def test_timeline_events_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().sync_timeline_events_from_markdown(project.root)
    client = TestClient(app)

    response = client.get("/projects/timeline/events", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json()["schemaVersion"] == 1


def test_scene_contract_and_readiness_endpoints(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    create_response = client.post(
        "/projects/scene-contract",
        json={"root": str(project.root), "chapterId": "001", "title": "山门测试"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["chapterId"] == "001"

    readiness_response = client.get(
        "/projects/readiness",
        params={"root": str(project.root), "chapterId": "001"},
    )

    assert readiness_response.status_code == 200
    assert readiness_response.json()["status"] == "block"
    assert any(issue["field"] == "focus" for issue in readiness_response.json()["issues"])


def test_scene_contract_create_and_save_refresh_context_pack(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            focus="旧重点",
            goal="主角想通过测试。",
            conflict="旧敌阻挠。",
            turn="测试石异动。",
            outcome="主角通过但被盯上。",
            hook="长老封锁消息。",
            emotionalBeat="主角从压抑转为警惕。",
            mustAvoid=["提前揭秘"],
            readerPromises=["废柴逆袭"],
        ),
    )
    ContextPackService().build_context_pack(project.root, "001")
    client = TestClient(app)

    create_response = client.post(
        "/projects/scene-contract",
        json={"root": str(project.root), "chapterId": "001", "title": "山门测试"},
    )

    assert create_response.status_code == 200

    save_response = client.put(
        "/projects/scene-contract",
        json={
            "root": str(project.root),
            "contract": {
                "chapterId": "001",
                "title": "第二版",
                "focus": "新重点",
                "goal": "主角想通过测试。",
                "conflict": "旧敌阻挠。",
                "turn": "测试石异动。",
                "outcome": "主角通过但被盯上。",
                "hook": "长老封锁消息。",
                "emotionalBeat": "主角从压抑转为警惕。",
                "mustAvoid": ["提前揭秘"],
                "readerPromises": ["废柴逆袭"],
            },
        },
    )

    assert save_response.status_code == 200
    context_pack = ContextPackService().read_context_pack(project.root, "001")
    contract_item = next(
        item for item in context_pack.included if item.source == "story/chapter-briefs/001.json"
    )
    assert contract_item.data["title"] == "第二版"
    assert context_pack.included[0].data["focus"] == "新重点"


def test_context_pack_endpoints(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    client = TestClient(app)

    build_response = client.post(
        "/projects/context-pack",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert build_response.status_code == 200
    assert build_response.json()["path"] == "story/context-packs/001.json"

    read_response = client.get(
        "/projects/context-pack",
        params={"root": str(project.root), "chapterId": "001"},
    )

    assert read_response.status_code == 200
    assert read_response.json()["chapterId"] == "001"


def test_context_pack_endpoint_accepts_token_budget(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    facts = [
        {
            "id": "fact_critical",
            "text": "测试石最高优先级记忆。" + "关键线索" * 20,
            "importance": "critical",
            "confidence": 0.95,
            "validFrom": "chapter:001",
        }
    ]
    facts.extend(
        {
            "id": f"fact_low_{index:02d}",
            "text": f"测试石低优先级背景 {index}。" + "旁支资料" * 60,
            "importance": "low",
            "confidence": 0.95,
            "validFrom": "chapter:001",
        }
        for index in range(12)
    )
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps({"schemaVersion": 1, "facts": facts}, ensure_ascii=False),
    )
    client = TestClient(app)

    response = client.post(
        "/projects/context-pack",
        json={
            "root": str(project.root),
            "chapterId": "001",
            "maxEstimatedTokens": 520,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["estimatedTokens"] <= 520
    facts_item = next(item for item in payload["included"] if item["source"] == "memory/facts.json")
    kept_ids = [fact["id"] for fact in facts_item["data"]["facts"]]
    assert "fact_critical" in kept_ids
    excluded_facts = next(
        item for item in payload["excluded"] if item["source"] == "memory/facts.json"
    )
    assert excluded_facts["data"]["facts"]["droppedCount"] == len(facts) - len(kept_ids)


def test_post_chapter_review_and_apply_endpoints(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "chapters/001.md", "# 第一章\n\n主角通过测试。")
    client = TestClient(app)

    review_response = client.post(
        "/projects/chapter/review",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["sourceReview"] == "reviews/001.review.json"

    first_apply_response = client.post(
        "/projects/canon-patch/apply",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert first_apply_response.status_code == 200
    first_operations = first_apply_response.json()["operations"]
    auto_applied = [operation for operation in first_operations if operation["status"] == "applied"]
    proposed = [operation for operation in first_operations if operation["status"] == "proposed"]
    assert any(
        operation["target"] == "memory/chapter-summaries.json"
        for operation in auto_applied
    )
    assert proposed

    accept_response = client.post(
        "/projects/canon-patch/accept",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert accept_response.status_code == 200
    accept_operations = accept_response.json()["operations"]
    assert any(
        operation["target"] == "memory/chapter-summaries.json"
        and operation["status"] == "applied"
        for operation in accept_operations
    )
    assert any(operation["status"] == "proposed" for operation in accept_operations)

    apply_response = client.post(
        "/projects/canon-patch/apply",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert apply_response.status_code == 200
    apply_operations = apply_response.json()["operations"]
    assert any(
        operation["target"] == "memory/chapter-summaries.json"
        and operation["status"] == "applied"
        for operation in apply_operations
    )
    assert any(operation["status"] == "proposed" for operation in apply_operations)


def test_continuity_check_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "提前揭秘")
    client = TestClient(app)

    response = client.post(
        "/projects/continuity/check",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert response.status_code == 200
    assert response.json()["issues"]


def test_chapter_gate_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "提前揭秘")
    client = TestClient(app)

    response = client.post(
        "/projects/chapter/gate",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert response.status_code == 200
    assert response.json()["status"] in {"block", "warn"}
    assert any(issue["stage"] == "continuity" for issue in response.json()["issues"])


def test_writing_quality_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(project.root, "drafts/001.generated.md", "# 第一章\n\n太短。")
    client = TestClient(app)

    response = client.post(
        "/projects/writing-quality/check",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert response.status_code == 200
    assert response.json()["chapterId"] == "001"
    assert response.json()["issues"]


def test_editorial_review_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    client = TestClient(app)

    response = client.post(
        "/projects/editorial-review/check",
        json={"root": str(project.root), "chapterId": "001"},
    )

    assert response.status_code == 200
    assert response.json()["chapterId"] == "001"
    assert response.json()["reviewer"] == "local-editor-v1"
    assert response.json()["issues"]


def test_editorial_review_endpoint_accepts_command_backend(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n林澈参加测试。他感到十分愤怒。最后测试通过。",
    )
    script = project.root / "editor.py"
    script.write_text(
        "import json, sys\n"
        "prompt = json.loads(open(sys.argv[1], encoding='utf-8').read())\n"
        "report = {'reviewer': 'api-llm-editor', 'score': 61, 'status': 'warn', 'issues': [{"
        "'type': 'emotion_lacks_specificity', 'severity': 'medium', 'dimension': 'emotion', "
        "'evidence': [prompt['source']], 'message': '情绪不够具体。', "
        "'suggestions': ['补一个无法立刻说出口的反应。']}], 'strengths': []}\n"
        "open(sys.argv[2], 'w', encoding='utf-8').write(json.dumps(report, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/projects/editorial-review/check",
        json={
            "root": str(project.root),
            "chapterId": "001",
            "backend": "command",
            "commandTemplate": f"{sys.executable} editor.py {{prompt_file}} {{output_file}}",
        },
    )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "api-llm-editor"
    assert response.json()["issues"][0]["type"] == "emotion_lacks_specificity"


def test_sequence_evaluation_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "主角曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    SkillRunner().run(
        SkillRunRequest(
            projectRoot=project.root,
            skillId="chapter-writer",
            variables={"chapterId": "001", "chapterTitle": "第一章"},
        )
    )
    client = TestClient(app)

    response = client.post(
        "/projects/sequence/evaluate",
        json={"root": str(project.root), "startChapterId": "001", "endChapterId": "001"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pass"
    assert response.json()["chapters"][0]["chapterId"] == "001"
    assert response.json()["revisionPlanPath"] == "runs/revision-plan-001-001.json"
    assert response.json()["revisionPlan"]["status"] == "ready"
    assert (project.root / "runs" / "revision-plan-001-001.json").exists()


def test_sequence_evaluation_endpoint_writes_revision_plan_for_failed_range(
    tmp_path,
) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "主角曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角通过测试。",
    )
    client = TestClient(app)

    response = client.post(
        "/projects/sequence/evaluate",
        json={"root": str(project.root), "startChapterId": "001", "endChapterId": "001"},
    )

    plan = response.json()["revisionPlan"]
    stored = json.loads(
        (project.root / "runs" / "revision-plan-001-001.json").read_text(encoding="utf-8")
    )

    assert response.status_code == 200
    assert response.json()["status"] in {"warn", "block"}
    assert response.json()["revisionPlanPath"] == "runs/revision-plan-001-001.json"
    assert plan["status"] == "needs-revision"
    assert plan["priorityChapters"] == ["001"]
    assert plan["chapters"][0]["rewriteBrief"]["repairActions"]
    assert any(
        issue["type"] == "too_short"
        for issue in plan["chapters"][0]["issues"]
    )
    assert stored["recommendedNextAction"] == (
        "revise-priority-chapters-and-rerun-five-chapter-regression"
    )


def test_revision_rerun_materializes_brief_and_uses_it_in_prompt(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "主角曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角通过测试。",
    )
    client = TestClient(app)
    client.post(
        "/projects/sequence/evaluate",
        json={"root": str(project.root), "startChapterId": "001", "endChapterId": "001"},
    )
    ProjectService().write_text(
        project.root,
        "models/writing-models.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultProfileId": "revision-model",
                "profiles": [
                    {
                        "id": "revision-model",
                        "label": "Revision Model",
                        "backend": "local-command",
                        "agentId": "local-model",
                        "baseModel": "local-base",
                        "commandTemplate": (
                            f"{sys.executable} -c \"from pathlib import Path; "
                            "p=Path(r'{prompt_file}').read_text(encoding='utf-8'); "
                            "marker='REVISION_BRIEF_SEEN' if "
                            "'story/revision-briefs/001.json' in p else 'NO_BRIEF'; "
                            "text='# 重写章\\n\\n'+marker+' 测试石前，主角在压力下做出选择，"
                            "代价和钩子都更清楚。'; "
                            "Path(r'{output_file}').write_text(text, encoding='utf-8'); "
                            "print(text)\""
                        ),
                        "timeoutSeconds": 60,
                    }
                ],
            },
            ensure_ascii=False,
        ),
    )

    response = client.post(
        "/projects/revision/rerun",
        json={
            "root": str(project.root),
            "revisionPlanPath": "runs/revision-plan-001-001.json",
            "maxChapters": 1,
            "agentId": "local-model",
            "modelProfile": "revision-model",
        },
    )

    context_pack = ContextPackService().read_context_pack(project.root, "001")
    draft = (project.root / "drafts/001.generated.md").read_text(encoding="utf-8")
    brief = json.loads(
        (project.root / "story" / "revision-briefs" / "001.json").read_text(
            encoding="utf-8"
        )
    )

    assert response.status_code == 200
    assert response.json()["revisionBriefs"][0]["path"] == "story/revision-briefs/001.json"
    assert response.json()["rerunChapters"][0]["modelProfile"] == "revision-model"
    assert response.json()["sequenceReportPath"] == "runs/sequence-evaluation-001-001.json"
    assert response.json()["revisionPlanPath"] == "runs/revision-plan-001-001.json"
    assert brief["rewriteBrief"]["repairActions"]
    assert "REVISION_BRIEF_SEEN" in draft
    assert "story/revision-briefs/001.json" in {item.source for item in context_pack.included}


def test_revision_auto_rerun_stops_when_sequence_becomes_ready(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "memory/facts.json",
        json.dumps(
            {
                "facts": [
                    {
                        "id": "fact_linggen_baseline",
                        "text": "主角曾被视为残缺灵根。",
                        "validFrom": "chapter:001",
                        "confidence": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    ProjectService().write_text(
        project.root,
        "drafts/001.generated.md",
        "# 第一章\n\n主角通过测试。",
    )
    client = TestClient(app)
    client.post(
        "/projects/sequence/evaluate",
        json={"root": str(project.root), "startChapterId": "001", "endChapterId": "001"},
    )

    response = client.post(
        "/projects/revision/rerun",
        json={
            "root": str(project.root),
            "revisionPlanPath": "runs/revision-plan-001-001.json",
            "maxChapters": 1,
            "maxRounds": 3,
            "agentId": "local-dry-run",
        },
    )

    assert response.status_code == 200
    assert response.json()["roundCount"] == 1
    assert response.json()["maxRounds"] == 3
    assert response.json()["stoppedReason"] == "ready"
    assert response.json()["finalStatus"] == "ready"
    assert response.json()["rounds"][0]["revisionBriefs"][0]["path"] == (
        "story/revision-briefs/001.json"
    )


def test_plot_direction_endpoint(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    client = TestClient(app)

    response = client.post(
        "/projects/plot/direction",
        json={"root": str(project.root), "chapterId": "001", "userIntent": "我想提前揭秘"},
    )

    assert response.status_code == 200
    assert response.json()["options"]
    assert response.json()["recommendedOptionId"]

    apply_response = client.post(
        "/projects/plot/direction/apply",
        json={
            "root": str(project.root),
            "chapterId": "001",
            "optionId": response.json()["options"][1]["id"],
        },
    )

    assert apply_response.status_code == 200
    assert "强化人物代价" in apply_response.json()["focus"]


def test_canon_patch_operations_endpoint_updates_selected_status(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n"
        "测试石前，主角咬牙通过测试。旧敌开始忌惮。"
        "主角通过但被盯上，长老封锁消息。",
    )
    PostChapterService().build_review_and_patch(project.root, "001")
    patch = json.loads(
        (project.root / "patches/001.canon-patch.json").read_text(encoding="utf-8")
    )
    operation_id = patch["operations"][0]["id"]
    client = TestClient(app)

    response = client.post(
        "/projects/canon-patch/operations",
        json={
            "root": str(project.root),
            "chapterId": "001",
            "operationIds": [operation_id],
            "status": "accepted",
        },
    )

    assert response.status_code == 200
    assert next(
        operation for operation in response.json()["operations"] if operation["id"] == operation_id
    )["status"] == "accepted"


def test_polish_endpoint_uses_reviewable_draft_path(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    ProjectService().write_text(
        project.root,
        "chapters/001.md",
        "# 第一章\n\n他感觉非常紧张，然后说道：“我要继续。”\n",
    )
    client = TestClient(app)

    response = client.post(
        "/projects/polish",
        json={
            "root": str(project.root),
            "sourcePath": "chapters/001.md",
            "instruction": "保持剧情不变，提升节奏。",
            "preferTrainedModel": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["outputPath"] == "drafts/001.polished.md"
    assert (project.root / "drafts" / "001.polished.md").exists()


def test_project_job_cancel_endpoint_marks_queued_job_cancelled(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    job = JobController()._create(  # noqa: SLF001
        project.root,
        kind="local-training",
        title="Train",
        detail="queued",
    )
    client = TestClient(app)

    response = client.post(
        f"/projects/jobs/{job.jobId}/cancel",
        params={"root": str(project.root)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["requestedCancelAt"]


def test_project_job_retry_endpoint_starts_retry_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    try:
        JobController().run_sync(
            project.root,
            kind="skill-run",
            title="Run chapter-writer",
            detail="retry chapter 001",
            work=lambda _job: (_ for _ in ()).throw(RuntimeError("first failed")),
            params={
                "skillId": "chapter-writer",
                "chapterId": "001",
                "chapterTitle": "第一章",
                "agentId": "local-dry-run",
                "modelProfile": "",
            },
        )
    except RuntimeError:
        pass
    failed = JobController().list_jobs(project.root)[0]
    client = TestClient(app)

    response = client.post(
        f"/projects/jobs/{failed.jobId}/retry",
        params={"root": str(project.root)},
    )
    retry_id = response.json()["jobId"]
    JobController().wait_for_job(retry_id, timeout=5)
    retry = JobController().get_job(project.root, retry_id)

    assert response.status_code == 200
    assert retry.status == "completed"
    assert retry.retryOfJobId == failed.jobId
    assert (project.root / "drafts/001.generated.md").exists()


def test_project_jobs_recover_endpoint_restarts_queued_skill_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    write_ready_contract(project.root)
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="skill-run",
        title="Run chapter-writer",
        detail="queued chapter 001",
        params={
            "skillId": "chapter-writer",
            "chapterId": "001",
            "chapterTitle": "第一章",
            "agentId": "local-dry-run",
            "modelProfile": "",
        },
    )
    client = TestClient(app)

    response = client.post("/projects/jobs/recover", params={"root": str(project.root)})
    JobController().wait_for_job(queued.jobId, timeout=5)
    recovered = JobController().get_job(project.root, queued.jobId)

    assert response.status_code == 200
    assert response.json()[0]["jobId"] == queued.jobId
    assert recovered.status == "completed"
    assert (project.root / "drafts/001.generated.md").exists()


def test_project_jobs_listing_marks_orphaned_running_job_interrupted(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="skill-run",
        title="Run chapter-writer",
        detail="orphan",
    )
    JobController()._update(project.root, queued, status="running")  # noqa: SLF001
    client = TestClient(app)

    response = client.get("/projects/jobs", params={"root": str(project.root)})

    assert response.status_code == 200
    assert response.json()[0]["status"] == "interrupted"


def test_project_job_events_rejects_missing_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    client = TestClient(app)

    response = client.get(
        "/projects/jobs/missing/events",
        params={"root": str(project.root)},
    )

    assert response.status_code == 400


def test_api_create_guided_project_builds_beginner_foundation(tmp_path) -> None:
    response = TestClient(app).post(
        "/projects/create-guided",
        json={
            "path": str(tmp_path / "guided-api"),
            "title": "API 新手项目",
            "idea": "一个新人从一次错误选择里学会承担代价。",
            "genre": "成长冒险",
            "targetReaders": "喜欢清晰目标和情绪推进的读者",
            "protagonistName": "小禾",
            "protagonistDesire": "想证明自己可以独自完成任务。",
            "protagonistWound": "害怕再次拖累别人。",
            "opponent": "控制资源的导师",
            "worldRule": "每次机会都会带来新的责任。",
            "longMystery": "导师为什么隐瞒过去的失败。",
            "corePromise": "主角会在代价中成长。",
            "volumeGoal": "第一卷完成第一次独立任务。",
        },
    )

    root = tmp_path / "guided-api"

    assert response.status_code == 200
    assert response.json()["chapterCount"] == 5
    assert response.json()["nextRoute"].endswith("chapterId=001")
    assert (root / "bible.md").exists()
    assert (root / "characters" / "protagonist.md").exists()
    assert (root / "story" / "chapter-briefs" / "001.json").exists()
    assert "小禾" in (root / "characters" / "protagonist.md").read_text(encoding="utf-8")

def test_route_surface_is_api_only() -> None:
    paths = {route.path for route in app.routes}

    assert all(
        path in {
            "/health",
            "/skills",
            "/agents/detect",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }
        or path.startswith("/api/")
        or path.startswith("/projects/")
        for path in paths
    )
