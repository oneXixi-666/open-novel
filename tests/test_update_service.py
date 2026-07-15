from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from open_novel.core.update_runtime import UpdateCoordinator
from open_novel.core.update_service import UpdatePreparationError, UpdateService
from open_novel.server import app
from open_novel.web import routes_system


@pytest.fixture(autouse=True)
def reset_update_check_cache() -> None:
    routes_system._reset_update_check_cache()
    yield
    routes_system._reset_update_check_cache()


def _release_payload(tag: str = "v0.2.0") -> dict[str, object]:
    return {
        "tag_name": tag,
        "name": "Open Novel 0.2.0",
        "body": "新增在线更新能力。",
        "published_at": "2026-07-15T08:00:00Z",
        "html_url": "https://github.com/oneXixi-666/open-novel/releases/tag/v0.2.0",
        "assets": [
            {
                "name": "open-novel-0.2.0.zip",
                "browser_download_url": "https://example.test/open-novel-0.2.0.zip",
            },
            {
                "name": "open-novel-0.2.0.zip.sha256",
                "browser_download_url": "https://example.test/open-novel-0.2.0.zip.sha256",
            },
        ],
    }


def test_update_service_reports_downloadable_new_release() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_release_payload(), request=request)
        )
    )

    result = UpdateService(current_version="0.1.0", client=client).check()

    assert result["checkSucceeded"] is True
    assert result["updateAvailable"] is True
    assert result["downloadReady"] is True
    assert result["latestVersion"] == "0.2.0"
    assert result["status"] == "发现新版本"
    assert result["packageUrl"].endswith("open-novel-0.2.0.zip")
    assert result["checksumUrl"].endswith("open-novel-0.2.0.zip.sha256")


def test_update_service_reports_current_version_and_missing_assets() -> None:
    payload = _release_payload("v0.1.0")
    payload["assets"] = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
    )

    result = UpdateService(current_version="0.1.0", client=client).check()

    assert result["checkSucceeded"] is True
    assert result["updateAvailable"] is False
    assert result["downloadReady"] is False
    assert result["status"] == "已是最新版本"


def test_update_service_returns_chinese_failure_for_unavailable_release() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={}, request=request)
        )
    )

    result = UpdateService(current_version="0.1.0", client=client).check()

    assert result["checkSucceeded"] is False
    assert result["status"] == "检查失败"
    assert "尚未发布" in result["message"]


def test_update_service_falls_back_when_github_api_is_rate_limited() -> None:
    class RedirectClient:
        def get(self, url, **kwargs):
            request = httpx.Request("GET", url)
            if request.url.host == "api.github.com":
                return httpx.Response(403, request=request)
            redirected_request = httpx.Request(
                "GET",
                "https://github.com/oneXixi-666/open-novel/releases/tag/v0.2.0",
            )
            return httpx.Response(200, request=redirected_request)

    result = UpdateService(
        current_version="0.1.0",
        client=RedirectClient(),  # type: ignore[arg-type]
    ).check()

    assert result["checkSucceeded"] is True
    assert result["latestVersion"] == "0.2.0"
    assert result["downloadReady"] is True
    assert result["packageUrl"].endswith("/v0.2.0/open-novel-0.2.0.zip")


