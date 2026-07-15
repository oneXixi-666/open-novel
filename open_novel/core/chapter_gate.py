from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_novel.core.book_assets import BookAssetService
from open_novel.core.chapter_pipeline import ChapterPipelineService
from open_novel.core.character_asset import CharacterAssetService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.continuity import ContinuityService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.models import ChapterGateIssue, ChapterGateReport
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.quality_calibration import QualityThresholdConfig
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.text_support import important_terms
from open_novel.core.writing_quality import WritingQualityService


class ChapterGateService:
    guidance_only_readiness_fields = {
        "internalNeed",
        "woundOrFear",
        "stakes",
        "cost",
        "subtext",
        "aftertaste",
    }

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        context_pack_service: ContextPackService | None = None,
        continuity_service: ContinuityService | None = None,
        post_chapter_service: PostChapterService | None = None,
        memory_validation_service: MemoryValidationService | None = None,
        writing_quality_service: WritingQualityService | None = None,
        editorial_review_service: EditorialReviewService | None = None,
        character_asset_service: CharacterAssetService | None = None,
        book_asset_service: BookAssetService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.context_pack_service = context_pack_service or ContextPackService(
            self.project_service,
            self.story_guidance,
        )
        self.continuity_service = continuity_service or ContinuityService(
            self.project_service,
            self.story_guidance,
        )
        self.post_chapter_service = post_chapter_service or PostChapterService(
            self.project_service,
            self.story_guidance,
            self.context_pack_service,
        )
        self.memory_validation_service = memory_validation_service or MemoryValidationService(
            self.project_service
        )
        self.writing_quality_service = writing_quality_service or WritingQualityService(
            self.project_service,
            self.story_guidance,
        )
        self.editorial_review_service = editorial_review_service or EditorialReviewService(
            self.project_service,
            self.story_guidance,
        )
        self.character_asset_service = character_asset_service or CharacterAssetService(
            self.project_service
        )
        self.book_asset_service = book_asset_service or BookAssetService()

    def report_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"runs/chapter-gate-{normalized}.json"

    def check_chapter(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None = None,
        include_review: bool = True,
        include_draft: bool = True,
        editorial_profile_id: str = "",
        threshold_config: QualityThresholdConfig | None = None,
    ) -> ChapterGateReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        issues: list[ChapterGateIssue] = []
        artifacts: list[str] = []

        issues.extend(self._readiness_issues(root, normalized))
        issues.extend(self._memory_issues(root, artifacts))
        issues.extend(self._context_issues(root, normalized, artifacts))
        issues.extend(self._character_asset_issues(root, normalized, artifacts))
        if include_draft:
            issues.extend(self._world_rule_issues(root, normalized, draft_path, artifacts))
            issues.extend(self._memory_conflict_issues(root, normalized, draft_path, artifacts))
            issues.extend(self._continuity_issues(root, normalized, draft_path, artifacts))
            issues.extend(
                self._quality_issues(
                    root,
                    normalized,
                    draft_path,
                    artifacts,
                    threshold_config,
                )
            )
            issues.extend(
                self._editorial_issues(
                    root,
                    normalized,
                    draft_path,
                    artifacts,
                    editorial_profile_id=editorial_profile_id,
                )
            )
        if include_review:
            issues.extend(self._review_risk_issues(root, normalized))

        report = ChapterGateReport(
            chapterId=normalized,
            status=self._status(issues),
            score=self._score(issues),
            issues=issues,
            generatedArtifacts=artifacts,
            recommendedNextAction=self._recommended_next_action(issues),
        )
        self.project_service.write_text(
            root,
            self.report_path(normalized),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        ChapterPipelineService(self.project_service).update_step(
            root,
            normalized,
            "gate",
            status="blocked" if report.status == "block" else "ready",
            artifact=self.report_path(normalized),
            message=f"chapter gate {report.status}",
        )
        return report

    def _readiness_issues(self, root: Path, chapter_id: str) -> list[ChapterGateIssue]:
        report = self.story_guidance.check_readiness(root, chapter_id)
        return [
            ChapterGateIssue(
                severity=issue.severity,
                stage="readiness",
                type=issue.field,
                message=issue.message,
                evidence=[f"story/chapter-briefs/{chapter_id}.json#{issue.field}"],
            )
            for issue in report.issues
            if issue.field not in self.guidance_only_readiness_fields
        ]

    def _memory_issues(self, root: Path, artifacts: list[str]) -> list[ChapterGateIssue]:
        report = self.memory_validation_service.validate_project(root)
        artifacts.append(self.memory_validation_service.report_path)
        return [
            ChapterGateIssue(
                severity=issue.severity,
                stage="memory",
                type=issue.type,
                message=issue.message,
                evidence=issue.evidence,
            )
            for issue in report.issues
        ]

    def _context_issues(
        self,
        root: Path,
        chapter_id: str,
        artifacts: list[str],
    ) -> list[ChapterGateIssue]:
        path = self.context_pack_service.context_pack_path(chapter_id)
        try:
            contract = self.story_guidance.read_scene_contract(root, chapter_id)
        except FileNotFoundError:
            contract = None
        if contract is not None and not self._context_pack_fresh_enough(
            root,
            chapter_id,
            contract.model_dump(mode="json"),
        ):
            return [
                ChapterGateIssue(
                    severity="blocker",
                    stage="context",
                    type="stale_context_pack",
                    message="上下文包不是基于当前章节合同生成的，请重新构建。",
                    evidence=[path, f"story/chapter-briefs/{chapter_id}.json"],
                )
            ]
        try:
            context_pack = self.context_pack_service.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return [
                ChapterGateIssue(
                    severity="medium",
                    stage="context",
                    type="missing_context_pack",
                    message="缺少本章上下文包，写作前无法确认记忆选择是否完整。",
                    evidence=[path],
                )
            ]
        artifacts.append(context_pack.path)
        memory_sources = [
            item.source for item in context_pack.included if item.source.startswith("memory/")
        ]
        if memory_sources:
            return []
        return [
            ChapterGateIssue(
                severity="low",
                stage="context",
                type="no_memory_context",
                message="上下文包没有包含任何结构化记忆，需确认本章是否真的不依赖前文。",
                evidence=[path],
            )
        ]

    def _character_asset_issues(
        self,
        root: Path,
        chapter_id: str,
        artifacts: list[str],
    ) -> list[ChapterGateIssue]:
        asset_path = CharacterAssetService.memory_path
        if not self.project_service.file_exists(root, asset_path):
            return []
        if asset_path not in artifacts:
            artifacts.append(asset_path)
        try:
            contract = self.story_guidance.read_scene_contract(root, chapter_id)
            context_pack = self.context_pack_service.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return []

        contract_data = contract.model_dump(mode="json")
        keywords = self.context_pack_service._keywords_from_contract(contract_data)
        selected_data = self.character_asset_service.select_for_context(
            root,
            chapter_id,
            contract_data,
            keywords,
        )
        selected_assets = selected_data.get("assets", []) if isinstance(selected_data, dict) else []
        if not isinstance(selected_assets, list) or not selected_assets:
            return []

        included_item = next(
            (
                item
                for item in context_pack.included
                if item.source == CharacterAssetService.memory_path
            ),
            None,
        )
        included_assets = []
        if included_item is not None and isinstance(included_item.data, dict):
            raw_assets = included_item.data.get("assets", [])
            if isinstance(raw_assets, list):
                included_assets = raw_assets
        included_ids = {
            str(asset.get("id"))
            for asset in included_assets
            if isinstance(asset, dict) and asset.get("id")
        }

        issues: list[ChapterGateIssue] = []
        for asset in selected_assets:
            if not isinstance(asset, dict):
                continue
            asset_id = str(asset.get("id") or "")
            if not asset_id:
                continue
            importance = str(asset.get("importance") or "")
            is_important = importance in {"high", "critical"}
            if is_important and asset_id not in included_ids:
                issues.append(
                    ChapterGateIssue(
                        severity="medium",
                        stage="context",
                        type="missing_character_asset_context",
                        message=f"关键角色资源未进入上下文包：{asset_id}。",
                        evidence=[asset_path, context_pack.path],
                    )
                )
            cooldown = self._safe_int(asset.get("cooldown"))
            last_used = str(asset.get("lastUsedChapter") or "")
            if asset_id in included_ids and cooldown > 0 and is_important:
                issues.append(
                    ChapterGateIssue(
                        severity="low",
                        stage="context",
                        type="character_asset_reuse_risk",
                        message=f"高重要度角色资源仍处于冷却期，需确认本章重复调度是否必要：{asset_id}。",
                        evidence=[asset_path, context_pack.path],
                    )
                )
            elif asset_id in included_ids and last_used == chapter_id and is_important:
                issues.append(
                    ChapterGateIssue(
                        severity="low",
                        stage="context",
                        type="character_asset_reuse_risk",
                        message=f"高重要度角色资源已标记为本章使用，需确认上下文包不是重复旧状态：{asset_id}。",
                        evidence=[asset_path, context_pack.path],
                    )
                )
        return issues

    def _world_rule_issues(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None,
        artifacts: list[str],
    ) -> list[ChapterGateIssue]:
        source = draft_path or f"drafts/{chapter_id}.generated.md"
        if not self.project_service.file_exists(root, source):
            return []
        try:
            context_pack = self.context_pack_service.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return []
        asset_item = next(
            (
                item
                for item in context_pack.included
                if item.source == BookAssetService.context_source
            ),
            None,
        )
        if asset_item is None:
            return []
        violations = self.book_asset_service.hard_rule_violations(
            asset_item.data,
            self._draft_body(root, source),
        )
        if not violations:
            return []
        if BookAssetService.context_source not in artifacts:
            artifacts.append(BookAssetService.context_source)
        return [
            ChapterGateIssue(
                severity="blocker",
                stage="continuity",
                type="world_rule_conflict",
                message=(f"草稿违反已确认世界规则「{item['title']}」：{item['rule']}"),
                evidence=[source, context_pack.path, BookAssetService.context_source],
            )
            for item in violations[:3]
        ]

    def _context_pack_fresh_enough(
        self,
        root: Path,
        chapter_id: str,
        contract_data: dict[str, Any],
    ) -> bool:
        try:
            context_pack = self.context_pack_service.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return False
        contract_item = next(
            (
                item
                for item in context_pack.included
                if item.source == self.story_guidance.contract_path(chapter_id)
            ),
            None,
        )
        if contract_item is None:
            return False
        included_contract = contract_item.data
        if not isinstance(included_contract, dict):
            return False
        return (
            included_contract.get("title") == contract_data.get("title")
            and included_contract.get("focus") == contract_data.get("focus")
            and included_contract.get("goal") == contract_data.get("goal")
            and included_contract.get("conflict") == contract_data.get("conflict")
            and included_contract.get("turn") == contract_data.get("turn")
            and included_contract.get("outcome") == contract_data.get("outcome")
            and included_contract.get("hook") == contract_data.get("hook")
            and included_contract.get("emotionalBeat") == contract_data.get("emotionalBeat")
            and included_contract.get("relationshipBeat") == contract_data.get("relationshipBeat")
            and included_contract.get("internalNeed") == contract_data.get("internalNeed")
            and included_contract.get("woundOrFear") == contract_data.get("woundOrFear")
            and included_contract.get("stakes") == contract_data.get("stakes")
            and included_contract.get("cost") == contract_data.get("cost")
            and included_contract.get("subtext") == contract_data.get("subtext")
            and included_contract.get("aftertaste") == contract_data.get("aftertaste")
            and included_contract.get("logicDependencies") == contract_data.get("logicDependencies")
            and included_contract.get("mustInclude") == contract_data.get("mustInclude")
            and included_contract.get("mustAvoid") == contract_data.get("mustAvoid")
            and included_contract.get("readerPromises") == contract_data.get("readerPromises")
        )

    def _continuity_issues(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None,
        artifacts: list[str],
        threshold_config: QualityThresholdConfig | None = None,
    ) -> list[ChapterGateIssue]:
        source = draft_path or f"drafts/{chapter_id}.generated.md"
        if not self.project_service.file_exists(root, source):
            return []
        try:
            report = self.continuity_service.check_draft(root, chapter_id, draft_path=draft_path)
        except FileNotFoundError:
            return []
        artifacts.append(self.continuity_service.report_path(chapter_id))
        return [
            ChapterGateIssue(
                severity=issue.severity,
                stage="continuity",
                type=issue.type,
                message=issue.message,
                evidence=issue.evidence,
            )
            for issue in report.issues
        ]

    def _memory_conflict_issues(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None,
        artifacts: list[str],
    ) -> list[ChapterGateIssue]:
        source = draft_path or f"drafts/{chapter_id}.generated.md"
        if not self.project_service.file_exists(root, source):
            return []
        body = self._draft_body(root, source)
        facts = self._memory_claim_texts(
            root,
            "memory/facts.json",
            "facts",
            current_chapter_id=chapter_id,
        )
        events = self._memory_claim_texts(
            root,
            "memory/timeline-events.json",
            "events",
            current_chapter_id=chapter_id,
        )
        claims = [*facts, *events]
        if not claims:
            return []
        artifacts.extend(
            path
            for path in ["memory/facts.json", "memory/timeline-events.json"]
            if path not in artifacts
        )
        issues: list[ChapterGateIssue] = []
        for claim in claims:
            terms = [term for term in self._claim_terms(claim) if len(term) >= 2]
            if not terms:
                continue
            if any(self._draft_denies_claim_term(body, term) for term in terms):
                issues.append(
                    ChapterGateIssue(
                        severity="blocker",
                        stage="memory",
                        type="memory_conflict",
                        message=f"草稿疑似否定已确认记忆：{claim[:40]}",
                        evidence=[source, "memory/facts.json", "memory/timeline-events.json"],
                    )
                )
                break
        return issues

    def _draft_denies_claim_term(self, body: str, term: str) -> bool:
        negative_markers = ("从未", "没有", "没见过", "未曾", "不存在", "不曾")
        sentences = [item for item in re.split(r"[。！？!?；;\n]+", body) if item.strip()]
        for sentence in sentences:
            if term not in sentence:
                continue
            for marker in negative_markers:
                marker_index = sentence.find(marker)
                term_index = sentence.find(term)
                if marker_index >= 0 and term_index >= 0 and abs(marker_index - term_index) <= 12:
                    return True
        return False

    def _memory_claim_texts(
        self,
        root: Path,
        relative_path: str,
        list_key: str,
        *,
        current_chapter_id: str,
    ) -> list[str]:
        if not self.project_service.file_exists(root, relative_path):
            return []
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return []
        values = data.get(list_key) if isinstance(data, dict) else None
        if not isinstance(values, list):
            return []
        texts: list[str] = []
        current_order = self._chapter_order(current_chapter_id)
        for value in values:
            if not isinstance(value, dict):
                continue
            source_chapter = str(value.get("chapterId") or value.get("validFrom") or "")
            source_chapter = source_chapter.removeprefix("chapter:")
            source_order = self._chapter_order(source_chapter)
            if (
                value.get("_operationId")
                and current_order is not None
                and source_order is not None
                and source_order >= current_order
            ):
                continue
            text = str(value.get("text") or value.get("summary") or value.get("label") or "")
            if text:
                texts.append(text)
        return texts

    def _claim_terms(self, claim: str) -> list[str]:
        terms = [
            *important_terms(claim),
            *re.findall(r"[\u4e00-\u9fa5]{2,8}[A-Za-z0-9]{1,4}", claim),
            *re.findall(
                r"(?:获得|得到|拿到|取得|见过)([\u4e00-\u9fa5]{1,6}[A-Za-z0-9]{1,4})", claim
            ),
        ]
        subject_match = re.match(
            r"^([一-龥]{2,4})(?:、|与|和|获得|得到|拿到|取得|见过|拥有)",
            claim,
        )
        subjects = {subject_match.group(1)} if subject_match else set()
        for term in list(terms):
            entity_match = re.search(r"([\u4e00-\u9fa5]{2,4}[A-Za-z0-9]{1,4})$", term)
            if entity_match:
                terms.append(entity_match.group(1))
        stop = {"主角", "获得", "得到", "从未", "没有", "已经", "曾经"}
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            if term in stop or term in subjects or term in seen:
                continue
            seen.add(term)
            result.append(term)
        return result

    def _chapter_order(self, chapter_id: str) -> int | None:
        match = re.search(r"(\d+)", chapter_id)
        return int(match.group(1)) if match else None

    def _quality_issues(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None,
        artifacts: list[str],
        threshold_config: QualityThresholdConfig | None = None,
    ) -> list[ChapterGateIssue]:
        source = draft_path or f"drafts/{chapter_id}.generated.md"
        if not self.project_service.file_exists(root, source):
            return []
        try:
            report = self.writing_quality_service.evaluate_chapter(
                root,
                chapter_id,
                draft_path=draft_path,
                threshold_config=threshold_config,
            )
        except FileNotFoundError:
            return []
        body = self._draft_body(root, source)
        artifacts.append(self.writing_quality_service.report_path(chapter_id))
        return [
            ChapterGateIssue(
                severity=issue.severity,
                stage="quality",
                type=issue.type,
                message=issue.message,
                evidence=issue.evidence,
                textSnippet=self._quality_text_snippet(body, issue.type),
                suggestionHint=issue.suggestions[0] if issue.suggestions else "",
            )
            for issue in report.issues
        ]

    def _editorial_issues(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None,
        artifacts: list[str],
        editorial_profile_id: str = "",
    ) -> list[ChapterGateIssue]:
        source = draft_path or f"drafts/{chapter_id}.generated.md"
        if not self.project_service.file_exists(root, source):
            return []
        expected_profile_id = (
            self.project_service._normalize_slug(editorial_profile_id, "editorial profile id")
            if editorial_profile_id.strip()
            else ""
        )
        try:
            report = self.editorial_review_service.read_report(root, chapter_id)
            current_profile_id = str(report.metrics.get("profileId") or "")
            if report.source != source or (
                expected_profile_id and current_profile_id != expected_profile_id
            ):
                report = self.editorial_review_service.review_chapter(
                    root,
                    chapter_id,
                    draft_path=draft_path,
                    profile_id=editorial_profile_id,
                )
        except FileNotFoundError:
            try:
                report = self.editorial_review_service.review_chapter(
                    root,
                    chapter_id,
                    draft_path=draft_path,
                    profile_id=editorial_profile_id,
                )
            except FileNotFoundError:
                return []
        artifacts.append(self.editorial_review_service.report_path(chapter_id))
        return [
            ChapterGateIssue(
                severity=issue.severity,
                stage="editorial",
                type=issue.type,
                message=issue.message,
                evidence=issue.evidence,
            )
            for issue in report.issues
        ]

    def _review_risk_issues(self, root: Path, chapter_id: str) -> list[ChapterGateIssue]:
        try:
            review = self.post_chapter_service.read_review(root, chapter_id)
        except FileNotFoundError:
            return []
        issues: list[ChapterGateIssue] = []
        for item in review.items:
            if item.kind != "continuity_risk":
                continue
            severity = self._payload_severity(item.payload)
            issues.append(
                ChapterGateIssue(
                    severity=severity,
                    stage="review",
                    type=str(item.payload.get("field") or item.id),
                    message=item.text,
                    evidence=item.evidence,
                )
            )
        return issues

    def _payload_severity(self, payload: dict[str, Any]) -> str:
        severity = str(payload.get("severity") or "medium")
        if severity in {"low", "medium", "high", "blocker"}:
            return severity
        return "medium"

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _status(self, issues: list[ChapterGateIssue]) -> str:
        if any(issue.severity == "blocker" for issue in issues):
            return "block"
        if issues:
            return "warn"
        return "pass"

    def _score(self, issues: list[ChapterGateIssue]) -> int:
        penalty = {
            "blocker": 35,
            "high": 18,
            "medium": 9,
            "low": 3,
        }
        return max(0, 100 - sum(penalty[issue.severity] for issue in issues))

    def _draft_body(self, root: Path, source: str) -> str:
        try:
            text = self.project_service.read_text(root, source)
        except FileNotFoundError:
            return ""
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _quality_text_snippet(self, body: str, issue_type: str) -> str:
        paragraphs = [paragraph.strip() for paragraph in body.splitlines() if paragraph.strip()]
        if not paragraphs:
            return ""
        if issue_type in {"weak_ending_hook", "weak_aftertaste"}:
            return self._short_snippet(paragraphs[-1])
        if issue_type in {"paragraph_too_long", "over_exposition"}:
            target = max(paragraphs, key=len)
            return self._short_snippet(target)
        if issue_type == "too_short":
            return self._short_snippet(body)
        return self._short_snippet(paragraphs[0])

    def _short_snippet(self, text: str) -> str:
        return text.strip()[:50]

    def _recommended_next_action(self, issues: list[ChapterGateIssue]) -> str:
        if any(issue.severity == "blocker" for issue in issues):
            return "fix-blocking-chapter-issues"
        if any(issue.stage == "memory" for issue in issues):
            return "fix-memory-schema-before-drafting"
        if any(issue.stage == "readiness" for issue in issues):
            return "complete-scene-contract-before-drafting"
        if any(issue.stage == "context" for issue in issues):
            return "build-or-review-context-pack"
        if any(issue.stage == "continuity" for issue in issues):
            return "revise-draft-and-rerun-continuity"
        if any(issue.stage == "review" for issue in issues):
            return "revise-accepted-chapter-or-adjust-canon-patch"
        return "ready"
