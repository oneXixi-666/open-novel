from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import open_novel.core.update_runtime as update_runtime
from open_novel.core.update_runtime import (
    UpdateCoordinator,
    UpdateRuntimeError,
    UpdateRuntimeExecutor,
    UpdateStateStore,
)
from open_novel.server import app


class FakeProcess:
    def __init__(self) -> None:
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self) -> None:
        self.stopped = True

    def wait(self, timeout=None) -> int:
        self.stopped = True
        return 0

    def kill(self) -> None:
        self.stopped = True


class FakeInstaller:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def wait_for_process_exit(self, pid: int, timeout_seconds: int = 120) -> None:
        self.actions.append(f"wait:{pid}")

    def apply(self, plan_path: Path) -> dict[str, object]:
        self.actions.append("apply")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["status"] = "applied"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return {}

    def rollback(self, plan_path: Path) -> dict[str, object]:
        self.actions.append("rollback")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["status"] = "rolled_back"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return {}


class RecordingExecutor(UpdateRuntimeExecutor):
    def __init__(self, installer: FakeInstaller, *, fail_target_health: bool = False) -> None:
        super().__init__(installer=installer)
        self.commands: list[list[str]] = []
        self.health_versions: list[str] = []
        self.fail_target_health = fail_target_health

    def _run_command(self, command: list[str], *, cwd: Path) -> None:
        self.commands.append(command)

    def _wait_for_health(
        self,
        url: str,
        *,
        expected_version: str,
        process=None,
    ) -> None:
        self.health_versions.append(expected_version)
        if self.fail_target_health and len(self.health_versions) == 1:
            raise UpdateRuntimeError("目标版本健康检查失败。")


