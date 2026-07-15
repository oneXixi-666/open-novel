from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from open_novel.core.update_installer import UpdateInstaller, UpdateInstallError
from open_novel.core.update_service import UpdatePreparationError, UpdateService
from open_novel.core.workspace_storage import default_workspace_db_path


class UpdateRuntimeError(RuntimeError):
    """Raised when an automatic update cannot be coordinated safely."""


class UpdateStateStore:
    def __init__(self, update_root: Path | None = None) -> None:
        configured = os.environ.get("OPEN_NOVEL_UPDATE_DIR", "").strip()
        self.root = (
            update_root
            or (Path(configured) if configured else None)
            or Path.cwd() / ".open-novel" / "updates"
        ).expanduser().resolve()
        self.status_path = self.root / "update-status.json"
        self.compose_request_path = self.root / "compose-update-request.json"
        self.compose_helper_path = self.root / "compose-helper.json"

    def read(self) -> dict[str, Any]:
        if not self.status_path.is_file():
            return {
                "phase": "idle",
                "status": "尚未开始更新",
                "message": "可以先检查是否有新版本。",
                "currentVersion": "",
                "targetVersion": "",
                "deploymentMode": deployment_mode(),
                "finished": True,
                "succeeded": False,
                "rolledBack": False,
                "updatedAt": "",
            }
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "phase": "failed",
                "status": "更新状态无法读取",
                "message": "更新状态文件损坏，请检查 .open-novel/updates。",
                "currentVersion": "",
                "targetVersion": "",
                "deploymentMode": deployment_mode(),
                "finished": True,
                "succeeded": False,
                "rolledBack": False,
                "updatedAt": "",
            }
        return payload if isinstance(payload, dict) else {}

    def write(self, **values: Any) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            **self.read(),
            **values,
            "updatedAt": datetime.now(UTC).isoformat(),
        }
        temporary = self.status_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.status_path)
        return payload

    def compose_helper_ready(self, max_age_seconds: int = 15) -> bool:
        try:
            payload = json.loads(self.compose_helper_path.read_text(encoding="utf-8"))
            heartbeat = datetime.fromisoformat(str(payload["heartbeatAt"]))
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return (datetime.now(UTC) - heartbeat).total_seconds() <= max_age_seconds

    def write_compose_heartbeat(self, pid: int) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": pid,
            "heartbeatAt": datetime.now(UTC).isoformat(),
        }
        temporary = self.compose_helper_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.compose_helper_path)


def deployment_mode() -> str:
    value = os.environ.get("OPEN_NOVEL_DEPLOYMENT_MODE", "source").strip().lower()
    return "compose" if value == "compose" else "source"


