from __future__ import annotations

from open_novel.web.author_presenter import (
    job_kind_label,
    job_progress_label,
    job_status_label,
    pipeline_message_label,
    pipeline_status_label,
    pipeline_step_label,
    run_preview,
    run_status_label,
)


def test_author_presenter_labels_pipeline_for_default_author_view() -> None:
    assert pipeline_step_label("scene_contract") == "章节要求"
    assert pipeline_step_label("context_pack") == "本章资料"
    assert pipeline_step_label("unknown_step") == "unknown step"
    assert pipeline_status_label("ready") == "已准备"
    assert pipeline_status_label("blocked") == "需处理"
    assert pipeline_message_label("artifact exists") == "已准备好"


def test_author_presenter_filters_run_preview_plumbing() -> None:
    preview = run_preview(
        "\n".join(
            [
                "skillId: chapter-writer",
                "agentId: local",
                "Use Context Pack and drafts/001.generated.md",
                '{"outputPath": "drafts/001.generated.md"}',
                "```json",
                '{"runId": "run_001"}',
                "```",
            ]
        ),
        "empty",
    )

    assert "skillId" not in preview
    assert "agentId" not in preview
    assert "drafts/001.generated.md" not in preview
    assert "本章资料" in preview
    assert "相关资料" in preview


def test_author_presenter_labels_runs_and_jobs() -> None:
    assert run_status_label("running") == "进行中"
    assert run_status_label("") == "已有记录"
    assert job_kind_label("chapter-draft") == "AI 起草"
    assert job_kind_label("skill-run") == "写作任务"
    assert "后台" not in job_kind_label("unknown-kind")
    assert job_status_label("cancelled") == "已取消"
    assert job_progress_label({"completed": 2, "total": 5}) == "进度 2/5"
    assert job_progress_label({"step": "build-context"}) == "进度 build-context"
