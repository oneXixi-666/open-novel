from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from pathlib import Path

from open_novel.agents.process_control import run_cancellable_process
from open_novel.core.models import LocalTuningPlan, LocalTuningRun
from open_novel.core.project import ProjectService
from open_novel.core.writing_model import WritingModelService
from open_novel.exporters.service import ExportService
from open_novel.security.path_guard import PathGuard


class LocalTrainingService:
    plan_path = "exports/local-tuning-plan.json"
    run_path = "runs/local-tuning-run.json"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        export_service: ExportService | None = None,
        writing_model_service: WritingModelService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.export_service = export_service or ExportService(self.project_service)
        self.writing_model_service = writing_model_service or WritingModelService(
            self.project_service
        )

    def plan_local_tuning(
        self,
        project_root: Path,
        backend: str = "custom",
        base_model: str = "",
        output_dir: str = "models/adapters/latest",
        model_profile_id: str = "latest-trained",
        inference_command_template: str | None = None,
        min_examples: int | None = None,
        train_command: str | None = None,
    ) -> LocalTuningPlan:
        project = self.project_service.open_project(project_root)
        readiness = self.export_service.training_readiness(project.root)
        dataset_path = self.export_service.export_writing_training_jsonl(project.root)
        required = min_examples or readiness.minRecommendedExamples
        backend_value = self._backend(backend)
        command = self._command(
            train_command or os.environ.get("OPEN_NOVEL_TRAIN_COMMAND", ""),
            project.root,
            dataset_path,
            output_dir,
            base_model,
        )
        status = self._status(readiness.eligibleCount, required, command)
        plan = LocalTuningPlan(
            status=status,
            backend=backend_value,
            datasetPath=dataset_path.relative_to(project.root).as_posix(),
            outputDir=output_dir,
            modelProfileId=model_profile_id,
            baseModel=base_model,
            inferenceCommandTemplate=(
                inference_command_template or os.environ.get("OPEN_NOVEL_INFER_COMMAND", "")
            ),
            eligibleCount=readiness.eligibleCount,
            minRecommendedExamples=required,
            command=command,
            commandPreview=" ".join(shlex.quote(part) for part in command),
            suggestedCommands=self._suggested_commands(backend_value, base_model, output_dir),
            reportPath=self.plan_path,
            recommendedNextAction=self._recommended_next_action(
                readiness.eligibleCount,
                required,
                command,
            ),
        )
        self.project_service.write_text(
            project.root,
            self.plan_path,
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return plan

    def run_local_tuning(
        self,
        project_root: Path,
        backend: str = "custom",
        base_model: str = "",
        output_dir: str = "models/adapters/latest",
        model_profile_id: str = "latest-trained",
        inference_command_template: str | None = None,
        min_examples: int | None = None,
        train_command: str | None = None,
        force: bool = False,
        timeout_seconds: int = 3600,
        cancel_check: Callable[[], bool] | None = None,
    ) -> LocalTuningRun:
        project = self.project_service.open_project(project_root)
        plan = self.plan_local_tuning(
            project.root,
            backend=backend,
            base_model=base_model,
            output_dir=output_dir,
            model_profile_id=model_profile_id,
            inference_command_template=inference_command_template,
            min_examples=min_examples,
            train_command=train_command,
        )
        if plan.status == "block" and not force:
            run = LocalTuningRun(
                status="skipped",
                command=plan.command,
                message=plan.recommendedNextAction,
            )
            self._write_run(project.root, run)
            return run
        if not plan.command:
            run = LocalTuningRun(
                status="skipped",
                command=[],
                message="缺少本地训练命令，请配置 OPEN_NOVEL_TRAIN_COMMAND。",
            )
            self._write_run(project.root, run)
            return run

        completed = run_cancellable_process(
            plan.command,
            cwd=project.root,
            timeout_seconds=max(1, timeout_seconds),
            cancel_check=cancel_check,
        )
        if completed["cancelled"]:
            run = LocalTuningRun(
                status="cancelled",
                command=plan.command,
                exitCode=completed["exitCode"],
                stdout=str(completed["stdout"])[-8000:],
                stderr=str(completed["stderr"])[-8000:],
                message="本地微调任务已取消。",
            )
            self._write_run(project.root, run)
            return run
        if completed["timedOut"]:
            run = LocalTuningRun(
                status="failed",
                command=plan.command,
                exitCode=completed["exitCode"],
                stdout=str(completed["stdout"])[-8000:],
                stderr=str(completed["stderr"])[-8000:],
                message="本地微调任务执行超时。",
            )
            self._write_run(project.root, run)
            return run
        exit_code = int(completed["exitCode"])
        stdout = str(completed["stdout"])
        stderr = str(completed["stderr"])
        run = LocalTuningRun(
            status="completed" if exit_code == 0 else "failed",
            command=plan.command,
            exitCode=exit_code,
            stdout=stdout[-8000:],
            stderr=stderr[-8000:],
            modelProfilePath=self.writing_model_service.registry_path
            if exit_code == 0 and plan.inferenceCommandTemplate.strip()
            else "",
            modelProfileId=plan.modelProfileId
            if exit_code == 0 and plan.inferenceCommandTemplate.strip()
            else "",
            message="本地微调任务已完成。"
            if exit_code == 0
            else "本地微调任务执行失败。",
        )
        if exit_code == 0 and plan.inferenceCommandTemplate.strip():
            self.writing_model_service.register_profile(
                project.root,
                profile_id=plan.modelProfileId,
                base_model=plan.baseModel,
                adapter_path=plan.outputDir,
                command_template=plan.inferenceCommandTemplate,
                label=f"{plan.backend} 微调写作模型",
                training_run_path=self.run_path,
                set_default=False,
                notes=(
                    "Generated by local tuning. Keep using chapter contracts, context packs, "
                    "and gates; promote this profile to default only after a safe five-chapter "
                    "model comparison report."
                ),
            )
            run.message = (
                "本地训练命令已完成并登记写作模型；这只代表模型文件已产出，"
                "下一步必须运行五章模型对比，确认质量没有退化后再提升为默认模型。"
            )
        self._write_run(project.root, run)
        return run

    def _write_run(self, root: Path, run: LocalTuningRun) -> None:
        self.project_service.write_text(
            root,
            self.run_path,
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def _command(
        self,
        template: str,
        root: Path,
        dataset_path: Path,
        output_dir: str,
        base_model: str,
    ) -> list[str]:
        if not template.strip():
            return []
        formatted = template.format(
            project=str(root),
            dataset=str(dataset_path),
            dataset_rel=dataset_path.relative_to(root).as_posix(),
            output_dir=output_dir,
            base_model=base_model,
        )
        command = shlex.split(formatted)
        if not command:
            return []
        executable = command[0]
        if "/" in executable:
            resolved = Path(executable).expanduser()
            if not resolved.is_absolute():
                resolved = PathGuard(root).resolve(executable)
            command[0] = str(resolved)
        return command

    def _status(self, eligible_count: int, required: int, command: list[str]) -> str:
        if eligible_count <= 0:
            return "block"
        if eligible_count < required:
            return "warn"
        if not command:
            return "warn"
        return "ready"

    def _recommended_next_action(
        self,
        eligible_count: int,
        required: int,
        command: list[str],
    ) -> str:
        if eligible_count <= 0:
            return "create-and-accept-quality-checked-chapters-before-local-tuning"
        if eligible_count < required:
            return "collect-more-quality-checked-examples-before-local-tuning"
        if not command:
            return "set-open-novel-train-command-before-running-local-tuning"
        return "run-local-tuning-and-then-evaluate-a-five-chapter-regression"

    def _backend(self, backend: str) -> str:
        if backend in {"custom", "mlx-lm", "llama-factory"}:
            return backend
        raise ValueError(f"unsupported local tuning backend: {backend}")

    def _suggested_commands(
        self,
        backend: str,
        base_model: str,
        output_dir: str,
    ) -> list[list[str]]:
        model = base_model or "<local-base-model>"
        if backend == "mlx-lm":
            return [
                [
                    "python",
                    "-m",
                    "mlx_lm",
                    "lora",
                    "--model",
                    model,
                    "--train",
                    "--data",
                    "{dataset}",
                    "--adapter-path",
                    output_dir,
                ]
            ]
        if backend == "llama-factory":
            return [
                [
                    "llamafactory-cli",
                    "train",
                    "<llama-factory-config.yaml>",
                ]
            ]
        return [
            [
                "OPEN_NOVEL_TRAIN_COMMAND='your-trainer --data {dataset} "
                "--output {output_dir} --model {base_model}'"
            ]
        ]
