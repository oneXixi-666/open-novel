from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from open_novel.core.beginner_guidance import BeginnerGuidanceService, BeginnerProjectInput
from open_novel.core.chapter_drafting import ChapterDraftService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.continuity import ContinuityService
from open_novel.core.diff import TextDiffService
from open_novel.core.editorial_profile import EditorialProfileService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.gate_recovery import GateRecoveryService
from open_novel.core.issue_navigation import IssueNavigationService
from open_novel.core.jobs import JobController
from open_novel.core.knowledge_base import KnowledgeBaseService
from open_novel.core.local_training import LocalTrainingService
from open_novel.core.memory_topic import MemoryTopicService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.model_comparison import ModelComparisonService
from open_novel.core.models import (
    EditorialReviewReport,
    JobRecord,
    ModelComparisonPromotionRequest,
    ModelComparisonRequest,
    SceneContract,
    SkillRunRequest,
)
from open_novel.core.plot_direction import PlotDirectionService
from open_novel.core.polishing import ChapterPolishService
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.regression_scenario import RegressionScenarioService
from open_novel.core.relationship_graph import RelationshipGraphService
from open_novel.core.revision_plan import RevisionPlanService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.skills import SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import DEFAULT_STYLE_PROFILE_PATH, StyleProfileService
from open_novel.core.style_promotion import StyleProfilePromotionService
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.core.writing_model import WritingModelService
from open_novel.core.writing_quality import WritingQualityService
from open_novel.exporters.service import ExportService
from open_novel.logging_config import configure_logging
from open_novel.security.path_guard import PathGuard

configure_logging()

from open_novel.web import (  # noqa: E402, F401
    routes_basic,
    routes_system,
    routes_workbench,
)
from open_novel.web.app import app, mount_static_if_configured  # noqa: E402
from open_novel.web.author_presenter import (  # noqa: E402
    job_kind_label,
    job_progress_label,
    job_status_label,
    pipeline_message_label,
    pipeline_status_label,
    pipeline_step_label,
    run_preview,
    run_status_label,
)

mount_static_if_configured(os.environ.get("OPEN_NOVEL_STATIC_DIR", "").strip())


class CreateProjectRequest(BaseModel):
    path: Path
    title: str = "未命名小说"
    language: str = "zh-CN"
    targetChapterCount: int = 100
    targetWordsPerChapter: int = 2500
    platform: str = "通用网文"


class BeginnerProjectCreateRequest(BaseModel):
    path: Path
    title: str = "未命名小说"
    language: str = "zh-CN"
    idea: str = ""
    platform: str = "generic"
    genre: str = ""
    targetReaders: str = ""
    chapterWordTarget: int = 2500
    protagonistName: str = "主角"
    protagonistDesire: str = ""
    protagonistWound: str = ""
    opponent: str = ""
    worldRule: str = ""
    longMystery: str = ""
    corePromise: str = ""
    volumeGoal: str = ""
    styleProfileId: str = "generic-web-serial"
    chapterCount: int = 5
    targetChapterCount: int = 100


class FileRequest(BaseModel):
    path: str
    content: str


class ExportRequest(BaseModel):
    root: Path
    format: str


class ChapterCreateRequest(BaseModel):
    root: Path
    chapterId: str | None = None
    title: str | None = None


class DraftAcceptRequest(BaseModel):
    root: Path
    draftPath: str
    chapterId: str | None = None
    force: bool = False


class DiffRequest(BaseModel):
    root: Path
    leftPath: str
    rightPath: str


class PolishRequest(BaseModel):
    root: Path
    sourcePath: str
    instruction: str = ""
    agentId: str = ""
    modelProfile: str = ""
    preferTrainedModel: bool = True


class CharacterCreateRequest(BaseModel):
    root: Path
    characterId: str
    name: str | None = None


class SceneContractCreateRequest(BaseModel):
    root: Path
    chapterId: str
    title: str | None = None


class SceneContractSaveRequest(BaseModel):
    root: Path
    contract: SceneContract


class ContextPackBuildRequest(BaseModel):
    root: Path
    chapterId: str
    maxEstimatedTokens: int | None = None


class PostChapterRequest(BaseModel):
    root: Path
    chapterId: str


class CanonPatchAcceptRequest(BaseModel):
    root: Path
    chapterId: str
    operationIds: list[str] | None = None


class CanonPatchUpdateRequest(BaseModel):
    root: Path
    chapterId: str
    operationIds: list[str]
    status: str


class ContinuityCheckRequest(BaseModel):
    root: Path
    chapterId: str
    draftPath: str | None = None


class ChapterGateRequest(BaseModel):
    root: Path
    chapterId: str
    draftPath: str | None = None
    editorialProfileId: str = ""


class WritingQualityRequest(BaseModel):
    root: Path
    chapterId: str
    draftPath: str | None = None


class EditorialReviewRequest(BaseModel):
    root: Path
    chapterId: str
    draftPath: str | None = None
    backend: str = "local"
    commandTemplate: str = ""
    timeoutSeconds: int = 600
    profileId: str = ""


class SequenceEvaluationRequest(BaseModel):
    root: Path
    startChapterId: str
    endChapterId: str
    preferDrafts: bool = True


class RevisionRerunRequest(BaseModel):
    root: Path
    revisionPlanPath: str
    maxChapters: int = 3
    maxRounds: int = 1
    agentId: str = ""
    modelProfile: str = ""
    preferTrainedModel: bool = True


class PlotDirectionRequest(BaseModel):
    root: Path
    chapterId: str
    userIntent: str


class PlotDirectionApplyRequest(BaseModel):
    root: Path
    chapterId: str
    optionId: str


class WritingModelRegisterRequest(BaseModel):
    root: Path
    profileId: str
    baseModel: str = ""
    adapterPath: str = ""
    commandTemplate: str = ""
    label: str = ""
    timeoutSeconds: int = 600
    setDefault: bool = True


class WritingModelDefaultRequest(BaseModel):
    root: Path
    profileId: str


class EditorialProfileRegisterRequest(BaseModel):
    root: Path
    profileId: str
    backend: str = "local"
    commandTemplate: str = ""
    label: str = ""
    reviewer: str = ""
    promptPreset: str = "generic-humanity"
    styleProfilePath: str = DEFAULT_STYLE_PROFILE_PATH
    rubric: list[str] = Field(default_factory=list)
    timeoutSeconds: int = 600
    setDefault: bool = True


class EditorialProfileDefaultRequest(BaseModel):
    root: Path
    profileId: str


class StyleProfileApplyRequest(BaseModel):
    root: Path
    profileId: str
    projectProfileId: str = "project-style"
    label: str = "Project style override"
    path: str = DEFAULT_STYLE_PROFILE_PATH


class StyleProfilePromotionRequest(BaseModel):
    root: Path
    candidateProfilePath: str
    startChapterId: str
    endChapterId: str
    preferDrafts: bool = True


class StyleProfilePromotionExportRequest(BaseModel):
    root: Path
    promotionReportPath: str
    outputPath: str = ""


class StyleProfileExportValidationRequest(BaseModel):
    root: Path
    exportedProfilePath: str


class RelationshipEventUpdateRequest(BaseModel):
    root: Path
    eventId: str
    status: str
    pressure: str = ""
    unresolvedEmotion: str = ""
    evidence: list[str] = Field(default_factory=list)


class ProjectPlanUpdateRequest(BaseModel):
    root: Path
    targetChapterCount: int = 100
    targetWordsPerChapter: int = 2500
    platform: str = "通用网文"
    cadence: str = "稳定连载"
    notes: str = ""


def _chapter_id_for_studio_file(file: str) -> str:
    if file.startswith("drafts/"):
        return (
            ProjectService()
            .chapter_path_for_draft(file)
            .removeprefix("chapters/")
            .removesuffix(".md")
        )
    if file.startswith("chapters/") and file.endswith(".md"):
        return file.removeprefix("chapters/").removesuffix(".md")
    if file.startswith("story/context-packs/") and file.endswith(".json"):
        return file.removeprefix("story/context-packs/").removesuffix(".json")
    if file.startswith("story/chapter-briefs/") and file.endswith(".json"):
        return file.removeprefix("story/chapter-briefs/").removesuffix(".json")
    return ""


def _chapter_id_from_paths(*paths: str) -> str:
    for path in paths:
        chapter_id = _chapter_id_for_studio_file(path)
        if chapter_id:
            return ProjectService().normalize_chapter_id(chapter_id)
    return ""


def _chapter_source_display_label(
    root: Path,
    chapter_id: str,
    source_path: str,
    source_label: str,
) -> str:
    title = _chapter_display_title(root, chapter_id, source_path)
    label = f"{_chapter_ordinal(chapter_id)} {title}".strip()
    if source_label == "draft":
        return f"{label} · 草稿"
    if source_label == "chapter":
        return label
    return "暂无正文"


def _context_pack_ui_items(items: list[object]) -> list[dict[str, str]]:
    return [
        {
            "label": _source_display_label(str(getattr(item, "source", ""))),
            "category": _context_pack_source_category(str(getattr(item, "source", ""))),
            "reason": str(getattr(item, "reason", "")),
        }
        for item in items
    ]


def _context_pack_source_category(source: str) -> str:
    if source == "memory/character-assets.json" or source.startswith("characters/"):
        return "角色资源"
    if source == "knowledge/index.json" or source.startswith("knowledge/"):
        return "知识来源"
    if source in {"memory/writing-lessons.json", "memory/writing-formulas.json"}:
        return "写作经验"
    if source.startswith("memory/"):
        return "伏笔与记忆"
    if source.startswith("story/chapter-briefs/") or source.startswith("chapters/"):
        return "章节与风格"
    if source == "story/style-profile.json":
        return "章节与风格"
    return "其他资料"


def _context_pack_diff_author_summary(diff: dict[str, object]) -> str:
    changed = bool(diff.get("changed"))
    added_sources = _context_pack_author_source_groups(diff.get("addedSources", []))
    removed_sources = _context_pack_author_source_groups(diff.get("removedSources", []))
    kept_sources = diff.get("keptSources", [])
    kept_count = len(kept_sources) if isinstance(kept_sources, list) else 0
    status = (
        "内容有变化，建议先确认新增和移除的资料类型。"
        if changed
        else "内容没有变化，可以回章节继续写。"
    )
    lines = [
        "# 本章资料预览",
        status,
        f"保留资料：{kept_count} 条",
    ]
    if added_sources:
        lines.append("## 新增资料")
        lines.extend(f"- {item}" for item in added_sources)
    else:
        lines.append("新增资料：无")
    if removed_sources:
        lines.append("## 移除资料")
        lines.extend(f"- {item}" for item in removed_sources)
    else:
        lines.append("移除资料：无")
    return "\n".join(lines)