def health_url() -> str:
    configured = os.environ.get("OPEN_NOVEL_HEALTH_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    port = os.environ.get("OPEN_NOVEL_PORT", "8765").strip() or "8765"
    return f"http://127.0.0.1:{port}/health"


def _configured_command(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise UpdateRuntimeError(f"{name} 必须是 JSON 字符串数组。") from exc
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise UpdateRuntimeError(f"{name} 必须是非空 JSON 字符串数组。")
    return [item.strip() for item in value]


def source_restart_command() -> list[str]:
    configured = _configured_command("OPEN_NOVEL_RESTART_COMMAND")
    if configured:
        return configured
    host = os.environ.get("OPEN_NOVEL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.environ.get("OPEN_NOVEL_PORT", "8765").strip() or "8765"
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "open_novel.server:app",
        "--host",
        host,
        "--port",
        port,
    ]


def source_dependency_command(install_root: Path) -> list[str]:
    configured = _configured_command("OPEN_NOVEL_DEPENDENCY_COMMAND")
    if configured:
        return configured
    uv = shutil.which("uv")
    if uv and (install_root / "uv.lock").is_file():
        return [uv, "sync", "--frozen"]
    return [sys.executable, "-m", "pip", "install", "."]


class UpdateCoordinator:
    def __init__(
        self,
        *,
        service: UpdateService | None = None,
        state: UpdateStateStore | None = None,
        install_root: Path | None = None,
    ) -> None:
        self.service = service or UpdateService()
        self.state = state or UpdateStateStore()
        self.install_root = (install_root or Path.cwd()).expanduser().resolve()

    def check(self) -> dict[str, Any]:
        mode = deployment_mode()
        result = self.service.check()
        automatic_ready = (
            self.state.compose_helper_ready()
            if mode == "compose"
            else (self.install_root / "scripts" / "open_novel_updater.py").is_file()
        )
        return {
            **result,
            "deploymentMode": mode,
            "deploymentLabel": "Docker Compose" if mode == "compose" else "源码单机",
            "automaticUpdateReady": automatic_ready,
            "automaticUpdateMessage": (
                (
                    "宿主机更新助手已连接。"
                    if mode == "compose"
                    else "外部源码更新器已就绪。"
                )
                if automatic_ready
                else (
                    "宿主机更新助手未运行，请先使用项目更新入口启动 Docker Compose。"
                    if mode == "compose"
                    else "源码更新器脚本缺失，当前安装无法执行自动更新。"
                )
            ),
        }

    def status(self) -> dict[str, Any]:
        return self.state.read()

    def install_latest(self, *, service_pid: int) -> dict[str, Any]:
        mode = deployment_mode()
        active_status = self.state.read()
        if not bool(active_status.get("finished", True)):
            raise UpdateRuntimeError("已有更新正在执行，请等待当前更新完成。")
        if mode == "compose" and not self.state.compose_helper_ready():
            raise UpdateRuntimeError(
                "宿主机更新助手未运行，请先执行更新文档中的 Docker Compose 启动命令。"
            )
        script_path = self.install_root / "scripts" / "open_novel_updater.py"
        if mode == "source" and not script_path.is_file():
            raise UpdateRuntimeError("源码更新器脚本不存在，无法启动外部更新进程。")
        try:
            prepared = self.service.prepare_latest(
                update_root=self.state.root,
                database_path=default_workspace_db_path(),
                install_root=self.install_root,
            )
        except UpdatePreparationError as exc:
            raise UpdateRuntimeError(str(exc)) from exc

        plan_path = Path(str(prepared["planPath"])).resolve()
        plan = self._load_plan(plan_path)
        plan.update(
            {
                "deploymentMode": mode,
                "healthUrl": health_url(),
                "restartCommand": source_restart_command() if mode == "source" else [],
                "dependencyCommand": (
                    source_dependency_command(self.install_root) if mode == "source" else []
                ),
            }
        )
        self._write_plan(plan_path, plan)
        self.state.write(
            phase="prepared",
            status="更新包已准备",
            message="更新包和数据库备份已准备，正在交给外部更新进程。",
            currentVersion=str(plan.get("currentVersion") or ""),
            targetVersion=str(plan.get("targetVersion") or ""),
            deploymentMode=mode,
            finished=False,
            succeeded=False,
            rolledBack=False,
            planPath=str(plan_path),
        )

        if mode == "compose":
            request = {
                "schemaVersion": 1,
                "planPath": str(plan_path),
                "targetVersion": str(plan.get("targetVersion") or ""),
                "requestedAt": datetime.now(UTC).isoformat(),
            }
            self._write_json_atomic(self.state.compose_request_path, request)
            self.state.write(
                phase="waiting_host",
                status="等待宿主机更新",
                message="宿主机更新助手将构建新镜像并重启服务。",
            )
            shutdown_required = False
        else:
            command = [
                sys.executable,
                str(script_path),
                "--run-source-plan",
                str(plan_path),
                "--wait-pid",
                str(service_pid),
            ]
            _spawn_detached(command, cwd=self.install_root)
            self.state.write(
                phase="waiting_restart",
                status="等待服务退出",
                message="外部更新进程已启动，当前服务即将重启。",
            )
            shutdown_required = True

        return {
            **prepared,
            "status": "自动更新已启动",
            "message": (
                "宿主机更新助手已接收请求，服务将自动重启。"
                if mode == "compose"
                else "外部更新进程已接管，服务将自动退出、更新并重启。"
            ),
            "deploymentMode": mode,
            "shutdownRequired": shutdown_required,
        }

    def _load_plan(self, plan_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateRuntimeError("更新计划无法读取。") from exc
        if not isinstance(payload, dict):
            raise UpdateRuntimeError("更新计划格式不正确。")
        return payload

    def _write_plan(self, plan_path: Path, plan: dict[str, Any]) -> None:
        self._write_json_atomic(plan_path, plan)

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


class UpdateRuntimeExecutor:
    def __init__(
        self,
        *,
        installer: UpdateInstaller | None = None,
        health_timeout_seconds: int = 120,
    ) -> None:
        self.installer = installer or UpdateInstaller()
        self.health_timeout_seconds = health_timeout_seconds

    def run_source(self, plan_path: Path, *, wait_pid: int) -> dict[str, Any]:
        plan_path = plan_path.expanduser().resolve()
        plan = self._load_plan(plan_path)
        state = UpdateStateStore(plan_path.parent.parent)
        install_root = Path(str(plan["installRoot"])).expanduser().resolve()
        current_version = str(plan.get("currentVersion") or "")
        target_version = str(plan.get("targetVersion") or "")
        dependency_command = self._command(plan, "dependencyCommand")
        restart_command = self._command(plan, "restartCommand")
        health = str(plan.get("healthUrl") or health_url())
        new_process: subprocess.Popen[bytes] | None = None
        applied = False
        try:
            state.write(
                phase="waiting_restart",
                status="等待旧服务退出",
                message="正在等待当前服务安全退出。",
            )
            self.installer.wait_for_process_exit(wait_pid)
            state.write(
                phase="applying",
                status="正在替换程序",
                message="正在应用已校验的新版本文件。",
            )
            self.installer.apply(plan_path)
            applied = True
            state.write(
                phase="syncing_dependencies",
                status="正在同步依赖",
                message="正在按新版本锁定文件同步运行依赖。",
            )
            self._run_command(dependency_command, cwd=install_root)
            state.write(
                phase="restarting",
                status="正在重启服务",
                message="新版本程序已启动，正在等待健康检查。",
            )
            new_process = _spawn_detached(restart_command, cwd=install_root)
            self._wait_for_health(
                health,
                expected_version=target_version,
                process=new_process,
            )
            return state.write(
                phase="success",
                status="更新成功",
                message=f"已更新到版本 {target_version}。",
                finished=True,
                succeeded=True,
                rolledBack=False,
            )
        except Exception as exc:
            if new_process is not None:
                _stop_process(new_process)
            rollback_error = ""
            try:
                state.write(
                    phase="rolling_back",
                    status="正在回滚",
                    message="新版本未通过健康检查，正在恢复更新前版本。",
                )
                if applied:
                    self.installer.rollback(plan_path)
                    self._run_command(dependency_command, cwd=install_root)
                old_process = _spawn_detached(restart_command, cwd=install_root)
                self._wait_for_health(
                    health,
                    expected_version=current_version,
                    process=old_process,
                )
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
            if rollback_error:
                state.write(
                    phase="failed",
                    status="更新失败",
                    message=f"{_error_text(exc)}；自动回滚未完成：{rollback_error}",
                    finished=True,
                    succeeded=False,
                    rolledBack=False,
                )
                raise UpdateRuntimeError("更新失败，自动回滚未完成。") from exc
            return state.write(
                phase="rolled_back",
                status="已自动回滚",
                message=f"{_error_text(exc)}；旧版本已恢复运行，数据库未被修改。",
                finished=True,
                succeeded=False,
                rolledBack=True,
            )

    def run_compose(self, plan_path: Path, *, project_root: Path) -> dict[str, Any]:
        plan_path = plan_path.expanduser().resolve()
        project_root = project_root.expanduser().resolve()
        plan = self._load_plan(plan_path)
        state = UpdateStateStore(project_root / ".open-novel" / "updates")
        current_version = str(plan.get("currentVersion") or "")
        target_version = str(plan.get("targetVersion") or "")
        health = str(
            os.environ.get("OPEN_NOVEL_COMPOSE_HEALTH_URL", "").strip()
            or "http://127.0.0.1:8000/health"
        )
        self._rebase_compose_plan(plan_path, plan, project_root)
        applied = False
        try:
            state.write(
                phase="applying",
                status="正在应用新版本",
                message="宿主机正在替换程序文件并准备构建镜像。",
            )
            self.installer.apply(plan_path)
            applied = True
            state.write(
                phase="building",
                status="正在构建镜像",
                message="正在构建新版本 Docker 镜像。",
            )
            self._run_command(
                ["docker", "compose", "build", "open-novel"],
                cwd=project_root,
            )
            state.write(
                phase="restarting",
                status="正在重启容器",
                message="正在启动新版本容器并保留本地 SQLite 数据卷。",
            )
            self._run_command(
                ["docker", "compose", "up", "-d", "open-novel"],
                cwd=project_root,
            )
            self._wait_for_health(health, expected_version=target_version)
            return state.write(
                phase="success",
                status="更新成功",
                message=f"Docker Compose 已更新到版本 {target_version}。",
                finished=True,
                succeeded=True,
                rolledBack=False,
            )
        except Exception as exc:
            rollback_error = ""
            try:
                state.write(
                    phase="rolling_back",
                    status="正在回滚",
                    message="新容器未通过健康检查，正在恢复旧版本。",
                )
                if applied:
                    self.installer.rollback(plan_path)
                    self._run_command(
                        ["docker", "compose", "build", "open-novel"],
                        cwd=project_root,
                    )
                    self._run_command(
                        ["docker", "compose", "up", "-d", "open-novel"],
                        cwd=project_root,
                    )
                    self._wait_for_health(health, expected_version=current_version)
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
            if rollback_error:
                state.write(
                    phase="failed",
                    status="更新失败",
                    message=f"{_error_text(exc)}；自动回滚未完成：{rollback_error}",
                    finished=True,
                    succeeded=False,
                    rolledBack=False,
                )
                raise UpdateRuntimeError("Docker Compose 更新失败，自动回滚未完成。") from exc
            return state.write(
                phase="rolled_back",
                status="已自动回滚",
                message=f"{_error_text(exc)}；旧容器继续运行，SQLite 数据卷未被替换。",
                finished=True,
                succeeded=False,
                rolledBack=True,
            )

    def _rebase_compose_plan(
        self,
        plan_path: Path,
        plan: dict[str, Any],
        project_root: Path,
    ) -> None:
        package_name = Path(str(plan.get("packagePath") or "")).name
        backup_name = Path(str(plan.get("databaseBackupPath") or "")).name
        plan.update(
            {
                "installRoot": str(project_root),
                "packagePath": str(plan_path.parent / package_name),
                "databasePath": str(project_root / ".open-novel" / "workspace.sqlite3"),
                "databaseBackupPath": (
                    str(plan_path.parent / backup_name) if backup_name else ""
                ),
            }
        )
        temporary = plan_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, plan_path)

    def _run_command(self, command: list[str], *, cwd: Path) -> None:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise UpdateRuntimeError(
                f"命令执行失败：{' '.join(command)}"
                + (f"；{detail[-500:]}" if detail else "")
            )

    def _wait_for_health(
        self,
        url: str,
        *,
        expected_version: str,
        process: subprocess.Popen[bytes] | None = None,
    ) -> None:
        deadline = time.monotonic() + max(1, self.health_timeout_seconds)
        last_error = ""
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise UpdateRuntimeError("新服务进程提前退出。")
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200:
                    payload = response.json()
                    if str(payload.get("version") or "") == expected_version:
                        return
                    last_error = "健康检查返回的版本与目标版本不一致。"
            except (httpx.HTTPError, ValueError) as exc:
                last_error = str(exc)
            time.sleep(0.5)
        raise UpdateRuntimeError(last_error or "等待服务健康检查超时。")

    def _load_plan(self, plan_path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateRuntimeError("更新计划无法读取。") from exc
        if not isinstance(payload, dict):
            raise UpdateRuntimeError("更新计划格式不正确。")
        return payload

    def _command(self, plan: dict[str, Any], key: str) -> list[str]:
        value = plan.get(key)
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise UpdateRuntimeError(f"更新计划缺少有效的 {key}。")
        return value


def terminate_current_service(delay_seconds: float = 1.0) -> None:
    time.sleep(max(0.1, delay_seconds))
    os.kill(os.getpid(), signal.SIGTERM)


def _spawn_detached(command: list[str], *, cwd: Path) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _error_text(exc: Exception) -> str:
    if isinstance(exc, (UpdateInstallError, UpdateRuntimeError)):
        return str(exc)
    return "更新执行过程中发生异常"
