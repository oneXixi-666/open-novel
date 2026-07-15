from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from open_novel.core.book_analysis import BookAnalysisReport, BookAnalysisService
from open_novel.core.models import SkillRunRequest
from open_novel.core.project import ProjectService

if TYPE_CHECKING:
    from open_novel.core.skills import SkillRunner


class WritingFormula(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    guidance: str
    status: Literal["suggested", "active", "retired"] = "suggested"
    evidenceChapters: list[str] = Field(default_factory=list)
    evidenceQuotes: list[str] = Field(default_factory=list)
    sourceAnalysis: str = ""
    confidence: float = 0.5


class WritingFormulaMemory(BaseModel):
    schemaVersion: int = 1
    formulas: list[WritingFormula] = Field(default_factory=list)


class WritingFormulaCandidate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=40)
    guidance: str = Field(min_length=1, max_length=300)
    evidenceQuotes: list[str] = Field(min_length=1, max_length=3)
    confidence: float = Field(ge=0, le=1)

    @field_validator("evidenceQuotes")
    @classmethod
    def normalize_quotes(cls, value: list[str]) -> list[str]:
        quotes = [item.strip() for item in value if item.strip()]
        if not quotes:
            raise ValueError("evidenceQuotes must contain at least one quote")
        return list(dict.fromkeys(quotes))


class WritingFormulaCandidateArtifact(BaseModel):
    schemaVersion: int = 1
    status: Literal["candidate", "promoted"] = "candidate"
    runId: str
    sourceLabel: str
    sourceHash: str
    agentId: str
    candidates: list[WritingFormulaCandidate] = Field(min_length=1)