def _context_pack_author_source_groups(sources: object) -> list[str]:
    if not isinstance(sources, list):
        return []
    grouped: dict[str, int] = {}
    for source in sources:
        category = _context_pack_source_category(str(source))
        grouped[category] = grouped.get(category, 0) + 1
    return [f"{category} {count} 条" for category, count in sorted(grouped.items())]


def _source_display_label(source: str) -> str:
    if source.startswith("characters/"):
        return "角色档案"
    if source.startswith("chapters/"):
        chapter_id = Path(source).stem
        return f"{_chapter_ordinal(chapter_id)} 正文"
    if source.startswith("drafts/"):
        chapter_id = _chapter_id_for_studio_file(source)
        return f"{_chapter_ordinal(chapter_id)} 草稿"
    if source.startswith("story/chapter-briefs/"):
        chapter_id = Path(source).stem
        return f"{_chapter_ordinal(chapter_id)} 章节规划"
    if source.startswith("story/context-packs/"):
        chapter_id = Path(source).stem
        return f"{_chapter_ordinal(chapter_id)} 上下文"
    labels = {
        "novel.json": "作品信息",
        "bible.md": "故事圣经",
        "style.md": "风格指南",
        "rules.md": "写作规则",
        "outline.md": "大纲",
        "timeline.md": "时间线",
        "story/style-profile.json": "风格模板",
        "memory/facts.json": "事实记忆",
        "memory/open-loops.json": "悬念与伏笔",
        "memory/character-states.json": "角色状态",
        "memory/relationship-states.json": "关系状态",
        "memory/timeline-events.json": "时间线事件",
        "memory/chapter-summaries.json": "章节摘要",
        "memory/promises.json": "读者承诺",
        "memory/emotional-arcs.json": "情绪弧线",
        "memory/long-term-memory.json": "长期记忆",
        "memory/writing-lessons.json": "写作经验",
    }
    return labels.get(source, "项目内容")


def _ui_issue_navigation_items(
    root: Path,
    chapter_id: str,
    items: object,
) -> list[dict[str, object]]:
    if not isinstance(items, list):
        return []
    return [
        {
            **item,
            "severityLabel": _severity_label(str(item.get("severity") or "")),
            "reportLabel": _report_label(str(item.get("report") or "")),
            "typeLabel": _issue_type_label(str(item.get("type") or "")),
            "actionCategory": _issue_action_category(str(item.get("type") or "")),
            "suggestedAction": _ui_suggested_action(str(item.get("suggestedAction") or "")),
            "targets": _ui_targets(root, chapter_id, item.get("targets", [])),
        }
        for item in items
        if isinstance(item, dict)
    ]


def _ui_report_issues(issues: object) -> list[dict[str, object]]:
    if not isinstance(issues, list):
        return []
    return [
        {
            "severityLabel": _severity_label(str(_issue_value(issue, "severity"))),
            "typeLabel": _issue_type_label(str(_issue_value(issue, "type"))),
            "actionCategory": _issue_action_category(str(_issue_value(issue, "type"))),
            "stageLabel": _report_label(str(_issue_value(issue, "stage"))),
            "dimensionLabel": _report_label(str(_issue_value(issue, "dimension"))),
            "message": str(_issue_value(issue, "message")),
        }
        for issue in issues
    ]


def _ui_readiness_issues(issues: object) -> list[dict[str, object]]:
    if not isinstance(issues, list):
        return []
    return [
        {
            "severity": str(_issue_value(issue, "severity")),
            "severityLabel": _severity_label(str(_issue_value(issue, "severity"))),
            "message": str(_issue_value(issue, "message")),
            "quickFix": str(_issue_value(issue, "quickFix")),
        }
        for issue in issues
    ]


def _ui_pipeline_steps(steps: object) -> list[dict[str, object]]:
    if not isinstance(steps, list):
        return []
    return [
        {
            "id": str(_issue_value(step, "id")),
            "label": _pipeline_step_label(str(_issue_value(step, "id"))),
            "status": str(_issue_value(step, "status")),
            "statusLabel": _pipeline_status_label(str(_issue_value(step, "status"))),
            "artifact": str(_issue_value(step, "artifact")),
            "message": str(_issue_value(step, "message")),
            "messageLabel": _pipeline_message_label(str(_issue_value(step, "message"))),
        }
        for step in steps
    ]


def _pipeline_step_label(step_id: str) -> str:
    return pipeline_step_label(step_id)


def _pipeline_status_label(status: str) -> str:
    return pipeline_status_label(status)


def _pipeline_message_label(message: str) -> str:
    return pipeline_message_label(message)


def _issue_value(issue: object, field: str) -> object:
    if isinstance(issue, dict):
        return issue.get(field, "")
    return getattr(issue, field, "")


def _ui_gate_recovery(
    root: Path,
    chapter_id: str,
    recovery: object,
) -> object:
    if not isinstance(recovery, dict):
        return recovery
    steps = recovery.get("steps")
    if not isinstance(steps, list):
        return recovery
    recovery = {**recovery}
    recovery["steps"] = [
        {
            **step,
            "severityLabel": _severity_label(str(step.get("severity") or "")),
            "stageLabel": _report_label(str(step.get("stage") or "")),
            "typeLabels": [
                _issue_type_label(str(issue_type))
                for issue_type in step.get("types", [])
                if str(issue_type).strip()
            ],
            "actionCategories": _issue_action_categories(step.get("types", [])),
            "targets": _ui_targets(root, chapter_id, step.get("targets", [])),
        }
        for step in steps
        if isinstance(step, dict)
    ]
    return recovery


def _ui_targets(root: Path, chapter_id: str, targets: object) -> list[dict[str, str]]:
    if not isinstance(targets, list):
        return []
    return [
        {
            **target,
            "label": _ui_target_label(root, chapter_id, target),
        }
        for target in targets
        if isinstance(target, dict)
    ]


def _ui_target_label(root: Path, chapter_id: str, target: dict[str, object]) -> str:
    kind = str(target.get("kind") or "")
    path = str(target.get("path") or "")
    field = str(target.get("field") or "")
    if kind == "contract":
        field_label = _contract_field_label(field)
        return f"章节合同 / {field_label}" if field_label else "章节合同"
    if kind in {"source", "memory"}:
        return _source_display_label(path)
    if kind == "relationship-edge":
        return "关系历史"
    label = str(target.get("label") or "")
    if label and "/" not in label:
        return label
    return _source_display_label(path)


def _contract_field_label(field: str) -> str:
    labels = {
        "title": "标题",
        "pov": "视角",
        "time": "时间",
        "location": "地点",
        "focus": "本章重点",
        "goal": "目标",
        "conflict": "冲突",
        "turn": "转折",
        "outcome": "结果",
        "hook": "钩子",
        "emotionalBeat": "情绪节拍",
        "relationshipBeat": "关系节拍",
        "internalNeed": "内在需求",
        "woundOrFear": "伤口或恐惧",
        "stakes": "利害关系",
        "cost": "代价",
        "subtext": "潜台词",
        "aftertaste": "余味",
        "logicDependencies": "逻辑依赖",
        "mustInclude": "必须写到",
        "mustAvoid": "必须避免",
        "readerPromises": "读者承诺",
    }
    return labels.get(field, field)


def _ui_suggested_action(text: str) -> str:
    updated = text
    for field in [
        "relationshipBeat",
        "emotionalBeat",
        "readerPromises",
        "logicDependencies",
        "internalNeed",
        "woundOrFear",
        "mustInclude",
        "mustAvoid",
        "aftertaste",
        "subtext",
        "stakes",
        "focus",
        "goal",
        "conflict",
        "turn",
        "outcome",
        "hook",
        "cost",
    ]:
        updated = updated.replace(field, _contract_field_label(field))
    return updated


def _issue_action_categories(issue_types: object) -> list[str]:
    if not isinstance(issue_types, list):
        return []
    categories = []
    for issue_type in issue_types:
        category = _issue_action_category(str(issue_type))
        if category not in categories:
            categories.append(category)
    return categories


def _issue_action_category(issue_type: str) -> str:
    material_types = {
        "missing_context_pack",
        "stale_context_pack",
        "no_memory_context",
        "missing_character_asset_context",
        "missing_file",
        "missing_list",
        "missing_text",
        "missing_id",
        "missing_from_character",
        "missing_to_character",
        "missing_relationship_status",
        "missing_emotion",
        "missing_emotional_beat",
        "relationship_transition_needs_review",
        "payoff_due_soon",
        "payoff_overdue",
    }
    character_types = {
        "abstract_human_core",
        "motivation_not_personal",
        "missing_choice",
        "weak_emotional_grounding",
        "emotion_told_not_felt",
        "emotion_lacks_specificity",
        "emotional_discontinuity",
        "relationship_discontinuity",
        "relationship_turn_unearned",
        "weak_subtext",
        "dialogue_lacks_subtext",
        "missing_stakes",
        "missing_cost",
        "payoff_without_cost",
        "ending_lacks_aftertaste",
        "weak_aftertaste",
        "scene_lacks_pressure",
        "character_asset_reuse_risk",
    }
    canon_types = {
        "character_state_contradiction",
        "relationship_state_contradiction",
        "timeline_order_conflict",
        "violated_must_avoid",
        "missing_must_include",
        "ungrounded_logic_dependency",
        "reader_promise_drift",
        "reader_promise_not_advanced",
        "reader_focus_diffuse",
        "focus_drift",
        "focus_not_supported",
        "outcome_drift",
        "hook_drift",
        "invalid_order",
        "invalid_chapter_ref",
        "invalid_payoff_window",
        "invalid_confidence",
        "invalid_evidence",
        "duplicate_id",
        "schema_error",
        "invalid_json",
        "item_schema_error",
    }
    craft_types = {
        "too_short",
        "paragraph_too_long",
        "missing_dialogue",
        "weak_conflict_escalation",
        "over_exposition",
        "description_outweighs_drama",
        "weak_ending_hook",
    }
    if issue_type in material_types:
        return "资料缺失"
    if issue_type in character_types:
        return "角色空转"
    if issue_type in canon_types:
        return "设定冲突"
    if issue_type in craft_types:
        return "写法重复"
    return "其他问题"


