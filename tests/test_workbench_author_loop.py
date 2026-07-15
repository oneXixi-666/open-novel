from __future__ import annotations

import json
from urllib.parse import quote

from fastapi.testclient import TestClient

from open_novel.core.jobs import JobController
from open_novel.core.models import SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.server import app
from open_novel.web.routes_workbench import WorkbenchPresenter


def test_workbench_first_version_author_loop_contract(tmp_path, monkeypatch) -> None:
    async def fake_agent_assist(self, request):
        return {
            "title": "AI 辅助 · 续写",
            "content": "雨夜站台的广告灯第三次闪烁时，异常声纹忽然压低。",
            "suggestions": [],
            "candidateText": "雨夜站台的广告灯第三次闪烁时，异常声纹忽然压低。",
        }

    monkeypatch.setattr(WorkbenchPresenter, "agent_assist", fake_agent_assist)
    client, project = _client_with_author_project(tmp_path, monkeypatch)
    book_id = project.root.as_posix()
    encoded_book_id = quote(book_id, safe="")

    workspace = _ok(client.get("/api/workspace"))
    assert workspace["books"][0]["id"] == book_id
    assert workspace["creationOptions"]["platformStyles"]
    assert workspace["creationOptions"]["genres"]
    assert {action["key"] for action in workspace["models"][0]["actions"]} >= {"validate", "apply"}

    created = _ok(
        client.post(
            "/api/books",
            json={
                "draft": {
                    "title": "回归新书",
                    "platform": "generic",
                    "styleProfileId": "generic-web-serial",
                    "styleProfileLabel": "通用网文连载",
                    "genre": "都市悬疑",
                    "tagline": "用声音找回被改写的真相。",
                    "firstChapterTitle": "第一章 试音",
                    "seed": "主角在雨夜录音里听见自己的警告。",
                },
                "existingBookCount": len(workspace["books"]),
                "defaultModelId": "local-dry-run",
            },
        )
    )
    assert created["book"]["title"] == "回归新书"
    assert created["book"]["currentModelId"] == ""
    assert created["chapter"]["id"]

    model = _ok(
        client.put(
            f"/api/books/{encoded_book_id}/model",
            json={"bookId": book_id, "modelId": "local-dry-run"},
        )
    )
    validation = _ok(
        client.post("/api/models/local-dry-run/validate", json={"modelId": "local-dry-run"})
    )
    assert model == {"bookId": book_id, "modelId": "local-dry-run"}
    assert validation["status"] == "待验证"
    assert validation["coverage"] == 0
    assert validation["warnings"]

    material = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/materials",
            json={
                "id": "rain-station",
                "bookId": book_id,
                "type": "地点",
                "title": "雨夜站台",
                "summary": "废弃站台会把异常声纹藏进广告灯闪烁里。",
                "influence": "让当前章的声音线索和记忆代价同时发生。",
                "related": ["当前章节", "沈砚", "录音"],
                "confidence": 86,
                "details": {"位置": "旧线站台", "规则": "灯闪三次后出现声纹"},
            },
        )
    )
    linked = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/chapters/001/materials/link",
            json={
                "bookId": book_id,
                "chapterId": "001",
                "materialIds": [material["material"]["id"]],
                "mode": "replace",
            },
        )
    )
    related_materials = _ok(
        client.get(
            f"/api/books/{encoded_book_id}/chapters/001/materials",
            params={"type": "地点", "scope": "related"},
        )
    )
    assert linked["chapter"]["linkedMaterialIds"] == ["rain-station"]
    assert related_materials["materials"][0]["id"] == "rain-station"

    planned = _ok(
        client.put(
            f"/api/books/{encoded_book_id}/chapters/001/planning",
            json={
                "bookId": book_id,
                "chapterId": "001",
                "tasks": ["确认异常声纹来源", "让同行人证词发生偏差"],
                "plotPoints": ["广告灯闪三次", "录音末尾出现下一处地点"],
            },
        )
    )
    assert planned["chapter"]["tasks"] == ["确认异常声纹来源", "让同行人证词发生偏差"]
    assert "录音末尾出现下一处地点" in planned["chapter"]["plotPoints"]

    assist = _ok(
        client.post(
            "/api/agent/assist",
            json={
                "bookId": book_id,
                "chapterId": "001",
                "scope": "chapter",
                "action": "续写",
                "input": "围绕雨夜站台和异常声纹续写一段候选。",
            },
        )
    )
    candidate = assist.get("candidateText") or assist["content"]
    assert candidate
    assert "agentId" not in assist

    draft = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/chapters/001/draft",
            json={"bookId": book_id, "chapterId": "001", "nextContent": candidate},
        )
    )
    prepared = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/chapters/001/prepare",
            json={"bookId": book_id, "chapterId": "001"},
        )
    )
    gate = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/chapters/001/gate",
            json={"bookId": book_id, "chapterId": "001"},
        )
    )
    assert draft["chapter"]["status"] == "草稿"
    assert prepared["display"]
    assert gate["gate"]["status"] in {"pass", "warn", "block"}

    reviews = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/reviews/run",
            json={"bookId": book_id, "chapterId": "001"},
        )
    )
    review = reviews["reviews"][0]
    repaired = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/reviews/{quote(review['id'], safe='')}/repair",
            json={
                "bookId": book_id,
                "chapterId": review["chapterId"],
                "reviewId": review["id"],
                "repairText": "补强主角听见异常后的主动选择。",
            },
        )
    )
    confirmed = _ok(
        client.patch(
            f"/api/books/{encoded_book_id}/reviews/{quote(review['id'], safe='')}",
            json={"bookId": book_id, "reviewId": review["id"], "status": "已确认"},
        )
    )
    assert repaired["chapter"]["status"] == "草稿"
    assert confirmed["review"]["status"] == "已确认"

    accepted = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/chapters/001/accept",
            json={"bookId": book_id, "chapterId": "001", "force": True},
        )
    )
    assert accepted["chapter"]["status"] == "完成"

    memory_updates = _ok(client.get(f"/api/books/{encoded_book_id}/chapters/001/memory-updates"))
    applicable_update = next(item for item in memory_updates["memoryUpdates"] if item["canApply"])
    applied_memory = _ok(
        client.post(
            (
                f"/api/books/{encoded_book_id}/memory-updates/"
                f"{quote(applicable_update['id'], safe='')}/apply"
            ),
            json={"bookId": book_id, "chapterId": "001"},
        )
    )
    assert applied_memory["memoryUpdate"]["status"] == "applied"

    export_check = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/exports/check",
            json={"bookId": book_id, "kind": "正文", "range": "全书"},
        )
    )
    export_result = _ok(
        client.post(
            f"/api/books/{encoded_book_id}/exports",
            json={"bookId": book_id, "kind": "正文", "range": "全书"},
        )
    )
    assert export_check["readiness"]["kind"] == "正文"
    assert isinstance(export_check["readiness"]["ready"], bool)
    assert export_result["resultName"] == "manuscript.txt"
    assert export_result["summary"]
    assert "path" not in json.dumps(export_result, ensure_ascii=False).lower()

    next_chapter = _ok(client.post(f"/api/books/{encoded_book_id}/chapters/next"))
    assert next_chapter["chapter"]["id"] != "001"

    job = JobController()._create(  # noqa: SLF001 - tests the facade against real job records.
        project.root,
        kind="chapter-draft",
        title="生成章节候选",
        detail="正在整理下一章上下文。",
    )
    jobs = _ok(client.get(f"/api/books/{encoded_book_id}/jobs"))
    job_detail = _ok(client.get(f"/api/books/{encoded_book_id}/jobs/{job.jobId}"))
    job_events = _ok(client.get(f"/api/books/{encoded_book_id}/jobs/{job.jobId}/events"))
    runs = _ok(client.get(f"/api/books/{encoded_book_id}/runs"))
    assert jobs["jobs"][0]["title"] == "生成章节候选"
    assert job_detail["job"]["id"] == job.jobId
    assert "events" in job_events
    assert "runs" in runs

    book_workspace = _ok(client.get(f"/api/books/{encoded_book_id}/workspace"))
    assert [book["id"] for book in book_workspace["books"]] == [book_id]
    assert all(item["bookId"] == book_id for item in book_workspace["materials"])
    assert all(item["bookId"] == book_id for item in book_workspace["reviews"])