class WritingFormulaService:
    memory_path = "memory/writing-formulas.json"

    formula_catalog = {
        "conflict_visible_in_scene": (
            "冲突必须场景化",
            "把阻力写成可见动作、规则压力或人物对抗，而不是只在叙述里说明。",
        ),
        "dialogue_carries_pressure": (
            "对白承载压力",
            "关键对白要推动选择、试探关系或暴露代价，避免只做信息转述。",
        ),
        "ending_hook_grounded": (
            "钩子从结果里长出来",
            "章末新问题应由本章结果自然引出，并留下下一步行动压力。",
        ),
        "emotion_named_and_enacted": (
            "情绪有触发和动作",
            "情绪节拍要同时有触发、身体/动作反应和选择变化。",
        ),
        "reader_promise_advanced": (
            "读者承诺必须推进",
            "每章至少让一个读者承诺出现新线索、兑现一小步或付出新代价。",
        ),
    }

    def __init__(
        self,
        project_service: ProjectService | None = None,
        book_analysis_service: BookAnalysisService | None = None,
        skill_runner: SkillRunner | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.book_analysis_service = book_analysis_service or BookAnalysisService(
            self.project_service
        )
        if skill_runner is None:
            from open_novel.core.skills import SkillRunner

            skill_runner = SkillRunner(project_service=self.project_service)
        self.skill_runner = skill_runner

    def read_memory(self, root: Path) -> WritingFormulaMemory:
        if not self.project_service.file_exists(root, self.memory_path):
            return WritingFormulaMemory()
        return WritingFormulaMemory.model_validate_json(
            self.project_service.read_text(root, self.memory_path)
        )

    def write_memory(self, root: Path, memory: WritingFormulaMemory) -> None:
        self.project_service.write_text(
            root,
            self.memory_path,
            json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def promote_from_analysis(self, root: Path, report_path: str) -> WritingFormulaMemory:
        report = self.book_analysis_service.read_report(root, report_path)
        memory = self.read_memory(root)
        by_id = {formula.id: formula for formula in memory.formulas}
        for candidate in report.formulaCandidates:
            formula_id = str(candidate.get("id") or "")
            evidence = [str(item) for item in candidate.get("evidenceChapters", []) if str(item)]
            if not formula_id or not evidence:
                continue
            title, guidance = self.formula_catalog.get(
                formula_id,
                (formula_id.replace("_", " "), "保留该写法模式，后续由作者人工细化。"),
            )
            existing = by_id.get(formula_id)
            if existing is None:
                by_id[formula_id] = WritingFormula(
                    id=formula_id,
                    title=title,
                    guidance=guidance,
                    evidenceChapters=evidence,
                    sourceAnalysis=report.path,
                    confidence=float(candidate.get("confidence") or 0.5),
                )
                continue
            existing.evidenceChapters = sorted(set([*existing.evidenceChapters, *evidence]))
            existing.sourceAnalysis = report.path
            existing.confidence = max(
                existing.confidence,
                float(candidate.get("confidence") or 0.5),
            )
        updated = WritingFormulaMemory(formulas=sorted(by_id.values(), key=lambda item: item.id))
        self.write_memory(root, updated)
        return updated

    def promote_report(self, root: Path, report: BookAnalysisReport) -> WritingFormulaMemory:
        self.project_service.write_text(
            root,
            report.path,
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return self.promote_from_analysis(root, report.path)

    def extract_external_candidates(
        self,
        root: Path,
        *,
        source_text: str,
        source_label: str,
        agent_id: str,
        model_profile: str | None = None,
    ) -> tuple[WritingFormulaCandidateArtifact, str]:
        text = source_text.strip()
        label = source_label.strip()
        if not text or len(text) > 50_000:
            raise ValueError("外部文本长度必须在 1 到 50000 字符之间。")
        if not label:
            raise ValueError("外部文本必须提供来源标签。")
        if not agent_id.strip() or agent_id.strip() == "local-dry-run":
            raise ValueError("外部写法提取必须使用真实 Agent 或已配置模型。")
        result = self.skill_runner.run(
            SkillRunRequest(
                projectRoot=root,
                skillId="writing-formula-extractor",
                variables={"sourceText": text, "sourceLabel": label},
                agentId=agent_id.strip(),
                modelProfile=model_profile,
            )
        )
        try:
            raw = json.loads(result.outputText)
        except json.JSONDecodeError as exc:
            raise ValueError("写法特征候选不是有效 JSON。") from exc
        if not isinstance(raw, list):
            raise ValueError("写法特征候选必须是 JSON 数组。")
        candidates = [WritingFormulaCandidate.model_validate(item) for item in raw]
        ids = [item.id for item in candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("写法特征候选 ID 不能重复。")
        for candidate in candidates:
            missing = [quote for quote in candidate.evidenceQuotes if quote not in text]
            if missing:
                raise ValueError(f"候选 {candidate.id} 包含不在原文中的证据引用。")
        artifact = WritingFormulaCandidateArtifact(
            runId=result.runId,
            sourceLabel=label,
            sourceHash=self._source_hash(text),
            agentId=result.agentId,
            candidates=candidates,
        )
        artifact_path = f"story/formula-candidates/{result.runId}.json"
        self.project_service.write_text(
            root,
            artifact_path,
            json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return artifact, artifact_path

    def promote_from_external_candidates(
        self,
        root: Path,
        candidate_path: str,
        selected_ids: list[str],
    ) -> WritingFormulaMemory:
        artifact = WritingFormulaCandidateArtifact.model_validate_json(
            self.project_service.read_text(root, candidate_path)
        )
        selected = set(selected_ids)
        if not selected:
            raise ValueError("至少选择一条写法特征候选。")
        available = {item.id for item in artifact.candidates}
        missing = selected - available
        if missing:
            raise ValueError("候选不存在: " + "、".join(sorted(missing)))
        memory = self.read_memory(root)
        by_id = {formula.id: formula for formula in memory.formulas}
        for candidate in artifact.candidates:
            if candidate.id not in selected:
                continue
            existing = by_id.get(candidate.id)
            if existing is None:
                by_id[candidate.id] = WritingFormula(
                    id=candidate.id,
                    title=candidate.title,
                    guidance=candidate.guidance,
                    evidenceQuotes=candidate.evidenceQuotes,
                    sourceAnalysis=candidate_path,
                    confidence=candidate.confidence,
                )
                continue
            existing.evidenceQuotes = sorted(
                set([*existing.evidenceQuotes, *candidate.evidenceQuotes])
            )
            existing.sourceAnalysis = candidate_path
            existing.confidence = max(existing.confidence, candidate.confidence)
        updated = WritingFormulaMemory(formulas=sorted(by_id.values(), key=lambda item: item.id))
        self.write_memory(root, updated)
        artifact.status = "promoted"
        self.project_service.write_text(
            root,
            candidate_path,
            json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return updated

    def _source_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
