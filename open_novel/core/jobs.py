from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from open_novel.core.models import JobRecord
from open_novel.core.project import ProjectService

T = TypeVar("T")


class JobController:
    jobs_dir = "runs/jobs"
    index_path = "runs/jobs/index.json"
    _threads: dict[str, threading.Thread] = {}
    _lock = threading.Lock()

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def run_sync(
        self,
        root: Path,
        kind: str,
        title: str,
        detail: str,
        work: Callable[[JobRecord], T],
        *,
        params: dict[str, object] | None = None,
    ) -> JobRecord:
        project = self.project_service.open_project(root)
        job = self._create(project.root, kind, title, detail, params=params)
        return self._run_existing_job(project.root, job, work)

    def submit_background(
        self,
        root: Path,
        kind: str,
        title: str,
        detail: str,
        work: Callable[[JobRecord], T],
        *,
        retry_of_job_id: str = "",
        params: dict[str, object] | None = None,
    ) -> JobRecord:
        project = self.project_service.open_project(root)
        job = self._create(
            project.root,
            kind,
            title,
            detail,
            retry_of_job_id=retry_of_job_id,
            params=params,
        )
        thread = threading.Thread(
            target=self._background_target,
            args=(project.root, job, work),
            name=f"open-novel-{job.jobId}",
            daemon=True,
        )
        with self._lock:
            self._threads[job.jobId] = thread
        thread.start()
        return job

    def wait_for_job(self, job_id: str, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)

    def request_cancel(self, root: Path, job_id: str) -> JobRecord:
        project = self.project_service.open_project(root)
        job = self.get_job(project.root, job_id)
        if job.status in {"completed", "failed", "cancelled"}:
            return job
        return self._update(
            project.root,
            job,
            status="cancelled" if job.status == "queued" else job.status,
            requestedCancelAt=datetime.now(UTC),
            finishedAt=datetime.now(UTC) if job.status == "queued" else job.finishedAt,
            logs=[*job.logs, "cancel requested"],
        )

    def retry_job(
        self,
        root: Path,
        job_id: str,
        work: Callable[[JobRecord], T],
    ) -> JobRecord:
        project = self.project_service.open_project(root)
        original = self.get_job(project.root, job_id)
        return self.submit_background(
            project.root,
            original.kind,
            original.title,
            original.detail,
            work,
            retry_of_job_id=original.jobId,
            params=original.params,
        )

    def update_progress(
        self,
        root: Path,
        job_id: str,
        progress: dict[str, object],
        message: str = "",
    ) -> JobRecord:
        project = self.project_service.open_project(root)
        job = self.get_job(project.root, job_id)
        logs = [*job.logs, message] if message else job.logs
        return self._update(project.root, job, progress=progress, logs=logs)

    def is_cancel_requested(self, root: Path, job_id: str) -> bool:
        try:
            job = self.get_job(root, job_id)
        except (FileNotFoundError, ValueError):
            return False
        return job.requestedCancelAt is not None

    def _background_target(
        self,
        root: Path,
        job: JobRecord,
        work: Callable[[JobRecord], T],
    ) -> None:
        try:
            self._run_existing_job(root, job, work)
        except Exception:
            pass
        finally:
            with self._lock:
                self._threads.pop(job.jobId, None)

    def recover_jobs(
        self,
        root: Path,
        resolver: Callable[[JobRecord], Callable[[JobRecord], object]],
    ) -> list[JobRecord]:
        project = self.project_service.open_project(root)
        recovered: list[JobRecord] = []
        recovered.extend(self.mark_orphaned_running_jobs(project.root))
        for job in self.list_jobs(project.root, limit=200):
            if job.status != "queued":
                continue
            if job.requestedCancelAt is not None:
                recovered.append(
                    self._update(
                        project.root,
                        job,
                        status="cancelled",
                        finishedAt=datetime.now(UTC),
                        logs=[*job.logs, "queued job cancelled during recovery"],
                    )
                )
                continue
            try:
                work = resolver(job)
            except Exception as exc:
                recovered.append(
                    self._update(
                        project.root,
                        job,
                        status="failed",
                        finishedAt=datetime.now(UTC),
                        error=str(exc),
                        logs=[*job.logs, f"job recovery failed: {exc}"],
                    )
                )
                continue
            recovered.append(self._start_existing_background(project.root, job, work))
        return recovered

    def mark_orphaned_running_jobs(self, root: Path) -> list[JobRecord]:
        project = self.project_service.open_project(root)
        interrupted: list[JobRecord] = []
        with self._lock:
            live_job_ids = set(self._threads)
        for job in self.list_jobs(project.root, limit=200):
            if job.status != "running" or job.jobId in live_job_ids:
                continue
            interrupted.append(
                self._update(
                    project.root,
                    job,
                    status="interrupted",
                    finishedAt=datetime.now(UTC),
                    error="job was running but no local worker thread is active",
                    logs=[*job.logs, "job interrupted during recovery"],
                )
            )
        return interrupted

    def _start_existing_background(
        self,
        root: Path,
        job: JobRecord,
        work: Callable[[JobRecord], object],
    ) -> JobRecord:
        thread = threading.Thread(
            target=self._background_target,
            args=(root, job, work),
            name=f"open-novel-{job.jobId}",
            daemon=True,
        )
        with self._lock:
            self._threads[job.jobId] = thread
        thread.start()
        return job

    def _run_existing_job(
        self,
        root: Path,
        job: JobRecord,
        work: Callable[[JobRecord], T],
    ) -> JobRecord:
        try:
            if self.is_cancel_requested(root, job.jobId):
                return self._update(
                    root,
                    job,
                    status="cancelled",
                    finishedAt=datetime.now(UTC),
                    logs=[*job.logs, "job cancelled before start"],
                )
            job = self._update(
                root,
                job,
                status="running",
                startedAt=datetime.now(UTC),
                logs=[*job.logs, "job started"],
            )
            result = work(job)
            latest = self.get_job(root, job.jobId)
            result_dict = self._result_to_dict(result)
            result_status = result_dict.get("status")
            if result_status == "cancelled":
                return self._update(
                    root,
                    latest,
                    status="cancelled",
                    finishedAt=datetime.now(UTC),
                    result=result_dict,
                    logs=[*latest.logs, "job cancelled by worker result"],
                )
            if latest.requestedCancelAt is not None:
                return self._update(
                    root,
                    latest,
                    status="cancelled",
                    finishedAt=datetime.now(UTC),
                    result=result_dict,
                    logs=[*latest.logs, "job cancelled after work finished"],
                )
            job = self._update(
                root,
                latest,
                status="completed",
                finishedAt=datetime.now(UTC),
                result=result_dict,
                logs=[*latest.logs, "job completed"],
            )
        except Exception as exc:
            latest = self.get_job(root, job.jobId)
            if latest.requestedCancelAt is not None:
                return self._update(
                    root,
                    latest,
                    status="cancelled",
                    finishedAt=datetime.now(UTC),
                    error=str(exc),
                    logs=[*latest.logs, f"job cancelled with error: {exc}"],
                )
            self._update(
                root,
                latest,
                status="failed",
                finishedAt=datetime.now(UTC),
                error=str(exc),
                logs=[*latest.logs, f"job failed: {exc}"],
            )
            raise
        return job

    def list_jobs(self, root: Path, limit: int = 50) -> list[JobRecord]:
        project = self.project_service.open_project(root)
        jobs: list[JobRecord] = []
        for relative_path in reversed(
            self.project_service.list_paths(project.root, self.jobs_dir)
        ):
            if not relative_path.endswith(".json") or relative_path == self.index_path:
                continue
            try:
                jobs.append(
                    JobRecord.model_validate_json(
                        self.project_service.read_text(project.root, relative_path)
                    )
                )
            except ValueError:
                continue
        return jobs[:limit]

    def get_job(self, root: Path, job_id: str) -> JobRecord:
        project = self.project_service.open_project(root)
        relative_path = f"{self.jobs_dir}/{job_id}.json"
        if not self.project_service.file_exists(project.root, relative_path):
            raise FileNotFoundError(f"missing job: {job_id}")
        return JobRecord.model_validate_json(
            self.project_service.read_text(project.root, relative_path)
        )

    def _create(
        self,
        root: Path,
        kind: str,
        title: str,
        detail: str,
        *,
        retry_of_job_id: str = "",
        params: dict[str, object] | None = None,
    ) -> JobRecord:
        job = JobRecord(
            jobId=self._new_job_id(),
            kind=kind,
            status="queued",
            title=title,
            detail=detail,
            retryOfJobId=retry_of_job_id,
            params=params or {},
            logs=["job queued"],
        )
        self._write(root, job)
        return job

    def _update(self, root: Path, job: JobRecord, **updates: object) -> JobRecord:
        data = job.model_dump()
        data.update(updates)
        updated = JobRecord.model_validate(data)
        self._write(root, updated)
        return updated

    def _write(self, root: Path, job: JobRecord) -> None:
        text = json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self.project_service.write_text(root, f"{self.jobs_dir}/{job.jobId}.json", text)
        self._write_index(root)

    def _write_index(self, root: Path) -> None:
        jobs = [
            job.model_dump(mode="json", exclude={"logs"})
            for job in self.list_jobs(root, limit=200)
        ]
        self.project_service.write_text(
            root,
            self.index_path,
            json.dumps({"schemaVersion": 1, "jobs": jobs}, ensure_ascii=False, indent=2) + "\n",
        )

    def _new_job_id(self) -> str:
        return "job_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")

    def _result_to_dict(self, result: object) -> dict[str, object]:
        if result is None:
            return {}
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")  # type: ignore[no-any-return, attr-defined]
        if isinstance(result, dict):
            return result
        return {"value": str(result)}
