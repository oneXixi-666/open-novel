from __future__ import annotations

import json
from pathlib import Path
from shutil import which
from typing import Any

from fastapi import HTTPException

from open_novel.security.path_guard import PathGuard


class WorkbenchModelService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def set_book_model(self, request: Any) -> dict[str, str]:
        root = self.presenter._root_from_book_id(request.bookId)
        model_id = request.modelId.strip()
        if not model_id:
            self.presenter.model_library_service.set_book_selection(
                book_id=request.bookId,
                model_id="",
            )
            self.presenter.project_service.write_text(
                root,
                self.presenter.model_selection_path,
                json.dumps({"modelId": ""}, ensure_ascii=False, indent=2) + "\n",
            )
            return {"bookId": request.bookId, "modelId": ""}
        try:
            library_model = self.presenter.model_library_service.get_model(model_id)
        except FileNotFoundError:
            library_model = None
        if library_model is not None:
            if library_model["status"] != "usable":
                raise HTTPException(
                    status_code=400,
                    detail="这个模型还没有完成训练和验证，暂时不能用于作品。",
                )
            try:
                runtime_profile = self.presenter.model_library_service.runtime_profile(model_id)
                self.presenter.model_service.register_profile(
                    root,
                    profile_id=runtime_profile["profileId"],
                    base_model=runtime_profile["baseModel"],
                    adapter_path=runtime_profile["adapterPath"],
                    command_template=runtime_profile["commandTemplate"],
                    label=runtime_profile["label"],
                    training_run_path=runtime_profile["trainingRunPath"],
                    set_default=True,
                    notes="来自工作区公共模型库。",
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            self.presenter.model_library_service.set_book_selection(
                book_id=request.bookId,
                model_id=model_id,
                model_version_id=str(library_model.get("activeVersionId") or ""),
            )
            self.presenter.project_service.write_text(
                root,
                self.presenter.model_selection_path,
                json.dumps({"modelId": model_id}, ensure_ascii=False, indent=2) + "\n",
            )
            return {"bookId": request.bookId, "modelId": model_id}
        try:
            profile = self.presenter.model_service.get_profile(root, model_id)
            registry = self.presenter.model_service.read_registry(root)
            if (
                profile.trainingRunPath.strip()
                and registry.defaultProfileId != profile.id
            ):
                raise ValueError(
                    "训练产出的写作模型必须先通过多章节模型对比，不能直接用于当前书。"
                )
        except FileNotFoundError:
            pass
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self.presenter.project_service.write_text(
            root,
            self.presenter.model_selection_path,
            json.dumps({"modelId": model_id}, ensure_ascii=False, indent=2) + "\n",
        )
        return {"bookId": request.bookId, "modelId": model_id}

    def validate_model(self, request: Any) -> dict[str, Any]:
        model_id = request.modelId.strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="缺少模型编号。")
        if model_id == "local-dry-run":
            return {
                "modelId": model_id,
                "status": "待验证",
                "coverage": 0,
                "checks": ["这是自动测试使用的协议执行器，不是真实写作模型"],
                "warnings": ["不能用于产品自动生成主链。"],
                "recommendedNextAction": "请选择并验证真实 CLI Agent 或项目写作模型。",
            }
        if model_id == "codex-cli":
            executable = which("codex")
            if executable:
                return {
                    "modelId": model_id,
                    "status": "可使用",
                    "coverage": 74,
                    "checks": [
                        f"已找到 CLI：{executable}",
                        "可用于工作台候选生成",
                        "候选会先等待作者确认",
                    ],
                    "warnings": [],
                    "recommendedNextAction": "可以先绑定到当前书，再运行章节候选或审稿修复。",
                }
            return {
                "modelId": model_id,
                "status": "待验证",
                "coverage": 28,
                "checks": ["未找到 codex CLI 可执行文件", "当前无法稳定返回工作台候选"],
                "warnings": ["请先确认本机已安装并可直接执行 codex。"],
                "recommendedNextAction": "先安装或修复 codex CLI，再重新验证。",
            }
        for root in self.presenter._workspace_roots():
            try:
                profile = self.presenter.model_service.get_profile(root, model_id)
            except FileNotFoundError:
                continue
            checks = ["已在项目模型注册表中找到 profile"]
            warnings: list[str] = []
            status: str = "可使用"
            coverage = 82
            if profile.commandTemplate.strip():
                checks.append("已配置 inference command template")
            else:
                status = "待验证"
                coverage = 34
                warnings.append("当前 profile 还没有 inference command template。")
            if profile.baseModel.strip():
                checks.append(f"base model：{profile.baseModel}")
            if profile.adapterPath.strip():
                checks.append(f"adapter：{profile.adapterPath}")
                adapter_exists = self.model_path_exists(root, profile.adapterPath)
                if adapter_exists:
                    checks.append("已找到 adapter 路径")
                else:
                    status = "待验证"
                    coverage = min(coverage, 56)
                    warnings.append("adapter path 当前不存在，运行时可能无法加载模型。")
            if not profile.baseModel.strip() and not profile.adapterPath.strip():
                warnings.append("尚未填写 base model 或 adapter path。")
            if profile.timeoutSeconds > 0:
                checks.append(f"超时设置：{profile.timeoutSeconds} 秒")
            try:
                command = self.presenter.model_service._command_for_profile(  # noqa: SLF001
                    root,
                    profile,
                    Path(root) / ".open-novel-validate-prompt.md",
                    Path(root) / ".open-novel-validate-output.md",
                )
                executable = command[0]
                resolved_executable = self.resolve_model_executable(root, executable)
                if resolved_executable:
                    checks.append(f"命令入口可解析：{resolved_executable}")
                else:
                    status = "待验证"
                    coverage = min(coverage, 48)
                    warnings.append("命令模板已配置，但当前执行入口不存在或不在 PATH 中。")
            except KeyError as exc:
                status = "待验证"
                coverage = min(coverage, 38)
                warnings.append(f"命令模板缺少占位符：{exc.args[0]}")
            except ValueError as exc:
                status = "待验证"
                coverage = min(coverage, 38)
                warnings.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive fallback
                status = "待验证"
                coverage = min(coverage, 38)
                warnings.append(f"命令模板当前无法解析：{exc}")
            return {
                "modelId": model_id,
                "status": status,
                "coverage": coverage,
                "checks": checks,
                "warnings": warnings,
                "recommendedNextAction": (
                    "可以绑定到当前书并开始生成候选。"
                    if status == "可使用"
                    else "先修复命令模板、执行入口或模型路径，再重新验证。"
                ),
            }
        return {
            "modelId": model_id,
            "status": "待验证",
            "coverage": 24,
            "checks": ["当前工作区没有找到对应模型 profile"],
            "warnings": ["这可能是旧模型标识，或当前书尚未注册该模型。"],
            "recommendedNextAction": "先确认模型注册状态，再重新验证。",
        }

    def compare_models(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可比较模型的作品。")
        registry = self.presenter.model_service.read_registry(root)
        profiles = registry.profiles
        if len(profiles) < 2:
            raise HTTPException(
                status_code=400,
                detail="请先在当前项目中注册至少两个写作模型，再运行模型对比。",
            )

        base_profile_id = (
            request.baseProfileId.strip() or registry.defaultProfileId or profiles[0].id
        )
        tuned_profile_id = request.tunedProfileId.strip()
        if not tuned_profile_id:
            tuned_profile_id = next(
                (profile.id for profile in profiles if profile.id != base_profile_id),
                "",
            )
        if not tuned_profile_id or tuned_profile_id == base_profile_id:
            raise HTTPException(status_code=400, detail="模型对比需要两个不同的写作模型。")

        try:
            report = self.presenter.model_comparison_service.compare_five_chapter_profiles(
                root,
                start_chapter_id=request.startChapterId.strip() or "001",
                chapter_count=request.chapterCount,
                base_profile_id=base_profile_id,
                tuned_profile_id=tuned_profile_id,
                reference_agent_id=request.referenceAgentId.strip() or "local-dry-run",
                include_reference_agent=request.includeReferenceAgent,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        candidate_lookup = {
            candidate.candidateId: candidate for candidate in report.candidates
        }

        def candidate_label(candidate_id: str) -> str:
            if not candidate_id:
                return ""
            candidate = candidate_lookup.get(candidate_id)
            if candidate and candidate.modelProfileId:
                return self.model_profile_label(root, candidate.modelProfileId)
            if candidate_id == "local-dry-run":
                return "本地草稿助手"
            if candidate_id == "codex-cli":
                return "Codex CLI"
            return candidate_id

        summary = report.summary
        return {
            "comparisonId": report.comparisonId,
            "rangeLabel": f"{report.startChapterId} - {report.endChapterId}",
            "chapterCount": report.chapterCount,
            "baseProfileId": report.baseProfileId,
            "baseProfileLabel": candidate_label(report.baseProfileId),
            "tunedProfileId": report.tunedProfileId,
            "tunedProfileLabel": candidate_label(report.tunedProfileId),
            "referenceAgentId": report.referenceAgentId,
            "referenceAgentLabel": candidate_label(report.referenceAgentId),
            "bestCandidateId": summary.bestCandidateId,
            "bestCandidateLabel": (
                candidate_label(summary.bestCandidateId) or summary.bestCandidateLabel
            ),
            "bestStatus": summary.bestStatus,
            "promotionDecision": summary.promotionDecision,
            "promotionReasons": summary.promotionReasons,
            "regressionPassed": summary.regressionPassed,
            "safeToSetDefault": summary.safeToSetDefault,
            "recommendedNextAction": report.recommendedNextAction,
            "scoreSummary": {
                "base": {
                    "quality": summary.baseQualityScore,
                    "gate": summary.baseGateScore,
                    "averageGate": summary.baseAverageGateScore,
                    "editorial": summary.baseEditorialScore,
                    "highOrBlockerCount": summary.baseEditorialHighOrBlockerCount,
                },
                "tuned": {
                    "quality": summary.tunedQualityScore,
                    "gate": summary.tunedGateScore,
                    "averageGate": summary.tunedAverageGateScore,
                    "editorial": summary.tunedEditorialScore,
                    "highOrBlockerCount": summary.tunedEditorialHighOrBlockerCount,
                },
                "reference": (
                    {
                        "quality": summary.referenceQualityScore,
                        "gate": summary.referenceGateScore,
                        "editorial": summary.referenceEditorialScore,
                    }
                    if summary.referenceCandidateId
                    else None
                ),
            },
            "deltas": {
                "quality": summary.qualityDelta,
                "gate": summary.gateDelta,
                "editorial": summary.editorialDelta,
                "editorialHighOrBlocker": summary.editorialHighOrBlockerDelta,
                "referenceVsTunedQuality": summary.referenceDeltaQualityVsTuned,
                "referenceVsTunedGate": summary.referenceDeltaGateVsTuned,
                "referenceVsTunedEditorial": summary.referenceDeltaEditorialVsTuned,
            },
            "candidates": [
                {
                    "id": candidate.candidateId,
                    "label": candidate_label(candidate.candidateId),
                    "kind": "profile" if candidate.modelProfileId else "reference-agent",
                    "status": candidate.sequence.status,
                    "qualityScore": candidate.sequence.minQualityScore,
                    "gateScore": candidate.sequence.minGateScore,
                    "editorialScore": candidate.editorial.minScore,
                    "highOrBlockerCount": candidate.editorial.highOrBlockerCount,
                }
                for candidate in report.candidates
            ],
        }

    def list_writing_models(self, book_id: str = "") -> dict[str, Any]:
        root = self.presenter._target_root(book_id)
        if root is None:
            return {"bookId": "", "defaultProfileId": "", "profiles": []}
        registry = self.presenter.model_service.read_registry(root)
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "profiles": [
                self.profile_payload(root, profile, registry.defaultProfileId)
                for profile in registry.profiles
            ],
        }

    def create_writing_model(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可注册模型的作品。")
        try:
            profile = self.presenter.model_service.register_profile(
                root,
                profile_id=request.profileId,
                base_model=request.baseModel,
                adapter_path=request.adapterPath,
                command_template=request.commandTemplate,
                label=request.label,
                timeout_seconds=request.timeoutSeconds,
                set_default=request.setDefault,
                notes=request.notes,
            )
            registry = self.presenter.model_service.read_registry(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "profile": self.profile_payload(root, profile, registry.defaultProfileId),
            "summary": f"已登记写作模型：{profile.label or profile.id}",
        }

    def set_default_writing_model(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可设置默认模型的作品。")
        try:
            profile = self.presenter.model_service.get_profile(root, request.profileId)
            if profile.trainingRunPath.strip():
                raise ValueError(
                    "训练产出的写作模型必须先通过多章节模型对比，不能直接设为默认。"
                )
            registry = self.presenter.model_service.set_default_profile(root, request.profileId)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "summary": f"已将默认写作模型切换为：{request.profileId}",
        }

    def promote_model_compare(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可提升默认模型的作品。")
        try:
            registry = self.presenter.model_comparison_service.promote_tuned_profile_from_report(
                root,
                request.comparisonReportPath,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "summary": f"已将对比胜出的模型设为默认：{registry.defaultProfileId}",
        }

    def quality_distribution(self, book_id: str = "") -> dict[str, Any]:
        root = self.presenter._target_root(book_id)
        if root is None:
            return {
                "bookId": "",
                "currentThresholds": {},
                "items": [],
            }
        report = self.presenter.export_service.training_readiness(root)
        labels = {
            str(item.get("chapterId") or ""): str(item.get("label") or "")
            for item in self.presenter.workbench_repository.list_calibration_annotations(root)
        }
        thresholds = self.presenter.workbench_repository.read_quality_thresholds(root)
        return {
            "bookId": root.as_posix(),
            "currentThresholds": thresholds.to_dict(),
            "items": [
                {
                    "chapterId": item.chapterId,
                    "score": item.qualityScore,
                    "similarity": item.previousSimilarity,
                    "gateStatus": item.gateStatus or "unknown",
                    "eligible": item.eligible,
                    "label": labels.get(item.chapterId, ""),
                }
                for item in report.items
            ],
        }

    def profile_payload(self, root: Path, profile: Any, default_profile_id: str) -> dict[str, Any]:
        return {
            "id": profile.id,
            "label": profile.label or profile.id,
            "baseModel": profile.baseModel,
            "adapterPath": profile.adapterPath,
            "commandTemplate": profile.commandTemplate,
            "timeoutSeconds": profile.timeoutSeconds,
            "notes": profile.notes,
            "trainingRunPath": profile.trainingRunPath,
            "updatedAt": self.presenter._short_datetime(profile.updatedAt),
            "isDefault": profile.id == default_profile_id,
        }

    def model_profile_label(self, root: Path, profile_id: str) -> str:
        profile_id = (profile_id or "").strip()
        if not profile_id:
            return ""
        try:
            profile = self.presenter.model_service.get_profile(root, profile_id)
        except FileNotFoundError:
            return profile_id
        return profile.label or profile.id

    def resolve_model_executable(self, root: Path, executable: str) -> str:
        value = str(executable or "").strip()
        if not value:
            return ""
        if "/" in value:
            resolved = Path(value).expanduser()
            if not resolved.is_absolute():
                resolved = PathGuard(root).resolve(value)
            return str(resolved) if resolved.exists() else ""
        located = which(value)
        return located or ""

    def model_path_exists(self, root: Path, relative_or_absolute: str) -> bool:
        value = str(relative_or_absolute or "").strip()
        if not value:
            return False
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate.exists()
        if self.presenter.project_service.is_database_project(root):
            return self.presenter.project_service.file_exists(
                root,
                value,
            ) or bool(self.presenter.project_service.list_paths(root, value))
        try:
            return PathGuard(root).resolve(value).exists()
        except Exception:
            return False