def test_system_update_endpoint_uses_configured_api(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_NOVEL_UPDATE_API_URL", "https://example.test/latest")

    def fake_check(self):
        return {
            "checkSucceeded": True,
            "currentVersion": "0.1.0",
            "latestVersion": "0.2.0",
            "updateAvailable": True,
            "downloadReady": True,
            "status": "发现新版本",
            "message": "版本 0.2.0 已发布，可以下载安装。",
            "releaseName": "Open Novel 0.2.0",
            "releaseNotes": "",
            "publishedAt": "",
            "releaseUrl": "",
            "packageUrl": "https://example.test/open-novel-0.2.0.zip",
            "checksumUrl": "https://example.test/open-novel-0.2.0.zip.sha256",
        }

    monkeypatch.setattr(UpdateService, "check", fake_check)

    response = TestClient(app).get("/api/system/update")

    assert response.status_code == 200
    assert response.json()["latestVersion"] == "0.2.0"


def test_system_update_auto_detect_endpoint_returns_polling_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        UpdateCoordinator,
        "check",
        lambda self: {
            "checkSucceeded": True,
            "currentVersion": "0.1.0",
            "latestVersion": "0.2.0",
            "updateAvailable": True,
        },
    )

    response = TestClient(app).get("/api/system/update/auto-detect")

    assert response.status_code == 200
    assert response.json()["updateAvailable"] is True
    assert response.json()["pollIntervalSeconds"] == 60
    assert response.json()["checkedAt"].endswith("+00:00")


def test_system_update_auto_detect_reuses_shared_cache(monkeypatch) -> None:
    calls = 0

    def fake_check(self):
        nonlocal calls
        calls += 1
        return {
            "checkSucceeded": True,
            "currentVersion": "0.1.0",
            "latestVersion": "0.2.0",
            "updateAvailable": True,
        }

    monkeypatch.setattr(UpdateCoordinator, "check", fake_check)
    client = TestClient(app)

    first = client.get("/api/system/update/auto-detect")
    second = client.get("/api/system/update/auto-detect")

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["checkedAt"] == second.json()["checkedAt"]


def test_manual_update_check_refreshes_shared_cache(monkeypatch) -> None:
    calls = 0

    def fake_check(self):
        nonlocal calls
        calls += 1
        return {
            "checkSucceeded": True,
            "currentVersion": "0.1.0",
            "latestVersion": f"0.{calls}.0",
            "updateAvailable": True,
        }

    monkeypatch.setattr(UpdateCoordinator, "check", fake_check)
    client = TestClient(app)

    first = client.get("/api/system/update/auto-detect")
    manual = client.get("/api/system/update")
    cached = client.get("/api/system/update/auto-detect")

    assert first.json()["latestVersion"] == "0.1.0"
    assert manual.json()["latestVersion"] == "0.2.0"
    assert cached.json()["latestVersion"] == "0.2.0"
    assert calls == 2


def test_update_service_prepares_verified_package_and_database_backup(tmp_path) -> None:
    package = b"verified release package"
    checksum = sha256(package).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/latest"):
            return httpx.Response(200, json=_release_payload(), request=request)
        if request.url.path.endswith(".zip.sha256"):
            return httpx.Response(
                200,
                text=f"{checksum}  open-novel-0.2.0.zip\n",
                request=request,
            )
        return httpx.Response(200, content=package, request=request)

    db_path = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (value) VALUES ('保留数据')")
    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = UpdateService(
        current_version="0.1.0",
        api_url="https://example.test/latest",
        client=client,
    ).prepare_latest(
        update_root=tmp_path / "updates",
        database_path=db_path,
        install_root=tmp_path / "application",
    )

    plan_path = Path(result["planPath"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert Path(result["packagePath"]).read_bytes() == package
    assert plan["packageSha256"] == checksum
    assert plan["status"] == "prepared"
    with sqlite3.connect(result["databaseBackupPath"]) as conn:
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "保留数据"


def test_update_service_rejects_bad_checksum_without_leaving_package(tmp_path) -> None:
    package = b"tampered release package"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/latest"):
            return httpx.Response(200, json=_release_payload(), request=request)
        if request.url.path.endswith(".zip.sha256"):
            return httpx.Response(
                200,
                text=f"{'0' * 64}  open-novel-0.2.0.zip\n",
                request=request,
            )
        return httpx.Response(200, content=package, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = UpdateService(
        current_version="0.1.0",
        api_url="https://example.test/latest",
        client=client,
    )

    with pytest.raises(UpdatePreparationError, match="校验失败"):
        service.prepare_latest(update_root=tmp_path / "updates")

    assert not list((tmp_path / "updates").rglob("*.zip"))