def _severity_label(severity: str) -> str:
    return {
        "blocker": "阻塞",
        "high": "高优先级",
        "medium": "中优先级",
        "low": "低优先级",
        "info": "提示",
        "": "提示",
    }.get(severity, severity)


def _report_label(report: str) -> str:
    return {
        "readiness": "开写准备",
        "memory": "故事记忆",
        "context": "上下文",
        "continuity": "连续性",
        "quality": "文笔质量",
        "editorial": "编辑审查",
        "gate": "章节质检",
        "review": "章后复盘",
    }.get(report, report)


def _issue_type_label(issue_type: str) -> str:
    labels = {
        "too_short": "篇幅不足",
        "missing_choice": "缺少明确选择",
        "weak_conflict_escalation": "冲突升级不足",
        "weak_ending_hook": "章尾钩子偏弱",
        "focus_not_supported": "正文没有托住本章重点",
        "focus_drift": "本章重点漂移",
        "emotional_told_not_felt": "情绪被说明而不是被感受到",
        "abstract_human_core": "人物内核偏抽象",
        "missing_stakes": "缺少利害关系",
        "missing_cost": "缺少代价",
        "weak_subtext": "潜台词不足",
        "dialogue_lacks_subtext": "对白缺少潜台词",
        "payoff_without_cost": "兑现缺少代价",
        "reader_promise_not_advanced": "读者承诺没有推进",
        "reader_focus_diffuse": "读者焦点分散",
        "relationship_turn_unearned": "关系转折缺少铺垫",
        "relationship_discontinuity": "关系状态不连续",
        "emotional_discontinuity": "情绪衔接不连续",
        "violated_must_avoid": "触碰了必须避免的内容",
        "missing_must_include": "遗漏必须写到的内容",
        "ungrounded_logic_dependency": "逻辑依赖缺少正文支撑",
    }
    return labels.get(issue_type, issue_type.replace("_", " "))


def _studio_content_items(root: Path, selected_file: str) -> dict[str, list[dict[str, object]]]:
    project_root = PathGuard(root).root
    chapter_ids = _chapter_ids_for_studio(root)
    chapters: list[dict[str, object]] = []
    drafts: list[dict[str, object]] = []

    for chapter_id in chapter_ids:
        chapter_path = f"chapters/{chapter_id}.md"
        title = _chapter_display_title(root, chapter_id, chapter_path)
        chapters.append(
            {
                "id": chapter_id,
                "label": f"{_chapter_ordinal(chapter_id)} {title}".strip(),
                "path": chapter_path,
                "active": selected_file == chapter_path,
                "status": "已写" if (project_root / chapter_path).is_file() else "待写",
            }
        )

    drafts_dir = project_root / "drafts"
    if drafts_dir.exists():
        for draft in sorted(drafts_dir.glob("*.md")):
            relative_path = draft.relative_to(project_root).as_posix()
            chapter_id = _chapter_id_for_studio_file(relative_path)
            title = _chapter_display_title(root, chapter_id, relative_path)
            kind = "润色稿" if draft.name.endswith(".polished.md") else "草稿"
            drafts.append(
                {
                    "id": chapter_id,
                    "label": f"{_chapter_ordinal(chapter_id)} {title}".strip(),
                    "path": relative_path,
                    "active": selected_file == relative_path,
                    "status": kind,
                }
            )

    return {"chapters": chapters, "drafts": drafts}


def _chapter_ids_for_studio(root: Path) -> list[str]:
    project_root = PathGuard(root).root
    ids: set[str] = set()
    for folder, suffix in (("chapters", ".md"), ("story/chapter-briefs", ".json")):
        directory = project_root / folder
        if not directory.exists():
            continue
        for path in directory.glob(f"*{suffix}"):
            ids.add(path.stem)
    return sorted(ids, key=_chapter_sort_key)


def _chapter_sort_key(chapter_id: str) -> tuple[int, int | str]:
    if chapter_id.isdigit():
        return (0, int(chapter_id))
    return (1, chapter_id)


def _studio_content_label(root: Path, file: str) -> str:
    chapter_id = _chapter_id_for_studio_file(file)
    if chapter_id:
        title = _chapter_display_title(root, chapter_id, file)
        prefix = _chapter_ordinal(chapter_id)
        if file.startswith("drafts/"):
            suffix = "润色稿" if file.endswith(".polished.md") else "草稿"
            return f"{prefix} {title} · {suffix}".strip()
        return f"{prefix} {title}".strip()
    return "内容"


def _studio_requires_advanced_editor(file: str) -> bool:
    return file.endswith(".json") or file.startswith("runs/")


def _studio_author_file_summary(file: str, content: str) -> str:
    label = _source_display_label(file)
    if not _studio_requires_advanced_editor(file):
        return content
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {}
    lines = [
        f"# {label}",
        "这是项目资料原文。默认模式只显示摘要，原文编辑请进入高级模式。",
    ]
    if file.startswith("story/context-packs/") and isinstance(data, dict):
        included = data.get("included", [])
        excluded = data.get("excluded", [])
        if isinstance(included, list):
            lines.append(f"已纳入本章资料：{len(included)} 条")
            groups = _context_pack_author_source_groups(
                [str(item.get("source") or "") for item in included if isinstance(item, dict)]
            )
            if groups:
                lines.append("## 资料类型")
                lines.extend(f"- {item}" for item in groups)
        if isinstance(excluded, list) and excluded:
            lines.append(f"暂未纳入：{len(excluded)} 条")
    elif file.startswith("story/chapter-briefs/") and isinstance(data, dict):
        for title, key in [
            ("本章重点", "focus"),
            ("目标", "goal"),
            ("冲突", "conflict"),
            ("转折", "turn"),
            ("结果", "outcome"),
            ("钩子", "hook"),
        ]:
            value = str(data.get(key) or "").strip()
            if value:
                lines.append(f"- {title}：{value}")
    elif file == "memory/long-term-memory.json" and isinstance(data, dict):
        topics = data.get("topics", [])
        if isinstance(topics, list):
            lines.append(f"长期记忆主题：{len(topics)} 条")
            for topic in topics[:5]:
                if isinstance(topic, dict):
                    title = str(topic.get("title") or "记忆主题").strip()
                    summary = str(topic.get("summary") or "").strip()
                    lines.append(f"- {title}" + (f"：{summary}" if summary else ""))
    elif file == "novel.json" and isinstance(data, dict):
        metadata = data.get("metadata", {})
        if isinstance(metadata, dict):
            for title, key in [("书名", "title"), ("语言", "language"), ("平台", "platform")]:
                value = str(metadata.get(key) or "").strip()
                if value:
                    lines.append(f"- {title}：{value}")
    else:
        lines.append("请回到对应的资料页查看作者视图，或进入高级模式编辑原文。")
    return "\n".join(lines)


def _object_field(item: object, field: str) -> object:
    if isinstance(item, dict):
        return item.get(field, "")
    return getattr(item, field, "") if item is not None else ""


def _model_author_next_action(action: object) -> str:
    return _author_next_action(action)


def _author_next_action(action: object) -> str:
    value = str(action or "").strip()
    labels = {
        "fill-required-scene-contract-fields": "先补齐章节目标、冲突、转折和钩子",
        "review-readiness-warnings-before-drafting": "先复查开写提醒，再让 AI 起草",
        "ready-to-draft": "可以开始 AI 起草",
        "fix-blocking-chapter-issues": "先修复阻塞问题，再接收正文",
        "fix-memory-schema-before-drafting": "先修复故事记忆，再重新起草",
        "complete-scene-contract-before-drafting": "先补完整本章要求，再重新起草",
        "build-or-review-context-pack": "先重建或复查本章资料",
        "revise-draft-and-rerun-continuity": "先修改草稿，再复查连续性",
        "revise-accepted-chapter-or-adjust-canon-patch": "先修改正文或调整设定补丁",
        "ready": "可以继续下一步",
        "create-and-accept-quality-checked-chapters": "先完成并接收一批质量合格章节",
        "collect-more-quality-checked-examples-before-training": "继续积累质量合格章节样本",
        "review-skipped-training-examples": "复查被跳过的训练样本",
        "ready-for-offline-local-tuning": "可以准备本地微调",
        "create-and-accept-quality-checked-chapters-before-local-tuning": (
            "先完成并接收质量合格章节，再训练模型"
        ),
        "collect-more-quality-checked-examples-before-local-tuning": (
            "继续积累质量合格章节后再训练"
        ),
        "set-open-novel-train-command-before-running-local-tuning": "先配置本地训练命令",
        "run-local-tuning-and-then-evaluate-a-five-chapter-regression": (
            "先运行本地训练，再做五章回归验证"
        ),
        "promote-tuned-profile-or-run-cli-baseline-comparison": (
            "可考虑晋升新模型，或先补一次命令行基线对比"
        ),
        "do-not-promote-tuned-profile-regressed-quality-or-gate": (
            "不要晋升，先修复质量或质检回退"
        ),
        "do-not-promote-tuned-profile-regressed-editorial-style": ("不要晋升，先修复编辑风格回退"),
        "collect-more-five-chapter-comparison-data-before-promoting": (
            "继续收集五章对比证据后再晋升"
        ),
        "revise-candidate-or-collect-better-five-chapter-examples": (
            "先改进候选模型或准备更好的五章样本"
        ),
    }
    if not value:
        return ""
    return labels.get(value, value.replace("-", " "))


def _chapter_display_title(root: Path, chapter_id: str, relative_path: str = "") -> str:
    for candidate in [relative_path, f"chapters/{chapter_id}.md"]:
        if not candidate:
            continue
        try:
            text = ProjectService().read_text(root, candidate)
        except (FileNotFoundError, ValueError):
            continue
        title = _markdown_title(text)
        if title:
            return _strip_chapter_prefix(title, chapter_id)
    try:
        contract = StoryGuidanceService().read_scene_contract(root, chapter_id)
    except (FileNotFoundError, ValueError):
        return ""
    return _strip_chapter_prefix(contract.title, chapter_id)


def _markdown_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped:
            return ""
    return ""


