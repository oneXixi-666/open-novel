from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.models import ReadinessIssue, ReadinessReport, SceneContract
from open_novel.core.project import ProjectService


class StoryGuidanceService:
    required_fields = {
        "focus": (
            "blocker",
            "缺少本章重点，章节容易变成散点推进。",
            "用一句话写清本章最重要的读者收获。",
        ),
        "goal": (
            "blocker",
            "缺少主角或场景目标，行动线不够清楚。",
            "补一句角色想在本章达成什么。",
        ),
        "conflict": (
            "blocker",
            "缺少反对力量或阻碍，章节会缺少张力。",
            "指定一个人物、规则、环境或内心阻力。",
        ),
        "turn": (
            "high",
            "缺少转折，章节可能只有线性推进。",
            "补一个信息、局势或关系上的变化点。",
        ),
        "outcome": (
            "blocker",
            "缺少结果，章节结束后状态变化不明确。",
            "写清本章结束时事实、关系或局势发生了什么变化。",
        ),
        "hook": (
            "high",
            "缺少结尾钩子，连载阅读动力不足。",
            "补一个新问题、危险、承诺或未完成动作。",
        ),
        "emotionalBeat": (
            "high",
            "缺少情绪节拍，角色体验和读者情感连接会偏弱。",
            "写清角色从什么情绪走向什么情绪，以及触发原因。",
        ),
    }
    human_core_fields = {
        "internalNeed": (
            "medium",
            "缺少人物内在需求，角色行动容易只剩剧情任务。",
            "补一句主角真正想证明、守住或逃开的东西。",
        ),
        "woundOrFear": (
            "low",
            "缺少旧伤或恐惧，冲突对人物的刺痛感会偏弱。",
            "补一句本章压力戳中了角色哪处旧伤或恐惧。",
        ),
        "stakes": (
            "medium",
            "缺少失败代价，人物选择容易没有重量。",
            "写清如果本章失败，主角会失去什么或让谁受伤。",
        ),
        "cost": (
            "medium",
            "缺少行动代价，爽点容易像无成本开挂。",
            "写清主角推进目标后付出的代价、暴露的弱点或引来的新危险。",
        ),
        "subtext": (
            "low",
            "缺少潜台词，人物互动容易太直白。",
            "补一句角色嘴上不说但动作、停顿或误解会泄露的真意。",
        ),
        "aftertaste": (
            "low",
            "缺少章节余味，结尾可能只有钩子没有情绪回声。",
            "补一句读者在结尾应留下的爽感、不安、酸涩或期待。",
        ),
    }

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()
        from open_novel.core.context_pack import ContextPackService as _ContextPackService

        self.context_pack_service = _ContextPackService(self.project_service)

    def contract_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"story/chapter-briefs/{normalized}.json"

    def create_scene_contract(
        self,
        root: Path,
        chapter_id: str,
        title: str | None = None,
    ) -> SceneContract:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        contract = SceneContract(chapterId=normalized, title=(title or "").strip())
        self.write_scene_contract(root, contract)
        return contract

    def read_scene_contract(self, root: Path, chapter_id: str) -> SceneContract:
        return SceneContract.model_validate_json(
            self.project_service.read_text(root, self.contract_path(chapter_id))
        )

    def write_scene_contract(self, root: Path, contract: SceneContract) -> None:
        relative_path = self.contract_path(contract.chapterId)
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(contract.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self.context_pack_service.build_context_pack(root, contract.chapterId)
        from open_novel.core.chapter_pipeline import ChapterPipelineService

        pipeline = ChapterPipelineService(self.project_service)
        pipeline.update_step(
            root,
            contract.chapterId,
            "scene_contract",
            artifact=relative_path,
            message="章节要求已保存",
        )
        pipeline.update_step(
            root,
            contract.chapterId,
            "context_pack",
            artifact=f"story/context-packs/{contract.chapterId}.json",
            message="本章资料已随章节要求更新",
        )

    def check_readiness(self, root: Path, chapter_id: str) -> ReadinessReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        try:
            contract = self.read_scene_contract(root, normalized)
        except FileNotFoundError:
            return ReadinessReport(
                chapterId=normalized,
                status="block",
                score=0,
                issues=[
                    ReadinessIssue(
                        severity="blocker",
                        field="sceneContract",
                        message="缺少结构化章节合同。",
                        quickFix=f"创建 {self.contract_path(normalized)} 后再生成草稿。",
                    )
                ],
                missingContext=[self.contract_path(normalized)],
                recommendedNextAction="create-scene-contract",
            )

        issues = self._contract_issues(contract)
        blocker_count = sum(1 for issue in issues if issue.severity == "blocker")
        high_count = sum(1 for issue in issues if issue.severity == "high")
        score = max(0, 100 - blocker_count * 25 - high_count * 12 - len(issues) * 3)
        status = "pass"
        if blocker_count:
            status = "block"
        elif issues:
            status = "warn"

        missing_context = []
        if not contract.logicDependencies:
            missing_context.append("logicDependencies")
        if not contract.mustAvoid:
            missing_context.append("mustAvoid")

        return ReadinessReport(
            chapterId=normalized,
            status=status,
            score=score,
            issues=issues,
            missingContext=missing_context,
            recommendedNextAction=self._next_action(status),
        )

    def _contract_issues(self, contract: SceneContract) -> list[ReadinessIssue]:
        issues: list[ReadinessIssue] = []
        for field, (severity, message, quick_fix) in self.required_fields.items():
            value = getattr(contract, field)
            if isinstance(value, str) and value.strip():
                continue
            issues.append(
                ReadinessIssue(
                    severity=severity,
                    field=field,
                    message=message,
                    quickFix=quick_fix,
                )
            )
        for field, (severity, message, quick_fix) in self.human_core_fields.items():
            value = getattr(contract, field)
            if isinstance(value, str) and value.strip():
                continue
            issues.append(
                ReadinessIssue(
                    severity=severity,
                    field=field,
                    message=message,
                    quickFix=quick_fix,
                )
            )

        if not contract.logicDependencies:
            issues.append(
                ReadinessIssue(
                    severity="medium",
                    field="logicDependencies",
                    message="缺少逻辑依赖，后续检查很难判断因果是否成立。",
                    quickFix="列出本章成立所依赖的前置事实、时间线事件或人物知识。",
                )
            )
        if not contract.mustAvoid:
            issues.append(
                ReadinessIssue(
                    severity="medium",
                    field="mustAvoid",
                    message="缺少禁止事项，AI 生成时更容易提前揭秘或破坏设定。",
                    quickFix="列出本章不能写、不能改、不能提前揭示的内容。",
                )
            )
        if not contract.readerPromises:
            issues.append(
                ReadinessIssue(
                    severity="low",
                    field="readerPromises",
                    message="缺少读者承诺，本章爽点、谜题或情感期待不够明确。",
                    quickFix="补充本章要推进或兑现的读者期待。",
                )
            )
        if not contract.relationshipBeat:
            issues.append(
                ReadinessIssue(
                    severity="low",
                    field="relationshipBeat",
                    message="缺少关系节拍，人物关系变化容易只停留在剧情事件上。",
                    quickFix="补充本章人物关系从什么状态变到什么状态，或写明本章关系不变化。",
                )
            )
        return issues

    def _next_action(self, status: str) -> str:
        if status == "block":
            return "fill-required-scene-contract-fields"
        if status == "warn":
            return "review-readiness-warnings-before-drafting"
        return "ready-to-draft"
