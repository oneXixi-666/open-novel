from __future__ import annotations

from pathlib import Path
from typing import Any


class WorkbenchRunService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def runs_for_roots(self, roots: list[Path]) -> list[dict[str, Any]]:
        return [run for root in roots for run in self.runs_for_root(root)]

    def runs_for_root(self, root: Path) -> list[dict[str, Any]]:
        file_runs = [
            self.run_summary(root, run)
            for run in self.presenter.project_service.list_runs(root, limit=50)
        ]
        for run in file_runs:
            self.presenter.workbench_repository.upsert_run_summary(root, run)
        stored_runs = self.presenter.workbench_repository.list_run_summaries(root)
        by_id = {str(run.get("id")): run for run in stored_runs}
        by_id.update({str(run.get("id")): run for run in file_runs})
        return list(by_id.values())

    def run_summary(self, root: Path, run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run.get("runId") or Path(str(run.get("path") or "run")).parent.name)
        skill_id = str(run.get("skillId") or run.get("kind") or "run")
        status = str(run.get("status") or "成功")
        summary = str(
            run.get("summary") or run.get("outputPath") or run.get("path") or "运行记录已生成。"
        )
        title = str(run.get("title") or self.run_title(skill_id, run_id))
        if skill_id == "model-comparison":
            title = self.model_comparison_title(run, run_id)
            summary = self.model_comparison_summary(run, summary)
            status = self.model_comparison_status(run)
        return {
            "id": run_id,
            "bookId": root.as_posix(),
            "title": title,
            "kind": self.run_kind(skill_id),
            "status": (
                "失败"
                if status in {"failed", "error"}
                else "警告"
                if status in {"warn", "warning"}
                else "成功"
            ),
            "createdAt": (
                self.short_date(str(run.get("createdAt") or run.get("updatedAt") or ""))
                or "未知时间"
            ),
            "summary": summary,
        }

    def run_title(self, skill_id: str, run_id: str) -> str:
        label = {
            "chapter-writer": "章节生成",
            "line-editor": "段落润色",
            "review": "审稿运行",
        }.get(skill_id, skill_id)
        return f"{label} · {run_id}"

    def run_kind(self, skill_id: str) -> str:
        if "review" in skill_id or "gate" in skill_id or "quality" in skill_id:
            return "审稿"
        if "export" in skill_id:
            return "导出"
        if "model" in skill_id or "training" in skill_id:
            return "模型"
        return "生成"

    def model_comparison_title(self, run: dict[str, Any], fallback_id: str) -> str:
        start = str(run.get("startChapterId") or "")
        end = str(run.get("endChapterId") or "")
        if start and end:
            return f"模型对比 · {start}-{end}"
        return f"模型对比 · {fallback_id}"

    def model_comparison_summary(self, run: dict[str, Any], fallback: str) -> str:
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        if isinstance(summary, dict):
            best_candidate_id = str(summary.get("bestCandidateId") or "")
            safe = bool(summary.get("safeToSetDefault"))
            reasons = (
                summary.get("promotionReasons")
                if isinstance(summary.get("promotionReasons"), list)
                else []
            )
            if best_candidate_id:
                safety = "可直接提升为默认模型" if safe else "暂不建议直接切换默认"
                reason_text = str(reasons[0]) if reasons else "已生成模型比较摘要。"
                return f"最佳候选：{best_candidate_id}，{safety}。{reason_text}"
        return fallback

    def model_comparison_status(self, run: dict[str, Any]) -> str:
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        if not isinstance(summary, dict):
            return str(run.get("status") or "成功")
        best_status = str(summary.get("bestStatus") or "")
        if best_status == "block":
            return "failed"
        if best_status == "warn":
            return "warn"
        return str(run.get("status") or "成功")

    def short_date(self, value: str) -> str:
        return value.split("T", 1)[0] if "T" in value else value
