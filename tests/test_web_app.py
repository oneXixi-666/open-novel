from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from open_novel.server import app
from open_novel.web.app import app as shared_app


def route_paths() -> set[str]:
    return {route.path for route in app.routes}


def is_expected_route(path: str) -> bool:
    return (
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
    )


def test_server_uses_shared_react_api_app() -> None:
    assert app is shared_app


def test_health_route_returns_json() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_optional_access_token_protects_non_health_routes(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_NOVEL_ACCESS_TOKEN", "launch-secret")
    client = TestClient(app)

    health = client.get("/health")
    missing = client.get("/skills")
    wrong = client.get("/skills", headers={"Authorization": "Bearer wrong-secret"})
    bearer = client.get(
        "/skills",
        headers={"Authorization": "Bearer launch-secret"},
    )
    browser_basic = client.get("/skills", auth=("open-novel", "launch-secret"))
    custom_header = client.get(
        "/skills",
        headers={"X-Open-Novel-Token": "launch-secret"},
    )

    assert health.status_code == 200
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Basic")
    assert bearer.status_code == 200
    assert browser_basic.status_code == 200
    assert custom_header.status_code == 200


def test_docker_compose_binds_to_loopback_and_exposes_token_setting() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert "OPEN_NOVEL_ACCESS_TOKEN: ${OPEN_NOVEL_ACCESS_TOKEN:-}" in compose


def test_first_version_keeps_only_api_and_project_routes() -> None:
    paths = route_paths()

    assert "/skills" in paths
    assert "/agents/detect" in paths
    assert "/api/workspace" in paths
    assert "/api/books" in paths
    assert "/projects/workspace" in paths
    assert "/projects/chapter" in paths


def test_route_surface_is_api_only() -> None:
    paths = route_paths()

    assert all(is_expected_route(path) for path in paths)
