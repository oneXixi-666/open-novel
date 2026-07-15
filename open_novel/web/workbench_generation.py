from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.chapter_drafting import ChapterDraftService
from open_novel.core.generation_artifacts import (
    GenerationArtifactService,
    GenerationExecutionError,
    GenerationRoute,
)
from open_novel.core.models import ContextPack, SceneContract
from open_novel.core.polishing import ChapterPolishService
from open_novel.core.skills import SkillRunner
from open_novel.security.path_guard import PathGuard


class WorkbenchGenerationService:
    max_repair_attempts = 2

    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter
        self.skill_runner = SkillRunner(
            project_service=presenter.project_service,
            cli_agent_service=presenter.cli_agent_service,
            writing_model_service=presenter.model_service,
            ai_runtime_service=presenter.ai_runtime_service,
        )
        self.artifacts = GenerationArtifactService(
            presenter.project_service,
            presenter.model_service,
            self.skill_runner,
        )
        self.long_form_planning = self.artifacts.long_form_planning
        self.drafting = ChapterDraftService(
            project_service=presenter.project_service,
            story_guidance=presenter.story_guidance_service,
            skill_runner=self.skill_runner,
            writing_model_service=presenter.model_service,
        )
        self.polishing = ChapterPolishService(
            project_service=presenter.project_service,
            skill_runner=self.skill_runner,
            writing_model_service=presenter.model_service,
        )

    def generation_for_book(self, book_id: str) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        return self.presenter._generation_response(root, "已读取当前书生成状态。")

    def set_generation_mode(self, book_id: str, request: Any) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        state = self._state(
            root,
            current,
            stage=str(current.get("stage") or self.presenter._derived_generation_stage(root)),
            status=str(current.get("status") or "idle"),
            mode=request.interventionMode,
            batch_target=request.batchTarget,
            auto_step_limit=(
                request.autoStepLimit
                if request.autoStepLimit is not None
                else request.batchTarget * 7 + 8
                if request.interventionMode == "full_auto"
                else 1
            ),
            auto_steps_used=0,
            next_action="生成档位和本次目标已保存，可以继续生成。",
            last_result="已保存生成控制设置。",
        )
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已保存生成控制设置。")

    def continue_generation(self, book_id: str, *, request_id: str = "") -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        normalized_request_id = request_id.strip()
        if normalized_request_id and not self.presenter.workbench_repository.claim_continue_request(
            root, normalized_request_id
        ):
            return self.presenter._generation_response(root, "该生成请求已处理，已返回当前状态。")
        state = self.presenter._read_generation_state(root)
        if state.get("status") == "paused":
            return self.presenter._generation_response(root, "当前生成已暂停，恢复后才能继续。")
        if state.get("status") == "waiting_confirm":
            return self.presenter._generation_response(
                root, "当前候选仍待确认，请确认或回退后继续。"
            )
        mode = self.presenter._generation_mode(state)
        batch_target = self.presenter._generation_batch_target(state)
        batch_done = int(state.get("batchDone") or 0)
        max_steps = self.presenter._generation_auto_step_limit(
            state,
            mode=mode,
            batch_target=batch_target,
        )
        message = "已推进生成状态。"
        for step_index in range(max_steps):
            try:
                state, message, stopped = self.advance_once(
                    root,
                    mode=mode,
                    batch_target=batch_target,
                    batch_done=batch_done,
                )
            except GenerationExecutionError as exc:
                current = self.presenter._read_generation_state(root)
                state = self._blocked_state(root, current, exc)
                message = exc.author_message
                stopped = True
            batch_done = int(state.get("batchDone") or batch_done)
            state["autoStepsUsed"] = step_index + 1
            if normalized_request_id:
                state["lastContinueRequestId"] = normalized_request_id
            if not stopped and mode == "full_auto" and step_index + 1 >= max_steps:
                state = self._state(
                    root,
                    state,
                    stage=str(state.get("stage") or self.presenter._derived_generation_stage(root)),
                    status="waiting_confirm",
                    next_action="本次自动推进已达到步数上限，确认后可继续下一批推进。",
                    confirmations=[f"已达到本次自动推进上限：{max_steps} 步。"],
                    last_result="自动推进已按作者设置的步数上限安全停止。",
                    artifact_type="auto_step_limit",
                    can_confirm=True,
                    auto_steps_used=step_index + 1,
                )
                message = "本次自动推进已达到步数上限。"
                stopped = True
            self.presenter._write_generation_state(root, state)
            if stopped:
                break
        return self.presenter._generation_response(root, message)

    def confirm_generation(self, book_id: str, request: Any) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        request_id = str(getattr(request, "requestId", "") or "").strip()
        if request_id and current.get("lastConfirmRequestId") == request_id:
            return self.presenter._generation_response(root, "该确认请求已处理，已返回当前状态。")
        stage = str(current.get("stage") or self.presenter._derived_generation_stage(root))
        chapter_id = str(current.get("activeChapterId") or self.presenter._latest_chapter_id(root))
        try:
            if str(current.get("activeArtifactType") or "") == "auto_step_limit":
                state = self._state(
                    root,
                    current,
                    stage=stage,
                    status="idle",
                    next_action="可以继续下一批自动推进。",
                    last_result="作者已确认继续自动推进。",
                    clear_artifact=True,
                    auto_steps_used=0,
                )
                message = "已确认自动推进上限提示，可以继续生成。"
            elif stage == "architecture":
                selected = str(
                    getattr(request, "optionId", "") or current.get("selectedOptionId") or ""
                )
                route = self._resolve_route(root)
                architecture, _ = self.artifacts.build_architecture(
                    root,
                    route,
                    selected,
                    self.presenter.architecture_path,
                )
                state = self._state(
                    root,
                    current,
                    stage="blueprint",
                    status="idle",
                    next_action="生成当前范围章节蓝图。",
                    last_result=f"已确认作品方向：{architecture['directionTitle']}。",
                    clear_artifact=True,
                )
                message = "作品方向已确认，可以生成章节蓝图。"
            elif stage == "blueprint":
                if str(current.get("activeArtifactType") or "") == "long_form_plan":
                    plan = self.artifacts.apply_long_form_plan(root)
                    state = self._state(
                        root,
                        current,
                        stage="blueprint",
                        status="idle",
                        next_action="生成当前范围章节蓝图。",
                        last_result=f"已确认 {len(plan['volumes'])} 卷长篇规划。",
                        clear_artifact=True,
                    )
                    message = "长篇规划已确认，可以生成当前范围章节蓝图。"
                else:
                    blueprint = self.artifacts.apply_blueprint(root, self.presenter.blueprint_path)
                    self.apply_blueprint_to_chapter_briefs(root)
                    state = self._state(
                        root,
                        current,
                        stage="contract",
                        status="idle",
                        next_action="生成当前章合同候选。",
                        last_result=f"已确认 {len(blueprint['chapters'])} 章蓝图。",
                        clear_artifact=True,
                    )
                    message = "章节蓝图已确认，可以进入当前章合同。"
            elif stage == "contract":
                contract = self.artifacts.read_contract_candidate(root, chapter_id)
                self._accept_contract(root, contract)
                state = self._state(
                    root,
                    current,
                    stage="context",
                    status="idle",
                    next_action="构建上下文并生成章节草稿候选。",
                    last_result="章节合同已确认。",
                    clear_artifact=True,
                )
                message = "章节合同已确认，可以生成正文候选。"
            elif stage == "draft":
                self._apply_confirmed_draft(root, chapter_id)
                state = self._state(
                    root,
                    current,
                    stage="gate",
                    status="idle",
                    next_action="运行接收前检查。",
                    last_result="章节草稿候选已确认。",
                )
                message = "章节草稿候选已确认，可以运行接收前检查。"
            elif stage == "accept":
                try:
                    accepted = self.presenter.accept_generation_chapter(root.as_posix(), chapter_id)
                except Exception as exc:
                    if self.presenter._stored_chapter_status(root, chapter_id) == "完成":
                        raise GenerationExecutionError(
                            "memory_update_failed",
                            "本章正文已定稿，但记忆更新尚未完成，可以从当前阶段重试。",
                            retryable=True,
                        ) from exc
                    raise
                state = self._state(
                    root,
                    current,
                    stage="memory",
                    status="idle",
                    next_action="应用可自动确认的记忆更新。",
                    last_result=f"{accepted['chapter']['title']} 已定稿，等待记忆更新。",
                )
                message = "本章已定稿，可以更新记忆。"
            elif (
                stage == "gate" and str(current.get("activeArtifactType") or "") == "chapter_repair"
            ):
                self._apply_repair_candidate(
                    root,
                    chapter_id,
                    int(current.get("retryCount") or 1),
                )
                state = self._state(
                    root,
                    current,
                    stage="gate",
                    status="idle",
                    next_action="重新运行接收前检查。",
                    last_result="修复候选已应用，等待重新检查。",
                    clear_artifact=True,
                )
                message = "修复候选已应用，可以重新运行检查。"
            else:
                raise GenerationExecutionError(
                    "confirmation_required",
                    "当前阶段没有可确认候选，请先继续生成或处理阻断。",
                )
        except GenerationExecutionError as exc:
            state = self._blocked_state(root, current, exc)
            message = exc.author_message
        if request_id:
            state["lastConfirmRequestId"] = request_id
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, message)

    def pause_generation(self, book_id: str) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        state = self._state(
            root,
            current,
            stage=str(current.get("stage") or self.presenter._derived_generation_stage(root)),
            status="paused",
            next_action="恢复后从当前阶段继续生成。",
            last_result="作者已暂停自动生成。",
        )
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已暂停自动生成。")

    def resume_generation(self, book_id: str) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        state = self._state(
            root,
            current,
            stage=str(current.get("stage") or self.presenter._derived_generation_stage(root)),
            status="idle",
            next_action="已恢复，可以从当前阶段继续生成。",
            last_result="已恢复自动生成。",
        )
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已恢复自动生成。")

    def takeover_generation(self, book_id: str, request: Any) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        target_label = {"writing": "章节", "library": "资料", "review": "审稿"}[request.target]
        state = self._state(
            root,
            current,
            stage=str(current.get("stage") or self.presenter._derived_generation_stage(root)),
            status="paused",
            next_action=f"作者接管到{target_label}页，完成后可恢复生成。",
            last_result=f"已切换为作者接管：{target_label}。",
        )
        self.presenter._write_generation_state(root, state)
        response = self.presenter._generation_response(root, f"已进入{target_label}接管。")
        response["target"] = request.target
        return response

    def regenerate_candidate(self, book_id: str, *, request_id: str = "") -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        normalized_request_id = request_id.strip()
        if normalized_request_id and current.get("lastCandidateRequestId") == normalized_request_id:
            return self.presenter._generation_response(root, "该重生成请求已处理，已返回当前状态。")
        if str(current.get("status") or "") != "waiting_confirm":
            raise GenerationExecutionError(
                "confirmation_required",
                "当前没有等待确认的候选，不能重新生成。",
            )
        stage = str(current.get("stage") or "")
        artifact_type = str(current.get("activeArtifactType") or "")
        chapter_id = str(current.get("activeChapterId") or self.presenter._latest_chapter_id(root))
        route = self._resolve_route(root)
        route = GenerationRoute(
            route.agent_id,
            route.model_profile,
            route.label,
            bypass_cache=True,
        )
        candidate_options: list[dict[str, Any]] | None = None
        selected_option_id = ""
        if artifact_type == "book_direction":
            candidate, _ = self._generate_directions(root, route)
            candidate_options = self._direction_option_summaries(candidate)
            selected_option_id = str(candidate.get("recommendedOptionId") or "")
        elif artifact_type in {"long_form_plan", "long_form_replan"}:
            self.artifacts.generate_long_form_plan(
                root,
                route,
                replan=artifact_type == "long_form_replan",
            )
        elif artifact_type == "chapter_blueprint":
            existing = self.artifacts.current_candidate(root, stage, chapter_id) or {}
            chapters = (
                existing.get("chapters") if isinstance(existing.get("chapters"), list) else []
            )
            self.artifacts.generate_blueprint(
                root,
                route,
                chapter_count=max(
                    10, len(chapters), self.presenter._generation_batch_target(current)
                ),
            )
        elif artifact_type == "scene_contract":
            self.artifacts.generate_contract(
                root,
                route,
                chapter_id=chapter_id,
                chapter_intent=self._chapter_intent(root, chapter_id),
            )
        elif artifact_type == "chapter_draft":
            chapter = self.presenter._active_generation_chapter(root)
            self._archive_existing_draft(root, chapter_id, "candidate")
            self.build_context_pack(root, chapter_id)
            result = self.drafting.draft_chapter(
                root,
                chapter_id,
                chapter_title=str(chapter.get("title") or ""),
                agent_id=route.agent_id,
                model_profile=route.model_profile,
                bypass_cache=route.bypass_cache,
            )
            draft = result.outputText.strip()
            if len(draft) < 200 or "local dry-run output" in draft.lower():
                raise GenerationExecutionError(
                    "invalid_structured_output",
                    "模型返回的章节正文过短或不是可用正文，请重新生成。",
                    retryable=True,
                )
        else:
            raise GenerationExecutionError(
                "confirmation_required",
                "当前候选类型暂不支持重新生成。",
            )
        state = self._state(
            root,
            current,
            stage=stage,
            status="waiting_confirm",
            next_action="审阅新候选版本，确认后继续。",
            last_result="已生成新版本，旧版本仍可查看和切换。",
            can_confirm=True,
            candidate_options=candidate_options,
            selected_option_id=selected_option_id,
        )
        if normalized_request_id:
            state["lastCandidateRequestId"] = normalized_request_id
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已生成新候选版本。")

    def select_candidate(
        self, book_id: str, candidate_id: str, *, request_id: str = ""
    ) -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        normalized_request_id = request_id.strip()
        if (
            normalized_request_id
            and current.get("lastCandidateSelectRequestId") == normalized_request_id
        ):
            return self.presenter._generation_response(
                root, "该候选选择请求已处理，已返回当前状态。"
            )
        if str(current.get("status") or "") != "waiting_confirm":
            raise GenerationExecutionError(
                "confirmation_required",
                "当前没有等待确认的候选版本。",
            )
        stage = str(current.get("stage") or "")
        artifact_type = str(current.get("activeArtifactType") or "")
        chapter_id = str(current.get("activeChapterId") or self.presenter._latest_chapter_id(root))
        selected: dict[str, Any] | None = None
        if artifact_type == "chapter_draft":
            self._select_draft_candidate(root, chapter_id, candidate_id)
        else:
            selected = self.artifacts.select_candidate(
                root,
                stage,
                chapter_id,
                candidate_id,
                artifact_type,
            )
        state = self._state(
            root,
            current,
            stage=stage,
            status="waiting_confirm",
            next_action="已切换候选版本，审阅后确认继续。",
            last_result="已切换当前候选版本，正式内容尚未改变。",
            can_confirm=True,
            candidate_options=(
                self._direction_option_summaries(selected)
                if artifact_type == "book_direction" and selected
                else None
            ),
            selected_option_id=(
                str(selected.get("recommendedOptionId") or "")
                if artifact_type == "book_direction" and selected
                else ""
            ),
        )
        if normalized_request_id:
            state["lastCandidateSelectRequestId"] = normalized_request_id
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已切换候选版本。")

    def rollback_candidate(self, book_id: str, *, request_id: str = "") -> dict[str, Any]:
        root = self.presenter._root_from_book_id(book_id)
        current = self.presenter._read_generation_state(root)
        normalized_request_id = request_id.strip()
        if (
            normalized_request_id
            and current.get("lastCandidateRollbackRequestId") == normalized_request_id
        ):
            return self.presenter._generation_response(root, "该回退请求已处理，已返回当前状态。")
        if str(current.get("status") or "") != "waiting_confirm":
            raise GenerationExecutionError(
                "confirmation_required",
                "当前没有可以返回的确认点。",
            )
        artifact_type = str(current.get("activeArtifactType") or "")
        chapter_id = str(current.get("activeChapterId") or self.presenter._latest_chapter_id(root))
        completed = [
            item
            for item in self.presenter._chapters_for_root(root)
            if str(item.get("status") or "") == "完成"
        ]
        if artifact_type in {"long_form_plan", "chapter_blueprint", "scene_contract"} and completed:
            raise GenerationExecutionError(
                "unsafe_rollback",
                "已有定稿章节依赖当前结构，不能直接返回上一个结构确认点。可以重新生成当前候选或接管修改。",
            )
        if artifact_type == "long_form_plan":
            self._remove_project_file(root, self.presenter.architecture_path)
            target_stage = "architecture"
            target_artifact = "book_direction"
            next_action = "重新审阅作品方向，确认后会重建作品架构。"
        elif artifact_type == "chapter_blueprint":
            self._remove_long_form_plan(root)
            target_stage = "blueprint"
            target_artifact = "long_form_plan"
            next_action = "重新审阅长篇规划，确认后会重建卷级规划。"
        elif artifact_type == "scene_contract":
            self._remove_blueprint(root)
            target_stage = "blueprint"
            target_artifact = "chapter_blueprint"
            next_action = "重新审阅章节蓝图，确认后会重建章节目标。"
        elif artifact_type == "chapter_draft":
            self._archive_existing_draft(root, chapter_id, "candidate")
            self._remove_project_file(root, f"drafts/{chapter_id}.generated.md")
            self.presenter._write_chapter_status(root, chapter_id, "待写")
            target_stage = "contract"
            target_artifact = "scene_contract"
            next_action = "重新审阅章节合同，确认后会重新生成正文候选。"
        else:
            raise GenerationExecutionError(
                "unsafe_rollback",
                "当前阶段没有安全的上一个确认点。",
            )
        state = self._state(
            root,
            current,
            stage=target_stage,
            status="waiting_confirm",
            next_action=next_action,
            last_result="已返回上一个确认点，下游正式内容已安全失效，候选版本仍保留。",
            artifact_type=target_artifact,
            can_confirm=True,
            candidate_options=(
                self._direction_option_summaries(
                    self.artifacts.current_candidate(root, "architecture", chapter_id) or {}
                )
                if target_artifact == "book_direction"
                else None
            ),
        )
        if normalized_request_id:
            state["lastCandidateRollbackRequestId"] = normalized_request_id
        self.presenter._write_generation_state(root, state)
        return self.presenter._generation_response(root, "已返回上一个确认点。")

    def advance_once(
        self,
        root: Path,
        *,
        mode: str,
        batch_target: int,
        batch_done: int,
    ) -> tuple[dict[str, Any], str, bool]:
        current = self.presenter._read_generation_state(root)
        stage = str(current.get("stage") or "contract")
        if stage != "memory" and not self.has_architecture(root):
            route = self._resolve_route(root)
            candidate, result = self._generate_directions(root, route)
            should_pause = mode in {"stage_confirm", "deep_control"}
            selected = str(candidate["recommendedOptionId"])
            if not should_pause:
                self.artifacts.build_architecture(
                    root,
                    route,
                    selected,
                    self.presenter.architecture_path,
                )
            state = self._state(
                root,
                current,
                stage="architecture" if should_pause else "blueprint",
                status="waiting_confirm" if should_pause else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                next_action=(
                    "选择并确认作品方向后生成章节蓝图。" if should_pause else "继续生成章节蓝图。"
                ),
                confirmations=["已生成多套作品方向，请选择后继续。"] if should_pause else [],
                last_result="已由真实模型生成作品方向候选。",
                artifact_type="book_direction",
                run_status="completed",
                source_model_label=route.label,
                can_confirm=should_pause,
                candidate_options=self._direction_option_summaries(candidate),
                selected_option_id=selected,
            )
            return state, "已生成作品方向候选。", should_pause

        if (
            stage != "memory"
            and not self.has_blueprint(root)
            and not self.long_form_planning.has_plan(root)
        ):
            route = self._resolve_route(root)
            candidate, _ = self.artifacts.generate_long_form_plan(root, route)
            should_pause = mode in {"stage_confirm", "deep_control"}
            if not should_pause:
                self.artifacts.apply_long_form_plan(root)
            state = self._state(
                root,
                current,
                stage="blueprint",
                status="waiting_confirm" if should_pause else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                next_action=(
                    "确认整书与卷级规划后生成章节蓝图。"
                    if should_pause
                    else "继续生成当前范围章节蓝图。"
                ),
                confirmations=["长篇规划候选已生成，请确认后继续。"] if should_pause else [],
                last_result=(
                    f"已由真实模型生成 {len(candidate['plan']['volumes'])} 卷长篇规划候选。"
                ),
                artifact_type="long_form_plan",
                run_status="completed",
                source_model_label=route.label,
                can_confirm=should_pause,
            )
            return state, "已生成长篇规划候选。", should_pause

        if stage != "memory" and not self.has_blueprint(root):
            route = self._resolve_route(root)
            chapter_count = max(10, batch_target)
            candidate, result = self.artifacts.generate_blueprint(
                root,
                route,
                chapter_count=chapter_count,
            )
            should_pause = mode in {"stage_confirm", "deep_control"}
            if not should_pause:
                self.artifacts.apply_blueprint(root, self.presenter.blueprint_path)
                self.apply_blueprint_to_chapter_briefs(root)
            state = self._state(
                root,
                current,
                stage="blueprint" if should_pause else "contract",
                status="waiting_confirm" if should_pause else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                next_action=(
                    "确认章节蓝图后进入当前章合同。" if should_pause else "继续生成当前章合同。"
                ),
                confirmations=[f"已生成 {chapter_count} 章蓝图，请确认后继续。"]
                if should_pause
                else [],
                last_result=f"已由真实模型生成 {len(candidate['chapters'])} 章蓝图。",
                artifact_type="chapter_blueprint",
                run_status="completed",
                source_model_label=route.label,
                can_confirm=should_pause,
            )
            return state, "已生成章节蓝图候选。", should_pause

        chapter = self.presenter._active_generation_chapter(root)
        chapter_id = str(chapter.get("id") or self.presenter._latest_chapter_id(root))
        chapter_status = str(chapter.get("status") or "待写")

        if stage == "memory" and chapter_status == "完成":
            try:
                self._apply_accepted_memory(root, chapter_id, mode)
            except GenerationExecutionError:
                raise
            except Exception as exc:
                raise GenerationExecutionError(
                    "memory_update_failed",
                    "本章正文已定稿，但记忆更新尚未完成，可以从当前阶段重试。",
                    retryable=True,
                ) from exc
            batch_done += 1
            deviation = self.long_form_planning.evaluate_deviation(root, chapter_id)
            state = self._state(
                root,
                current,
                stage="next_chapter",
                status="completed" if batch_done >= batch_target else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                next_action="本次目标完成。" if batch_done >= batch_target else "继续准备下一章。",
                last_result=f"本章记忆和资料更新已完成。{deviation['reason']}",
                clear_artifact=True,
            )
            return state, "本章记忆更新已完成。", batch_done >= batch_target

        if chapter_status == "完成":
            if batch_done >= batch_target:
                return (
                    self._state(
                        root,
                        current,
                        stage="next_chapter",
                        status="completed",
                        mode=mode,
                        batch_target=batch_target,
                        batch_done=batch_done,
                        next_action="本次目标完成，可以设置新目标继续生成。",
                        last_result="本次生成目标已完成。",
                        clear_artifact=True,
                    ),
                    "本次生成目标已完成。",
                    True,
                )
            created = self.presenter.create_next_chapter(root.as_posix())
            next_chapter = created["chapter"]
            return (
                self._state(
                    root,
                    current,
                    stage="contract",
                    status="idle",
                    mode=mode,
                    batch_target=batch_target,
                    batch_done=batch_done,
                    active_chapter_id=str(next_chapter.get("id") or ""),
                    next_action="生成新章节合同候选。",
                    last_result=f"已创建 {next_chapter.get('title') or '下一章'}。",
                    clear_artifact=True,
                ),
                "已创建下一章。",
                False,
            )

        route = self._resolve_route(root)
        if not self._has_complete_contract(root, chapter_id):
            intent = self._chapter_intent(root, chapter_id)
            contract, result = self.artifacts.generate_contract(
                root,
                route,
                chapter_id=chapter_id,
                chapter_intent=intent,
            )
            should_pause = mode == "deep_control"
            if not should_pause:
                self._accept_contract(root, contract)
            state = self._state(
                root,
                current,
                stage="contract" if should_pause else "context",
                status="waiting_confirm" if should_pause else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                active_chapter_id=chapter_id,
                next_action=(
                    "确认章节合同后构建上下文。" if should_pause else "继续构建上下文并生成正文。"
                ),
                confirmations=["章节合同候选已生成，请确认后继续。"] if should_pause else [],
                last_result="已由真实模型生成章节合同候选。",
                artifact_type="scene_contract",
                run_status="completed",
                source_model_label=route.label,
                can_confirm=should_pause,
            )
            return state, "已生成章节合同候选。", should_pause

        if stage == "contract":
            existing_draft = f"drafts/{chapter_id}.generated.md"
            if not self.presenter.project_service.file_exists(root, existing_draft):
                state = self._state(
                    root,
                    current,
                    stage="context",
                    status="idle",
                    mode=mode,
                    batch_target=batch_target,
                    batch_done=batch_done,
                    active_chapter_id=chapter_id,
                    next_action="构建当前章上下文并生成正文。",
                    last_result="章节合同已就绪。",
                    clear_artifact=True,
                )
                return state, "章节合同已就绪，可以构建上下文。", False

        if chapter_status == "待写":
            self.build_context_pack(root, chapter_id)
            self._archive_existing_draft(root, chapter_id, "before-generation")
            result = self.drafting.draft_chapter(
                root,
                chapter_id,
                chapter_title=str(chapter.get("title") or ""),
                agent_id=route.agent_id,
                model_profile=route.model_profile,
            )
            draft = result.outputText.strip()
            if len(draft) < 200 or "local dry-run output" in draft.lower():
                raise GenerationExecutionError(
                    "invalid_structured_output",
                    "模型返回的章节正文过短或不是可用正文，请重新生成。",
                    retryable=True,
                )
            self.presenter._write_chapter_status(root, chapter_id, "审阅")
            should_pause = mode in {"chapter_confirm", "deep_control"}
            state = self._state(
                root,
                current,
                stage="draft" if should_pause else "gate",
                status="waiting_confirm" if should_pause else "idle",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                active_chapter_id=chapter_id,
                next_action=(
                    "审阅草稿候选并确认后运行检查。" if should_pause else "继续运行接收前检查。"
                ),
                confirmations=["章节草稿候选已生成，请确认后继续检查。"] if should_pause else [],
                last_result="已由真实模型生成章节草稿候选。",
                artifact_type="chapter_draft",
                run_status="completed",
                source_model_label=route.label,
                can_confirm=should_pause,
            )
            return state, "已生成章节草稿候选。", should_pause

        gate = self._check_gate(root, chapter_id)
        gate_status = str(gate["gate"]["status"])
        if gate_status == "block":
            retry_count = int(current.get("retryCount") or 0)
            should_repair = mode == "full_auto" or (
                str(current.get("status") or "") == "blocked" and bool(current.get("canRetry"))
            )
            if should_repair and retry_count < self.max_repair_attempts:
                result = self._repair_draft(root, chapter_id, route, gate, retry_count + 1)
                if mode == "full_auto":
                    self._apply_repair_candidate(root, chapter_id, retry_count + 1)
                state = self._state(
                    root,
                    current,
                    stage="gate",
                    status="idle" if mode == "full_auto" else "waiting_confirm",
                    mode=mode,
                    batch_target=batch_target,
                    batch_done=batch_done,
                    active_chapter_id=chapter_id,
                    next_action=(
                        "重新运行接收前检查。"
                        if mode == "full_auto"
                        else "审阅修复候选并确认后重新检查。"
                    ),
                    last_result=f"已生成第 {retry_count + 1} 次修复候选。",
                    artifact_type="chapter_repair",
                    run_status="completed",
                    source_model_label=route.label,
                    retry_count=retry_count + 1,
                    can_retry=True,
                    can_confirm=mode != "full_auto",
                )
                return state, "已生成修复候选。", mode != "full_auto"
            blockers = self._gate_blockers(gate)
            state = self._state(
                root,
                current,
                stage="gate",
                status="blocked",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                active_chapter_id=chapter_id,
                next_action=(
                    "自动修复已达到上限，请接管章节处理。"
                    if retry_count >= self.max_repair_attempts
                    else "先处理接收前检查阻断，再继续生成。"
                ),
                blockers=blockers,
                last_result=str(gate.get("display") or "接收前检查阻断。"),
                retry_count=retry_count,
                can_retry=retry_count < self.max_repair_attempts,
                recovery_summary="可重试当前阶段，或接管章节人工修复。",
            )
            return state, "接收前检查阻断，需要先处理。", True

        should_confirm = mode in {"stage_confirm", "chapter_confirm", "deep_control"}
        if should_confirm:
            state = self._state(
                root,
                current,
                stage="accept",
                status="waiting_confirm",
                mode=mode,
                batch_target=batch_target,
                batch_done=batch_done,
                active_chapter_id=chapter_id,
                next_action="确认本章定稿后继续更新记忆。",
                confirmations=["接收前检查已完成，确认后接收本章正文。"],
                last_result=str(gate.get("display") or "接收前检查完成。"),
                can_confirm=True,
            )
            return state, "等待作者确认本章定稿。", True

        try:
            accepted = self.presenter.accept_generation_chapter(root.as_posix(), chapter_id)
        except Exception as exc:
            if self.presenter._stored_chapter_status(root, chapter_id) == "完成":
                raise GenerationExecutionError(
                    "memory_update_failed",
                    "本章正文已定稿，但记忆更新尚未完成，可以从当前阶段重试。",
                    retryable=True,
                ) from exc
            raise
        state = self._state(
            root,
            current,
            stage="memory",
            status="idle",
            mode=mode,
            batch_target=batch_target,
            batch_done=batch_done,
            active_chapter_id=chapter_id,
            next_action="继续应用记忆更新。",
            last_result=f"{accepted['chapter']['title']} 已定稿，等待记忆更新。",
        )
        return state, "本章已自动定稿。", False

    def has_architecture(self, root: Path) -> bool:
        architecture = self.presenter._read_json(root, self.presenter.architecture_path)
        return bool(str(architecture.get("serialHook") or "").strip())

    def has_blueprint(self, root: Path) -> bool:
        blueprint = self.presenter._read_json(root, self.presenter.blueprint_path)
        chapters = blueprint.get("chapters") if isinstance(blueprint, dict) else None
        return isinstance(chapters, list) and len(chapters) >= 10

    def apply_blueprint_to_chapter_briefs(self, root: Path) -> None:
        blueprint = self.presenter._read_json(root, self.presenter.blueprint_path)
        chapters = blueprint.get("chapters") if isinstance(blueprint.get("chapters"), list) else []
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter_id = self.presenter.project_service.normalize_chapter_id(
                str(item.get("chapterId") or "")
            )
            if not chapter_id:
                continue
            goal = str(item.get("goal") or "").strip()
            conflict = str(item.get("conflict") or "").strip()
            turn = str(item.get("turn") or "").strip()
            outcome = str(item.get("outcome") or "").strip()
            hook = str(item.get("hook") or "").strip()
            brief = {
                "schemaVersion": 2,
                "chapterId": chapter_id,
                "title": str(item.get("title") or chapter_id),
                "focus": goal,
                "goal": goal,
                "conflict": conflict,
                "turn": turn,
                "outcome": outcome,
                "hook": hook,
                "characterChange": str(item.get("characterChange") or ""),
                "promiseProgression": str(item.get("promiseProgression") or ""),
                "logicDependencies": self.presenter._string_list(item.get("logicDependencies")),
                "workbenchTasks": self.presenter._unique_nonempty([goal, conflict, turn, hook]),
            }
            self.presenter.project_service.write_text(
                root,
                f"story/chapter-briefs/{chapter_id}.blueprint.json",
                json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
            )

    def build_context_pack(self, root: Path, chapter_id: str) -> ContextPack:
        context_pack = self.presenter.context_pack_service.build_context_pack(root, chapter_id)
        self.presenter.workbench_repository.upsert_context_pack(root, context_pack)
        return context_pack

    def _apply_confirmed_draft(self, root: Path, chapter_id: str) -> None:
        draft = self.presenter.project_service.read_text(
            root,
            f"drafts/{chapter_id}.generated.md",
        )
        chapter_path = f"chapters/{chapter_id}.md"
        self.presenter.project_service.write_text(root, chapter_path, draft)
        self.presenter._write_chapter_status(root, chapter_id, "草稿")
        chapter = self.presenter._chapter_for_file(root, PathGuard(root).resolve(chapter_path))
        self.presenter.workbench_repository.upsert_chapter(root, chapter)

    def restore_scene_contract_from_repository(self, root: Path, chapter_id: str) -> bool:
        return self._restore_contract(root, chapter_id)

    def scene_contract_complete(self, contract: SceneContract) -> bool:
        return self._contract_complete(contract)

    def upsert_context_pack_if_exists(self, root: Path, chapter_id: str) -> None:
        try:
            context_pack = self.presenter.context_pack_service.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return
        self.presenter.workbench_repository.upsert_context_pack(root, context_pack)

    def current_artifact(self, root: Path) -> dict[str, Any] | None:
        state = self.presenter._read_generation_state(root)
        stage = str(state.get("stage") or "")
        chapter_id = str(state.get("activeChapterId") or self.presenter._latest_chapter_id(root))
        artifact_type = str(state.get("activeArtifactType") or "")
        if artifact_type == "chapter_draft":
            return self._draft_artifact(root, chapter_id, state)
        if artifact_type in {"long_form_plan", "long_form_replan"}:
            candidate = self.artifacts.long_form_candidate(
                root,
                replan=artifact_type == "long_form_replan",
            )
        else:
            candidate = self.artifacts.current_candidate(root, stage, chapter_id)
        if not candidate:
            return None
        versions = self.artifacts.candidate_versions(
            root,
            stage,
            chapter_id,
            artifact_type,
        )
        if not str(candidate.get("candidateId") or "").strip():
            if artifact_type in {"long_form_plan", "long_form_replan"}:
                candidate = (
                    self.artifacts.long_form_candidate(
                        root,
                        replan=artifact_type == "long_form_replan",
                    )
                    or candidate
                )
            else:
                candidate = self.artifacts.current_candidate(root, stage, chapter_id) or candidate
        current_id = str(candidate.get("candidateId") or "")
        payload: dict[str, Any] = {
            "artifactType": str(candidate.get("artifactType") or ""),
            "status": str(candidate.get("status") or "candidate"),
            "sourceModelLabel": str(state.get("sourceModelLabel") or ""),
            "candidateId": current_id,
            "version": int(candidate.get("version") or 1),
            "versions": [self._candidate_version_payload(item, current_id) for item in versions],
        }
        if stage == "architecture":
            payload["recommendedOptionId"] = str(candidate.get("recommendedOptionId") or "")
            payload["selectedOptionId"] = str(
                state.get("selectedOptionId") or candidate.get("recommendedOptionId") or ""
            )
            payload["options"] = self._direction_option_summaries(candidate)
        elif stage == "blueprint":
            if artifact_type in {"long_form_plan", "long_form_replan"}:
                plan = candidate.get("plan") if isinstance(candidate.get("plan"), dict) else {}
                volumes = plan.get("volumes") if isinstance(plan.get("volumes"), list) else []
                payload["summary"] = f"已生成 {len(volumes)} 卷长篇规划候选。"
            else:
                chapters = candidate.get("chapters")
                payload["chapterCount"] = len(chapters) if isinstance(chapters, list) else 0
                payload["summary"] = f"已生成 {payload['chapterCount']} 章蓝图候选。"
        elif stage == "contract":
            contract = candidate.get("contract")
            if isinstance(contract, dict):
                payload["summary"] = str(contract.get("focus") or contract.get("goal") or "")
        payload["detail"] = self._candidate_detail(candidate)
        return payload

    def _candidate_version_payload(
        self,
        candidate: dict[str, Any],
        current_id: str,
    ) -> dict[str, Any]:
        candidate_id = str(candidate.get("candidateId") or "")
        detail = self._candidate_detail(candidate)
        return {
            "id": candidate_id,
            "version": int(candidate.get("version") or 1),
            "title": f"版本 {int(candidate.get('version') or 1)}",
            "summary": self._candidate_summary(candidate),
            "createdAt": str(candidate.get("createdAt") or ""),
            "selected": candidate_id == current_id,
            "detail": detail,
        }

    def _candidate_summary(self, candidate: dict[str, Any]) -> str:
        artifact_type = str(candidate.get("artifactType") or "")
        if artifact_type == "book_direction":
            options = candidate.get("options") if isinstance(candidate.get("options"), list) else []
            return f"{len(options)} 套作品方向"
        if artifact_type in {"long_form_plan", "long_form_replan"}:
            plan = candidate.get("plan") if isinstance(candidate.get("plan"), dict) else {}
            volumes = plan.get("volumes") if isinstance(plan.get("volumes"), list) else []
            return f"{len(volumes)} 卷长篇规划"
        if artifact_type == "chapter_blueprint":
            chapters = (
                candidate.get("chapters") if isinstance(candidate.get("chapters"), list) else []
            )
            return f"{len(chapters)} 章蓝图"
        if artifact_type == "scene_contract":
            contract = (
                candidate.get("contract") if isinstance(candidate.get("contract"), dict) else {}
            )
            return str(contract.get("focus") or contract.get("goal") or "章节合同")
        return "生成候选"

    def _candidate_detail(self, candidate: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(candidate.get("artifactType") or "")
        if artifact_type == "book_direction":
            return {"options": candidate.get("options") or []}
        if artifact_type in {"long_form_plan", "long_form_replan"}:
            return {"plan": candidate.get("plan") or {}}
        if artifact_type == "chapter_blueprint":
            return {"chapters": candidate.get("chapters") or []}
        if artifact_type == "scene_contract":
            return {"contract": candidate.get("contract") or {}}
        return {}

    def _draft_artifact(
        self,
        root: Path,
        chapter_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        current_path = f"drafts/{chapter_id}.generated.md"
        if not self.presenter.project_service.file_exists(root, current_path):
            return None
        versions: list[dict[str, Any]] = []
        history_paths = [
            path
            for path in self.presenter.project_service.list_paths(root, "drafts/history")
            if Path(path).name.startswith(f"{chapter_id}.candidate-") and path.endswith(".md")
        ]
        for index, relative_path in enumerate(history_paths, start=1):
            text = self.presenter.project_service.read_text(root, relative_path)
            versions.append(
                {
                    "id": Path(relative_path).name,
                    "version": index,
                    "title": f"版本 {index}",
                    "summary": f"{len(text.strip())} 字",
                    "createdAt": "",
                    "selected": False,
                    "detail": {"text": text},
                }
            )
        current_text = self.presenter.project_service.read_text(root, current_path)
        current_version = len(versions) + 1
        current_id = f"{chapter_id}.current.md"
        versions.append(
            {
                "id": current_id,
                "version": current_version,
                "title": f"版本 {current_version}",
                "summary": f"{len(current_text.strip())} 字",
                "createdAt": "",
                "selected": True,
                "detail": {"text": current_text},
            }
        )
        return {
            "artifactType": "chapter_draft",
            "status": "candidate",
            "sourceModelLabel": str(state.get("sourceModelLabel") or ""),
            "candidateId": current_id,
            "version": current_version,
            "summary": f"章节正文候选，共 {len(current_text.strip())} 字。",
            "detail": {"text": current_text},
            "versions": list(reversed(versions)),
        }

    def _select_draft_candidate(self, root: Path, chapter_id: str, candidate_id: str) -> None:
        current_id = f"{chapter_id}.current.md"
        if candidate_id == current_id:
            return
        if Path(candidate_id).name != candidate_id:
            raise GenerationExecutionError(
                "invalid_structured_output",
                "所选正文候选版本不存在，请刷新后重试。",
            )
        history_path = f"drafts/history/{candidate_id}"
        if not self.presenter.project_service.file_exists(root, history_path):
            raise GenerationExecutionError(
                "invalid_structured_output",
                "所选正文候选版本不存在，请刷新后重试。",
            )
        self._archive_existing_draft(root, chapter_id, "candidate")
        self.presenter.project_service.write_text(
            root,
            f"drafts/{chapter_id}.generated.md",
            self.presenter.project_service.read_text(root, history_path),
        )

    def _remove_long_form_plan(self, root: Path) -> None:
        plan = self.long_form_planning.read_plan(root)
        for volume in plan.get("volumes", []):
            if not isinstance(volume, dict):
                continue
            volume_id = str(volume.get("volumeId") or "")
            if volume_id:
                self._remove_project_file(root, f"story/volume-plans/{volume_id}.json")
                self._remove_project_file(root, f"story/arc-contracts/{volume_id}.json")
        self._remove_project_file(root, self.long_form_planning.plan_path)

    def _remove_blueprint(self, root: Path) -> None:
        blueprint = self.presenter._read_json(root, self.presenter.blueprint_path)
        for chapter in blueprint.get("chapters", []):
            if isinstance(chapter, dict):
                chapter_id = str(chapter.get("chapterId") or "")
                if chapter_id:
                    self._remove_project_file(
                        root, f"story/chapter-briefs/{chapter_id}.blueprint.json"
                    )
        self._remove_project_file(root, self.presenter.blueprint_path)

    def _remove_project_file(self, root: Path, relative_path: str) -> None:
        self.presenter.project_service.delete_text(root, relative_path)

    def _resolve_route(self, root: Path) -> GenerationRoute:
        return self.artifacts.resolve_route(root, self.presenter._selected_model_id(root))

    def _generate_directions(
        self, root: Path, route: GenerationRoute
    ) -> tuple[dict[str, Any], Any]:
        book = self.presenter.book_for_root(root)
        idea = (
            self.presenter.project_service.read_text(root, "notes/ideas.md")
            if self.presenter.project_service.file_exists(root, "notes/ideas.md")
            else str(book.get("tagline") or "")
        )
        return self.artifacts.generate_directions(
            root,
            route,
            title=str(book.get("title") or "当前作品"),
            genre=str(book.get("genre") or "通用网文"),
            idea=idea.strip(),
            style_label=str(book.get("styleProfileLabel") or "通用网文连载"),
        )

    def _chapter_intent(self, root: Path, chapter_id: str) -> str:
        blueprint = self.presenter._read_json(root, self.presenter.blueprint_path)
        chapters = blueprint.get("chapters") if isinstance(blueprint.get("chapters"), list) else []
        current = next(
            (
                item
                for item in chapters
                if isinstance(item, dict) and str(item.get("chapterId") or "") == chapter_id
            ),
            {},
        )
        previous_id = (
            f"{int(chapter_id) - 1:03d}" if chapter_id.isdigit() and int(chapter_id) > 1 else ""
        )
        previous_tail = ""
        if previous_id:
            previous_path = f"chapters/{previous_id}.md"
            if self.presenter.project_service.file_exists(root, previous_path):
                previous_tail = self.presenter.project_service.read_text(
                    root, previous_path
                )[-1200:]
        return json.dumps(
            {
                "blueprint": current,
                "previousChapterTail": previous_tail,
            },
            ensure_ascii=False,
        )

    def _has_complete_contract(self, root: Path, chapter_id: str) -> bool:
        if self._restore_contract(root, chapter_id):
            return True
        try:
            contract = self.presenter.story_guidance_service.read_scene_contract(root, chapter_id)
        except FileNotFoundError:
            return False
        if not self._contract_complete(contract):
            return False
        self.presenter.workbench_repository.upsert_scene_contract(root, contract)
        return True

    def _restore_contract(self, root: Path, chapter_id: str) -> bool:
        stored = self.presenter.workbench_repository.read_scene_contract(root, chapter_id)
        if not stored or not self._contract_complete(stored):
            return False
        self.presenter.story_guidance_service.write_scene_contract(root, stored)
        return True

    def _contract_complete(self, contract: SceneContract) -> bool:
        required = [
            contract.focus,
            contract.goal,
            contract.conflict,
            contract.turn,
            contract.outcome,
            contract.hook,
            contract.emotionalBeat,
            contract.relationshipBeat,
            contract.internalNeed,
            contract.woundOrFear,
            contract.stakes,
            contract.cost,
            contract.subtext,
            contract.aftertaste,
        ]
        return all(str(value or "").strip() for value in required) and bool(
            contract.mustAvoid and contract.readerPromises
        )

    def _accept_contract(self, root: Path, contract: SceneContract) -> None:
        self.presenter.story_guidance_service.write_scene_contract(root, contract)
        self.presenter.workbench_repository.upsert_scene_contract(root, contract)
        self.artifacts.mark_contract_accepted(root, contract.chapterId)
        self.build_context_pack(root, contract.chapterId)

    def _repair_draft(
        self,
        root: Path,
        chapter_id: str,
        route: GenerationRoute,
        gate: dict[str, Any],
        attempt: int,
    ) -> Any:
        source = f"drafts/{chapter_id}.generated.md"
        blockers = self._gate_blockers(gate)
        result = self.polishing.polish_file(
            root,
            source,
            instruction="修复以下接收前阻断，同时保持已确认剧情事实和章节合同："
            + "；".join(blockers),
            agent_id=route.agent_id,
            model_profile=route.model_profile,
        )
        repaired = result.outputText.strip()
        if len(repaired) < 200:
            raise GenerationExecutionError(
                "invalid_structured_output",
                "模型返回的修复候选过短，请接管章节或更换模型。",
                retryable=True,
            )
        self.presenter.project_service.write_text(
            root,
            self._repair_candidate_path(chapter_id, attempt),
            repaired.rstrip() + "\n",
        )
        return result

    def _apply_repair_candidate(self, root: Path, chapter_id: str, attempt: int) -> None:
        candidate_path = self._repair_candidate_path(chapter_id, attempt)
        repaired = self.presenter.project_service.read_text(root, candidate_path)
        self._archive_existing_draft(root, chapter_id, "before-repair")
        self.presenter.project_service.write_text(
            root,
            f"drafts/{chapter_id}.generated.md",
            repaired.rstrip() + "\n",
        )

    def _repair_candidate_path(self, chapter_id: str, attempt: int) -> str:
        return f"drafts/{chapter_id}.repair-{attempt}.candidate.md"

    def _archive_existing_draft(self, root: Path, chapter_id: str, prefix: str) -> None:
        source = f"drafts/{chapter_id}.generated.md"
        if not self.presenter.project_service.file_exists(root, source):
            return
        source_text = self.presenter.project_service.read_text(root, source)
        if not source_text.strip():
            return
        attempt = 1
        while self.presenter.project_service.file_exists(
            root, f"drafts/history/{chapter_id}.{prefix}-{attempt}.md"
        ):
            attempt += 1
        self.presenter.project_service.write_text(
            root,
            f"drafts/history/{chapter_id}.{prefix}-{attempt}.md",
            source_text,
        )

    def _apply_accepted_memory(self, root: Path, chapter_id: str, mode: str) -> None:
        service = self.presenter._post_chapter_service()
        try:
            patch = service.read_canon_patch(root, chapter_id)
        except FileNotFoundError:
            patch = service.build_review_and_patch(root, chapter_id)
        if mode == "deep_control":
            pending = [
                operation
                for operation in patch.operations
                if operation.status == "proposed" and operation.action != "defer"
            ]
            if pending:
                raise GenerationExecutionError(
                    "confirmation_required",
                    "本章正文已定稿，请先确认记忆更新候选后再继续。",
                    retryable=True,
                )
        else:
            patch = service.accept_canon_patch(root, chapter_id)
        if any(operation.status == "accepted" for operation in patch.operations):
            service.apply_canon_patch(root, chapter_id)
        self.presenter._memory_updates_for_chapter(root, root.as_posix(), chapter_id)

    def _gate_blockers(self, gate: dict[str, Any]) -> list[str]:
        issues = gate.get("gate", {}).get("issues", [])
        sorted_issues = sorted(
            [item for item in issues if isinstance(item, dict)],
            key=lambda item: 0 if str(item.get("severity") or "") in {"blocker", "high"} else 1,
        )
        blockers = [
            str(item.get("message") or "").strip()
            for item in sorted_issues[:3]
            if str(item.get("message") or "").strip()
        ]
        return blockers or ["接收前检查阻断，需要先修复关键问题。"]

    def _check_gate(self, root: Path, chapter_id: str) -> dict[str, Any]:
        report = self.presenter.chapter_gate_service.check_chapter(
            root,
            chapter_id,
            draft_path=f"drafts/{chapter_id}.generated.md",
        )
        if self.presenter._stored_chapter_status(root, chapter_id) != "完成":
            self.presenter._write_chapter_status(root, chapter_id, "审阅")
        return {
            "gate": {
                "status": report.status,
                "score": report.score,
                "issues": [
                    {
                        "severity": issue.severity,
                        "stage": issue.stage,
                        "type": issue.type,
                        "message": issue.message,
                    }
                    for issue in report.issues
                ],
                "recommendedNextAction": report.recommendedNextAction,
            },
            "display": self.presenter._gate_display(report.status, report.score),
        }

    def _blocked_state(
        self,
        root: Path,
        current: dict[str, Any],
        error: GenerationExecutionError,
    ) -> dict[str, Any]:
        return self._state(
            root,
            current,
            stage=(
                "memory"
                if error.code == "memory_update_failed"
                else str(current.get("stage") or self.presenter._derived_generation_stage(root))
            ),
            status="paused" if error.code == "cancelled" else "blocked",
            next_action=(
                "恢复后从当前阶段继续。"
                if error.code == "cancelled"
                else "处理模型或生成问题后重试当前阶段。"
            ),
            blockers=[error.author_message],
            last_result=error.author_message,
            run_status="cancelled" if error.code == "cancelled" else "failed",
            can_retry=error.retryable,
            recovery_summary="当前阶段和已有候选已保留。",
        )

    def _state(
        self,
        root: Path,
        current: dict[str, Any],
        *,
        stage: str,
        status: str,
        mode: str | None = None,
        batch_target: int | None = None,
        batch_done: int | None = None,
        auto_step_limit: int | None = None,
        auto_steps_used: int | None = None,
        active_chapter_id: str | None = None,
        next_action: str,
        blockers: list[str] | None = None,
        confirmations: list[str] | None = None,
        last_result: str,
        artifact_type: str | None = None,
        run_status: str | None = None,
        source_model_label: str | None = None,
        retry_count: int | None = None,
        can_retry: bool | None = None,
        can_confirm: bool | None = None,
        recovery_summary: str | None = None,
        candidate_options: list[dict[str, str]] | None = None,
        selected_option_id: str | None = None,
        clear_artifact: bool = False,
    ) -> dict[str, Any]:
        resolved_mode = mode or self.presenter._generation_mode(current)
        resolved_batch_target = batch_target or self.presenter._generation_batch_target(current)
        state = self.presenter._generation_state_payload(
            root,
            stage=stage,
            status=status,
            mode=resolved_mode,
            batch_target=resolved_batch_target,
            batch_done=(int(current.get("batchDone") or 0) if batch_done is None else batch_done),
            auto_step_limit=(
                self.presenter._generation_auto_step_limit(
                    current,
                    mode=resolved_mode,
                    batch_target=resolved_batch_target,
                )
                if auto_step_limit is None
                else auto_step_limit
            ),
            auto_steps_used=(
                int(current.get("autoStepsUsed") or 0)
                if auto_steps_used is None
                else auto_steps_used
            ),
            active_chapter_id=(
                str(current.get("activeChapterId") or self.presenter._latest_chapter_id(root))
                if active_chapter_id is None
                else active_chapter_id
            ),
            next_action=next_action,
            blockers=blockers or [],
            confirmations=confirmations or [],
            last_result=last_result,
            active_artifact_type=(
                ""
                if clear_artifact
                else artifact_type or str(current.get("activeArtifactType") or "")
            ),
            active_run_status=(
                "" if clear_artifact else run_status or str(current.get("activeRunStatus") or "")
            ),
            source_model_label=(
                ""
                if clear_artifact
                else source_model_label or str(current.get("sourceModelLabel") or "")
            ),
            retry_count=(
                0
                if clear_artifact
                else int(current.get("retryCount") or 0)
                if retry_count is None
                else retry_count
            ),
            can_retry=False
            if clear_artifact
            else bool(current.get("canRetry"))
            if can_retry is None
            else can_retry,
            can_confirm=False
            if clear_artifact
            else bool(current.get("canConfirm"))
            if can_confirm is None
            else can_confirm,
            can_takeover=True,
            recovery_summary=(
                ""
                if clear_artifact
                else recovery_summary or str(current.get("recoverySummary") or "")
            ),
            candidate_options=(
                [] if clear_artifact else candidate_options or current.get("candidateOptions") or []
            ),
            selected_option_id=(
                ""
                if clear_artifact
                else selected_option_id or str(current.get("selectedOptionId") or "")
            ),
        )
        return state

    def _direction_option_summaries(self, candidate: dict[str, Any]) -> list[dict[str, str]]:
        options = candidate.get("options")
        if not isinstance(options, list):
            return []
        return [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "summary": str(item.get("centralConflict") or ""),
                "readerExperience": str(item.get("targetReaderExperience") or ""),
                "recommendation": str(item.get("recommendation") or ""),
            }
            for item in options
            if isinstance(item, dict)
        ]
