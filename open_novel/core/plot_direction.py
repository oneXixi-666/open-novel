from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import PlotDirectionOption, PlotDirectionReport, SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService


class PlotDirectionService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        context_pack_service: ContextPackService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.context_pack_service = context_pack_service or ContextPackService(
            self.project_service,
            self.story_guidance,
        )

    def report_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"story/branches/{normalized}.direction-report.json"

    def suggest_directions(
        self,
        root: Path,
        chapter_id: str,
        user_intent: str,
    ) -> PlotDirectionReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        contract = self.story_guidance.read_scene_contract(root, normalized)
        context_pack = self.context_pack_service.build_context_pack(root, normalized)
        intent = user_intent.strip()
        if not intent:
            intent = "延续当前章节合同推进剧情。"

        risks = self._risks_for_intent(intent, contract.mustAvoid)
        basis = [
            f"contract:{self.story_guidance.contract_path(normalized)}",
            f"context:{context_pack.path}",
        ]
        options = [
            PlotDirectionOption(
                id=f"direction_{normalized}_recommended",
                label="稳态推进",
                recommendation="recommended",
                focus=contract.focus or intent,
                likelyOutcome=contract.outcome or "推进当前目标，并留下可继续展开的后果。",
                emotionalImpact=contract.emotionalBeat or "保持角色情绪有明确前后变化。",
                logicCost="低：沿用当前合同和已选上下文。",
                readerPromiseImpact=self._promise_impact(contract.readerPromises),
                risks=risks,
                nextContractUpdates={
                    "focus": contract.focus or intent,
                    "goal": contract.goal,
                    "outcome": contract.outcome,
                    "hook": contract.hook,
                },
            ),
            PlotDirectionOption(
                id=f"direction_{normalized}_emotional",
                label="情感加压",
                recommendation="viable",
                focus=f"围绕“{intent}”强化人物代价和关系变化。",
                likelyOutcome="剧情目标推进较慢，但人物关系和情绪余波更强。",
                emotionalImpact=contract.relationshipBeat or contract.emotionalBeat,
                logicCost="中：需要确保情绪场景仍服务主线目标。",
                readerPromiseImpact="增强读者代入，但要避免拖慢爽点或主线兑现。",
                risks=["可能稀释本章外部冲突。"],
                nextContractUpdates={
                    "emotionalBeat": contract.emotionalBeat,
                    "relationshipBeat": contract.relationshipBeat,
                },
            ),
            PlotDirectionOption(
                id=f"direction_{normalized}_reveal",
                label="提前揭示",
                recommendation="risky",
                focus=f"用“{intent}”制造更强信息刺激。",
                likelyOutcome="短期钩子更强，但可能提前消耗谜题或破坏后续铺垫。",
                emotionalImpact="角色会更快进入震惊、怀疑或对抗状态。",
                logicCost="高：需要检查 mustAvoid、伏笔窗口和角色知识边界。",
                readerPromiseImpact="可能提前兑现承诺，也可能让长期悬念缩水。",
                risks=risks or ["可能提前解释核心谜题。"],
                nextContractUpdates={"mustAvoid": contract.mustAvoid},
            ),
        ]
        recommended = next(
            option.id for option in options if option.recommendation == "recommended"
        )
        report = PlotDirectionReport(
            chapterId=normalized,
            userIntent=intent,
            basis=basis,
            options=options,
            recommendedOptionId=recommended,
        )
        self.project_service.write_text(
            root,
            self.report_path(normalized),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def read_direction_report(self, root: Path, chapter_id: str) -> PlotDirectionReport:
        return PlotDirectionReport.model_validate_json(
            self.project_service.read_text(root, self.report_path(chapter_id))
        )

    def apply_direction(
        self,
        root: Path,
        chapter_id: str,
        option_id: str,
    ) -> SceneContract:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        report = self.read_direction_report(root, normalized)
        option = next((item for item in report.options if item.id == option_id), None)
        if option is None:
            raise ValueError(f"unknown direction option: {option_id}")
        if option.recommendation == "risky":
            raise ValueError("risky direction options must be revised before applying")
        contract = self.story_guidance.read_scene_contract(root, normalized)
        updates = option.nextContractUpdates
        for field, value in updates.items():
            if hasattr(contract, field):
                setattr(contract, field, value)
        if option.focus:
            contract.focus = option.focus
        if option.likelyOutcome:
            contract.outcome = option.likelyOutcome
        if option.emotionalImpact:
            contract.emotionalBeat = option.emotionalImpact
        self.story_guidance.write_scene_contract(root, contract)
        return contract

    def _risks_for_intent(self, user_intent: str, must_avoid: list[str]) -> list[str]:
        risks = []
        for forbidden in must_avoid:
            if forbidden and self._intent_touches_forbidden(user_intent, forbidden):
                risks.append(f"用户意图触碰禁止事项：{forbidden}")
        return risks

    def _intent_touches_forbidden(self, user_intent: str, forbidden: str) -> bool:
        if forbidden in user_intent or user_intent in forbidden:
            return True
        intent_terms = set(self._terms(user_intent))
        forbidden_terms = set(self._terms(forbidden))
        if intent_terms & forbidden_terms:
            return True
        reveal_words = {"揭秘", "揭示", "解释", "真相", "曝光", "暴露"}
        return bool(intent_terms & reveal_words and forbidden_terms & reveal_words)

    def _terms(self, text: str) -> list[str]:
        separators = " ，,。.!！?？、；;：:\n\t"
        normalized = text
        for separator in separators:
            normalized = normalized.replace(separator, " ")
        terms = [part.strip() for part in normalized.split(" ") if part.strip()]
        if not terms:
            terms = [text]
        compact = "".join(terms)
        for word in ["提前", "揭秘", "揭示", "解释", "真相", "曝光", "暴露"]:
            if word in compact:
                terms.append(word)
        return terms

    def _promise_impact(self, promises: list[str]) -> str:
        if not promises:
            return "未绑定明确读者承诺，建议先补 readerPromises。"
        return "推进读者承诺：" + "、".join(promises)
