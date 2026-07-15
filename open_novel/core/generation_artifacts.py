from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from open_novel.core.active_prohibitions import ActiveProhibitionService
from open_novel.core.long_form_planning import LongFormPlanService
from open_novel.core.models import SceneContract, SkillRunRequest, SkillRunResult, utc_now
from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.skills import SkillRunner
from open_novel.core.writing_model import WritingModelService

CLI_AGENTS = {"codex-cli": "codex", "claude-cli": "claude", "qwen-cli": "qwen"}


@dataclass(frozen=True)
class GenerationRoute:
    agent_id: str
    model_profile: str | None
    label: str
    bypass_cache: bool = False


class GenerationExecutionError(RuntimeError):
    def __init__(self, code: str, author_message: str, *, retryable: bool = False) -> None:
        super().__init__(author_message)
        self.code = code
        self.author_message = author_message
        self.retryable = retryable


class GenerationArtifactService:
    direction_candidate_path = "story/generation-candidates/book-directions.json"
    architecture_candidate_path = "story/generation-candidates/book-architecture.json"
    blueprint_candidate_path = "story/generation-candidates/chapter-blueprint.json"
    candidate_versions_path = "story/generation-candidates/versions"

    def __init__(
        self,
        project_service: ProjectService,
        model_service: WritingModelService,
        skill_runner: SkillRunner,
    ) -> None:
        self.project_service = project_service
        self.model_service = model_service
        self.skill_runner = skill_runner
        self.long_form_planning = LongFormPlanService(project_service)
        self.project_plan = ProjectPlanService(project_service)

    def resolve_route(self, root: Path, selected_model_id: str) -> GenerationRoute:
        _ = root, selected_model_id
        try:
            account = self.skill_runner.ai_runtime_service.account_for_role("writing")
        except (AttributeError, FileNotFoundError) as exc:
            raise GenerationExecutionError(
                "model_not_configured",
                "尚未给写作角色分配可用 AI 账号，请先到模型页完成设置。",
            ) from exc
        return GenerationRoute("api-writing", None, account.name)

    def generate_directions(
        self,
        root: Path,
        route: GenerationRoute,
        *,
        title: str,
        genre: str,
        idea: str,
        style_label: str,
    ) -> tuple[dict[str, Any], SkillRunResult]:
        result = self._run(
            root,
            route,
            "book-direction-generator",
            {
                "bookTitle": title,
                "genre": genre,
                "idea": idea,
                "styleLabel": style_label,
                "optionCount": "3",
            },
        )
        payload = self._parse_json(result.outputText)
        options = payload.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= 3:
            self._invalid("作品方向必须包含 2 到 3 套完整候选。")
        normalized: list[dict[str, Any]] = []
        required = [
            "title",
            "genrePositioning",
            "protagonistDesire",
            "centralConflict",
            "serialHook",
            "targetReaderExperience",
            "recommendation",
        ]
        for index, raw in enumerate(options, start=1):
            if not isinstance(raw, dict):
                self._invalid("作品方向候选格式不完整。")
            option = {key: self._required_text(raw, key) for key in required}
            option["id"] = str(raw.get("id") or f"direction-{index}").strip()
            risks = raw.get("risks")
            option["risks"] = self._string_list(risks)
            if not option["risks"]:
                self._invalid("每套作品方向必须说明主要风险。")
            normalized.append(option)
        ids = {item["id"] for item in normalized}
        if len(ids) != len(normalized):
            self._invalid("作品方向候选 id 不能重复。")
        recommended = str(payload.get("recommendedOptionId") or normalized[0]["id"]).strip()
        if recommended not in ids:
            self._invalid("推荐作品方向必须指向一个有效候选。")
        candidate = {
            "schemaVersion": 1,
            "artifactType": "book_direction",
            "sourceAgentId": result.agentId,
            "sourceModelProfile": result.modelProfile or "",
            "runId": result.runId,
            "status": "candidate",
            "recommendedOptionId": recommended,
            "options": normalized,
            "createdAt": utc_now().isoformat(),
        }
        self._write_candidate(root, self.direction_candidate_path, candidate)
        return candidate, result

    def build_architecture(
        self,
        root: Path,
        route: GenerationRoute,
        option_id: str,
        architecture_path: str,
    ) -> tuple[dict[str, Any], SkillRunResult]:
        candidate = self._read_json(root, self.direction_candidate_path)
        options = candidate.get("options") if isinstance(candidate, dict) else None
        if not isinstance(options, list):
            self._invalid("当前没有可确认的作品方向候选。")
        selected_id = option_id.strip() or str(candidate.get("recommendedOptionId") or "")
        selected = next(
            (item for item in options if isinstance(item, dict) and item.get("id") == selected_id),
            None,
        )
        if selected is None:
            self._invalid("请选择一个有效的作品方向候选。")
        result = self._run(
            root,
            route,
            "book-architecture-builder",
            {"selectedDirection": json.dumps(selected, ensure_ascii=False)},
        )
        payload = self._parse_json(result.outputText)
        book = self.project_service.open_project(root)
        core_selling_points = self._string_list(payload.get("coreSellingPoints"))
        long_term_hooks = self._string_list(payload.get("longTermHooks"))
        risks = self._string_list(payload.get("risks"))
        if not core_selling_points or not long_term_hooks or not risks:
            self._invalid("正式作品架构必须包含核心卖点、长线钩子和执行风险。")
        architecture = {
            "schemaVersion": 2,
            "title": book.metadata.title,
            "directionId": selected_id,
            "directionTitle": self._required_text(payload, "directionTitle"),
            "genrePositioning": self._required_text(payload, "genrePositioning"),
            "coreSellingPoints": core_selling_points,
            "protagonistDesire": self._required_text(payload, "protagonistGoal"),
            "centralConflict": self._required_text(payload, "centralConflict"),
            "storyEngine": self._required_text(payload, "storyEngine"),
            "escalationPath": self._required_text(payload, "escalationPath"),
            "longTermHooks": long_term_hooks,
            "serialHook": long_term_hooks[0],
            "targetReaderExperience": self._required_text(payload, "targetReaderExperience"),
            "risks": risks,
            "recommendation": self._required_text(payload, "recommendation"),
            "sourceRunId": result.runId,
            "createdAt": utc_now().isoformat(),
        }
        self._write_json(
            root,
            self.architecture_candidate_path,
            {
                "schemaVersion": 1,
                "artifactType": "book_architecture",
                "sourceAgentId": result.agentId,
                "sourceModelProfile": result.modelProfile or "",
                "runId": result.runId,
                "status": "accepted",
                "architecture": architecture,
                "createdAt": utc_now().isoformat(),
            },
        )
        self._write_json(root, architecture_path, architecture)
        candidate["status"] = "accepted"
        candidate["selectedOptionId"] = selected_id
        self._write_json(root, self.direction_candidate_path, candidate)
        return architecture, result

    def generate_blueprint(
        self,
        root: Path,
        route: GenerationRoute,
        *,
        chapter_count: int,
    ) -> tuple[dict[str, Any], SkillRunResult]:
        result = self._run(
            root,
            route,
            "chapter-blueprint-builder",
            {"chapterCount": str(chapter_count)},
        )
        payload = self._parse_json(result.outputText)
        try:
            normalized = self._normalize_blueprint(payload, chapter_count)
        except GenerationExecutionError as exc:
            result = self._run(
                root,
                route,
                "chapter-blueprint-repairer",
                {
                    "chapterCount": str(chapter_count),
                    "validationFeedback": exc.author_message,
                    "previousBlueprint": result.outputText,
                },
            )
            payload = self._parse_json(result.outputText)
            normalized = self._normalize_blueprint(payload, chapter_count)
        candidate = {
            "schemaVersion": 2,
            "artifactType": "chapter_blueprint",
            "sourceAgentId": result.agentId,
            "sourceModelProfile": result.modelProfile or "",
            "runId": result.runId,
            "status": "candidate",
            "chapters": normalized,
            "createdAt": utc_now().isoformat(),
        }
        self._write_candidate(root, self.blueprint_candidate_path, candidate)
        return candidate, result

    def generate_long_form_plan(
        self,
        root: Path,
        route: GenerationRoute,
        *,
        replan: bool = False,
        deviation_report: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], SkillRunResult]:
        skill_id = "long-form-replanner" if replan else "long-form-planner"
        project_plan = self.project_plan.read_plan(root)
        variables = {
            "targetChapterCount": str(project_plan.targetChapterCount),
            "targetChaptersPerPlot": str(project_plan.targetChaptersPerPlot),
        }
        if replan:
            variables["deviationReport"] = json.dumps(
                deviation_report or {}, ensure_ascii=False
            )
        result = self._run(root, route, skill_id, variables)
        payload = self._parse_json(result.outputText)
        try:
            plan = self.long_form_planning.validate_plan(payload)
        except ValueError as exc:
            raise GenerationExecutionError(
                "invalid_structured_output",
                str(exc),
                retryable=True,
            ) from exc
        candidate = {
            "schemaVersion": 1,
            "artifactType": "long_form_replan" if replan else "long_form_plan",
            "sourceAgentId": result.agentId,
            "sourceModelProfile": result.modelProfile or "",
            "runId": result.runId,
            "status": "candidate",
            "plan": plan,
            "createdAt": utc_now().isoformat(),
        }
        candidate_path = (
            self.long_form_planning.replan_candidate_path
            if replan
            else self.long_form_planning.candidate_path
        )
        self._write_candidate(root, candidate_path, candidate)
        return candidate, result

    def apply_long_form_plan(self, root: Path, *, replan: bool = False) -> dict[str, Any]:
        candidate_path = (
            self.long_form_planning.replan_candidate_path
            if replan
            else self.long_form_planning.candidate_path
        )
        plan = self.long_form_planning.apply_candidate(root, candidate_path)
        if replan:
            self.long_form_planning.mark_replanned(root)
        return plan

    def _normalize_blueprint(
        self,
        payload: dict[str, Any],
        chapter_count: int,
    ) -> list[dict[str, Any]]:
        chapters = payload.get("chapters")
        if not isinstance(chapters, list) or len(chapters) != chapter_count:
            self._invalid(f"章节蓝图必须恰好包含 {chapter_count} 章。")
        normalized: list[dict[str, Any]] = []
        required = [
            "title",
            "goal",
            "conflict",
            "turn",
            "outcome",
            "hook",
            "characterChange",
            "promiseProgression",
        ]
        for index, raw in enumerate(chapters, start=1):
            if not isinstance(raw, dict):
                self._invalid("章节蓝图条目格式不完整。")
            item = {key: self._required_text(raw, key) for key in required}
            item["chapterId"] = f"{index:03d}"
            item["logicDependencies"] = self._string_list(raw.get("logicDependencies"))
            normalized.append(item)
        for field in ["title", "goal", "hook"]:
            values = [self._comparison_text(item[field]) for item in normalized]
            if len(set(values)) != len(values):
                self._invalid(f"章节蓝图的 {field} 不能重复。")
        return normalized

    def apply_blueprint(self, root: Path, blueprint_path: str) -> dict[str, Any]:
        candidate = self._read_json(root, self.blueprint_candidate_path)
        chapters = candidate.get("chapters") if isinstance(candidate, dict) else None
        if not isinstance(chapters, list) or not chapters:
            self._invalid("当前没有可确认的章节蓝图候选。")
        blueprint = {
            "schemaVersion": 2,
            "bookTitle": self.project_service.open_project(root).metadata.title,
            "sourceRunId": candidate.get("runId", ""),
            "chapters": chapters,
            "createdAt": utc_now().isoformat(),
        }
        self._write_json(root, blueprint_path, blueprint)
        candidate["status"] = "accepted"
        self._write_json(root, self.blueprint_candidate_path, candidate)
        return blueprint

    def generate_contract(
        self,
        root: Path,
        route: GenerationRoute,
        *,
        chapter_id: str,
        chapter_intent: str,
    ) -> tuple[SceneContract, SkillRunResult]:
        prohibition_service = ActiveProhibitionService(self.project_service)
        prohibition_items = prohibition_service.collect(root)
        result = self._run(
            root,
            route,
            "generation-scene-contract-builder",
            {
                "chapterId": chapter_id,
                "chapterIntent": chapter_intent,
                "activeProhibitions": prohibition_service.format_for_prompt(root),
            },
        )
        payload = self._parse_json(result.outputText)
        payload["chapterId"] = chapter_id
        payload["pov"] = self._normalize_pov(str(payload.get("pov") or ""))
        existing_must_avoid = self._string_list(payload.get("mustAvoid"))
        payload["mustAvoid"] = list(
            dict.fromkeys(
                [
                    *existing_must_avoid,
                    *[str(item["forbidden"]) for item in prohibition_items],
                ]
            )
        )
        try:
            contract = SceneContract.model_validate(payload)
        except ValidationError as exc:
            self._invalid(f"章节合同字段不完整：{exc.errors()[0]['loc'][-1]}。")
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
        if not all(str(value or "").strip() for value in required):
            self._invalid("章节合同必须包含完整的剧情、人物和情绪字段。")
        if not contract.mustAvoid or not contract.readerPromises:
            self._invalid("章节合同必须包含避免项和读者承诺。")
        candidate_path = self.contract_candidate_path(chapter_id)
        self._write_candidate(
            root,
            candidate_path,
            {
                "schemaVersion": 1,
                "artifactType": "scene_contract",
                "sourceAgentId": result.agentId,
                "sourceModelProfile": result.modelProfile or "",
                "runId": result.runId,
                "status": "candidate",
                "contract": contract.model_dump(mode="json"),
                "createdAt": utc_now().isoformat(),
            },
        )
        return contract, result

    def _normalize_pov(self, value: str) -> str:
        normalized = re.sub(
            r"(?:第一|第二|第三)人称|有限视角|限知|全知|主视角|视角|POV",
            "",
            value,
            flags=re.IGNORECASE,
        )
        normalized = normalized.strip(" ，,。:：-_/")
        return normalized or value.strip()

    def read_contract_candidate(self, root: Path, chapter_id: str) -> SceneContract:
        candidate = self._read_json(root, self.contract_candidate_path(chapter_id))
        contract = candidate.get("contract") if isinstance(candidate, dict) else None
        if not isinstance(contract, dict):
            self._invalid("当前没有可确认的章节合同候选。")
        try:
            return SceneContract.model_validate(contract)
        except ValidationError as exc:
            raise GenerationExecutionError(
                "invalid_structured_output",
                "章节合同候选已损坏，请重新生成。",
                retryable=True,
            ) from exc

    def mark_contract_accepted(self, root: Path, chapter_id: str) -> None:
        path = self.contract_candidate_path(chapter_id)
        candidate = self._read_json(root, path)
        candidate["status"] = "accepted"
        self._write_json(root, path, candidate)

    def current_candidate(self, root: Path, stage: str, chapter_id: str) -> dict[str, Any] | None:
        path = {
            "architecture": self.direction_candidate_path,
            "blueprint": self.blueprint_candidate_path,
            "contract": self.contract_candidate_path(chapter_id),
        }.get(stage)
        if not path:
            return None
        candidate = self._read_json(root, path)
        return candidate or None

    def candidate_path_for(
        self,
        stage: str,
        chapter_id: str,
        artifact_type: str = "",
    ) -> str | None:
        if artifact_type in {"long_form_plan", "long_form_replan"}:
            return (
                self.long_form_planning.replan_candidate_path
                if artifact_type == "long_form_replan"
                else self.long_form_planning.candidate_path
            )
        return {
            "architecture": self.direction_candidate_path,
            "blueprint": self.blueprint_candidate_path,
            "contract": self.contract_candidate_path(chapter_id),
        }.get(stage)

    def candidate_versions(
        self,
        root: Path,
        stage: str,
        chapter_id: str,
        artifact_type: str = "",
    ) -> list[dict[str, Any]]:
        path = self.candidate_path_for(stage, chapter_id, artifact_type)
        if not path:
            return []
        current = self._read_json(root, path)
        versions = self._archived_candidates(root, path)
        if current:
            if not str(current.get("candidateId") or "").strip():
                version = max((int(item.get("version") or 0) for item in versions), default=0) + 1
                artifact_type = self._candidate_artifact_type(path, current)
                current = {
                    **current,
                    "artifactType": artifact_type,
                    "version": version,
                    "candidateId": f"{artifact_type}-v{version}",
                }
                self._write_json(root, path, current)
            versions.append(current)
        unique: dict[str, dict[str, Any]] = {}
        for candidate in versions:
            candidate_id = str(candidate.get("candidateId") or "").strip()
            if candidate_id:
                unique[candidate_id] = candidate
        return sorted(
            unique.values(),
            key=lambda item: int(item.get("version") or 0),
            reverse=True,
        )

    def select_candidate(
        self,
        root: Path,
        stage: str,
        chapter_id: str,
        candidate_id: str,
        artifact_type: str = "",
    ) -> dict[str, Any]:
        path = self.candidate_path_for(stage, chapter_id, artifact_type)
        if not path:
            self._invalid("当前阶段没有可选择的候选版本。")
        selected = next(
            (
                item
                for item in self.candidate_versions(root, stage, chapter_id, artifact_type)
                if str(item.get("candidateId") or "") == candidate_id
            ),
            None,
        )
        if selected is None:
            self._invalid("所选候选版本不存在，请刷新后重试。")
        current = self._read_json(root, path)
        if current and current.get("candidateId") != selected.get("candidateId"):
            self._archive_candidate(root, path, current)
        selected = {**selected, "status": "candidate", "selectedAt": utc_now().isoformat()}
        self._write_json(root, path, selected)
        return selected

    def long_form_candidate(self, root: Path, *, replan: bool = False) -> dict[str, Any] | None:
        path = (
            self.long_form_planning.replan_candidate_path
            if replan
            else self.long_form_planning.candidate_path
        )
        candidate = self._read_json(root, path)
        return candidate or None

    def contract_candidate_path(self, chapter_id: str) -> str:
        return f"story/generation-candidates/{chapter_id}.scene-contract.json"

    def _run(
        self,
        root: Path,
        route: GenerationRoute,
        skill_id: str,
        variables: dict[str, str],
    ) -> SkillRunResult:
        try:
            return self.skill_runner.run(
                SkillRunRequest(
                    projectRoot=root,
                    skillId=skill_id,
                    variables=variables,
                    agentId=route.agent_id,
                    modelProfile=route.model_profile,
                    bypassCache=route.bypass_cache,
                )
            )
        except FileNotFoundError as exc:
            raise GenerationExecutionError(
                "model_unavailable",
                "生成模型当前不可用，请验证模型后重试。",
            ) from exc
        except (RuntimeError, ValueError) as exc:
            message = str(exc).lower()
            if "cancel" in message:
                raise GenerationExecutionError(
                    "cancelled",
                    "本次生成已取消，可以从当前阶段恢复。",
                    retryable=True,
                ) from exc
            if "timeout" in message or "timed out" in message:
                raise GenerationExecutionError(
                    "generation_timeout",
                    "模型生成超时，可以重试、缩小批次或更换模型。",
                    retryable=True,
                ) from exc
            raise GenerationExecutionError(
                "upstream_failed",
                "模型生成没有完成，可以重试或更换模型。",
                retryable=True,
            ) from exc

    def _parse_json(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            if start < 0:
                self._invalid("模型没有返回结构化 JSON。")
            depth = 0
            in_string = False
            escaped = False
            end = -1
            for index, char in enumerate(stripped[start:], start=start):
                if escaped:
                    escaped = False
                    continue
                if char == "\\" and in_string:
                    escaped = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end < 0:
                self._invalid("模型返回的 JSON 不完整。")
            try:
                payload = json.loads(stripped[start:end])
            except json.JSONDecodeError as exc:
                raise GenerationExecutionError(
                    "invalid_structured_output",
                    "模型返回的结构化内容无法解析，请重新生成。",
                    retryable=True,
                ) from exc
        if not isinstance(payload, dict):
            self._invalid("模型返回的结构化内容必须是 JSON 对象。")
        return payload

    def _required_text(self, payload: dict[str, Any], key: str) -> str:
        value = str(payload.get(key) or "").strip()
        if not value:
            self._invalid(f"模型返回缺少 {key}。")
        return value

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _comparison_text(self, value: str) -> str:
        return "".join(value.lower().split())

    def _route_label(self, agent_id: str) -> str:
        return {
            "codex-cli": "Codex CLI",
            "claude-cli": "Claude Code",
            "qwen-cli": "Qwen Code",
        }.get(agent_id, agent_id)

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            payload = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, root: Path, relative_path: str, payload: dict[str, Any]) -> None:
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _write_candidate(self, root: Path, relative_path: str, payload: dict[str, Any]) -> None:
        current = self._read_json(root, relative_path)
        if current:
            self._archive_candidate(root, relative_path, current)
        versions = self._archived_candidates(root, relative_path)
        next_version = max((int(item.get("version") or 0) for item in versions), default=0) + 1
        artifact_type = self._candidate_artifact_type(relative_path, payload)
        candidate = {
            **payload,
            "artifactType": artifact_type,
            "version": next_version,
            "candidateId": f"{artifact_type}-v{next_version}",
        }
        self._write_json(root, relative_path, candidate)

    def _archive_candidate(
        self,
        root: Path,
        relative_path: str,
        candidate: dict[str, Any],
    ) -> None:
        candidate_id = str(candidate.get("candidateId") or "").strip()
        if not candidate_id:
            version = (
                max(
                    (
                        int(item.get("version") or 0)
                        for item in self._archived_candidates(root, relative_path)
                    ),
                    default=0,
                )
                + 1
            )
            artifact_type = self._candidate_artifact_type(relative_path, candidate)
            candidate = {
                **candidate,
                "artifactType": artifact_type,
                "version": version,
                "candidateId": f"{artifact_type}-v{version}",
            }
            candidate_id = str(candidate["candidateId"])
        archive_path = self._candidate_archive_path(relative_path, candidate_id)
        if not self.project_service.file_exists(root, archive_path):
            self._write_json(root, archive_path, candidate)

    def _archived_candidates(self, root: Path, relative_path: str) -> list[dict[str, Any]]:
        prefix = f"{self.candidate_versions_path}/{Path(relative_path).stem}"
        versions: list[dict[str, Any]] = []
        for archive_path in self.project_service.list_paths(root, prefix):
            if not archive_path.endswith(".json"):
                continue
            payload = self._read_json(root, archive_path)
            if payload:
                artifact_type = self._candidate_artifact_type(relative_path, payload)
                if str(payload.get("artifactType") or "") != artifact_type:
                    payload["artifactType"] = artifact_type
                    self._write_json(root, archive_path, payload)
                versions.append(payload)
        return versions

    def _candidate_archive_path(self, relative_path: str, candidate_id: str) -> str:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", candidate_id).strip("-")
        return f"{self.candidate_versions_path}/{Path(relative_path).stem}/{safe_id}.json"

    def _candidate_artifact_type(
        self,
        relative_path: str,
        candidate: dict[str, Any],
    ) -> str:
        existing = str(candidate.get("artifactType") or "").strip()
        if existing in {
            "book_direction",
            "chapter_blueprint",
            "long_form_plan",
            "long_form_replan",
            "scene_contract",
        }:
            return existing
        if relative_path == self.direction_candidate_path:
            return "book_direction"
        if relative_path == self.blueprint_candidate_path:
            return "chapter_blueprint"
        if relative_path == self.long_form_planning.candidate_path:
            return "long_form_plan"
        if relative_path == self.long_form_planning.replan_candidate_path:
            return "long_form_replan"
        if relative_path.endswith(".scene-contract.json"):
            return "scene_contract"
        return Path(relative_path).stem

    def _invalid(self, detail: str) -> None:
        raise GenerationExecutionError(
            "invalid_structured_output",
            detail,
            retryable=True,
        )
