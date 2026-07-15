from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from open_novel.core.jobs import JobController


class WorkbenchTrainingService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def model_training_readiness(self, book_id: str = "") -> dict[str, Any]:
        root = self.presenter._target_root(book_id)
        if root is None:
            return {
                "status": "block",
                "eligibleCount": 0,
                "skippedCount": 0,
                "minRecommendedExamples": 20,
                "checks": ["当前工作区还没有可检查训练就绪的作品。"],
                "warnings": ["请先创建作品并接收若干质量合格章节。"],
                "recommendedNextAction": "先准备并接收章节，再检查训练就绪。",
                "maturity": "训练只适合作为高质量样本后的离线增强，不能代替章节质量闭环。",
                "items": [],
            }
        report = self.presenter.export_service.training_readiness(root)
        skipped_reasons = self._skipped_reasons(report.items)
        checks = [
            f"可用训练样本 {report.eligibleCount} 章",
            f"跳过 {report.skippedCount} 章",
            f"建议至少 {report.minRecommendedExamples} 章高质量样本后再训练",
            report.recommendedNextAction,
        ]
        if skipped_reasons:
            checks.append("跳过原因：" + "、".join(skipped_reasons))
        warnings = (
            []
            if report.status == "ready"
            else [
                "当前训练样本数量或质量还不足以直接开始稳定训练。",
                "训练不会修复低质量正文；请先让章节通过质量、审稿和 gate 检查。",
            ]
        )
        return {
            "status": report.status,
            "eligibleCount": report.eligibleCount,
            "skippedCount": report.skippedCount,
            "minRecommendedExamples": report.minRecommendedExamples,
            "checks": checks,
            "warnings": warnings,
            "recommendedNextAction": report.recommendedNextAction,
            "maturity": (
                "训练是离线增强：只学习已验收章节的稳定风格，"
                "不能作为当前生成质量的主引擎。"
            ),
            "items": [self._readiness_item(item) for item in report.items],
        }

    def run_model_training(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可训练模型的作品。")
        readiness = self.presenter.export_service.training_readiness(root)
        effective_min_examples = (
            request.minExamples
            if isinstance(request.minExamples, int) and request.minExamples > 0
            else readiness.minRecommendedExamples
        )
        plan = self.presenter.local_training_service.plan_local_tuning(
            root,
            backend=request.backend,
            base_model=request.baseModel.strip(),
            output_dir=request.outputDir.strip() or "models/adapters/latest",
            model_profile_id=request.modelProfileId.strip() or "latest-trained",
            inference_command_template=request.inferenceCommandTemplate.strip() or None,
            min_examples=effective_min_examples,
            train_command=request.trainCommand.strip() or None,
        )
        if plan.status != "ready" and not request.force:
            raise HTTPException(
                status_code=400,
                detail="当前训练样本不足或质量未达标，暂时不能加入训练队列。",
            )

        params = {
            "backend": request.backend,
            "baseModel": request.baseModel.strip(),
            "outputDir": request.outputDir.strip() or "models/adapters/latest",
            "modelProfileId": request.modelProfileId.strip() or "latest-trained",
            "inferenceCommandTemplate": request.inferenceCommandTemplate.strip(),
            "minExamples": effective_min_examples,
            "trainCommand": request.trainCommand.strip(),
            "force": request.force,
            "timeoutSeconds": request.timeoutSeconds,
        }
        job = JobController().submit_background(
            root,
            kind="local-training",
            title="本地模型训练",
            detail=(
                f"已加入训练队列，可用样本 {readiness.eligibleCount} 章，"
                f"建议样本 {effective_min_examples} 章。"
            ),
            work=lambda current_job: self.presenter.local_training_service.run_local_tuning(
                root,
                backend=request.backend,
                base_model=request.baseModel.strip(),
                output_dir=request.outputDir.strip() or "models/adapters/latest",
                model_profile_id=request.modelProfileId.strip() or "latest-trained",
                inference_command_template=request.inferenceCommandTemplate.strip() or None,
                min_examples=effective_min_examples,
                train_command=request.trainCommand.strip() or None,
                force=request.force,
                timeout_seconds=request.timeoutSeconds,
                cancel_check=lambda: JobController().is_cancel_requested(root, current_job.jobId),
            ),
            params=params,
        )
        return {
            "bookId": root.as_posix(),
            "job": self.presenter._job_summary(root, job),
            "training": {
                "status": plan.status,
                "eligibleCount": plan.eligibleCount,
                "minRecommendedExamples": plan.minRecommendedExamples,
                "modelProfileId": plan.modelProfileId,
                "outputDir": plan.outputDir,
                "recommendedNextAction": plan.recommendedNextAction,
            },
            "summary": (
                f"已为《{self.presenter.book_for_root(root)['title']}》加入本地模型训练队列。"
                if plan.status == "ready"
                else "训练样本还不充分，但已按你的要求加入训练队列。"
            ),
        }

    def _readiness_item(self, item: Any) -> dict[str, Any]:
        return {
            "chapterId": item.chapterId,
            "eligible": item.eligible,
            "reason": item.reason,
            "reasonLabel": self._reason_label(item.reason),
            "qualityScore": item.qualityScore,
            "gateStatus": item.gateStatus or "unknown",
            "gateScore": item.gateScore,
            "issueCount": item.issueCount,
            "blockerCount": item.blockerCount,
            "previousSimilarity": item.previousSimilarity,
            "batchSimilarity": item.batchSimilarity,
            "batchDuplicateOf": item.batchDuplicateOf,
            "issueTypes": item.issueTypes,
            "actionSuggestion": item.actionSuggestion,
        }

    def _skipped_reasons(self, items: list[Any]) -> list[str]:
        reasons: list[str] = []
        for item in items:
            label = self._reason_label(item.reason)
            if item.reason and label not in reasons:
                reasons.append(label)
        return reasons[:3]

    def _reason_label(self, reason: str) -> str:
        labels = {
            "missing_scene_contract": "缺少章节合同",
            "quality_and_gate_failed": "质量和 gate 均未通过",
            "quality_failed": "质量分不足",
            "gate_failed": "gate 未通过",
            "batch_duplicate": "同批训练样本重复",
            "continuity_failed": "连贯性问题未修复",
        }
        return labels.get(reason, reason)
