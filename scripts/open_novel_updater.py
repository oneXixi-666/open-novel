from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from open_novel.core.update_installer import UpdateInstaller, UpdateInstallError
from open_novel.core.update_runtime import (
    UpdateRuntimeError,
    UpdateRuntimeExecutor,
    UpdateStateStore,
)
from open_novel.core.update_service import UpdatePreparationError, UpdateService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check and safely prepare an Open Novel release update."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only query and print the latest release information.",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Download, verify, back up the database, and write an update plan.",
    )
    parser.add_argument(
        "--apply-plan",
        type=Path,
        help="Apply a prepared plan after the running service has exited.",
    )
    parser.add_argument(
        "--rollback-plan",
        type=Path,
        help="Restore application files saved by an applied update plan.",
    )
    parser.add_argument(
        "--run-source-plan",
        type=Path,
        help="Apply, restart, health-check, and roll back a source installation.",
    )
    parser.add_argument(
        "--run-compose-plan",
        type=Path,
        help="Apply, rebuild, health-check, and roll back a Docker Compose installation.",
    )
    parser.add_argument(
        "--watch-compose",
        action="store_true",
        help="Run the host-side Docker Compose update helper.",
    )
    parser.add_argument(
        "--compose-up",
        action="store_true",
        help="Start Docker Compose and its detached host-side update helper.",
    )
    parser.add_argument(
        "--compose-down",
        action="store_true",
        help="Stop the host-side update helper and Docker Compose.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the persisted automatic update status.",
    )
    parser.add_argument(
        "--wait-pid",
        type=int,
        default=0,
        help="Wait for this service process id to exit before applying a plan.",
    )
    parser.add_argument(
        "--update-dir",
        type=Path,
        help="Directory used for downloaded update packages and plans.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Workspace SQLite path to back up before an update.",
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        default=Path.cwd(),
        help="Application installation root recorded in the update plan.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Docker Compose project root used by the host-side helper.",
    )
    return parser.parse_args()


def print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    actions = [
        args.check,
        args.prepare,
        bool(args.apply_plan),
        bool(args.rollback_plan),
        bool(args.run_source_plan),
        bool(args.run_compose_plan),
        args.watch_compose,
        args.compose_up,
        args.compose_down,
        args.status,
    ]
    if sum(bool(action) for action in actions) != 1:
        raise SystemExit("必须且只能选择一种更新操作。")
    project_root = args.project_root.expanduser().resolve()
    if args.status:
        print_payload(UpdateStateStore(project_root / ".open-novel" / "updates").read())
        return 0
    if args.compose_up:
        return compose_up(project_root)
    if args.compose_down:
        return compose_down(project_root)
    if args.watch_compose:
        return watch_compose(project_root)
    executor = UpdateRuntimeExecutor()
    if args.run_source_plan:
        try:
            print_payload(
                executor.run_source(
                    args.run_source_plan,
                    wait_pid=args.wait_pid,
                )
            )
        except UpdateRuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    if args.run_compose_plan:
        try:
            print_payload(
                executor.run_compose(
                    args.run_compose_plan,
                    project_root=project_root,
                )
            )
        except UpdateRuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    installer = UpdateInstaller()
    if args.apply_plan:
        try:
            installer.wait_for_process_exit(args.wait_pid)
            print_payload(installer.apply(args.apply_plan))
        except UpdateInstallError as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    if args.rollback_plan:
        try:
            print_payload(installer.rollback(args.rollback_plan))
        except UpdateInstallError as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    service = UpdateService()
    if args.check:
        print_payload(service.check())
        return 0
    try:
        result = service.prepare_latest(
            update_root=args.update_dir,
            database_path=args.database,
            install_root=args.install_root,
        )
    except UpdatePreparationError as exc:
        raise SystemExit(str(exc)) from exc
    print_payload(result)
    return 0


def compose_up(project_root: Path) -> int:
    completed = subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=project_root,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit("Docker Compose 启动失败，未启动宿主机更新助手。")
    helper_pid_path = _helper_pid_path(project_root)
    existing_pid = _read_pid(helper_pid_path)
    if existing_pid and _process_exists(existing_pid):
        print_payload(
            {
                "status": "Docker Compose 已启动",
                "message": "服务和宿主机更新助手均已运行。",
                "helperPid": existing_pid,
            }
        )
        return 0
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--watch-compose",
        "--project-root",
        str(project_root),
    ]
    kwargs: dict[str, Any] = {
        "cwd": project_root,
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
    process = subprocess.Popen(command, **kwargs)
    helper_pid_path.parent.mkdir(parents=True, exist_ok=True)
    helper_pid_path.write_text(f"{process.pid}\n", encoding="ascii")
    state = UpdateStateStore(project_root / ".open-novel" / "updates")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not state.compose_helper_ready():
        if process.poll() is not None:
            raise SystemExit("宿主机更新助手启动失败。")
        time.sleep(0.2)
    print_payload(
        {
            "status": "Docker Compose 已启动",
            "message": "服务和宿主机更新助手均已运行。",
            "helperPid": process.pid,
        }
    )
    return 0


def compose_down(project_root: Path) -> int:
    helper_pid_path = _helper_pid_path(project_root)
    pid = _read_pid(helper_pid_path)
    if pid and _process_exists(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    helper_pid_path.unlink(missing_ok=True)
    UpdateStateStore(project_root / ".open-novel" / "updates").compose_helper_path.unlink(
        missing_ok=True
    )
    completed = subprocess.run(
        ["docker", "compose", "down"],
        cwd=project_root,
        check=False,
    )
    return completed.returncode


def watch_compose(project_root: Path) -> int:
    state = UpdateStateStore(project_root / ".open-novel" / "updates")
    stop = False

    def request_stop(signum, frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        state.write_compose_heartbeat(os.getpid())
        request_path = state.compose_request_path
        if request_path.is_file():
            processing_path = request_path.with_name("compose-update-processing.json")
            try:
                os.replace(request_path, processing_path)
                request = json.loads(processing_path.read_text(encoding="utf-8"))
                plan_path = _host_plan_path(
                    project_root,
                    str(request.get("planPath") or ""),
                    str(request.get("targetVersion") or ""),
                )
                UpdateRuntimeExecutor().run_compose(
                    plan_path,
                    project_root=project_root,
                )
            except Exception as exc:
                state.write(
                    phase="failed",
                    status="更新失败",
                    message=f"宿主机更新助手执行失败：{exc}",
                    finished=True,
                    succeeded=False,
                    rolledBack=False,
                )
            finally:
                processing_path.unlink(missing_ok=True)
        time.sleep(1)
    state.compose_helper_path.unlink(missing_ok=True)
    _helper_pid_path(project_root).unlink(missing_ok=True)
    return 0


def _host_plan_path(project_root: Path, container_path: str, target_version: str) -> Path:
    filename = Path(container_path).name or "update-plan.json"
    if not target_version:
        raise UpdateRuntimeError("Docker Compose 更新请求缺少目标版本。")
    path = (
        project_root
        / ".open-novel"
        / "updates"
        / target_version
        / filename
    ).resolve()
    try:
        path.relative_to((project_root / ".open-novel" / "updates").resolve())
    except ValueError as exc:
        raise UpdateRuntimeError("Docker Compose 更新计划路径越界。") from exc
    if not path.is_file():
        raise UpdateRuntimeError("Docker Compose 更新计划不存在。")
    return path


def _helper_pid_path(project_root: Path) -> Path:
    return project_root / ".open-novel" / "updates" / "compose-helper.pid"


def _read_pid(path: Path) -> int:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
