from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from open_novel.core.models import (
    ChapterReviewItem,
    EditorialReviewIssue,
    EditorialReviewReport,
    WritingLesson,
    WritingLessonsMemory,
    WritingQualityIssue,
    WritingQualityReport,
)
from open_novel.core.project import ProjectService


class WritingLearningService:
    memory_path = "memory/writing-lessons.json"
    max_active_lessons = 24
    severity_order = {"low": 0, "medium": 1, "high": 2, "blocker": 3}

    category_by_field = {
        "focus": "focus",
        "emotionalBeat": "emotion",
        "relationshipBeat": "relationship",
        "internalNeed": "emotion",
        "woundOrFear": "emotion",
        "stakes": "emotion",
        "cost": "continuity",
        "subtext": "relationship",
        "aftertaste": "hook",
        "hook": "hook",
        "outcome": "continuity",
    }
    category_by_editorial_dimension = {
        "emotion": "emotion",
        "character": "emotion",
        "conflict": "focus",
        "payoff": "reader_promise",
        "subtext": "relationship",
        "aftertaste": "hook",
        "pacing": "style",
    }
    lesson_by_editorial_type = {
        "emotion_told_not_felt": (
            "情绪不能只靠说明，要用动作、停顿、对白、身体反应和选择让读者感到。"
        ),
        "emotion_lacks_specificity": "情绪要有具体对象、诱因和反应，避免泛泛写难过、愤怒或害怕。",
        "abstract_human_core": "章节必须把外部事件绑定到人物的私人伤口、尊严、恐惧或愿望。",
        "motivation_not_personal": "主角动机要有私人理由，不能只服务剧情流程。",
        "relationship_turn_unearned": "关系转折必须通过互动、误解、保护、代价或态度变化来挣得。",
        "scene_lacks_pressure": "场景要有即时压力、阻碍和失败代价，避免平铺推进。",
        "payoff_without_cost": "爽点、反转或兑现必须伴随代价、暴露风险或新的承诺。",
        "dialogue_lacks_subtext": "对白要保留潜台词、试探、回避或误读，不能只传递信息。",
        "ending_lacks_aftertaste": "章尾要留下情绪余味、未完成问题或下一章追读钩子。",
        "description_outweighs_drama": "描写必须服务冲突、人物判断或选择限制，不能压过戏剧推进。",
        "reader_focus_diffuse": "每章要守住一个核心读者承诺，避免多线信息稀释重点。",
    }
    category_by_quality_type = {
        "too_short": "style",
        "paragraph_too_long": "style",
        "missing_dialogue": "style",
        "missing_choice": "emotion",
        "weak_emotional_grounding": "emotion",
        "weak_conflict_escalation": "focus",
        "weak_ending_hook": "hook",
        "focus_not_supported": "focus",
        "missing_stakes": "emotion",
        "missing_cost": "continuity",
        "weak_subtext": "relationship",
        "weak_aftertaste": "hook",
        "reader_promise_not_advanced": "reader_promise",
        "over_exposition": "style",
    }
    lesson_by_quality_type = {
        "too_short": "章节草稿要给足冲突推进、情绪承载和结果变化，不能只写梗概。",
        "paragraph_too_long": "段落要服务连载阅读节奏，长段信息应拆成动作、对白和反应。",
        "missing_dialogue": "关键冲突要有对白压力、试探或误解，不能全靠旁白推进。",
        "missing_choice": "人物必须在压力下做选择，让读者看到主动性和代价。",
        "weak_emotional_grounding": "情绪要落到动作、身体反应、停顿、对白和选择，避免只给标签。",
        "weak_conflict_escalation": "章节中段必须升级阻力、信息差或风险，避免平铺直叙。",
        "weak_ending_hook": "章尾必须留下新的危险、问题、承诺或未完成动作。",
        "focus_not_supported": "正文要持续兑现章节 focus，重要场景不能偏离本章读者收获。",
        "missing_stakes": "失败代价要在正文里可见，让选择有重量。",
        "missing_cost": "爽点和推进必须伴随代价、暴露、关系变化或新危险。",
        "weak_subtext": "互动要有潜台词、回避、误读或话外压力，不能只直说信息。",
        "weak_aftertaste": "结尾要留下情绪回声，让爽感、不安或期待持续到下一章。",
        "reader_promise_not_advanced": "读者承诺要在本章建立、推进或部分兑现，不能悬空。",
        "over_exposition": "设定、背景和机制说明要压缩，并转化为当场冲突或人物判断。",
    }

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_lessons(self, root: Path) -> WritingLessonsMemory:
        if not self.project_service.file_exists(root, self.memory_path):
            return WritingLessonsMemory()
        return WritingLessonsMemory.model_validate_json(
            self.project_service.read_text(root, self.memory_path)
        )

    def write_lessons(self, root: Path, memory: WritingLessonsMemory) -> None:
        self.project_service.write_text(
            root,
            self.memory_path,
            json.dumps(memory.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def set_lesson_status(
        self,
        root: Path,
        lesson_id: str,
        status: str,
    ) -> WritingLesson:
        lesson_id = (lesson_id or "").strip()
        status = (status or "").strip()
        if status not in {"active", "retired"}:
            raise ValueError("lesson status must be active or retired")
        memory = self.read_lessons(root)
        for lesson in memory.lessons:
            if lesson.id != lesson_id:
                continue
            lesson.status = status
            self.write_lessons(root, memory)
            return lesson
        raise FileNotFoundError(f"missing writing lesson: {lesson_id}")

    def update_lesson(
        self,
        root: Path,
        lesson_id: str,
        *,
        lesson_text: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        applies_to: list[str] | None = None,
    ) -> WritingLesson:
        lesson_id = (lesson_id or "").strip()
        memory = self.read_lessons(root)
        for lesson in memory.lessons:
            if lesson.id != lesson_id:
                continue
            if lesson_text is not None:
                text = lesson_text.strip()
                if not text:
                    raise ValueError("lesson text is required")
                lesson.lesson = text
            if category is not None:
                lesson.category = self._category(category)
            if severity is not None:
                lesson.severity = self._severity(severity)
            if applies_to is not None:
                lesson.appliesTo = self._unique_strings(applies_to)
            self.write_lessons(root, memory)
            return lesson
        raise FileNotFoundError(f"missing writing lesson: {lesson_id}")

    def merge_lessons(
        self,
        root: Path,
        source_id: str,
        target_id: str,
    ) -> WritingLesson:
        source_id = (source_id or "").strip()
        target_id = (target_id or "").strip()
        if not source_id or not target_id or source_id == target_id:
            raise ValueError("source and target lessons must be different")
        memory = self.read_lessons(root)
        source = next((lesson for lesson in memory.lessons if lesson.id == source_id), None)
        target = next((lesson for lesson in memory.lessons if lesson.id == target_id), None)
        if source is None:
            raise FileNotFoundError(f"missing writing lesson: {source_id}")
        if target is None:
            raise FileNotFoundError(f"missing writing lesson: {target_id}")
        target.failureCount += source.failureCount
        target.successCount += source.successCount
        target.severity = self._max_severity(target.severity, source.severity)
        target.status = (
            "active"
            if target.status == "active" or source.status == "active"
            else "retired"
        )
        if source.source and source.source not in target.source.split(" | "):
            target.source = " | ".join(item for item in [target.source, source.source] if item)
        target.evidence = self._unique_strings([*target.evidence, *source.evidence])
        target.appliesTo = self._unique_strings([*target.appliesTo, *source.appliesTo])
        memory.lessons = [lesson for lesson in memory.lessons if lesson.id != source_id]
        self.write_lessons(root, memory)
        return target

    def lesson_usage(self, root: Path, limit: int = 5) -> dict[str, list[dict[str, object]]]:
        project = self.project_service.open_project(root)
        usage: dict[str, list[dict[str, object]]] = {}
        context_pack_paths = [
            path
            for path in self.project_service.list_paths(project.root, "story/context-packs")
            if path.endswith(".json")
        ]
        for relative_path in sorted(context_pack_paths, reverse=True):
            try:
                data = json.loads(
                    self.project_service.read_text(project.root, relative_path)
                )
            except (OSError, json.JSONDecodeError):
                continue
            chapter_id = str(data.get("chapterId") or Path(relative_path).stem)
            for lesson in self._lessons_from_context_pack(data):
                lesson_id = str(lesson.get("id") or "")
                if not lesson_id:
                    continue
                entries = usage.setdefault(lesson_id, [])
                if len(entries) >= limit:
                    continue
                entries.append(
                    {
                        "chapterId": chapter_id,
                        "path": relative_path,
                        "reasons": self._context_priority_reasons(lesson),
                    }
                )
        return usage

    def learn_from_review(
        self,
        root: Path,
        chapter_id: str,
        review_items: list[ChapterReviewItem],
    ) -> WritingLessonsMemory:
        memory = self.read_lessons(root)
        lessons_by_id = {lesson.id: lesson for lesson in memory.lessons}
        for item in review_items:
            if item.kind != "continuity_risk":
                continue
            field = str(item.payload.get("field") or "")
            category = self._category_for_field(field)
            lesson_id = f"lesson_{category}_{self._slug(field)}"
            expected = str(item.payload.get("expected") or "")
            lesson_text = self._lesson_text(category, field, expected)
            existing = lessons_by_id.get(lesson_id)
            if existing is None:
                existing = WritingLesson(
                    id=lesson_id,
                    category=category,
                    lesson=lesson_text,
                    source=f"reviews/{chapter_id}.review.json#{item.id}",
                    evidence=item.evidence,
                    appliesTo=[field] if field else [],
                    severity=self._severity(item.payload.get("severity")),
                )
                lessons_by_id[lesson_id] = existing
                memory.lessons.append(existing)
                continue
            existing.failureCount += 1
            existing.status = "active"
            existing.severity = self._max_severity(existing.severity, item.payload.get("severity"))
            for evidence in item.evidence:
                if evidence not in existing.evidence:
                    existing.evidence.append(evidence)
            if field and field not in existing.appliesTo:
                existing.appliesTo.append(field)
        memory.lessons = self._compact_lessons(memory.lessons)
        self.write_lessons(root, memory)
        return memory

    def learn_from_editorial_review(
        self,
        root: Path,
        report: EditorialReviewReport,
    ) -> WritingLessonsMemory:
        memory = self.read_lessons(root)
        lessons_by_id = {lesson.id: lesson for lesson in memory.lessons}
        for issue in report.issues:
            lesson_id = self._editorial_lesson_id(issue)
            lesson_text = self._editorial_lesson_text(issue)
            existing = lessons_by_id.get(lesson_id)
            if existing is None:
                existing = WritingLesson(
                    id=lesson_id,
                    category=self._category_for_editorial_issue(issue),
                    lesson=lesson_text,
                    source=f"{report.source}#{issue.type}",
                    evidence=issue.evidence,
                    appliesTo=self._editorial_applies_to(issue),
                    severity=issue.severity,
                )
                lessons_by_id[lesson_id] = existing
                memory.lessons.append(existing)
                continue
            existing.failureCount += 1
            existing.status = "active"
            existing.severity = self._max_severity(existing.severity, issue.severity)
            for evidence in issue.evidence:
                if evidence not in existing.evidence:
                    existing.evidence.append(evidence)
            for target in self._editorial_applies_to(issue):
                if target not in existing.appliesTo:
                    existing.appliesTo.append(target)
        memory.lessons = self._compact_lessons(memory.lessons)
        self.write_lessons(root, memory)
        return memory

    def learn_from_writing_quality(
        self,
        root: Path,
        report: WritingQualityReport,
        min_severity: str = "high",
    ) -> WritingLessonsMemory:
        memory, _ = self.learn_from_writing_quality_with_summary(
            root,
            report,
            min_severity=min_severity,
        )
        return memory

    def learn_from_writing_quality_with_summary(
        self,
        root: Path,
        report: WritingQualityReport,
        min_severity: str = "high",
    ) -> tuple[WritingLessonsMemory, dict[str, object]]:
        memory = self.read_lessons(root)
        lessons_by_id = {lesson.id: lesson for lesson in memory.lessons}
        before = {
            lesson.id: (lesson.failureCount, lesson.severity, lesson.status)
            for lesson in memory.lessons
        }
        skipped: list[str] = []
        for issue in report.issues:
            if not self._meets_min_severity(issue.severity, min_severity):
                skipped.append(issue.type)
                continue
            lesson_id = self._quality_lesson_id(issue)
            lesson_text = self._quality_lesson_text(issue)
            existing = lessons_by_id.get(lesson_id)
            if existing is None:
                existing = WritingLesson(
                    id=lesson_id,
                    category=self._category_for_quality_issue(issue),
                    lesson=lesson_text,
                    source=f"{report.source}#{issue.type}",
                    evidence=issue.evidence,
                    appliesTo=[issue.type],
                    severity=issue.severity,
                )
                lessons_by_id[lesson_id] = existing
                memory.lessons.append(existing)
                continue
            existing.failureCount += 1
            existing.status = "active"
            existing.severity = self._max_severity(existing.severity, issue.severity)
            for evidence in issue.evidence:
                if evidence not in existing.evidence:
                    existing.evidence.append(evidence)
            if issue.type not in existing.appliesTo:
                existing.appliesTo.append(issue.type)
        memory.lessons = self._compact_lessons(memory.lessons)
        self.write_lessons(root, memory)
        after = {
            lesson.id: (lesson.failureCount, lesson.severity, lesson.status)
            for lesson in memory.lessons
        }
        added = sorted(set(after) - set(before))
        updated = sorted(
            lesson_id
            for lesson_id in set(after) & set(before)
            if after[lesson_id] != before[lesson_id]
        )
        summary: dict[str, object] = {
            "source": report.source,
            "minSeverity": self._severity(min_severity),
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "addedCount": len(added),
            "updatedCount": len(updated),
            "skippedCount": len(skipped),
        }
        return memory, summary

    def record_lesson_successes(
        self,
        root: Path,
        chapter_id: str,
        quality_report: WritingQualityReport,
        editorial_report: EditorialReviewReport,
    ) -> tuple[WritingLessonsMemory, dict[str, object]]:
        chapter_id = self.project_service.normalize_chapter_id(chapter_id)
        context_pack_path = f"story/context-packs/{chapter_id}.json"
        used_lesson_ids = set(self._lesson_ids_from_context_pack_file(root, context_pack_path))
        memory = self.read_lessons(root)
        unresolved = self._unresolved_issue_keys(quality_report, editorial_report)
        succeeded: list[str] = []
        blocked: list[str] = []
        marker = f"success:{context_pack_path}"
        for lesson in memory.lessons:
            if lesson.id not in used_lesson_ids or lesson.status != "active":
                continue
            if self._lesson_matches_unresolved_issue(lesson, unresolved):
                blocked.append(lesson.id)
                continue
            if marker in lesson.evidence:
                continue
            lesson.successCount += 1
            lesson.evidence.append(marker)
            succeeded.append(lesson.id)
        if succeeded:
            self.write_lessons(root, memory)
        return memory, {
            "chapterId": chapter_id,
            "contextPack": context_pack_path,
            "succeeded": succeeded,
            "blocked": blocked,
            "succeededCount": len(succeeded),
            "blockedCount": len(blocked),
        }

    def selected_lessons(
        self,
        root: Path,
        chapter_keywords: set[str],
        limit: int = 8,
    ) -> list[WritingLesson]:
        memory = self.read_lessons(root)
        active = [lesson for lesson in memory.lessons if lesson.status == "active"]
        ranked = [
            (self._lesson_score(lesson, chapter_keywords), index, lesson)
            for index, lesson in enumerate(active)
        ]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [lesson for score, _, lesson in ranked if score > 0][:limit]

    def _compact_lessons(self, lessons: list[WritingLesson]) -> list[WritingLesson]:
        lessons.sort(key=lambda lesson: (-self._base_score(lesson), lesson.id))
        active_seen = 0
        compacted: list[WritingLesson] = []
        for lesson in lessons:
            if lesson.status == "active":
                active_seen += 1
                if active_seen > self.max_active_lessons:
                    lesson.status = "retired"
            compacted.append(lesson)
        return compacted

    def _lesson_score(self, lesson: WritingLesson, chapter_keywords: set[str]) -> int:
        score = self._base_score(lesson)
        searchable = " ".join([lesson.lesson, *lesson.appliesTo])
        if any(keyword and keyword in searchable for keyword in chapter_keywords):
            score += 20
        return score

    def _base_score(self, lesson: WritingLesson) -> int:
        severity_score = {"blocker": 80, "high": 60, "medium": 35, "low": 15}[lesson.severity]
        return severity_score + lesson.failureCount * 8 + lesson.successCount * 3

    def _category_for_field(self, field: str) -> str:
        if field.startswith("readerPromises"):
            return "reader_promise"
        if field.startswith("mustAvoid") or field.startswith("mustInclude"):
            return "continuity"
        return self.category_by_field.get(field, "style")

    def _lesson_text(self, category: str, field: str, expected: str) -> str:
        target = expected or field
        templates = {
            "focus": "后续章节必须让主要场景持续服务本章 focus，避免只堆设定或动作。",
            "emotion": "情绪节拍要用动作、对白、选择和余波落地，不能只写一句情绪说明。",
            "relationship": "关系变化必须通过互动和态度转折呈现，避免只在旁白里宣布。",
            "hook": "结尾钩子要形成未完成问题、危险或承诺，不能软收束。",
            "reader_promise": "读者承诺要在本章建立、推进或部分兑现，避免承诺悬空。",
            "continuity": "关键连续性约束必须显性落到正文，避免遗漏或提前泄露。",
            "style": "章节草稿要保留明确重点、情绪价值和信息增量。",
        }
        if target:
            return f"{templates[category]} 重点关注：{target}"
        return templates[category]

    def _editorial_lesson_id(self, issue: EditorialReviewIssue) -> str:
        return f"lesson_{self._category_for_editorial_issue(issue)}_{self._slug(issue.type)}"

    def _category_for_editorial_issue(self, issue: EditorialReviewIssue) -> str:
        return self.category_by_editorial_dimension.get(issue.dimension, "style")

    def _editorial_lesson_text(self, issue: EditorialReviewIssue) -> str:
        base = self.lesson_by_editorial_type.get(
            issue.type,
            "后续章节要修正重复出现的编辑问题，保证情绪、人物和读者承诺落到可见戏剧动作。",
        )
        suggestion = next((item for item in issue.suggestions if item.strip()), "")
        if suggestion:
            return f"{base} 建议：{suggestion}"
        return base

    def _editorial_applies_to(self, issue: EditorialReviewIssue) -> list[str]:
        targets = [issue.dimension, issue.type]
        return [target for target in targets if target]

    def _quality_lesson_id(self, issue: WritingQualityIssue) -> str:
        return f"lesson_{self._category_for_quality_issue(issue)}_{self._slug(issue.type)}"

    def _category_for_quality_issue(self, issue: WritingQualityIssue) -> str:
        return self.category_by_quality_type.get(issue.type, "style")

    def _quality_lesson_text(self, issue: WritingQualityIssue) -> str:
        base = self.lesson_by_quality_type.get(
            issue.type,
            "后续章节要修正重复出现的写作质量问题，保证重点、情绪和读者承诺可见。",
        )
        suggestion = next((item for item in issue.suggestions if item.strip()), "")
        if suggestion:
            return f"{base} 建议：{suggestion}"
        return base

    def _severity(self, value: object) -> str:
        severity = str(value or "medium")
        return severity if severity in {"low", "medium", "high", "blocker"} else "medium"

    def _category(self, value: object) -> str:
        category = str(value or "style")
        allowed = {
            "focus",
            "emotion",
            "relationship",
            "hook",
            "reader_promise",
            "continuity",
            "style",
        }
        return category if category in allowed else "style"

    def _max_severity(self, current: str, incoming: object) -> str:
        incoming_severity = self._severity(incoming)
        return (
            incoming_severity
            if self.severity_order[incoming_severity] > self.severity_order[current]
            else current
        )

    def _meets_min_severity(self, severity: str, min_severity: str) -> bool:
        current = self._severity(severity)
        minimum = self._severity(min_severity)
        return self.severity_order[current] >= self.severity_order[minimum]

    def _unique_strings(self, values: list[str]) -> list[str]:
        unique: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if item and item not in unique:
                unique.append(item)
        return unique

    def _lessons_from_context_pack(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        included = data.get("included")
        if not isinstance(included, list):
            return []
        lessons: list[dict[str, Any]] = []
        for item in included:
            if not isinstance(item, dict):
                continue
            if item.get("source") != self.memory_path:
                continue
            item_data = item.get("data")
            if not isinstance(item_data, dict):
                continue
            lesson_items = item_data.get("lessons")
            if not isinstance(lesson_items, list):
                continue
            lessons.extend(lesson for lesson in lesson_items if isinstance(lesson, dict))
        return lessons

    def _context_priority_reasons(self, lesson: dict[str, Any]) -> list[str]:
        priority = lesson.get("_contextPriority")
        if not isinstance(priority, dict):
            return []
        reasons = priority.get("reasons")
        if not isinstance(reasons, list):
            return []
        return [str(reason) for reason in reasons if str(reason).strip()]

    def _lesson_ids_from_context_pack_file(self, root: Path, context_pack_path: str) -> list[str]:
        try:
            data = json.loads(self.project_service.read_text(root, context_pack_path))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, dict):
            return []
        return [
            str(lesson.get("id"))
            for lesson in self._lessons_from_context_pack(data)
            if isinstance(lesson.get("id"), str) and str(lesson.get("id")).strip()
        ]

    def _unresolved_issue_keys(
        self,
        quality_report: WritingQualityReport,
        editorial_report: EditorialReviewReport,
    ) -> set[str]:
        keys = {issue.type for issue in quality_report.issues}
        for issue in editorial_report.issues:
            keys.add(issue.type)
            keys.add(issue.dimension)
        return keys

    def _lesson_matches_unresolved_issue(
        self,
        lesson: WritingLesson,
        unresolved: set[str],
    ) -> bool:
        applies_to = set(lesson.appliesTo)
        if not applies_to:
            applies_to = {lesson.category}
        return bool(applies_to & unresolved)

    def _slug(self, value: str) -> str:
        slug = "".join(char if char.isalnum() else "_" for char in value.strip())
        slug = "_".join(part for part in slug.split("_") if part)
        return slug.lower() or "general"