def _client_with_author_project(tmp_path, monkeypatch) -> tuple[TestClient, object]:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    project = ProjectService().create_project(tmp_path / "demo", title="异声追猎")
    project_service = ProjectService()
    project_service.write_text(
        project.root,
        "chapters/001.md",
        (
            "# 第一章 雨夜录音\n\n"
            "雨水砸在旧站牌上，沈砚按下录音键。耳机里先是一段空白，"
            "随后传来和他一模一样的声音：别回头。站台尽头的广告灯闪了三次，"
            "每一次闪烁，同行人的名字就从他的记忆里淡掉一笔。"
        ),
    )
    StoryGuidanceService().write_scene_contract(
        project.root,
        SceneContract(
            chapterId="001",
            title="雨夜录音",
            focus="沈砚第一次确认异常声纹不是幻听。",
            goal="沈砚想保存异常录音作为证据。",
            conflict="站台广播和同行人记忆同时被改写。",
            turn="录音里出现第二个沈砚的警告。",
            outcome="沈砚保住录音，但失去同行人的完整记忆。",
            hook="录音末尾出现了下一处地点的环境声。",
            emotionalBeat="沈砚从怀疑转为惊惧和决心。",
            relationshipBeat="同行人开始不信任沈砚的叙述。",
            logicDependencies=["沈砚能听见异常声纹"],
            mustInclude=["雨夜站台", "录音", "别回头"],
            mustAvoid=["提前解释异常来源"],
            readerPromises=["都市悬疑", "记忆代价", "声音线索"],
        ),
    )
    project_service.write_text(
        project.root,
        "memory/long-term-memory.json",
        """{
  "schemaVersion": 1,
  "topics": [
    {
      "id": "topic-shenyan",
      "summary": "沈砚会用声音判断风险，但每次取证都会带来记忆代价。",
      "sourceChapters": ["001"]
    }
  ],
  "entityIndex": [
    {"entityId": "shenyan", "name": "沈砚", "topicIds": ["topic-shenyan"]}
  ],
  "writingGuidance": []
}
""",
    )
    WorkspaceRegistryService().register_project(project.root)
    return TestClient(app), project


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()
