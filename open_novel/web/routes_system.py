from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import BackgroundTasks, HTTPException

from open_novel.core.update_runtime import (
    UpdateCoordinator,
    UpdateRuntimeError,
    terminate_current_service,
)
from open_novel.core.update_service import UpdatePreparationError, UpdateService
from open_novel.web.app import app

UPDATE_CHECK_CACHE_SECONDS = 60
_update_check_lock = Lock()
_update_check_cached_at = 0.0
_update_check_checked_at = ""
_update_check_cache: dict[str, Any] | None = None


def _check_system_update(*, force: bool) -> tuple[dict[str, Any], str]:
    global _update_check_cache
    global _update_check_cached_at
    global _update_check_checked_at

    with _update_check_lock:
        now = monotonic()
        if (
            not force
            and _update_check_cache is not None
            and now - _update_check_cached_at < UPDATE_CHECK_CACHE_SECONDS
        ):
            return dict(_update_check_cache), _update_check_checked_at

        result = UpdateCoordinator().check()
        checked_at = datetime.now(UTC).isoformat()
        _update_check_cache = dict(result)
        _update_check_cached_at = monotonic()
        _update_check_checked_at = checked_at
        return result, checked_at


def _reset_update_check_cache() -> None:
    global _update_check_cache
    global _update_check_cached_at
    global _update_check_checked_at

    with _update_check_lock:
        _update_check_cache = None
        _update_check_cached_at = 0.0
        _update_check_checked_at = ""


@app.get("/api/system/update")
def api_system_update() -> dict[str, Any]:
    result, _ = _check_system_update(force=True)
    return result


@app.get("/api/system/update/auto-detect")
def api_auto_detect_system_update() -> dict[str, Any]:
    result, checked_at = _check_system_update(force=False)
    return {
        **result,
        "checkedAt": checked_at,
        "pollIntervalSeconds": UPDATE_CHECK_CACHE_SECONDS,
    }


@app.get("/api/system/update/status")
def api_system_update_status() -> dict[str, Any]:
    return UpdateCoordinator().status()


@app.post("/api/system/update/install")
def api_install_system_update(background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        result = UpdateCoordinator().install_latest(service_pid=os.getpid())
    except UpdateRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result["shutdownRequired"] and not os.environ.get(
        "OPEN_NOVEL_DISABLE_UPDATE_SHUTDOWN", ""
    ).strip():
        background_tasks.add_task(terminate_current_service)
    return result


@app.post("/api/system/update/prepare")
def api_prepare_system_update() -> dict[str, Any]:
    try:
        return UpdateService().prepare_latest()
    except UpdatePreparationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
