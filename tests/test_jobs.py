from __future__ import annotations

from threading import Event

import pytest

from open_novel.core.jobs import JobController
from open_novel.core.project import ProjectService


def test_job_controller_records_completed_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    job = JobController().run_sync(
        project.root,
        kind="skill-run",
        title="Run chapter writer",
        detail="chapter 001",
        work=lambda _job: {"outputPath": "drafts/001.generated.md"},
    )

    stored = JobController().get_job(project.root, job.jobId)
    jobs = JobController().list_jobs(project.root)

    assert job.status == "completed"
    assert stored.result["outputPath"] == "drafts/001.generated.md"
    assert stored.startedAt is not None
    assert stored.finishedAt is not None
    assert jobs[0].jobId == job.jobId
    assert (project.root / "runs" / "jobs" / "index.json").exists()


def test_job_controller_records_failed_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    with pytest.raises(RuntimeError):
        JobController().run_sync(
            project.root,
            kind="local-training",
            title="Train",
            detail="missing command",
            work=lambda _job: (_ for _ in ()).throw(RuntimeError("training failed")),
        )

    job = JobController().list_jobs(project.root)[0]

    assert job.status == "failed"
    assert job.error == "training failed"
    assert any("job failed" in line for line in job.logs)


def test_job_controller_submit_background_returns_before_work_completes(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    started = Event()
    release = Event()

    def work(_job):
        started.set()
        release.wait(timeout=5)
        return {"done": True}

    job = JobController().submit_background(
        project.root,
        kind="skill-run",
        title="Run chapter writer",
        detail="chapter 001",
        work=work,
    )

    assert job.status == "queued"
    assert started.wait(timeout=2)
    running = JobController().get_job(project.root, job.jobId)
    assert running.status == "running"

    release.set()
    JobController().wait_for_job(job.jobId, timeout=5)
    completed = JobController().get_job(project.root, job.jobId)

    assert completed.status == "completed"
    assert completed.result["done"] is True


def test_job_controller_cancel_queued_job(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    job = JobController().run_sync(
        project.root,
        kind="skill-run",
        title="Run chapter writer",
        detail="chapter 001",
        work=lambda _job: {"ok": True},
    )
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="local-training",
        title="Train",
        detail="queued",
    )

    cancelled = JobController().request_cancel(project.root, queued.jobId)

    assert job.status == "completed"
    assert cancelled.status == "cancelled"
    assert cancelled.requestedCancelAt is not None


def test_job_controller_retry_job_links_original(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")

    with pytest.raises(RuntimeError):
        JobController().run_sync(
            project.root,
            kind="local-training",
            title="Train",
            detail="retry me",
            work=lambda _job: (_ for _ in ()).throw(RuntimeError("first failed")),
            params={"backend": "custom"},
        )
    original = JobController().list_jobs(project.root)[0]

    retry = JobController().retry_job(
        project.root,
        original.jobId,
        work=lambda _job: {"ok": True},
    )
    JobController().wait_for_job(retry.jobId, timeout=5)
    completed = JobController().get_job(project.root, retry.jobId)

    assert completed.status == "completed"
    assert completed.retryOfJobId == original.jobId
    assert completed.params["backend"] == "custom"


def test_job_controller_marks_orphaned_running_jobs_interrupted(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="skill-run",
        title="Run",
        detail="orphan",
    )
    running = JobController()._update(  # noqa: SLF001
        project.root,
        queued,
        status="running",
    )

    interrupted = JobController().mark_orphaned_running_jobs(project.root)
    stored = JobController().get_job(project.root, running.jobId)

    assert interrupted[0].jobId == running.jobId
    assert stored.status == "interrupted"
    assert "no local worker thread" in stored.error


def test_job_controller_recovers_queued_jobs(tmp_path) -> None:
    project = ProjectService().create_project(tmp_path / "demo", title="Demo")
    queued = JobController()._create(  # noqa: SLF001
        project.root,
        kind="skill-run",
        title="Run",
        detail="queued",
        params={"ok": True},
    )

    recovered = JobController().recover_jobs(
        project.root,
        resolver=lambda _job: (lambda _running_job: {"recovered": True}),
    )
    JobController().wait_for_job(queued.jobId, timeout=5)
    completed = JobController().get_job(project.root, queued.jobId)

    assert recovered[0].jobId == queued.jobId
    assert completed.status == "completed"
    assert completed.result["recovered"] is True
