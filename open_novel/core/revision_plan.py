from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.models import ChapterSequenceEvaluationReport
from open_novel.core.project import ProjectService


class RevisionPlanService:
    """Build actionable revision plans from sequence and chapter reports."""

    severity_rank = {"low": 0, "medium": 1, "high": 2, "blocker": 3}

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def report_path(self, start_chapter_id: str, end_chapter_id: str) -> str:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        return f"runs/revision-plan-{start}-{end}.json"

    def diagnosis_path(self, start_chapter_id: str, end_chapter_id: str) -> str:
        start = self.project_service.normalize_chapter_id(start_chapter_id)
        end = self.project_service.normalize_chapter_id(end_chapter_id)
        return f"runs/revision-diagnosis-{start}-{end}.json"

    def revision_brief_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"story/revision-briefs/{normalized}.json"

    def read_plan(self, root: Path, relative_path: str) -> dict[str, object]:
        data = json.loads(self.project_service.read_text(root, relative_path))
        if not isinstance(data, dict):
            raise ValueError(f"revision plan must be a JSON object: {relative_path}")
        return data

    def materialize_revision_briefs(
        self,
        root: Path,
        plan: dict[str, object],
        *,
        max_chapters: int = 3,
    ) -> list[dict[str, object]]:
        priority_chapters = [
            str(chapter_id)
            for chapter_id in plan.get("priorityChapters", [])
            if str(chapter_id).strip()
        ]
        chapters = plan.get("chapters", [])
        if not isinstance(chapters, list):
            chapters = []
        by_id = {
            str(chapter.get("chapterId")): chapter
            for chapter in chapters
            if isinstance(chapter, dict) and str(chapter.get("chapterId") or "").strip()
        }
        selected = priority_chapters[: max(1, max_chapters)]
        written: list[dict[str, object]] = []
        for chapter_id in selected:
            chapter = by_id.get(chapter_id, {})
            if not isinstance(chapter, dict):
                chapter = {}
            brief = {
                "schemaVersion": 1,
                "chapterId": chapter_id,
                "sourceRevisionPlan": plan.get("sourceSequenceReport", ""),
                "revisionPlanStatus": plan.get("status", ""),
                "priority": chapter.get("priority", 0),
                "draftPath": chapter.get("draftPath", f"drafts/{chapter_id}.generated.md"),
                "qualityScore": chapter.get("qualityScore", 0),
                "gateScore": chapter.get("gateScore", 0),
                "rewriteBrief": chapter.get("rewriteBrief", {}),
                "issues": chapter.get("issues", []),
            }
            output_path = self.revision_brief_path(chapter_id)
            self.project_service.write_text(
                root,
                output_path,
                json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
            )
            written.append(
                {
                    "chapterId": chapter_id,
                    "path": output_path,
                    "priority": brief["priority"],
                    "issueCount": len(brief["issues"]) if isinstance(brief["issues"], list) else 0,
                }
            )
        return written

    def build_failure_diagnosis(
        self,
        root: Path,
        plan: dict[str, object],
        *,
        source_result: dict[str, object] | None = None,
    ) -> dict[str, object]:
        start = str(plan.get("startChapterId") or "001")
        end = str(plan.get("endChapterId") or start)
        priority_chapters = [
            str(chapter_id)
            for chapter_id in plan.get("priorityChapters", [])
            if str(chapter_id).strip()
        ]
        issue_counts = self._issue_counts(plan)
        category_scores = self._diagnosis_category_scores(issue_counts, plan)
        ranked_categories = sorted(
            category_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        primary_cause = ranked_categories[0][0] if ranked_categories else "unknown"
        blockers = self._diagnosis_blockers(primary_cause, issue_counts)
        recommendations = self._diagnosis_recommendations(primary_cause, issue_counts)
        repair_packages = self._diagnosis_repair_packages(
            primary_cause,
            issue_counts,
            priority_chapters,
        )
        report = {
            "schemaVersion": 1,
            "status": "needs-human-review",
            "startChapterId": start,
            "endChapterId": end,
            "sourceRevisionPlan": self.report_path(start, end),
            "priorityChapters": priority_chapters,
            "primaryCause": primary_cause,
            "categoryScores": category_scores,
            "topIssuePatterns": [
                {"source": source, "type": issue_type, "count": count}
                for (source, issue_type), count in sorted(
                    issue_counts.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )[:8]
            ],
            "blockers": blockers,
            "recommendations": recommendations,
            "repairPackages": repair_packages,
            "sourceResult": source_result or {},
            "recommendedNextAction": self._diagnosis_next_action(primary_cause),
        }
        self.project_service.write_text(
            root,
            self.diagnosis_path(start, end),
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def build_for_sequence(
        self,
        root: Path,
        sequence: ChapterSequenceEvaluationReport,
    ) -> dict[str, object]:
        chapters: list[dict[str, object]] = []
        pattern_counts: dict[tuple[str, str], dict[str, object]] = {}
        for item in sequence.chapters:
            chapter_id = item.chapterId
            issues = self._chapter_issues(root, chapter_id)
            for issue in issues:
                key = (str(issue["source"]), str(issue["type"]))
                pattern = pattern_counts.setdefault(
                    key,
                    {
                        "source": issue["source"],
                        "type": issue["type"],
                        "count": 0,
                        "maxSeverity": issue["severity"],
                        "recommendation": self._repair_action(issue),
                    },
                )
                pattern["count"] = int(pattern["count"]) + 1
                pattern["maxSeverity"] = self._max_severity(
                    str(pattern["maxSeverity"]),
                    str(issue["severity"]),
                )
            chapters.append(
                {
                    "chapterId": chapter_id,
                    "status": item.gateStatus,
                    "priority": self._chapter_priority(item.gateStatus, item.qualityScore, issues),
                    "draftPath": f"drafts/{chapter_id}.generated.md",
                    "qualityScore": item.qualityScore,
                    "gateScore": item.gateScore,
                    "issues": issues,
                    "rewriteBrief": self._rewrite_brief(chapter_id, issues),
                }
            )

        priority_chapters = [
            str(chapter["chapterId"])
            for chapter in sorted(
                chapters,
                key=lambda chapter: (
                    -int(chapter["priority"]),
                    str(chapter["chapterId"]),
                ),
            )
            if int(chapter["priority"]) > 0
        ]
        global_patterns = sorted(
            pattern_counts.values(),
            key=lambda pattern: (
                -int(pattern["count"]),
                -self.severity_rank.get(str(pattern["maxSeverity"]), 1),
                str(pattern["type"]),
            ),
        )
        status = (
            "ready"
            if sequence.status == "pass" and not priority_chapters
            else "needs-revision"
        )
        report = {
            "schemaVersion": 1,
            "startChapterId": sequence.startChapterId,
            "endChapterId": sequence.endChapterId,
            "status": status,
            "sourceSequenceReport": (
                f"runs/sequence-evaluation-{sequence.startChapterId}-{sequence.endChapterId}.json"
            ),
            "priorityChapters": priority_chapters,
            "globalPatterns": global_patterns,
            "chapters": chapters,
            "recommendedNextAction": self._recommended_next_action(status, priority_chapters),
        }
        self.project_service.write_text(
            root,
            self.report_path(sequence.startChapterId, sequence.endChapterId),
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        return report

    def _chapter_issues(self, root: Path, chapter_id: str) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        issue_sources = [
            ("quality", f"runs/writing-quality-{chapter_id}.json"),
            ("editorial", f"runs/editorial-review-{chapter_id}.json"),
            ("gate", f"runs/chapter-gate-{chapter_id}.json"),
        ]
        for source, relative_path in issue_sources:
            data = self._read_json_if_exists(root, relative_path)
            if not isinstance(data, dict):
                continue
            raw_issues = data.get("issues")
            if not isinstance(raw_issues, list):
                continue
            for raw_issue in raw_issues:
                if not isinstance(raw_issue, dict):
                    continue
                issue = self._normalized_issue(source, raw_issue)
                issue["reportPath"] = relative_path
                issues.append(issue)
        issues.sort(
            key=lambda issue: (
                -self.severity_rank.get(str(issue["severity"]), 1),
                str(issue["source"]),
                str(issue["type"]),
            )
        )
        return issues[:12]

    def _read_json_if_exists(self, root: Path, relative_path: str) -> object | None:
        try:
            if not self.project_service.file_exists(root, relative_path):
                return None
            return json.loads(self.project_service.read_text(root, relative_path))
        except (OSError, json.JSONDecodeError):
            return None

    def _normalized_issue(self, source: str, raw_issue: dict[str, Any]) -> dict[str, object]:
        issue_type = str(raw_issue.get("type") or "unknown")
        severity = self._severity(raw_issue.get("severity"))
        suggestions = raw_issue.get("suggestions")
        if not isinstance(suggestions, list):
            suggestions = []
        evidence = raw_issue.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        issue = {
            "source": source,
            "stage": str(raw_issue.get("stage") or source),
            "type": issue_type,
            "severity": severity,
            "message": str(raw_issue.get("message") or issue_type),
            "suggestions": [str(item) for item in suggestions if str(item).strip()][:3],
            "evidence": [str(item) for item in evidence if str(item).strip()][:3],
            "repairAction": "",
        }
        issue["repairAction"] = self._repair_action(issue)
        return issue

    def _rewrite_brief(self, chapter_id: str, issues: list[dict[str, object]]) -> dict[str, object]:
        repair_actions = self._unique_strings(
            [str(issue["repairAction"]) for issue in issues if str(issue["repairAction"])]
        )
        preserve = [
            "保留已通过的 scene contract 目标、冲突、转折、结果和钩子。",
            "保留已建立的正史记忆，不用重写方式绕开连续性约束。",
        ]
        focus = repair_actions[:5] or ["当前章节评估通过，只需保持现有节奏和连续性。"]
        return {
            "focus": focus,
            "preserve": preserve,
            "repairActions": repair_actions,
            "nextCommand": (
                "rerun chapter draft and checks for "
                f"{chapter_id}, then rerun five-chapter regression"
            ),
        }

    def _repair_action(self, issue: dict[str, object]) -> str:
        issue_type = str(issue.get("type") or "")
        stage = str(issue.get("stage") or issue.get("source") or "")
        mapping = {
            "too_short": "扩写为完整场景，补足冲突推进、人物选择、结果变化和章尾余波。",
            "missing_choice": "补一个压力下的明确选择，让角色主动承担代价。",
            "weak_emotional_grounding": (
                "把情绪写进动作、停顿、对白、身体反应和选择，减少情绪标签。"
            ),
            "weak_conflict_escalation": "在中段增加阻力升级、信息差或风险扩大。",
            "weak_ending_hook": "重写章尾，留下未完成问题、新危险或下一章追读承诺。",
            "missing_cost": "让胜利、爽点或推进伴随代价、暴露、关系变化或新风险。",
            "weak_subtext": "改写关键对白，加入试探、回避、误读或话外压力。",
            "reader_promise_not_advanced": "让本章至少建立、推进或部分兑现一个读者承诺。",
            "over_exposition": "压缩设定说明，把信息转成当场冲突、判断或行动后果。",
            "emotion_told_not_felt": "删除直接说明式情绪，改用具体动作和互动让读者感到。",
            "abstract_human_core": "把外部事件绑定到角色的私人伤口、尊严、恐惧或愿望。",
            "relationship_turn_unearned": "补关系转折证据：互动、误会、保护、代价或态度变化。",
            "payoff_without_cost": "给兑现增加代价、见证者、反作用或新的承诺。",
            "dialogue_lacks_subtext": "重写对白，使其不只传递信息，还包含隐藏目的和压力。",
            "ending_lacks_aftertaste": "章尾补情绪回声，让爽感、不安或期待持续。",
            "missing_must_include": "补齐 scene contract 的 mustInclude 内容，并让它影响当前冲突。",
            "violated_must_avoid": "删除或改写违反 mustAvoid 的内容，避免提前泄露或破坏约束。",
            "focus_drift": "收束支线信息，让每个主要段落都服务本章 focus。",
            "outcome_drift": "重写结果段，确保正文实际抵达 scene contract outcome。",
            "hook_drift": "重写章尾钩子，让下一章问题清晰可追。",
            "ungrounded_logic_dependency": "补足逻辑依赖的正文证据，或先更新已确认记忆。",
        }
        if issue_type in mapping:
            return mapping[issue_type]
        if stage == "memory":
            return "先修复记忆文件或上下文包，再重跑章节检查。"
        if stage == "context":
            return "重建 context pack，确认关键正史、人物状态和写作经验被检索。"
        return "根据报告 message 和 evidence 重写对应段落，并重跑章节检查。"

    def _chapter_priority(
        self,
        gate_status: str,
        quality_score: int,
        issues: list[dict[str, object]],
    ) -> int:
        priority = max(
            (self.severity_rank.get(str(issue["severity"]), 1) * 25 for issue in issues),
            default=0,
        )
        if gate_status == "block":
            priority += 40
        elif gate_status == "warn":
            priority += 20
        if quality_score < 70:
            priority += 20
        return priority

    def _recommended_next_action(self, status: str, priority_chapters: list[str]) -> str:
        if status == "ready":
            return "ready-for-acceptance-or-model-comparison"
        if priority_chapters:
            return "revise-priority-chapters-and-rerun-five-chapter-regression"
        return "review-sequence-report-and-rerun-checks"

    def _issue_counts(self, plan: dict[str, object]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        chapters = plan.get("chapters", [])
        if not isinstance(chapters, list):
            return counts
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            issues = chapter.get("issues", [])
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                source = str(issue.get("source") or issue.get("stage") or "unknown")
                issue_type = str(issue.get("type") or "unknown")
                counts[(source, issue_type)] = counts.get((source, issue_type), 0) + 1
        return counts

    def _diagnosis_category_scores(
        self,
        issue_counts: dict[tuple[str, str], int],
        plan: dict[str, object],
    ) -> dict[str, int]:
        scores = {
            "model_output": 0,
            "style_template": 0,
            "context_memory": 0,
            "scene_contract": 0,
            "humanity_emotion": 0,
        }
        model_issues = {
            "too_short",
            "missing_dialogue",
            "missing_choice",
            "weak_conflict_escalation",
            "weak_ending_hook",
            "paragraph_too_long",
        }
        style_issues = {
            "over_exposition",
            "reader_focus_diffuse",
            "description_outweighs_drama",
        }
        memory_issues = {
            "ungrounded_logic_dependency",
            "timeline_order_conflict",
            "character_state_contradiction",
            "relationship_state_contradiction",
        }
        contract_issues = {
            "missing_must_include",
            "violated_must_avoid",
            "focus_drift",
            "outcome_drift",
            "hook_drift",
            "reader_promise_drift",
            "reader_promise_not_advanced",
        }
        emotion_issues = {
            "weak_emotional_grounding",
            "weak_subtext",
            "weak_aftertaste",
            "emotion_told_not_felt",
            "emotion_lacks_specificity",
            "abstract_human_core",
            "motivation_not_personal",
            "relationship_turn_unearned",
            "dialogue_lacks_subtext",
            "ending_lacks_aftertaste",
        }
        for (_source, issue_type), count in issue_counts.items():
            if issue_type in model_issues:
                scores["model_output"] += count
            if issue_type in style_issues:
                scores["style_template"] += count
            if issue_type in memory_issues:
                scores["context_memory"] += count
            if issue_type in contract_issues:
                scores["scene_contract"] += count
            if issue_type in emotion_issues:
                scores["humanity_emotion"] += count
        if len(plan.get("priorityChapters", [])) >= 3:
            scores["model_output"] += 2
        return {key: value for key, value in scores.items() if value > 0}

    def _diagnosis_blockers(
        self,
        primary_cause: str,
        issue_counts: dict[tuple[str, str], int],
    ) -> list[str]:
        blockers = {
            "model_output": [
                "模型连续多轮没有稳定执行 revision brief。",
                "草稿仍存在篇幅、选择、冲突升级或章尾钩子等基础生成问题。",
            ],
            "style_template": [
                "当前平台/题材模板对节奏、描写密度或爽点兑现约束不够具体。",
                "需要先调整 story/style-profile.json，再继续批量重写。",
            ],
            "context_memory": [
                "上下文或记忆无法支撑合同依赖，重写会持续绕不开同一连续性问题。",
                "需要先修复 memory 或重建 context pack。",
            ],
            "scene_contract": [
                "章节合同本身可能目标过散、mustAvoid/mustInclude 冲突或承诺不可兑现。",
                "需要先改 scene contract，再重写正文。",
            ],
            "humanity_emotion": [
                "多轮仍未把情绪、人味、潜台词和关系转折落到动作与选择。",
                "需要提高 revision brief 中的人物私因、代价和互动证据约束。",
            ],
            "unknown": ["需要人工查看 revision plan 和章节报告后再决定下一步。"],
        }
        result = blockers.get(primary_cause, blockers["unknown"]).copy()
        for (_source, issue_type), count in sorted(issue_counts.items()):
            if count >= 2:
                result.append(f"重复问题：{issue_type} 出现 {count} 次。")
        return result[:8]

    def _diagnosis_recommendations(
        self,
        primary_cause: str,
        issue_counts: dict[tuple[str, str], int],
    ) -> list[str]:
        recommendations = {
            "model_output": [
                "切换或重新训练写作模型，再跑五章回归。",
                "降低一次重写章节数，只重写最高优先级章节并观察是否改善。",
            ],
            "style_template": [
                "更新 story/style-profile.json，补充题材节奏、禁忌、爽点/情绪兑现规则。",
                "用五章样本评估候选模板后再晋升为内置 active profile。",
            ],
            "context_memory": [
                "先运行 memory validation/repair，确认事实、人物状态、伏笔和时间线可用。",
                "重建相关章节 context pack，检查关键来源是否被纳入。",
            ],
            "scene_contract": [
                "打开 Chapter Cockpit 修改 focus、outcome、hook、mustInclude/mustAvoid。",
                "把过多承诺拆到后续章节，降低单章合同负载。",
            ],
            "humanity_emotion": [
                "补充角色 internalNeed、woundOrFear、stakes、cost、subtext、aftertaste。",
                "在 revision brief 中要求对白、停顿、身体反应、选择代价和关系余波。",
            ],
            "unknown": ["人工检查报告 evidence，再决定是改合同、改模板、修记忆还是换模型。"],
        }
        result = recommendations.get(primary_cause, recommendations["unknown"]).copy()
        issue_types = {issue_type for (_source, issue_type) in issue_counts}
        if "too_short" in issue_types:
            result.append("把 chapterWordTarget 或模型输出长度要求调高后再试。")
        if "violated_must_avoid" in issue_types:
            result.append("把 mustAvoid 移到 revision brief 的硬性禁止项。")
        return result[:8]

    def _diagnosis_repair_packages(
        self,
        primary_cause: str,
        issue_counts: dict[tuple[str, str], int],
        priority_chapters: list[str],
    ) -> list[dict[str, object]]:
        packages: list[dict[str, object]] = []
        chapter_arg = ",".join(priority_chapters[:3]) or "priority chapters"
        first_priority_chapter = priority_chapters[0] if priority_chapters else ""

        def route(
            route: str,
            label: str,
            *,
            file: str = "",
        ) -> dict[str, object]:
            data: dict[str, object] = {"uiRoute": route, "uiLabel": label}
            if first_priority_chapter and route in {"chapter", "memory"}:
                data["uiParams"] = {"chapterId": first_priority_chapter}
            if route == "studio" and file:
                data["uiParams"] = {"file": file}
            return data

        base_by_cause: dict[str, list[dict[str, object]]] = {
            "model_output": [
                {
                    "id": "model-output-switch-or-tune",
                    "target": "models/writing-models.json",
                    "action": "register-or-select-better-writing-model",
                    "reason": "多轮重写仍无法执行 revision brief，优先排查模型能力或推理模板。",
                    "command": "open-novel train local-plan --project <project>",
                    **route("models", "Open Model Cockpit"),
                },
                {
                    "id": "model-output-narrow-rerun",
                    "target": "runs/revision-plan-*.json",
                    "action": "rerun-fewer-priority-chapters",
                    "reason": "降低一次重写负载，观察模型是否能先修好最高优先级章节。",
                    "api": "POST /projects/revision/rerun maxChapters=1 maxRounds=1",
                    **route("operations", "Open Operations"),
                },
            ],
            "style_template": [
                {
                    "id": "style-template-tighten",
                    "target": "story/style-profile.json",
                    "action": "revise-platform-genre-template",
                    "reason": "节奏、描写密度、爽点或题材禁忌需要写入可编辑风格模板。",
                    "command": "open-novel style apply <profile-id> --project <project>",
                    **route("models", "Open Style Profiles"),
                }
            ],
            "context_memory": [
                {
                    "id": "context-memory-repair",
                    "target": "memory/*.json",
                    "action": "validate-and-repair-memory",
                    "reason": "连续性依赖无法被上下文支持，重写前应先修记忆。",
                    "command": "open-novel project validate-memory --project <project>",
                    **route("memory", "Open Memory Cockpit"),
                },
                {
                    "id": "context-pack-rebuild",
                    "target": f"story/context-packs/{chapter_arg}.json",
                    "action": "rebuild-context-pack",
                    "reason": "确认关键正史、人物状态、伏笔和写作经验进入上下文。",
                    "api": "POST /projects/context-pack",
                    **route("memory", "Open Context Memory"),
                },
            ],
            "scene_contract": [
                {
                    "id": "scene-contract-revise",
                    "target": f"story/chapter-briefs/{chapter_arg}.json",
                    "action": "revise-scene-contract",
                    "reason": "合同可能过载、互相冲突或无法在单章兑现。",
                    "ui": "Chapter Cockpit",
                    **route("chapter", "Open Chapter Cockpit"),
                }
            ],
            "humanity_emotion": [
                {
                    "id": "humanity-fields-strengthen",
                    "target": f"story/chapter-briefs/{chapter_arg}.json",
                    "action": "strengthen-human-core-fields",
                    "reason": "补 internalNeed、woundOrFear、stakes、cost、subtext、aftertaste。",
                    "ui": "Chapter Cockpit",
                    **route("chapter", "Open Humanity Fields"),
                },
                {
                    "id": "humanity-editor-review",
                    "target": "runs/editorial-review-*.json",
                    "action": "review-humanity-editor-findings",
                    "reason": "先修复情绪、人味、关系转折和潜台词，再继续自动重写。",
                    "api": "POST /projects/editorial-review/check",
                    **route("chapter", "Open Editorial Findings"),
                },
            ],
        }
        packages.extend(base_by_cause.get(primary_cause, []))
        issue_types = {issue_type for (_source, issue_type) in issue_counts}
        if "too_short" in issue_types:
            packages.append(
                {
                    "id": "length-target-increase",
                    "target": "novel.json",
                    "action": "increase-chapter-word-target-or-output-budget",
                    "reason": "反复 too_short 表示模型输出长度或章节目标字数约束不足。",
                    "field": "chapterWordTarget",
                    **route("studio", "Open Studio", file="novel.json"),
                }
            )
        if "violated_must_avoid" in issue_types:
            packages.append(
                {
                    "id": "must-avoid-hard-ban",
                    "target": f"story/revision-briefs/{chapter_arg}.json",
                    "action": "promote-must-avoid-to-hard-ban",
                    "reason": "重写仍违反 mustAvoid，需要在 revision brief 中硬性禁止。",
                    **route("chapter", "Open Revision Brief"),
                }
            )
        if not packages:
            packages.append(
                {
                    "id": "manual-diagnosis",
                    "target": "runs/revision-diagnosis-*.json",
                    "action": "manual-review",
                    "reason": "自动归因不足，需要人工查看 evidence 和章节草稿。",
                    **route("operations", "Open Operations"),
                }
            )
        return packages[:8]

    def _diagnosis_next_action(self, primary_cause: str) -> str:
        actions = {
            "model_output": "change-or-tune-writing-model-then-rerun-regression",
            "style_template": "revise-style-profile-then-rerun-regression",
            "context_memory": "repair-memory-and-rebuild-context-pack",
            "scene_contract": "revise-scene-contract-before-rerun",
            "humanity_emotion": "strengthen-humanity-fields-and-revision-brief",
        }
        return actions.get(primary_cause, "manual-diagnosis-required")

    def _max_severity(self, current: str, incoming: str) -> str:
        return (
            incoming
            if self.severity_rank.get(incoming, 1) > self.severity_rank.get(current, 1)
            else current
        )

    def _severity(self, value: object) -> str:
        severity = str(value or "medium")
        return severity if severity in self.severity_rank else "medium"

    def _unique_strings(self, values: list[str]) -> list[str]:
        unique: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if item and item not in unique:
                unique.append(item)
        return unique
