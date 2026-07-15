from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from open_novel.core.book_assets import BookAssetService
from open_novel.core.character_asset import CharacterAssetService
from open_novel.core.knowledge_base import KnowledgeBaseService
from open_novel.core.models import ContextPack, ContextPackItem
from open_novel.core.project import ProjectService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.text_support import important_terms, text_supports_claim
from open_novel.core.writing_assets import WritingAssetService

if TYPE_CHECKING:
    from open_novel.core.story_guidance import StoryGuidanceService


class ContextPackService:
    default_max_estimated_tokens = 6000
    memory_sources = [
        "memory/facts.json",
        "memory/open-loops.json",
        "memory/character-states.json",
        "memory/relationship-states.json",
        "memory/timeline-events.json",
        "memory/promises.json",
        "memory/emotional-arcs.json",
        "memory/long-term-memory.json",
        "memory/chapter-summaries.json",
        "memory/writing-lessons.json",
    ]

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        character_assets: CharacterAssetService | None = None,
        knowledge_base: KnowledgeBaseService | None = None,
        book_assets: BookAssetService | None = None,
        writing_assets: WritingAssetService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance
        self.character_assets = character_assets or CharacterAssetService(self.project_service)
        self.knowledge_base = knowledge_base or KnowledgeBaseService(self.project_service)
        self.book_assets = book_assets or BookAssetService()
        self.writing_assets = writing_assets or WritingAssetService(self.project_service)

    def _story_guidance_service(self) -> StoryGuidanceService:
        if self.story_guidance is None:
            from open_novel.core.story_guidance import StoryGuidanceService as _StoryGuidanceService

            self.story_guidance = _StoryGuidanceService(self.project_service)
        return self.story_guidance

    def context_pack_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"story/context-packs/{normalized}.json"

    def read_context_pack(self, root: Path, chapter_id: str) -> ContextPack:
        return ContextPack.model_validate_json(
            self.project_service.read_text(root, self.context_pack_path(chapter_id))
        )

    def write_context_pack(self, root: Path, context_pack: ContextPack) -> None:
        self.project_service.write_text(
            root,
            context_pack.path,
            json.dumps(context_pack.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def build_context_pack(
        self,
        root: Path,
        chapter_id: str,
        max_estimated_tokens: int | None = None,
        write: bool = True,
    ) -> ContextPack:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        story_guidance = self._story_guidance_service()
        contract = story_guidance.read_scene_contract(root, normalized)
        style_profile = StyleProfileService(self.project_service).read_project_profile(root)
        contract_data = contract.model_dump(mode="json")
        emotional_context = self._incoming_emotional_context(root, normalized)
        if emotional_context:
            contract_data = {**contract_data, "emotionalContext": emotional_context}
        arc_context = self._arc_context(root, normalized)
        if arc_context:
            contract_data = {**contract_data, "arcContext": arc_context}
        planning_landing = self._planning_landing(root, normalized)
        if planning_landing:
            contract_data = {**contract_data, "planningLanding": planning_landing}
        style_context = self._context_style_profile(style_profile.model_dump(mode="json"))
        effective_writing_assets = self.writing_assets.effective_assets(root)
        if effective_writing_assets["formulas"] or effective_writing_assets["lessons"]:
            style_context["effectiveWritingAssets"] = effective_writing_assets
        included = [
            ContextPackItem(
                source=story_guidance.contract_path(normalized),
                reason="本章结构化合同，固定包含以避免重点、情感和逻辑边界丢失。",
                data=contract_data,
            ),
            ContextPackItem(
                source=StyleProfileService.default_profile_path,
                reason="项目级平台/题材/风格模板，固定包含以约束叙事节奏和审稿口径。",
                data=style_context,
            ),
        ]
        revision_brief_path = f"story/revision-briefs/{normalized}.json"
        revision_brief = self._read_json_if_exists(root, revision_brief_path)
        if revision_brief is not None:
            included.append(
                ContextPackItem(
                    source=revision_brief_path,
                    reason="本章重写优化计划，固定包含以修复上轮评估失败点。",
                    data=revision_brief,
                )
            )
        excluded: list[ContextPackItem] = []

        keywords = self._keywords_from_contract(contract_data)
        for source in self.memory_sources:
            data = self._read_json_if_exists(root, source)
            if data is None:
                excluded.append(ContextPackItem(source=source, reason="文件不存在。", data={}))
                continue
            data = self._semantic_memory_data(source, data, keywords)
            selected = self._select_relevant_data(data, normalized, keywords)
            selected = self._include_relevant_writing_lessons(source, data, selected, contract_data)
            selected = self._include_emotional_baseline(
                source,
                data,
                selected,
                contract_data,
                normalized,
            )
            if self._has_content(selected):
                included.append(
                    ContextPackItem(
                        source=source,
                        reason="与当前章节、合同关键词、最新人物状态或已确认记忆相关。",
                        data=selected,
                    )
                )
            else:
                excluded.append(
                    ContextPackItem(
                        source=source,
                        reason="未找到与当前章节或合同关键词直接相关的条目。",
                        data=self._empty_like(data),
                    )
                )

        character_asset_data = self.character_assets.select_for_context(
            root,
            normalized,
            contract_data,
            keywords,
        )
        if self._has_content(character_asset_data):
            included.append(
                ContextPackItem(
                    source=CharacterAssetService.memory_path,
                    reason="与本章人物、冲突或合同关键词相关的角色资源账本条目。",
                    data=character_asset_data,
                )
            )
        else:
            excluded.append(
                ContextPackItem(
                    source=CharacterAssetService.memory_path,
                    reason="未找到可调度的角色资源条目。",
                    data=self._empty_like(character_asset_data),
                )
            )

        book_asset_data = self.book_assets.select_for_context(
            root,
            normalized,
            contract_data,
            keywords,
        )
        if self._has_content(book_asset_data):
            included.append(
                ContextPackItem(
                    source=BookAssetService.context_source,
                    reason="已确认且与本章相关的世界规则、地点、势力和人物名册。",
                    data=book_asset_data,
                )
            )
        else:
            excluded.append(
                ContextPackItem(
                    source=BookAssetService.context_source,
                    reason="没有与本章相关的已确认书级资产。",
                    data=self._empty_like(book_asset_data),
                )
            )

        knowledge_data = self.knowledge_base.context_data(root, keywords)
        if self._has_content(knowledge_data):
            included.append(
                ContextPackItem(
                    source=KnowledgeBaseService.index_path,
                    reason="本地知识库中与本章合同关键词匹配的参考片段。",
                    data=knowledge_data,
                )
            )
        else:
            excluded.append(
                ContextPackItem(
                    source=KnowledgeBaseService.index_path,
                    reason="知识库为空或未找到与本章关键词匹配的片段。",
                    data=self._empty_like(knowledge_data),
                )
            )

        previous_chapter = self._previous_chapter_path(normalized)
        if previous_chapter:
            previous_text = self._read_text_if_exists(root, previous_chapter)
            if previous_text:
                included.append(
                    ContextPackItem(
                        source=previous_chapter,
                        reason="上一章正文用于承接钩子、情绪余波和连续动作。",
                        data={"excerpt": previous_text[:4000]},
                    )
                )
                included.append(
                    ContextPackItem(
                        source=f"{previous_chapter}#ending",
                        reason="上一章结尾2段，下一章开头必须自然衔接，不能跳跃。",
                        data={"endingText": self._ending_excerpt(previous_text)},
                    )
                )
            else:
                excluded.append(
                    ContextPackItem(source=previous_chapter, reason="上一章正文不存在。", data={})
                )

        budget = max_estimated_tokens or self.default_max_estimated_tokens
        included, budget_excluded = self._trim_to_token_budget(included, budget)
        excluded.extend(budget_excluded)

        context_pack = ContextPack(
            chapterId=normalized,
            path=self.context_pack_path(normalized),
            included=included,
            excluded=excluded,
            estimatedTokens=self._estimate_tokens(included),
        )
        if write:
            self.write_context_pack(root, context_pack)
        return context_pack

    def preview_context_pack(
        self,
        root: Path,
        chapter_id: str,
        max_estimated_tokens: int | None = None,
    ) -> ContextPack:
        return self.build_context_pack(
            root,
            chapter_id,
            max_estimated_tokens=max_estimated_tokens,
            write=False,
        )

    def context_pack_diff(
        self,
        root: Path,
        chapter_id: str,
        max_estimated_tokens: int | None = None,
    ) -> dict[str, object]:
        saved = self.read_context_pack(root, chapter_id)
        preview = self.preview_context_pack(
            root,
            chapter_id,
            max_estimated_tokens=max_estimated_tokens,
        )
        saved_text = self._context_pack_text(saved)
        preview_text = self._context_pack_text(preview)
        from open_novel.core.diff import TextDiffService

        diff_text = TextDiffService().unified(
            saved_text,
            preview_text,
            saved.path,
            f"{preview.path}:preview",
        )
        saved_sources = {item.source for item in saved.included}
        preview_sources = {item.source for item in preview.included}
        return {
            "chapterId": preview.chapterId,
            "path": preview.path,
            "diff": diff_text,
            "changed": bool(diff_text),
            "savedEstimatedTokens": saved.estimatedTokens,
            "previewEstimatedTokens": preview.estimatedTokens,
            "addedSources": sorted(preview_sources - saved_sources),
            "removedSources": sorted(saved_sources - preview_sources),
            "keptSources": sorted(saved_sources & preview_sources),
        }

    def _context_pack_text(self, context_pack: ContextPack) -> str:
        return json.dumps(context_pack.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    def _context_style_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {
            "schemaVersion": profile.get("schemaVersion", 1),
            "id": profile.get("id", ""),
            "extends": profile.get("extends", ""),
            "platform": profile.get("platform", ""),
            "genres": profile.get("genres", []),
            "readerExpectations": profile.get("readerExpectations", [])[:2],
            "plotRhythm": profile.get("plotRhythm", [])[:2],
            "emotionGuidance": profile.get("emotionGuidance", [])[:2],
            "editorialFocus": profile.get("editorialFocus", [])[:6],
        }
        return {key: value for key, value in compact.items() if value != "" and value != []}

    def ensure_context_pack(self, root: Path, chapter_id: str) -> ContextPack:
        try:
            return self.read_context_pack(root, chapter_id)
        except FileNotFoundError:
            return self.build_context_pack(root, chapter_id)

    def _trim_to_token_budget(
        self,
        included: list[ContextPackItem],
        budget: int,
    ) -> tuple[list[ContextPackItem], list[ContextPackItem]]:
        if budget <= 0 or self._estimate_tokens(included) <= budget or not included:
            return included, []

        fixed = [
            item
            for item in included
            if item.source == StyleProfileService.default_profile_path
            or item.source.startswith("story/chapter-briefs/")
            or item.source.startswith("story/revision-briefs/")
        ]
        if not fixed:
            fixed = [included[0]]
        remaining = budget - self._estimate_tokens(fixed)
        candidates = [
            (self._pack_item_priority(item), index, item)
            for index, item in enumerate(included[1:], start=1)
            if item not in fixed
        ]
        candidates.sort(key=lambda value: (-value[0], value[1]))

        kept = fixed.copy()
        excluded: list[ContextPackItem] = []
        for _, _, item in candidates:
            fitted, dropped = self._fit_context_item_to_budget(item, max(0, remaining))
            if fitted is not None:
                kept.append(fitted)
                remaining = budget - self._estimate_tokens(kept)
            if dropped is not None:
                excluded.append(dropped)
        return kept, excluded

    def _fit_context_item_to_budget(
        self,
        item: ContextPackItem,
        remaining_budget: int,
    ) -> tuple[ContextPackItem | None, ContextPackItem | None]:
        if remaining_budget <= 0:
            return None, self._budget_excluded_item(item, "预算已用尽。")
        if self._estimate_tokens([item]) <= remaining_budget:
            return item, None

        trimmed, summary = self._trim_context_data(
            item.source,
            item.reason,
            item.data,
            remaining_budget,
        )
        if self._has_content(trimmed):
            fitted = ContextPackItem(
                source=item.source,
                reason=f"{item.reason} 已按上下文预算保留最高优先级条目。",
                data=trimmed,
            )
            return fitted, self._budget_excluded_item(
                item,
                "部分条目因上下文预算被裁剪。",
                summary,
            )
        return None, self._budget_excluded_item(item, "条目过大且无法在预算内裁剪。")

    def _trim_context_data(
        self,
        source: str,
        reason: str,
        data: Any,
        remaining_budget: int,
    ) -> tuple[Any, Any]:
        if isinstance(data, dict) and isinstance(data.get("excerpt"), str):
            excerpt = data["excerpt"]
            trimmed = {"excerpt": excerpt[: max(0, remaining_budget * 4)]}
            trial = ContextPackItem(source=source, reason=reason, data=trimmed)
            if self._estimate_tokens([trial]) <= remaining_budget:
                return trimmed, {
                    "excerpt": {
                        "droppedCharacters": max(0, len(excerpt) - len(trimmed["excerpt"])),
                    }
                }
            return {}, self._budget_summary(data)

        if isinstance(data, dict):
            selected: dict[str, Any] = {}
            if "schemaVersion" in data:
                selected["schemaVersion"] = data["schemaVersion"]
            candidates: list[tuple[int, int, str, Any]] = []
            index = 0
            for key, value in data.items():
                if not isinstance(value, list):
                    continue
                for item in value:
                    candidates.append((self._data_priority(item), index, key, item))
                    index += 1
            candidates.sort(key=lambda value: (-value[0], value[1]))
            for _, _, key, value in candidates:
                trial = {**selected, key: [*selected.get(key, []), value]}
                trial_item = ContextPackItem(source=source, reason=reason, data=trial)
                if self._estimate_tokens([trial_item]) <= remaining_budget:
                    selected = trial
            return selected, self._dropped_summary_for_dict(data, selected)

        if isinstance(data, list):
            selected_list: list[Any] = []
            candidates = [
                (self._data_priority(item), index, item) for index, item in enumerate(data)
            ]
            candidates.sort(key=lambda value: (-value[0], value[1]))
            for _, _, value in candidates:
                trial = [*selected_list, value]
                trial_item = ContextPackItem(source=source, reason=reason, data=trial)
                if self._estimate_tokens([trial_item]) <= remaining_budget:
                    selected_list = trial
            return selected_list, self._dropped_summary_for_list(data, selected_list)

        trial = ContextPackItem(source=source, reason=reason, data=data)
        if self._estimate_tokens([trial]) <= remaining_budget:
            return data, {}
        return {}, self._budget_summary(data)

    def _budget_excluded_item(
        self,
        item: ContextPackItem,
        reason: str,
        summary: Any | None = None,
    ) -> ContextPackItem:
        return ContextPackItem(
            source=item.source,
            reason=reason,
            data=summary if summary is not None else self._budget_summary(item.data),
        )

    def _budget_summary(self, data: Any) -> Any:
        if isinstance(data, dict):
            summary: dict[str, Any] = {}
            if "schemaVersion" in data:
                summary["schemaVersion"] = data["schemaVersion"]
            for key, value in data.items():
                if isinstance(value, list):
                    summary[key] = {"droppedCount": len(value)}
            return summary
        if isinstance(data, list):
            return {"droppedCount": len(data)}
        return {}

    def _dropped_summary_for_dict(self, original: dict[str, Any], selected: dict[str, Any]) -> Any:
        summary: dict[str, Any] = {}
        if "schemaVersion" in original:
            summary["schemaVersion"] = original["schemaVersion"]
        for key, value in original.items():
            if not isinstance(value, list):
                continue
            kept = selected.get(key, [])
            if not isinstance(kept, list):
                kept = []
            summary[key] = self._dropped_summary_for_list(value, kept)
        return summary

    def _dropped_summary_for_list(self, original: list[Any], selected: list[Any]) -> Any:
        selected_ids = {self._stable_item_id(item, index) for index, item in enumerate(selected)}
        dropped = [
            item
            for index, item in enumerate(original)
            if self._stable_item_id(item, index) not in selected_ids
        ]
        return {
            "droppedCount": len(dropped),
            "droppedIds": [
                self._display_item_id(item, index) for index, item in enumerate(dropped[:10])
            ],
            "highestDroppedPriority": max(
                (self._data_priority(item) for item in dropped),
                default=0,
            ),
        }

    def _stable_item_id(self, item: Any, index: int) -> str:
        if isinstance(item, dict):
            for key in ("id", "chapterId", "characterId"):
                value = item.get(key)
                if value:
                    return f"{key}:{value}"
        return f"index:{index}"

    def _display_item_id(self, item: Any, index: int) -> str:
        if isinstance(item, dict):
            for key in ("id", "chapterId", "characterId"):
                value = item.get(key)
                if value:
                    return str(value)
        return f"index:{index}"

    def _pack_item_priority(self, item: ContextPackItem) -> int:
        if item.source.startswith("story/chapter-briefs/"):
            return 10_000
        if item.source.startswith("story/revision-briefs/"):
            return 9_750
        if item.source == StyleProfileService.default_profile_path:
            return 9_500
        if item.source.startswith("chapters/"):
            return 60
        return self._data_priority(item.data)

    def _data_priority(self, data: Any) -> int:
        if isinstance(data, dict):
            priority = data.get("_contextPriority")
            score = 0
            if isinstance(priority, dict):
                try:
                    score = int(priority.get("score", 0))
                except (TypeError, ValueError):
                    score = 0
            child_scores = [self._data_priority(value) for value in data.values()]
            return max([score, *child_scores])
        if isinstance(data, list):
            return max((self._data_priority(item) for item in data), default=0)
        return 0

    def _read_json_if_exists(self, root: Path, relative_path: str) -> Any | None:
        if not self.project_service.file_exists(root, relative_path):
            return None
        try:
            return json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {"_invalidJson": relative_path}

    def _read_text_if_exists(self, root: Path, relative_path: str) -> str:
        return self.project_service.read_text_if_exists(root, relative_path)

    def _arc_context(self, root: Path, chapter_id: str) -> dict[str, Any]:
        chapter_order = self._chapter_order(chapter_id)
        if chapter_order is None:
            return {}
        for relative_path in self.project_service.list_paths(root, "story/arc-contracts"):
            if not relative_path.endswith(".json"):
                continue
            try:
                data = json.loads(self.project_service.read_text(root, relative_path))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            start, end = self._parse_arc_range(str(data.get("chapterRange") or ""))
            if start is None or end is None or not start <= chapter_order <= end:
                continue
            milestones = [item for item in data.get("keyMilestones", []) if isinstance(item, dict)]
            return {
                "arcId": str(data.get("arcId") or Path(relative_path).stem),
                "title": str(data.get("title") or Path(relative_path).stem),
                "chapterRange": str(data.get("chapterRange") or ""),
                "arcGoal": str(data.get("arcGoal") or ""),
                "antagonist": str(data.get("antagonist") or ""),
                "emotionalArc": str(data.get("emotionalArc") or ""),
                "status": str(data.get("status") or "in_progress"),
                "progress": round((chapter_order - start + 1) * 100 / (end - start + 1)),
                "currentMilestones": [
                    item for item in milestones if str(item.get("chapterId") or "") == chapter_id
                ],
                "upcomingMilestones": self._upcoming_milestones(milestones, chapter_id),
            }
        return {}

    def _planning_landing(self, root: Path, chapter_id: str) -> dict[str, Any]:
        blueprint = self._read_json_if_exists(root, "story/chapter-blueprint.json")
        chapters = blueprint.get("chapters") if isinstance(blueprint, dict) else None
        if not isinstance(chapters, list):
            return {}
        landing = next(
            (
                item
                for item in chapters
                if isinstance(item, dict) and str(item.get("chapterId") or "") == chapter_id
            ),
            None,
        )
        if landing is None:
            return {}
        return {
            "segmentId": str(landing.get("segmentId") or ""),
            "goal": str(landing.get("goal") or ""),
            "hook": str(landing.get("hook") or ""),
            "promiseProgression": str(landing.get("promiseProgression") or ""),
            "logicDependencies": [
                str(item).strip()
                for item in landing.get("logicDependencies", [])
                if str(item).strip()
            ],
        }

    def _parse_arc_range(self, value: str) -> tuple[int | None, int | None]:
        match = re.search(r"(\d{1,4})\D+(\d{1,4})", value.strip())
        if match is None:
            return None, None
        return int(match.group(1)), int(match.group(2))

    def _upcoming_milestones(
        self,
        milestones: list[dict[str, Any]],
        chapter_id: str,
    ) -> list[dict[str, Any]]:
        current_order = self._chapter_order(chapter_id)
        if current_order is None:
            return []
        upcoming: list[tuple[int, int, dict[str, Any]]] = []
        for index, item in enumerate(milestones):
            order = self._chapter_order(str(item.get("chapterId") or ""))
            if order is not None and order > current_order:
                upcoming.append((order, index, item))
        upcoming.sort(key=lambda value: (value[0], value[1]))
        return [item for _, _, item in upcoming[:3]]

    def _semantic_memory_data(self, source: str, data: Any, keywords: set[str]) -> Any:
        if source != "memory/long-term-memory.json":
            return data
        if not isinstance(data, dict) or not isinstance(data.get("topics"), list):
            return data
        expanded_keywords = self._semantic_keywords(keywords)
        topics = []
        for topic in data["topics"]:
            if not isinstance(topic, dict):
                continue
            text = json.dumps(topic, ensure_ascii=False)
            if any(keyword and keyword in text for keyword in expanded_keywords):
                topics.append(
                    {
                        **topic,
                        "_contextPriority": {
                            "score": 55,
                            "reasons": ["semantic_keyword_match"],
                        },
                    }
                )
        if not topics:
            return data
        return {
            **data,
            "topics": topics,
        }

    def _semantic_keywords(self, keywords: set[str]) -> set[str]:
        synonyms = {
            "师父": {"师尊", "导师", "师傅"},
            "师尊": {"师父", "导师", "师傅"},
            "背叛": {"出卖", "倒戈", "反叛"},
            "出卖": {"背叛", "倒戈", "反叛"},
            "神器": {"法宝", "灵器", "宝物"},
            "法宝": {"神器", "灵器", "宝物"},
            "获得": {"得到", "拿到", "取得"},
            "得到": {"获得", "拿到", "取得"},
        }
        expanded = set(keywords)
        for keyword in list(keywords):
            for source, values in synonyms.items():
                if source in keyword:
                    expanded.update(values)
                    expanded.add(keyword.replace(source, next(iter(values))))
        return expanded

    def _select_relevant_data(self, data: Any, chapter_id: str, keywords: set[str]) -> Any:
        if isinstance(data, dict):
            selected: dict[str, Any] = {}
            for key, value in data.items():
                if isinstance(value, list):
                    matches = [item for item in value if self._matches(item, chapter_id, keywords)]
                    if matches:
                        selected[key] = self._prioritized_items(matches, chapter_id, keywords)
                elif key == "schemaVersion":
                    selected[key] = value
                elif self._matches(value, chapter_id, keywords):
                    selected[key] = value
            return selected
        if isinstance(data, list):
            return self._prioritized_items(
                [item for item in data if self._matches(item, chapter_id, keywords)],
                chapter_id,
                keywords,
            )
        return data if self._matches(data, chapter_id, keywords) else {}

    def _prioritized_items(
        self,
        items: list[Any],
        chapter_id: str,
        keywords: set[str],
    ) -> list[Any]:
        decorated = [
            (self._context_priority(item, chapter_id, keywords), index, item)
            for index, item in enumerate(items)
        ]
        decorated.sort(key=lambda value: (-value[0]["score"], value[1]))
        return [self._with_context_priority(item, priority) for priority, _, item in decorated]

    def _context_priority(
        self,
        item: Any,
        chapter_id: str,
        keywords: set[str],
    ) -> dict[str, Any]:
        text = json.dumps(item, ensure_ascii=False)
        reasons: list[str] = []
        score = 0
        current_order = self._chapter_order(chapter_id)
        if isinstance(item, dict):
            existing_priority = item.get("_contextPriority")
            existing_reasons = (
                existing_priority.get("reasons") if isinstance(existing_priority, dict) else []
            )
            if isinstance(existing_reasons, list):
                reasons.extend(str(reason) for reason in existing_reasons if str(reason))
            try:
                score += (
                    int(existing_priority.get("score", 0))
                    if isinstance(existing_priority, dict)
                    else 0
                )
            except (TypeError, ValueError):
                pass
        if chapter_id in text or f"chapter:{chapter_id}" in text:
            score += 100
            reasons.append("current_chapter")
        if isinstance(item, dict):
            status = str(item.get("status") or "")
            if status == "partial":
                score += 40
                reasons.append("partial")
            elif status == "open":
                score += 20
                reasons.append("open")
            importance_score, importance_reason = self._importance_priority(item)
            if importance_score:
                score += importance_score
                reasons.append(importance_reason)
            confidence_score, confidence_reason = self._confidence_priority(item)
            if confidence_score:
                score += confidence_score
                reasons.append(confidence_reason)
            recency_score, recency_reason = self._recency_priority(item, current_order)
            if recency_score:
                score += recency_score
                reasons.append(recency_reason)
            start, end = self._parse_payoff_window(str(item.get("expectedPayoffWindow") or ""))
            if current_order is not None and start is not None and end is not None:
                if current_order > end:
                    score += 90
                    reasons.append("payoff_overdue")
                elif current_order >= start:
                    score += 70
                    reasons.append("payoff_due_soon")
        keyword_hits = sorted(
            keyword for keyword in keywords if self._keyword_matches(text, keyword)
        )
        if keyword_hits:
            score += min(30, len(keyword_hits) * 5)
            reasons.append("keyword_match")
        return {
            "score": score,
            "reasons": reasons or ["matched"],
        }

    def _with_context_priority(self, item: Any, priority: dict[str, Any]) -> Any:
        if isinstance(item, dict):
            return {**item, "_contextPriority": priority}
        return item

    def _include_emotional_baseline(
        self,
        source: str,
        data: Any,
        selected: Any,
        contract_data: dict[str, Any],
        chapter_id: str,
    ) -> Any:
        if source == "memory/emotional-arcs.json":
            return self._include_latest_character_entries(
                data,
                selected,
                contract_data,
                chapter_id,
                list_key="beats",
                baseline_reason="latest_emotional_baseline",
            )
        if source == "memory/character-states.json":
            return self._include_latest_character_entries(
                data,
                selected,
                contract_data,
                chapter_id,
                list_key="states",
                baseline_reason="latest_character_state",
            )
        if source == "memory/relationship-states.json":
            return self._include_latest_relationship_entries(data, selected, chapter_id)
        return selected

    def _include_latest_relationship_entries(
        self,
        data: Any,
        selected: Any,
        chapter_id: str,
    ) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("relationships"), list):
            return selected
        latest: dict[str, dict[str, Any]] = {}
        for relationship in data["relationships"]:
            if not isinstance(relationship, dict):
                continue
            relation_id = str(relationship.get("id") or "")
            relation_chapter = str(relationship.get("chapterId") or "")
            if not relation_id or not self._chapter_before(relation_chapter, chapter_id):
                continue
            current = latest.get(relation_id)
            if current is None or self._chapter_before(
                str(current.get("chapterId") or ""),
                relation_chapter,
            ):
                latest[relation_id] = relationship
        if not latest:
            return selected
        selected_data = selected if isinstance(selected, dict) else {}
        relationships = selected_data.setdefault("relationships", [])
        if not isinstance(relationships, list):
            relationships = []
            selected_data["relationships"] = relationships
        existing_ids = {
            str(item.get("id"))
            for item in relationships
            if isinstance(item, dict) and item.get("id")
        }
        for relationship in latest.values():
            relation_id = str(relationship.get("id") or "")
            if relation_id in existing_ids:
                self._add_context_reason(
                    relationships,
                    relation_id,
                    "latest_relationship_state",
                    82,
                )
                continue
            relationships.append(
                self._with_context_priority(
                    relationship,
                    {"score": 82, "reasons": ["latest_relationship_state"]},
                )
            )
            existing_ids.add(relation_id)
        if "schemaVersion" in data:
            selected_data.setdefault("schemaVersion", data["schemaVersion"])
        return selected_data

    def _add_context_reason(
        self,
        items: list[Any],
        item_id: str,
        reason: str,
        score: int,
    ) -> None:
        for item in items:
            if not isinstance(item, dict) or str(item.get("id") or "") != item_id:
                continue
            priority = item.setdefault("_contextPriority", {})
            if not isinstance(priority, dict):
                item["_contextPriority"] = {"score": score, "reasons": [reason]}
                return
            priority["score"] = max(int(priority.get("score") or 0), score)
            reasons = priority.setdefault("reasons", [])
            if not isinstance(reasons, list):
                priority["reasons"] = [reason]
                return
            if reason not in reasons:
                reasons.append(reason)
            return

    def _include_relevant_writing_lessons(
        self,
        source: str,
        data: Any,
        selected: Any,
        contract_data: dict[str, Any],
    ) -> Any:
        if source != "memory/writing-lessons.json":
            return selected
        if not isinstance(data, dict) or not isinstance(data.get("lessons"), list):
            return selected
        categories = self._lesson_categories_for_contract(contract_data)
        selected_data = selected if isinstance(selected, dict) else {}
        lessons = selected_data.setdefault("lessons", [])
        if not isinstance(lessons, list):
            lessons = []
            selected_data["lessons"] = lessons
        existing_ids = {
            str(lesson.get("id"))
            for lesson in lessons
            if isinstance(lesson, dict) and lesson.get("id")
        }
        for lesson in data["lessons"]:
            if not isinstance(lesson, dict):
                continue
            if lesson.get("status") == "retired":
                continue
            if str(lesson.get("category") or "") not in categories:
                continue
            lesson_id = str(lesson.get("id") or "")
            if lesson_id and lesson_id in existing_ids:
                continue
            lessons.append(
                self._with_context_priority(
                    lesson,
                    {
                        "score": 75,
                        "reasons": ["writing_lesson_category_match"],
                    },
                )
            )
            if lesson_id:
                existing_ids.add(lesson_id)
        if "schemaVersion" in data:
            selected_data.setdefault("schemaVersion", data["schemaVersion"])
        return selected_data if lessons else selected

    def _lesson_categories_for_contract(self, contract_data: dict[str, Any]) -> set[str]:
        categories = {"style", "continuity"}
        if contract_data.get("focus"):
            categories.add("focus")
        if contract_data.get("emotionalBeat"):
            categories.add("emotion")
        if contract_data.get("relationshipBeat"):
            categories.add("relationship")
        if contract_data.get("hook"):
            categories.add("hook")
        if contract_data.get("readerPromises"):
            categories.add("reader_promise")
        return categories

    def _include_latest_character_entries(
        self,
        data: Any,
        selected: Any,
        contract_data: dict[str, Any],
        chapter_id: str,
        list_key: str,
        baseline_reason: str,
    ) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
            return selected

        pov = str(contract_data.get("pov") or "").strip()
        selected_data = selected if isinstance(selected, dict) else {}
        characters = selected_data.setdefault("characters", [])
        if not isinstance(characters, list):
            characters = []
            selected_data["characters"] = characters

        existing_by_id = {
            str(character.get("characterId")): character
            for character in characters
            if isinstance(character, dict) and character.get("characterId")
        }
        baselines: list[dict[str, Any]] = []
        for character in data["characters"]:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("characterId") or "")
            if not character_id:
                continue
            if pov and pov not in {character_id, str(character.get("name") or "")}:
                continue
            values = character.get(list_key)
            if not isinstance(values, list) or not values:
                continue
            latest = self._latest_entry_before_chapter(values, chapter_id)
            if latest is None:
                continue
            baseline = {
                "characterId": character_id,
                list_key: [
                    self._with_context_priority(
                        latest,
                        {
                            "score": 65,
                            "reasons": [baseline_reason],
                        },
                    )
                ],
            }
            existing_character = existing_by_id.get(character_id)
            if existing_character is not None:
                self._mark_latest_entry_as_baseline(
                    existing_character,
                    list_key,
                    latest,
                    baseline_reason,
                )
                continue
            baselines.append(baseline)

        if not baselines:
            return selected_data if selected_data != selected else selected
        characters.extend(baselines)
        if "schemaVersion" in data:
            selected_data.setdefault("schemaVersion", data["schemaVersion"])
        return selected_data

    def _mark_latest_entry_as_baseline(
        self,
        character: dict[str, Any],
        list_key: str,
        latest: Any,
        baseline_reason: str,
    ) -> None:
        values = character.get(list_key)
        if not isinstance(values, list):
            return
        latest_text = json.dumps(latest, ensure_ascii=False, sort_keys=True)
        for index, value in enumerate(values):
            value_text = json.dumps(
                {key: item for key, item in value.items() if key != "_contextPriority"}
                if isinstance(value, dict)
                else value,
                ensure_ascii=False,
                sort_keys=True,
            )
            if value_text != latest_text:
                continue
            priority = value.get("_contextPriority", {}) if isinstance(value, dict) else {}
            reasons = list(priority.get("reasons", [])) if isinstance(priority, dict) else []
            if baseline_reason not in reasons:
                reasons.append(baseline_reason)
            score = max(int(priority.get("score", 0)) if isinstance(priority, dict) else 0, 65)
            values[index] = self._with_context_priority(
                value,
                {
                    "score": score,
                    "reasons": reasons,
                },
            )
            return

    def _latest_entry_before_chapter(self, values: list[Any], chapter_id: str) -> Any | None:
        current_order = self._chapter_order(chapter_id)
        candidates: list[tuple[int, int, Any]] = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            entry_chapter = str(
                value.get("chapterId") or str(value.get("validFrom") or "").removeprefix("chapter:")
            )
            order = self._chapter_order(entry_chapter)
            if current_order is not None and order is not None and order >= current_order:
                continue
            candidates.append((order or -1, index, value))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def _matches(self, value: Any, chapter_id: str, keywords: set[str]) -> bool:
        text = json.dumps(value, ensure_ascii=False)
        if isinstance(value, dict):
            priority = value.get("_contextPriority")
            reasons = priority.get("reasons") if isinstance(priority, dict) else []
            if isinstance(reasons, list) and "semantic_keyword_match" in reasons:
                return True
        if chapter_id in text or f"chapter:{chapter_id}" in text:
            return True
        if self._is_context_pressure_item(value, chapter_id):
            return True
        return any(self._keyword_matches(text, keyword) for keyword in keywords)

    def _keyword_matches(self, text: str, keyword: str) -> bool:
        return bool(keyword and (keyword in text or text_supports_claim(text, keyword)))

    def _is_context_pressure_item(self, value: Any, chapter_id: str) -> bool:
        if not isinstance(value, dict):
            return False
        if value.get("status") == "partial":
            return True
        importance_score, _ = self._importance_priority(value)
        if importance_score >= 30:
            return True
        current_order = self._chapter_order(chapter_id)
        start, _ = self._parse_payoff_window(str(value.get("expectedPayoffWindow") or ""))
        return current_order is not None and start is not None and current_order >= start

    def _importance_priority(self, item: dict[str, Any]) -> tuple[int, str]:
        raw = str(item.get("importance") or item.get("priority") or "").lower()
        if raw in {"critical", "blocker", "p0"}:
            return 50, "importance_critical"
        if raw in {"high", "p1"}:
            return 35, "importance_high"
        if raw in {"medium", "normal"}:
            return 15, "importance_medium"
        if raw in {"low", "p2"}:
            return 5, "importance_low"
        return 0, ""

    def _confidence_priority(self, item: dict[str, Any]) -> tuple[int, str]:
        raw = item.get("confidence")
        if raw is None:
            return 0, ""
        try:
            confidence = float(raw)
        except (TypeError, ValueError):
            return 0, ""
        if confidence >= 0.9:
            return 10, "high_confidence"
        if confidence < 0.5:
            return -30, "low_confidence"
        return 0, ""

    def _recency_priority(
        self,
        item: dict[str, Any],
        current_order: int | None,
    ) -> tuple[int, str]:
        item_order = self._item_chapter_order(item)
        if current_order is None or item_order is None or item_order >= current_order:
            return 0, ""
        distance = current_order - item_order
        if distance == 1:
            return 25, "recent_previous_chapter"
        if distance <= 3:
            return 12, "recent_story_memory"
        return 0, ""

    def _item_chapter_order(self, item: dict[str, Any]) -> int | None:
        for key in ("chapterId", "validFrom", "introducedAt", "payoffAt", "lastTouchedAt"):
            value = item.get(key)
            if value is None:
                continue
            order = self._chapter_order_from_text(str(value))
            if order is not None:
                return order
        source = item.get("source")
        if source is not None:
            return self._chapter_order_from_text(str(source))
        return None

    def _chapter_order_from_text(self, value: str) -> int | None:
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        match = re.search(r"(?:chapter[:/_-]?|chapters/)(?P<chapter>\d{1,4})", stripped)
        if match is None:
            return None
        return int(match.group("chapter"))

    def _keywords_from_contract(self, contract_data: dict[str, Any]) -> set[str]:
        raw_values: list[str] = []
        for value in contract_data.values():
            if isinstance(value, str):
                raw_values.extend(self._split_keywords(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        raw_values.extend(self._split_keywords(item))
        return {keyword for keyword in raw_values if len(keyword) >= 2}

    def _split_keywords(self, text: str) -> list[str]:
        return important_terms(text)

    def _ending_excerpt(self, text: str) -> str:
        body = re.sub(r"^# .*$", "", text, count=1, flags=re.MULTILINE).strip()
        paragraphs = [item.strip() for item in body.splitlines() if item.strip()]
        if paragraphs:
            return "\n\n".join(paragraphs[-2:])
        return body[-500:]

    def _parse_payoff_window(self, value: str) -> tuple[int | None, int | None]:
        match = re.fullmatch(r"chapter:(?P<start>\d{1,4})-(?P<end>\d{1,4})", value.strip())
        if match is None:
            return None, None
        return int(match.group("start")), int(match.group("end"))

    def _chapter_order(self, chapter_id: str) -> int | None:
        return int(chapter_id) if chapter_id.isdigit() else None

    def _chapter_before(self, value: str, chapter_id: str) -> bool:
        item_order = self._chapter_order_from_text(value)
        current_order = self._chapter_order(chapter_id)
        return item_order is not None and current_order is not None and item_order < current_order

    def _has_content(self, data: Any) -> bool:
        if isinstance(data, dict):
            return any(
                key != "schemaVersion" and self._has_content(value) for key, value in data.items()
            )
        if isinstance(data, list):
            return bool(data)
        return bool(data)

    def _empty_like(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {"schemaVersion": data["schemaVersion"]} if "schemaVersion" in data else {}
        if isinstance(data, list):
            return []
        return None

    def _previous_chapter_path(self, chapter_id: str) -> str:
        if chapter_id.isdigit() and int(chapter_id) > 1:
            return f"chapters/{int(chapter_id) - 1:03d}.md"
        return ""

    def _incoming_emotional_context(self, root: Path, chapter_id: str) -> dict[str, Any]:
        previous_path = self._previous_chapter_path(chapter_id)
        if not previous_path:
            return {}
        previous_chapter_id = Path(previous_path).stem
        data = self._read_json_if_exists(root, "memory/emotional-arcs.json")
        if not isinstance(data, dict) or not isinstance(data.get("characters"), list):
            return {}
        for character in data["characters"]:
            if not isinstance(character, dict) or not isinstance(character.get("beats"), list):
                continue
            beats = [
                beat
                for beat in character["beats"]
                if isinstance(beat, dict)
                and str(beat.get("chapterId") or "") == previous_chapter_id
            ]
            if not beats:
                continue
            beat = beats[-1]
            incoming_emotion = str(beat.get("beat") or beat.get("emotion") or "").strip()
            if not incoming_emotion:
                continue
            return {
                "characterId": str(character.get("characterId") or "unknown"),
                "incomingEmotion": incoming_emotion,
                "incomingSource": f"chapter:{previous_chapter_id}",
                "transitionRequired": True,
            }
        return {}

    def _estimate_tokens(self, items: list[ContextPackItem]) -> int:
        text = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False)
        return max(1, len(text) // 4)