def _write_runtime_plan(root: Path, *, mode: str = "source") -> Path:
    update_dir = root / ".open-novel" / "updates" / "0.2.0"
    update_dir.mkdir(parents=True)
    package_path = update_dir / "open-novel-0.2.0.zip"
    package_path.write_bytes(b"package")
    plan_path = update_dir / "update-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "status": "prepared",
                "currentVersion": "0.1.0",
                "targetVersion": "0.2.0",
                "installRoot": str(root),
                "packagePath": str(package_path),
                "packageSha256": "unused-by-fake",
                "databasePath": str(root / ".open-novel" / "workspace.sqlite3"),
                "databaseBackupPath": "",
                "deploymentMode": mode,
                "healthUrl": "http://127.0.0.1:9999/health",
                "dependencyCommand": ["dependency-sync"],
                "restartCommand": ["restart-service"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return plan_path


def test_source_runtime_applies_restarts_and_reports_success(tmp_path, monkeypatch) -> None:
    plan_path = _write_runtime_plan(tmp_path)
    installer = FakeInstaller()
    executor = RecordingExecutor(installer)
    processes: list[FakeProcess] = []

    def fake_spawn(command, *, cwd):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(update_runtime, "_spawn_detached", fake_spawn)

    result = executor.run_source(plan_path, wait_pid=123)

    assert installer.actions == ["wait:123", "apply"]
    assert executor.commands == [["dependency-sync"]]
    assert executor.health_versions == ["0.2.0"]
    assert result["phase"] == "success"
    assert result["succeeded"] is True
    assert len(processes) == 1


def test_source_runtime_rolls_back_and_restarts_old_version(tmp_path, monkeypatch) -> None:
    plan_path = _write_runtime_plan(tmp_path)
    installer = FakeInstaller()
    executor = RecordingExecutor(installer, fail_target_health=True)
    processes: list[FakeProcess] = []

    def fake_spawn(command, *, cwd):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(update_runtime, "_spawn_detached", fake_spawn)

    result = executor.run_source(plan_path, wait_pid=123)

    assert installer.actions == ["wait:123", "apply", "rollback"]
    assert executor.commands == [["dependency-sync"], ["dependency-sync"]]
    assert executor.health_versions == ["0.2.0", "0.1.0"]
    assert processes[0].stopped is True
    assert result["phase"] == "rolled_back"
    assert result["rolledBack"] is True


def test_compose_runtime_builds_and_restarts_service(tmp_path) -> None:
    plan_path = _write_runtime_plan(tmp_path, mode="compose")
    installer = FakeInstaller()
    executor = RecordingExecutor(installer)

    result = executor.run_compose(plan_path, project_root=tmp_path)

    assert installer.actions == ["apply"]
    assert executor.commands == [
        ["docker", "compose", "build", "open-novel"],
        ["docker", "compose", "up", "-d", "open-novel"],
    ]
    assert executor.health_versions == ["0.2.0"]
    assert result["phase"] == "success"


def test_compose_runtime_rolls_back_after_health_failure(tmp_path) -> None:
    plan_path = _write_runtime_plan(tmp_path, mode="compose")
    installer = FakeInstaller()
    executor = RecordingExecutor(installer, fail_target_health=True)

    result = executor.run_compose(plan_path, project_root=tmp_path)

    assert installer.actions == ["apply", "rollback"]
    assert executor.commands == [
        ["docker", "compose", "build", "open-novel"],
        ["docker", "compose", "up", "-d", "open-novel"],
        ["docker", "compose", "build", "open-novel"],
        ["docker", "compose", "up", "-d", "open-novel"],
    ]
    assert executor.health_versions == ["0.2.0", "0.1.0"]
    assert result["phase"] == "rolled_back"


def test_coordinator_starts_detached_source_update(tmp_path, monkeypatch) -> None:
    class FakeService:
        def prepare_latest(self, **kwargs):
            plan_path = _write_runtime_plan(tmp_path)
            return {
                "status": "更新包已准备",
                "message": "prepared",
                "currentVersion": "0.1.0",
                "targetVersion": "0.2.0",
                "planPath": str(plan_path),
                "packagePath": str(plan_path.parent / "open-novel-0.2.0.zip"),
                "databaseBackupPath": "",
                "restartRequired": True,
            }

    script = tmp_path / "scripts" / "open_novel_updater.py"
    script.parent.mkdir()
    script.write_text("pass\n", encoding="utf-8")
    spawned: list[list[str]] = []
    monkeypatch.setenv("OPEN_NOVEL_DEPLOYMENT_MODE", "source")
    monkeypatch.setattr(
        update_runtime,
        "_spawn_detached",
        lambda command, cwd: spawned.append(command) or FakeProcess(),
    )

    result = UpdateCoordinator(
        service=FakeService(),  # type: ignore[arg-type]
        state=UpdateStateStore(tmp_path / ".open-novel" / "updates"),
        install_root=tmp_path,
    ).install_latest(service_pid=456)

    assert result["shutdownRequired"] is True
    assert spawned and "--run-source-plan" in spawned[0]
    plan = json.loads(Path(result["planPath"]).read_text(encoding="utf-8"))
    assert plan["deploymentMode"] == "source"
    assert plan["restartCommand"]
    assert plan["dependencyCommand"]


def test_compose_install_requires_live_host_helper(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DEPLOYMENT_MODE", "compose")
    coordinator = UpdateCoordinator(
        state=UpdateStateStore(tmp_path / ".open-novel" / "updates"),
        install_root=tmp_path,
    )

    with pytest.raises(UpdateRuntimeError, match="宿主机更新助手未运行"):
        coordinator.install_latest(service_pid=1)


def test_update_status_endpoint_returns_persisted_state(tmp_path, monkeypatch) -> None:
    update_root = tmp_path / "updates"
    monkeypatch.setenv("OPEN_NOVEL_UPDATE_DIR", str(update_root))
    UpdateStateStore(update_root).write(
        phase="success",
        status="更新成功",
        message="已更新。",
        currentVersion="0.1.0",
        targetVersion="0.2.0",
        deploymentMode="source",
        finished=True,
        succeeded=True,
        rolledBack=False,
    )

    response = TestClient(app).get("/api/system/update/status")

    assert response.status_code == 200
    assert response.json()["phase"] == "success"