def _strip_chapter_prefix(title: str, chapter_id: str) -> str:
    value = title.strip()
    if not value:
        return ""
    ordinal = _chapter_ordinal(chapter_id)
    for prefix in (ordinal, f"第{int(chapter_id) if chapter_id.isdigit() else chapter_id}章"):
        if value.startswith(prefix):
            return value.removeprefix(prefix).strip(" -_　")
    return value


def _chapter_ordinal(chapter_id: str) -> str:
    if not chapter_id.isdigit():
        return chapter_id
    return f"第{_chinese_number(int(chapter_id))}章"


def _chinese_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value <= 10:
        return "十" if value == 10 else digits[value]
    if value < 20:
        return "十" + digits[value % 10]
    if value < 100:
        tens, ones = divmod(value, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        if rest == 0:
            return digits[hundreds] + "百"
        connector = "" if rest >= 10 else "零"
        return digits[hundreds] + "百" + connector + _chinese_number(rest)
    return str(value)


def _form_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _relative_file_exists(root: Path, relative_path: str) -> bool:
    try:
        return PathGuard(root).resolve(relative_path).is_file()
    except ValueError:
        return False


def _read_text_file_if_exists(root: Path, relative_path: str) -> str | None:
    path = PathGuard(root).resolve(relative_path)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _read_json_file_if_exists(root: Path, relative_path: str) -> object | None:
    text = _read_text_file_if_exists(root, relative_path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _latest_relative_file(root: Path, pattern: str) -> str:
    guard = PathGuard(root)
    matches = sorted(
        (path for path in guard.root.glob(pattern) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        return ""
    return matches[0].relative_to(guard.root).as_posix()


def _read_editorial_report_if_exists(root: Path, chapter_id: str) -> EditorialReviewReport | None:
    text = _read_text_file_if_exists(root, EditorialReviewService().report_path(chapter_id))
    if text is None:
        return None
    try:
        return EditorialReviewReport.model_validate_json(text)
    except ValueError:
        return None


def _memory_file_summaries(root: Path) -> list[dict[str, object]]:
    paths = [
        "memory/facts.json",
        "memory/open-loops.json",
        "memory/character-states.json",
        "memory/relationship-states.json",
        "memory/timeline-events.json",
        "memory/promises.json",
        "memory/emotional-arcs.json",
        "memory/chapter-summaries.json",
        "memory/writing-lessons.json",
        "memory/long-term-memory.json",
    ]
    summaries: list[dict[str, object]] = []
    for relative_path in paths:
        path = PathGuard(root).resolve(relative_path)
        data = _read_json_file_if_exists(root, relative_path)
        summaries.append(
            {
                "path": relative_path,
                "label": _source_display_label(relative_path),
                "description": _memory_domain_description(relative_path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "count": _memory_item_count(data),
            }
        )
    return summaries


def _knowledge_source_summaries(root: Path, limit: int = 6) -> list[dict[str, object]]:
    sources_root = PathGuard(root).resolve(KnowledgeBaseService.sources_dir)
    if not sources_root.is_dir():
        return []
    summaries: list[dict[str, object]] = []
    for path in sorted(sources_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        summaries.append(
            {
                "path": path.relative_to(PathGuard(root).root).as_posix(),
                "name": path.name,
                "bytes": path.stat().st_size,
            }
        )
        if len(summaries) >= limit:
            break
    return summaries


def _memory_domain_description(path: str) -> str:
    descriptions = {
        "memory/facts.json": "已经确认的设定、事实和不可违背的信息。",
        "memory/open-loops.json": "还没有回收的伏笔、悬念和问题。",
        "memory/character-states.json": "角色当前状态、目标、认知和限制。",
        "memory/relationship-states.json": "人物之间的压力、关系变化和未解情绪。",
        "memory/timeline-events.json": "已经发生的关键事件和顺序。",
        "memory/promises.json": "对读者许下的爽点、谜题和情绪承诺。",
        "memory/emotional-arcs.json": "角色情绪变化和长期情感轨迹。",
        "memory/chapter-summaries.json": "已写章节的摘要和承接线索。",
        "memory/writing-lessons.json": "系统从草稿反馈里学到的写作经验。",
        "memory/long-term-memory.json": "压缩后的长期主题、旧线索和跨章节记忆。",
    }
    return descriptions.get(path, "项目记忆内容。")


def _ui_memory_validation_issues(issues: object) -> list[dict[str, str]]:
    if not isinstance(issues, list):
        return []
    items: list[dict[str, str]] = []
    for issue in issues:
        path = str(_issue_value(issue, "path"))
        items.append(
            {
                "severityLabel": _severity_label(str(_issue_value(issue, "severity"))),
                "sourceLabel": _source_display_label(path),
                "typeLabel": _issue_type_label(str(_issue_value(issue, "type"))),
                "message": str(_issue_value(issue, "message")),
            }
        )
    return items


def _memory_context_ui_items(items: list[object]) -> list[dict[str, str]]:
    return [
        {
            "label": _source_display_label(str(getattr(item, "source", ""))),
            "category": _context_pack_source_category(str(getattr(item, "source", ""))),
            "reason": str(getattr(item, "reason", "")),
        }
        for item in items
    ]


def _memory_context_impact_items(items: list[object]) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for item in items:
        category = _context_pack_source_category(str(getattr(item, "source", "")))
        counts[category] = counts.get(category, 0) + 1
    order = ["角色资源", "知识来源", "写作经验", "伏笔与记忆", "章节与风格", "其他资料"]
    descriptions = {
        "角色资源": "约束人物动机、压力和出场状态，避免角色写偏。",
        "知识来源": "补足题材资料、世界规则和专有设定，避免细节失真。",
        "写作经验": "把复盘得到的写法提醒带入起草，减少重复犯错。",
        "伏笔与记忆": "带回承诺、悬念、事实和关系变化，保证长线不断。",
        "章节与风格": "承接本章要求、已写正文和作品风格，让节奏一致。",
        "其他资料": "作为补充材料参与本章起草。",
    }
    actions = {
        "角色资源": "检查人物压力",
        "知识来源": "核对题材资料",
        "写作经验": "带入写法提醒",
        "伏笔与记忆": "回收长线线索",
        "章节与风格": "承接章节节奏",
        "其他资料": "补充写作材料",
    }
    return [
        {
            "category": category,
            "count": str(counts[category]),
            "description": descriptions[category],
            "action": actions[category],
        }
        for category in order
        if counts.get(category, 0)
    ]


def _memory_item_count(data: object | None) -> int:
    if isinstance(data, list):
        return len(data)
    if not isinstance(data, dict):
        return 0
    for key in (
        "facts",
        "loops",
        "characters",
        "events",
        "promises",
        "chapters",
        "lessons",
        "topics",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _run_author_preview(markdown: str, empty_message: str) -> str:
    """Keep default run previews useful to authors without exposing raw plumbing."""
    return run_preview(markdown, empty_message)


def _run_author_status(status: object) -> str:
    return run_status_label(status)


def _revision_rerun_path_for_report(report: dict[str, object]) -> str:
    path = str(report.get("path") or "")
    if path.startswith("runs/revision-plan-"):
        return path
    raw = report.get("summary", {}).get("raw", {})
    if isinstance(raw, dict):
        source = str(raw.get("sourceRevisionPlan") or "")
        if source.startswith("runs/revision-plan-") and source.endswith(".json"):
            return source
    return ""


def _run_model_comparison_job(root: str, params: dict[str, object], job: JobRecord | None = None):
    request = ModelComparisonRequest(
        root=Path(root),
        startChapterId=str(params.get("startChapterId", "001")),
        chapterCount=int(params.get("chapterCount", 5)),
        baseProfileId=str(params.get("baseProfileId", "")),
        tunedProfileId=str(params.get("tunedProfileId", "")),
        referenceAgentId=str(params.get("referenceAgentId", "local-dry-run")),
        includeReferenceAgent=bool(params.get("includeReferenceAgent", True)),
    )
    report = ModelComparisonService().compare_five_chapter_profiles(
        request.root,
        start_chapter_id=request.startChapterId,
        chapter_count=request.chapterCount,
        base_profile_id=request.baseProfileId,
        tuned_profile_id=request.tunedProfileId,
        reference_agent_id=request.referenceAgentId,
        include_reference_agent=request.includeReferenceAgent,
    )
    if job is not None:
        JobController().update_progress(
            Path(root),
            job.jobId,
            {"comparisonId": report.comparisonId, "status": report.summary.bestStatus},
            "model comparison completed",
        )
    return {
        "comparisonId": report.comparisonId,
        "reportPath": ModelComparisonService().report_path(report.comparisonId),
        "report": report.model_dump(mode="json"),
    }


def _run_skill_job(root: str, params: dict[str, object], job: JobRecord | None = None):
    skill_id = str(params.get("skillId", "chapter-writer"))
    chapter_id = str(params.get("chapterId", "001"))
    chapter_title = str(params.get("chapterTitle", "Untitled Chapter"))
    agent_id = str(params.get("agentId", "local-dry-run"))
    model_profile = str(params.get("modelProfile", ""))
    return SkillRunner().run(
        SkillRunRequest(
            projectRoot=Path(root),
            skillId=skill_id,
            variables={"chapterId": chapter_id, "chapterTitle": chapter_title},
            agentId=agent_id,
            modelProfile=model_profile or None,
        ),
        cancel_check=(
            (lambda: JobController().is_cancel_requested(Path(root), job.jobId))
            if job is not None
            else None
        ),
    )


def _run_chapter_draft_job(root: str, params: dict[str, object], job: JobRecord | None = None):
    chapter_id = str(params.get("chapterId", "001"))
    chapter_title = str(params.get("chapterTitle", ""))
    agent_id = str(params.get("agentId", ""))
    model_profile = str(params.get("modelProfile", ""))
    prefer_trained_model = bool(params.get("preferTrainedModel", True))
    result = ChapterDraftService().draft_chapter(
        Path(root),
        chapter_id,
        chapter_title=chapter_title,
        agent_id=agent_id,
        model_profile=model_profile or None,
        prefer_trained_model=prefer_trained_model,
    )
    normalized = ProjectService().normalize_chapter_id(chapter_id)
    draft_path = result.outputPath or f"drafts/{normalized}.generated.md"
    evaluation = ChapterDraftService().evaluate_and_learn(
        Path(root),
        normalized,
        draft_path=draft_path,
    )
    quality = evaluation["quality"]
    editorial = evaluation["editorial"]
    gate = evaluation["gate"]
    if job is not None:
        JobController().update_progress(
            Path(root),
            job.jobId,
            {
                "chapterId": normalized,
                "draftPath": draft_path,
                "qualityScore": quality.score,
                "editorialScore": editorial.score,
                "gateStatus": gate.status,
                "gateScore": gate.score,
            },
            f"chapter {normalized} drafted and checked",
        )
    return {
        "runId": result.runId,
        "agentId": result.agentId,
        "modelProfile": result.modelProfile,
        "outputPath": result.outputPath,
        "qualityPath": f"runs/writing-quality-{normalized}.json",
        "editorialPath": f"runs/editorial-review-{normalized}.json",
        "gatePath": ChapterGateService().report_path(normalized),
        "lessonsPath": evaluation["lessonsPath"],
        "learning": evaluation["learning"],
        "quality": quality.model_dump(mode="json"),
        "editorial": editorial.model_dump(mode="json"),
        "gate": gate.model_dump(mode="json"),
    }


def _run_polish_job(root: str, params: dict[str, object], job: JobRecord | None = None):
    source_path = str(params.get("sourcePath", "chapters/001.md"))
    instruction = str(params.get("instruction", ""))
    agent_id = str(params.get("agentId", ""))
    model_profile = str(params.get("modelProfile", ""))
    prefer_trained_model = bool(params.get("preferTrainedModel", True))
    result = ChapterPolishService().polish_file(
        Path(root),
        source_path,
        instruction=instruction,
        agent_id=agent_id,
        model_profile=model_profile or None,
        prefer_trained_model=prefer_trained_model,
    )
    if job is not None:
        JobController().update_progress(
            Path(root),
            job.jobId,
            {
                "sourcePath": source_path,
                "outputPath": result.outputPath,
                "agentId": result.agentId,
                "modelProfile": result.modelProfile or "",
            },
            f"{source_path} polished",
        )
    return {
        "runId": result.runId,
        "skillId": result.skillId,
        "agentId": result.agentId,
        "modelProfile": result.modelProfile,
        "sourcePath": source_path,
        "outputPath": result.outputPath,
    }


def _run_local_training_job(root: str, params: dict[str, object], job: JobRecord | None = None):
    return LocalTrainingService().run_local_tuning(
        Path(root),
        backend=str(params.get("backend", "custom")),
        base_model=str(params.get("baseModel", "")),
        output_dir=str(params.get("outputDir", "models/adapters/latest")),
        model_profile_id=str(params.get("modelProfileId", "latest-trained")),
        inference_command_template=str(params.get("inferenceCommandTemplate", "")) or None,
        min_examples=int(params.get("minExamples", 1)),
        train_command=str(params.get("trainCommand", "")) or None,
        force=bool(params.get("force", False)),
        timeout_seconds=int(params.get("timeoutSeconds", 3600)),
        cancel_check=(
            (lambda: JobController().is_cancel_requested(Path(root), job.jobId))
            if job is not None
            else None
        ),
    )


def _run_five_chapter_regression_job(
    root: str,
    params: dict[str, object],
    job: JobRecord | None = None,
) -> dict[str, object]:
    project_root = Path(root)
    start = ProjectService().normalize_chapter_id(str(params.get("startChapterId", "001")))
    count = max(1, min(int(params.get("chapterCount", 5)), 10))
    if not start.isdigit():
        raise ValueError("start chapter id must be numeric")
    start_number = int(start)
    end = f"{start_number + count - 1:03d}"
    agent_id = str(params.get("agentId", ""))
    model_profile = str(params.get("modelProfile", ""))
    prefer_trained_model = bool(params.get("preferTrainedModel", True))
    scenario = str(params.get("regressionScenario", "")).strip()
    scenario_report: dict[str, object] | None = None
    if scenario:
        scenario_report = RegressionScenarioService().seed(
            project_root,
            start_chapter_id=start,
            chapter_count=count,
            scenario=scenario,
        )
    run_ids: list[str] = []
    chapter_evaluations: list[dict[str, object]] = []
    draft_service = ChapterDraftService()
    for index, chapter_number in enumerate(range(start_number, start_number + count), start=1):
        if job is not None and JobController().is_cancel_requested(project_root, job.jobId):
            raise RuntimeError("job cancellation requested")
        chapter_id = f"{chapter_number:03d}"
        contract = StoryGuidanceService().read_scene_contract(project_root, chapter_id)
        result = draft_service.draft_chapter(
            project_root,
            chapter_id,
            chapter_title=contract.title or f"Chapter {chapter_id}",
            agent_id=agent_id,
            model_profile=model_profile or None,
            prefer_trained_model=prefer_trained_model,
        )
        run_ids.append(result.runId)
        draft_path = result.outputPath or f"drafts/{chapter_id}.generated.md"
        evaluation = draft_service.evaluate_and_learn(
            project_root,
            chapter_id,
            draft_path=draft_path,
        )
        quality = evaluation["quality"]
        editorial = evaluation["editorial"]
        gate = evaluation["gate"]
        chapter_evaluations.append(
            {
                "chapterId": chapter_id,
                "draftPath": draft_path,
                "qualityScore": quality.score,
                "qualityIssueCount": len(quality.issues),
                "editorialScore": editorial.score,
                "editorialIssueCount": len(editorial.issues),
                "gateStatus": gate.status,
                "gateScore": gate.score,
                "gateIssueCount": len(gate.issues),
                "qualityPath": f"runs/writing-quality-{chapter_id}.json",
                "editorialPath": f"runs/editorial-review-{chapter_id}.json",
                "gatePath": ChapterGateService().report_path(chapter_id),
                "learning": evaluation["learning"],
            }
        )
        if job is not None:
            JobController().update_progress(
                project_root,
                job.jobId,
                {
                    "current": index,
                    "total": count,
                    "chapterId": chapter_id,
                    "qualityScore": quality.score,
                    "editorialScore": editorial.score,
                    "gateStatus": gate.status,
                    "gateScore": gate.score,
                },
                f"chapter {chapter_id} drafted and checked",
            )
    report = ChapterSequenceEvaluationService().evaluate(project_root, start, end)
    revision_plan = RevisionPlanService().build_for_sequence(project_root, report)
    return {
        "runIds": run_ids,
        "chapterEvaluations": chapter_evaluations,
        "report": report.model_dump(mode="json"),
        "reportPath": f"runs/sequence-evaluation-{start}-{end}.json",
        "revisionPlan": revision_plan,
        "revisionPlanPath": RevisionPlanService().report_path(start, end),
        "regressionScenario": scenario,
        "scenarioReport": scenario_report or {},
    }


def _rerun_revision_plan(
    root: Path,
    revision_plan_path: str,
    *,
    max_chapters: int = 3,
    agent_id: str = "",
    model_profile: str = "",
    prefer_trained_model: bool = True,
    job: JobRecord | None = None,
) -> dict[str, object]:
    revision_service = RevisionPlanService()
    plan = revision_service.read_plan(root, revision_plan_path)
    start = ProjectService().normalize_chapter_id(str(plan.get("startChapterId", "001")))
    end = ProjectService().normalize_chapter_id(str(plan.get("endChapterId", start)))
    briefs = revision_service.materialize_revision_briefs(
        root,
        plan,
        max_chapters=max(1, min(max_chapters, 10)),
    )
    draft_service = ChapterDraftService()
    rerun_chapters: list[dict[str, object]] = []
    for index, brief in enumerate(briefs, start=1):
        if job is not None and JobController().is_cancel_requested(root, job.jobId):
            raise RuntimeError("job cancellation requested")
        chapter_id = str(brief["chapterId"])
        try:
            contract = StoryGuidanceService().read_scene_contract(root, chapter_id)
            chapter_title = contract.title or f"Chapter {chapter_id}"
        except FileNotFoundError:
            chapter_title = f"Chapter {chapter_id}"
        result = draft_service.draft_chapter(
            root,
            chapter_id,
            chapter_title=chapter_title,
            agent_id=agent_id,
            model_profile=model_profile or None,
            prefer_trained_model=prefer_trained_model,
        )
        draft_path = result.outputPath or f"drafts/{chapter_id}.generated.md"
        evaluation = draft_service.evaluate_and_learn(
            root,
            chapter_id,
            draft_path=draft_path,
        )
        quality = evaluation["quality"]
        editorial = evaluation["editorial"]
        gate = evaluation["gate"]
        rerun_chapters.append(
            {
                "chapterId": chapter_id,
                "revisionBriefPath": brief["path"],
                "runId": result.runId,
                "agentId": result.agentId,
                "modelProfile": result.modelProfile,
                "draftPath": draft_path,
                "qualityScore": quality.score,
                "editorialScore": editorial.score,
                "gateStatus": gate.status,
                "gateScore": gate.score,
                "learning": evaluation["learning"],
            }
        )
        if job is not None:
            JobController().update_progress(
                root,
                job.jobId,
                {
                    "current": index,
                    "total": len(briefs),
                    "chapterId": chapter_id,
                    "qualityScore": quality.score,
                    "editorialScore": editorial.score,
                    "gateStatus": gate.status,
                    "gateScore": gate.score,
                },
                f"revision chapter {chapter_id} drafted and checked",
            )
    sequence = ChapterSequenceEvaluationService().evaluate(root, start, end)
    next_plan = revision_service.build_for_sequence(root, sequence)
    return {
        "sourceRevisionPlanPath": revision_plan_path,
        "revisionBriefs": briefs,
        "rerunChapters": rerun_chapters,
        "sequence": sequence.model_dump(mode="json"),
        "sequenceReportPath": ChapterSequenceEvaluationService().report_path(start, end),
        "revisionPlan": next_plan,
        "revisionPlanPath": revision_service.report_path(start, end),
        "recommendedNextAction": next_plan.get("recommendedNextAction", ""),
    }


def _auto_rerun_revision_plan(
    root: Path,
    revision_plan_path: str,
    *,
    max_chapters: int = 3,
    max_rounds: int = 1,
    agent_id: str = "",
    model_profile: str = "",
    prefer_trained_model: bool = True,
    job: JobRecord | None = None,
) -> dict[str, object]:
    revision_service = RevisionPlanService()
    current_plan_path = revision_plan_path
    rounds: list[dict[str, object]] = []
    stopped_reason = "max-rounds-reached"
    limit = max(1, min(max_rounds, 5))
    for round_number in range(1, limit + 1):
        if job is not None and JobController().is_cancel_requested(root, job.jobId):
            raise RuntimeError("job cancellation requested")
        plan = revision_service.read_plan(root, current_plan_path)
        priority_chapters = [
            str(chapter_id)
            for chapter_id in plan.get("priorityChapters", [])
            if str(chapter_id).strip()
        ]
        if str(plan.get("status") or "") == "ready":
            stopped_reason = "already-ready"
            break
        if not priority_chapters:
            stopped_reason = "no-priority-chapters"
            break
        if job is not None:
            JobController().update_progress(
                root,
                job.jobId,
                {
                    "round": round_number,
                    "maxRounds": limit,
                    "revisionPlanPath": current_plan_path,
                    "priorityChapters": priority_chapters[:max_chapters],
                },
                f"revision rerun round {round_number}",
            )
        result = _rerun_revision_plan(
            root,
            current_plan_path,
            max_chapters=max_chapters,
            agent_id=agent_id,
            model_profile=model_profile,
            prefer_trained_model=prefer_trained_model,
            job=job,
        )
        result["round"] = round_number
        rounds.append(result)
        current_plan_path = str(result["revisionPlanPath"])
        next_plan = result.get("revisionPlan", {})
        if isinstance(next_plan, dict) and str(next_plan.get("status") or "") == "ready":
            stopped_reason = "ready"
            break
    final_round = rounds[-1] if rounds else {}
    final_plan = final_round.get("revisionPlan") if isinstance(final_round, dict) else None
    if not isinstance(final_plan, dict):
        final_plan = revision_service.read_plan(root, current_plan_path)
    diagnosis: dict[str, object] | None = None
    diagnosis_path = ""
    if str(final_plan.get("status") or "") != "ready":
        source_result = {
            "roundCount": len(rounds),
            "maxRounds": limit,
            "stoppedReason": stopped_reason,
            "finalRevisionPlanPath": current_plan_path,
        }
        diagnosis = revision_service.build_failure_diagnosis(
            root,
            final_plan,
            source_result=source_result,
        )
        diagnosis_path = revision_service.diagnosis_path(
            str(final_plan.get("startChapterId") or "001"),
            str(final_plan.get("endChapterId") or final_plan.get("startChapterId") or "001"),
        )
    return {
        "sourceRevisionPlanPath": revision_plan_path,
        "rounds": rounds,
        "roundCount": len(rounds),
        "maxRounds": limit,
        "stoppedReason": stopped_reason,
        "finalRevisionPlanPath": current_plan_path,
        "finalRevisionPlan": final_plan,
        "finalStatus": final_plan.get("status", ""),
        "diagnosis": diagnosis,
        "diagnosisPath": diagnosis_path,
        "recommendedNextAction": final_plan.get("recommendedNextAction", ""),
    }


def _run_revision_rerun_job(
    root: str,
    params: dict[str, object],
    job: JobRecord | None = None,
) -> dict[str, object]:
    max_rounds = int(params.get("maxRounds", 1))
    if max_rounds > 1:
        return _auto_rerun_revision_plan(
            Path(root),
            str(params.get("revisionPlanPath", "")),
            max_chapters=int(params.get("maxChapters", 3)),
            max_rounds=max_rounds,
            agent_id=str(params.get("agentId", "")),
            model_profile=str(params.get("modelProfile", "")),
            prefer_trained_model=bool(params.get("preferTrainedModel", True)),
            job=job,
        )
    return _rerun_revision_plan(
        Path(root),
        str(params.get("revisionPlanPath", "")),
        max_chapters=int(params.get("maxChapters", 3)),
        agent_id=str(params.get("agentId", "")),
        model_profile=str(params.get("modelProfile", "")),
        prefer_trained_model=bool(params.get("preferTrainedModel", True)),
        job=job,
    )


def _revision_repair_result_path(package_id: str) -> str:
    slug = ProjectService()._normalize_slug(package_id, "repair package id")
    return f"runs/revision-repair-{slug}.json"


def _apply_revision_repair_package(
    root: Path,
    diagnosis_path: str,
    package_id: str,
) -> dict[str, object]:
    diagnosis_file = PathGuard(root).resolve(diagnosis_path)
    diagnosis = json.loads(diagnosis_file.read_text(encoding="utf-8"))
    if not isinstance(diagnosis, dict):
        raise ValueError("revision diagnosis must be a JSON object")
    packages = diagnosis.get("repairPackages", [])
    if not isinstance(packages, list):
        raise ValueError("revision diagnosis has no repairPackages list")
    package = next(
        (
            item
            for item in packages
            if isinstance(item, dict) and str(item.get("id") or "") == package_id
        ),
        None,
    )
    if package is None:
        raise FileNotFoundError(f"missing repair package: {package_id}")
    action = str(package.get("action") or "")
    priority_chapters = [
        ProjectService().normalize_chapter_id(str(chapter_id))
        for chapter_id in diagnosis.get("priorityChapters", [])
        if str(chapter_id).strip()
    ]
    applied_artifacts: list[str] = []
    skipped_reason = ""
    if action == "rebuild-context-pack":
        for chapter_id in priority_chapters:
            context_pack = ContextPackService().build_context_pack(root, chapter_id)
            applied_artifacts.append(context_pack.path)
    elif action == "validate-and-repair-memory":
        proposal = MemoryValidationService().apply_safe_repairs(root)
        applied_artifacts.extend(
            [
                MemoryValidationService.report_path,
                MemoryValidationService.repair_report_path,
            ]
        )
        applied_artifacts.extend(
            [operation.target for operation in proposal.operations if operation.status == "applied"]
        )
    elif action == "review-humanity-editor-findings":
        for chapter_id in priority_chapters:
            draft_path = f"drafts/{chapter_id}.generated.md"
            if not PathGuard(root).resolve(draft_path).is_file():
                continue
            EditorialReviewService().review_chapter(root, chapter_id, draft_path=draft_path)
            applied_artifacts.append(f"runs/editorial-review-{chapter_id}.json")
    else:
        skipped_reason = "repair package requires human review or a dedicated workflow"
    status = "applied" if applied_artifacts else "manual"
    result = {
        "schemaVersion": 1,
        "status": status,
        "diagnosisPath": diagnosis_path,
        "packageId": package_id,
        "package": package,
        "priorityChapters": priority_chapters,
        "appliedArtifacts": applied_artifacts,
        "skippedReason": skipped_reason,
        "recommendedNextAction": (
            "rerun-revision-or-sequence-evaluation"
            if status == "applied"
            else "complete-manual-repair-package"
        ),
    }
    output_path = _revision_repair_result_path(package_id)
    ProjectService().write_text(
        root,
        output_path,
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    result["outputPath"] = output_path
    return result


def _job_work_from_record(root: str, job: JobRecord):
    params = job.params
    if job.kind == "chapter-draft":
        return lambda new_job: _run_chapter_draft_job(root, params, new_job)
    if job.kind == "line-polish":
        return lambda new_job: _run_polish_job(root, params, new_job)
    if job.kind == "skill-run":
        return lambda new_job: _run_skill_job(root, params, new_job)
    if job.kind == "local-training":
        return lambda new_job: _run_local_training_job(root, params, new_job)
    if job.kind == "five-chapter-regression":
        return lambda new_job: _run_five_chapter_regression_job(root, params, new_job)
    if job.kind == "revision-rerun":
        return lambda new_job: _run_revision_rerun_job(root, params, new_job)
    if job.kind == "model-comparison":
        return lambda new_job: _run_model_comparison_job(root, params, new_job)
    raise ValueError(f"unsupported job kind: {job.kind}")


def _recover_project_jobs(root: Path) -> list[JobRecord]:
    return JobController().recover_jobs(
        root,
        lambda job: _job_work_from_record(str(root), job),
    )


def _sse_event(event: str, data: object) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _stream_job_events(
    root: Path,
    job_id: str,
    interval_seconds: float = 0.5,
    max_events: int = 200,
):
    terminal_statuses = {"completed", "failed", "cancelled", "interrupted"}
    last_payload = ""
    sent = 0
    while sent < max_events:
        try:
            job = JobController().get_job(root, job_id)
        except FileNotFoundError:
            yield _sse_event("error", {"message": "job not found", "jobId": job_id})
            return
        payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if payload != last_payload:
            yield _sse_event("job", _job_ui_payload(job))
            last_payload = payload
            sent += 1
        if job.status in terminal_statuses:
            yield _sse_event("end", {"jobId": job.jobId, "status": job.status})
            return
        time.sleep(max(0.05, interval_seconds))
    yield _sse_event("end", {"jobId": job_id, "status": "timeout"})


def _job_ui_payload(job: JobRecord) -> dict[str, object]:
    data = job.model_dump(mode="json")
    data["authorKind"] = _job_author_kind(job.kind)
    data["authorStatus"] = _job_author_status(job.status)
    data["authorId"] = "后台任务"
    data["authorProgress"] = _job_author_progress(job.progress)
    return data


def _job_author_kind(kind: object) -> str:
    return job_kind_label(kind)


def _job_author_status(status: object) -> str:
    return job_status_label(status)


def _job_author_progress(progress: object) -> str:
    return job_progress_label(progress)


def _today_next_action(
    *,
    draft_exists: bool,
    chapter_exists: bool,
    readiness_issues: int,
    gate_status: str,
    context_ready: bool,
    accepted: bool = False,
) -> str:
    if accepted and chapter_exists:
        return "本章已成为正文"
    if draft_exists:
        return "审稿并决定是否接收"
    if gate_status == "block":
        return "先处理诊断问题"
    if readiness_issues:
        return "先补开写准备"
    if not context_ready:
        return "先重建章节上下文"
    if chapter_exists:
        return "润色或继续审稿"
    return "让 AI 起草候选稿"


@app.get("/projects/relationships/graph")
def relationship_graph(root: Path) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return RelationshipGraphService().build_graph(project.root)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/relationships/edges/{edge_id}")
def relationship_edge_detail(edge_id: str, root: Path) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return RelationshipGraphService().edge_detail(project.root, edge_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/relationships/events/update")
def update_relationship_event(request: RelationshipEventUpdateRequest) -> dict[str, object]:
    try:
        project = ProjectService().open_project(request.root)
        return RelationshipGraphService().update_relationship_event(
            project.root,
            request.eventId,
            status=request.status,
            pressure=request.pressure,
            unresolved_emotion=request.unresolvedEmotion,
            evidence=request.evidence,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/memory/topics/{topic_id}")
def memory_topic_detail(
    topic_id: str,
    root: Path,
    chapterId: str | None = None,
) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        chapter_id = ProjectService().normalize_chapter_id(chapterId) if chapterId else None
        return MemoryTopicService().topic_detail(project.root, topic_id, chapter_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/create")
def create_project(request: CreateProjectRequest) -> dict[str, object]:
    project = ProjectService().create_project(
        path=request.path,
        title=request.title,
        language=request.language,
    )
    ProjectPlanService().write_plan(
        project.root,
        target_chapter_count=request.targetChapterCount,
        target_words_per_chapter=request.targetWordsPerChapter,
        platform=request.platform,
    )
    WorkspaceRegistryService().register_project(project.root)
    payload = project.model_dump(mode="json")
    payload["plan"] = ProjectPlanService().summarize(project.root).model_dump(mode="json")
    return payload


@app.post("/projects/create-guided")
def create_guided_project(request: BeginnerProjectCreateRequest) -> dict[str, object]:
    result = BeginnerGuidanceService().create_guided_project(
        BeginnerProjectInput.model_validate(request.model_dump())
    )
    ProjectPlanService().write_plan(
        result.root,
        target_chapter_count=request.targetChapterCount,
        target_words_per_chapter=request.chapterWordTarget,
        platform=request.platform,
        cadence="日更优先",
    )
    WorkspaceRegistryService().register_project(result.root)
    payload = result.model_dump(mode="json")
    payload["plan"] = ProjectPlanService().summarize(result.root).model_dump(mode="json")
    return payload


@app.get("/projects/workspace")
def workspace_projects(page: int = 1, perPage: int = 8) -> dict[str, object]:
    return WorkspaceRegistryService().list_project_page(page=page, per_page=perPage)


@app.get("/projects/plan")
def project_plan(root: Path) -> dict[str, object]:
    project = ProjectService().open_project(root)
    return ProjectPlanService().summarize(project.root).model_dump(mode="json")


@app.post("/projects/plan")
def update_project_plan(request: ProjectPlanUpdateRequest) -> dict[str, object]:
    project = ProjectService().open_project(request.root)
    ProjectPlanService().write_plan(
        project.root,
        target_chapter_count=request.targetChapterCount,
        target_words_per_chapter=request.targetWordsPerChapter,
        platform=request.platform,
        cadence=request.cadence,
        notes=request.notes,
    )
    WorkspaceRegistryService().register_project(project.root)
    return ProjectPlanService().summarize(project.root).model_dump(mode="json")


@app.get("/projects/tree")
def project_tree(root: Path) -> list[str]:
    try:
        project = ProjectService().open_project(root)
        return ProjectService().list_files(project.root)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/runs")
def project_runs(root: Path) -> list[dict[str, object]]:
    try:
        project = ProjectService().open_project(root)
        return ProjectService().list_runs(project.root)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/runs/{run_id}")
def project_run_detail(root: Path, run_id: str) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return ProjectService().get_run(project.root, run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/jobs")
def project_jobs(root: Path) -> list[dict[str, object]]:
    try:
        project = ProjectService().open_project(root)
        _recover_project_jobs(project.root)
        return [
            job.model_dump(mode="json") for job in JobController().list_jobs(project.root, limit=50)
        ]
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/jobs/{job_id}/events")
def project_job_events(root: Path, job_id: str) -> StreamingResponse:
    try:
        project = ProjectService().open_project(root)
        _recover_project_jobs(project.root)
        JobController().get_job(project.root, job_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        _stream_job_events(project.root, job_id),
        media_type="text/event-stream",
    )


@app.get("/projects/jobs/{job_id}")
def project_job_detail(root: Path, job_id: str) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        _recover_project_jobs(project.root)
        return JobController().get_job(project.root, job_id).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/jobs/{job_id}/cancel")
def project_job_cancel(root: Path, job_id: str) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return JobController().request_cancel(project.root, job_id).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/jobs/{job_id}/retry")
def project_job_retry(root: Path, job_id: str) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        original = JobController().get_job(project.root, job_id)
        return (
            JobController()
            .retry_job(
                project.root,
                job_id,
                _job_work_from_record(str(project.root), original),
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/jobs/recover")
def project_jobs_recover(root: Path) -> list[dict[str, object]]:
    try:
        project = ProjectService().open_project(root)
        return [job.model_dump(mode="json") for job in _recover_project_jobs(project.root)]
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/characters")
def project_characters(root: Path) -> list[str]:
    try:
        project = ProjectService().open_project(root)
        return ProjectService().list_characters(project.root)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/characters")
def create_character(request: CharacterCreateRequest) -> dict[str, str]:
    try:
        path = ProjectService().create_character(
            request.root,
            character_id=request.characterId,
            name=request.name,
        )
        return {"status": "ok", "path": path}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/timeline/events")
def project_timeline_events(root: Path) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return ProjectService().read_timeline_events(project.root).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/timeline/sync")
def sync_project_timeline(root: Path) -> dict[str, object]:
    try:
        project = ProjectService().open_project(root)
        return (
            ProjectService()
            .sync_timeline_events_from_markdown(project.root)
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/scene-contract")
def create_scene_contract(request: SceneContractCreateRequest) -> dict[str, object]:
    try:
        contract = StoryGuidanceService().create_scene_contract(
            request.root,
            request.chapterId,
            title=request.title,
        )
        return contract.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/projects/scene-contract")
def save_scene_contract(request: SceneContractSaveRequest) -> dict[str, object]:
    try:
        StoryGuidanceService().write_scene_contract(request.root, request.contract)
        return {"status": "ok", "path": f"story/chapter-briefs/{request.contract.chapterId}.json"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/scene-contract")
def read_scene_contract(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return StoryGuidanceService().read_scene_contract(root, chapterId).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/readiness")
def check_readiness(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return StoryGuidanceService().check_readiness(root, chapterId).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/context-pack")
def build_context_pack(request: ContextPackBuildRequest) -> dict[str, object]:
    try:
        return (
            ContextPackService()
            .build_context_pack(
                request.root,
                request.chapterId,
                max_estimated_tokens=request.maxEstimatedTokens,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/context-pack")
def read_context_pack(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return ContextPackService().read_context_pack(root, chapterId).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/file")
def read_file(root: Path, path: str) -> dict[str, str]:
    try:
        content = ProjectService().read_text(root, path)
        return {"path": path, "content": content}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/projects/file")
def write_file(root: Path, request: FileRequest) -> dict[str, str]:
    try:
        ProjectService().write_text(root, request.path, request.content)
        if request.path == "timeline.md":
            ProjectService().sync_timeline_events_from_markdown(root)
        return {"status": "ok", "path": request.path}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/chapter")
def create_chapter(request: ChapterCreateRequest) -> dict[str, str]:
    try:
        path = ProjectService().create_chapter(
            request.root,
            chapter_id=request.chapterId,
            title=request.title,
        )
        return {"status": "ok", "path": path}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/draft/accept")
def accept_draft(request: DraftAcceptRequest) -> dict[str, object]:
    try:
        target_chapter_id = (
            ProjectService()
            .chapter_path_for_draft(request.draftPath)
            .removeprefix("chapters/")
            .removesuffix(".md")
            if request.chapterId is None
            else ProjectService().normalize_chapter_id(request.chapterId)
        )
        gate = ChapterGateService().check_chapter(
            request.root,
            target_chapter_id,
            draft_path=request.draftPath,
            include_review=False,
        )
        if gate.status == "block" and not request.force:
            recovery = GateRecoveryService().recovery_plan(gate)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "chapter gate blocked draft acceptance",
                    "gatePath": ChapterGateService().report_path(target_chapter_id),
                    "score": gate.score,
                    "issues": [issue.model_dump(mode="json") for issue in gate.issues],
                    "recovery": recovery,
                },
            )
        path = ProjectService().accept_draft(
            request.root,
            draft_path=request.draftPath,
            chapter_id=request.chapterId,
        )
        chapter_id = path.removeprefix("chapters/").removesuffix(".md")
        review_path = ""
        patch_path = ""
        try:
            patch = PostChapterService().build_review_and_patch(request.root, chapter_id)
        except FileNotFoundError:
            pass
        else:
            review_path = patch.sourceReview
            patch_path = PostChapterService().patch_path(chapter_id)
        return {
            "status": "ok",
            "path": path,
            "reviewPath": review_path,
            "patchPath": patch_path,
            "gateStatus": gate.status,
            "gatePath": ChapterGateService().report_path(chapter_id),
        }
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/context-pack/diff")
def diff_context_pack(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return ContextPackService().context_pack_diff(root, chapterId)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/chapter/review")
def review_chapter(request: PostChapterRequest) -> dict[str, object]:
    try:
        patch = PostChapterService().build_review_and_patch(request.root, request.chapterId)
        return patch.model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/chapter/review")
def read_chapter_review(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return PostChapterService().read_review(root, chapterId).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/canon-patch")
def read_canon_patch(root: Path, chapterId: str) -> dict[str, object]:
    try:
        return PostChapterService().read_canon_patch(root, chapterId).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/canon-patch/apply")
def apply_canon_patch(request: PostChapterRequest) -> dict[str, object]:
    try:
        return (
            PostChapterService()
            .apply_canon_patch(request.root, request.chapterId)
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/canon-patch/accept")
def accept_canon_patch(request: CanonPatchAcceptRequest) -> dict[str, object]:
    try:
        return (
            PostChapterService()
            .accept_canon_patch(
                request.root,
                request.chapterId,
                operation_ids=request.operationIds,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/canon-patch/operations")
def update_canon_patch_operations(request: CanonPatchUpdateRequest) -> dict[str, object]:
    try:
        return (
            PostChapterService()
            .update_canon_patch_operations(
                request.root,
                request.chapterId,
                request.operationIds,
                _canon_patch_status(request.status),
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _canon_patch_status(status: str) -> str:
    value = (status or "").strip()
    if value not in {"accepted", "rejected", "deferred"}:
        raise ValueError(f"unsupported canon patch status: {value}")
    return value


@app.post("/projects/continuity/check")
def check_continuity(request: ContinuityCheckRequest) -> dict[str, object]:
    try:
        return (
            ContinuityService()
            .check_draft(
                request.root,
                request.chapterId,
                draft_path=request.draftPath,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/chapter/gate")
def check_chapter_gate(request: ChapterGateRequest) -> dict[str, object]:
    try:
        return (
            ChapterGateService()
            .check_chapter(
                request.root,
                request.chapterId,
                draft_path=request.draftPath,
                editorial_profile_id=request.editorialProfileId,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/chapter/gate/recovery")
def chapter_gate_recovery(
    root: Path,
    chapterId: str,
    draftPath: str | None = None,
) -> dict[str, object]:
    try:
        chapter_id = ProjectService().normalize_chapter_id(chapterId)
        source = draftPath or f"drafts/{chapter_id}.generated.md"
        gate = ChapterGateService().check_chapter(
            root,
            chapter_id,
            draft_path=source,
            include_draft=True,
            include_review=False,
        )
        navigation = IssueNavigationService().build_navigation(chapter_id, {"gate": gate})
        return GateRecoveryService().recovery_plan(gate, navigation)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/chapter/issues/navigation")
def chapter_issue_navigation(
    root: Path,
    chapterId: str,
    draftPath: str | None = None,
) -> dict[str, object]:
    try:
        chapter_id = ProjectService().normalize_chapter_id(chapterId)
        source = draftPath or f"drafts/{chapter_id}.generated.md"
        quality = None
        editorial = None
        gate = None
        if PathGuard(root).resolve(source).is_file():
            quality = WritingQualityService().evaluate_chapter(
                root,
                chapter_id,
                draft_path=source,
            )
            editorial = _read_editorial_report_if_exists(root, chapter_id)
            if editorial is None or editorial.source != source:
                editorial = EditorialReviewService().review_chapter(
                    root,
                    chapter_id,
                    draft_path=source,
                )
            gate = ChapterGateService().check_chapter(
                root,
                chapter_id,
                draft_path=source,
                include_draft=True,
                include_review=False,
            )
        return IssueNavigationService().build_navigation(
            chapter_id,
            {"quality": quality, "editorial": editorial, "gate": gate},
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/writing-quality/check")
def check_writing_quality(request: WritingQualityRequest) -> dict[str, object]:
    try:
        return (
            WritingQualityService()
            .evaluate_chapter(
                request.root,
                request.chapterId,
                draft_path=request.draftPath,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/editorial-review/check")
def check_editorial_review(request: EditorialReviewRequest) -> dict[str, object]:
    try:
        return (
            EditorialReviewService()
            .review_chapter(
                request.root,
                request.chapterId,
                draft_path=request.draftPath,
                backend=request.backend,
                command_template=request.commandTemplate,
                timeout_seconds=request.timeoutSeconds,
                profile_id=request.profileId,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/sequence/evaluate")
def evaluate_sequence(request: SequenceEvaluationRequest) -> dict[str, object]:
    try:
        report = ChapterSequenceEvaluationService().evaluate(
            request.root,
            request.startChapterId,
            request.endChapterId,
            prefer_drafts=request.preferDrafts,
        )
        revision_plan = RevisionPlanService().build_for_sequence(request.root, report)
        result = report.model_dump(mode="json")
        result["revisionPlan"] = revision_plan
        result["revisionPlanPath"] = RevisionPlanService().report_path(
            report.startChapterId,
            report.endChapterId,
        )
        return result
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/revision/rerun")
def rerun_revision_plan(request: RevisionRerunRequest) -> dict[str, object]:
    try:
        if request.maxRounds <= 1:
            return _rerun_revision_plan(
                request.root,
                request.revisionPlanPath,
                max_chapters=request.maxChapters,
                agent_id=request.agentId,
                model_profile=request.modelProfile,
                prefer_trained_model=request.preferTrainedModel,
            )
        return _auto_rerun_revision_plan(
            request.root,
            request.revisionPlanPath,
            max_chapters=request.maxChapters,
            max_rounds=request.maxRounds,
            agent_id=request.agentId,
            model_profile=request.modelProfile,
            prefer_trained_model=request.preferTrainedModel,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/plot/direction")
def suggest_plot_direction(request: PlotDirectionRequest) -> dict[str, object]:
    try:
        return (
            PlotDirectionService()
            .suggest_directions(
                request.root,
                request.chapterId,
                request.userIntent,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/plot/direction/apply")
def apply_plot_direction(request: PlotDirectionApplyRequest) -> dict[str, object]:
    try:
        return (
            PlotDirectionService()
            .apply_direction(
                request.root,
                request.chapterId,
                request.optionId,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/diff")
def diff_files(request: DiffRequest) -> dict[str, str]:
    try:
        project = ProjectService().open_project(request.root)
        left_text = ProjectService().read_text(project.root, request.leftPath)
        right_text = ProjectService().read_text(project.root, request.rightPath)
        diff_text = TextDiffService().unified(
            left_text,
            right_text,
            request.leftPath,
            request.rightPath,
        )
        return {"diff": diff_text}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/skill/run")
def run_skill(request: SkillRunRequest) -> dict[str, object]:
    try:
        return SkillRunner().run(request).model_dump(mode="json")
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/polish")
def polish_file(request: PolishRequest) -> dict[str, object]:
    try:
        return (
            ChapterPolishService()
            .polish_file(
                request.root,
                request.sourcePath,
                instruction=request.instruction,
                agent_id=request.agentId,
                model_profile=request.modelProfile or None,
                prefer_trained_model=request.preferTrainedModel,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/models/writing")
def list_writing_models(root: Path) -> dict[str, object]:
    try:
        return WritingModelService().read_registry(root).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/writing")
def register_writing_model(request: WritingModelRegisterRequest) -> dict[str, object]:
    try:
        profile = WritingModelService().register_profile(
            request.root,
            profile_id=request.profileId,
            base_model=request.baseModel,
            adapter_path=request.adapterPath,
            command_template=request.commandTemplate,
            label=request.label,
            timeout_seconds=request.timeoutSeconds,
            set_default=request.setDefault,
        )
        return profile.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/writing/default")
def set_default_writing_model(request: WritingModelDefaultRequest) -> dict[str, object]:
    try:
        return (
            WritingModelService()
            .set_default_profile(
                request.root,
                request.profileId,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/models/editorial")
def list_editorial_profiles(root: Path) -> dict[str, object]:
    try:
        service = EditorialProfileService()
        registry = service.read_registry(root).model_dump(mode="json")
        registry["promptPresets"] = [
            preset.model_dump(mode="json") for preset in service.list_prompt_presets()
        ]
        return registry
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/editorial")
def register_editorial_profile(request: EditorialProfileRegisterRequest) -> dict[str, object]:
    try:
        profile = EditorialProfileService().register_profile(
            request.root,
            profile_id=request.profileId,
            backend=request.backend,
            command_template=request.commandTemplate,
            label=request.label,
            reviewer=request.reviewer,
            prompt_preset=request.promptPreset,
            style_profile_path=request.styleProfilePath,
            rubric=request.rubric,
            timeout_seconds=request.timeoutSeconds,
            set_default=request.setDefault,
        )
        return profile.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/editorial/default")
def set_default_editorial_profile(
    request: EditorialProfileDefaultRequest,
) -> dict[str, object]:
    try:
        return (
            EditorialProfileService()
            .set_default_profile(
                request.root,
                request.profileId,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/style-profiles")
def list_style_profiles() -> dict[str, object]:
    service = StyleProfileService()
    return {
        "profiles": [
            profile.model_dump(mode="json") for profile in service.list_builtin_profiles()
        ],
        "plannedSlots": service.list_planned_profile_slots(),
        "coverageCatalog": service.list_coverage_catalog(),
        "templatePacks": service.list_template_packs(),
        "maintenancePolicy": service.template_maintenance_policy(),
    }


@app.get("/projects/style-profiles/planned/{slot_id}/draft")
def draft_style_profile_from_planned_slot(slot_id: str) -> dict[str, object]:
    try:
        return (
            StyleProfileService()
            .draft_profile_from_planned_slot(
                slot_id,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/style-profiles/apply")
def apply_style_profile(request: StyleProfileApplyRequest) -> dict[str, object]:
    try:
        return (
            StyleProfileService()
            .write_project_profile_from_builtin(
                request.root,
                request.profileId,
                project_profile_id=request.projectProfileId,
                label=request.label,
                relative_path=request.path,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/style-profiles/promotion/evaluate")
def evaluate_style_profile_promotion(
    request: StyleProfilePromotionRequest,
) -> dict[str, object]:
    try:
        return StyleProfilePromotionService().evaluate_candidate(
            request.root,
            request.candidateProfilePath,
            request.startChapterId,
            request.endChapterId,
            prefer_drafts=request.preferDrafts,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/style-profiles/promotion/export")
def export_promoted_style_profile(
    request: StyleProfilePromotionExportRequest,
) -> dict[str, object]:
    try:
        return StyleProfilePromotionService().export_promotable_profile(
            request.root,
            request.promotionReportPath,
            output_path=request.outputPath,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/style-profiles/exported/validate")
def validate_exported_style_profile(
    request: StyleProfileExportValidationRequest,
) -> dict[str, object]:
    try:
        return StyleProfilePromotionService().validate_exported_profile(
            request.root,
            request.exportedProfilePath,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/compare")
def compare_writing_models(request: ModelComparisonRequest) -> dict[str, object]:
    try:
        return (
            ModelComparisonService()
            .compare_five_chapter_profiles(
                request.root,
                start_chapter_id=request.startChapterId,
                chapter_count=request.chapterCount,
                base_profile_id=request.baseProfileId,
                tuned_profile_id=request.tunedProfileId,
                reference_agent_id=request.referenceAgentId,
                include_reference_agent=request.includeReferenceAgent,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/models/compare/promote")
def promote_model_comparison(
    request: ModelComparisonPromotionRequest,
) -> dict[str, object]:
    try:
        return (
            ModelComparisonService()
            .promote_tuned_profile_from_report(
                request.root,
                request.comparisonReportPath,
            )
            .model_dump(mode="json")
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/export")
def export_project(request: ExportRequest) -> dict[str, str]:
    try:
        output = ExportService().export(request.root, request.format)
        return {"status": "ok", "path": output.as_posix()}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/export/training-data")
def export_training_data(request: ExportRequest) -> dict[str, str]:
    try:
        output = ExportService().export_writing_training_jsonl(request.root)
        return {"status": "ok", "path": output.as_posix()}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/export/training-readiness")
def export_training_readiness(request: ExportRequest) -> dict[str, object]:
    try:
        return ExportService().training_readiness(request.root).model_dump(mode="json")
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
