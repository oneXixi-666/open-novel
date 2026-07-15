from __future__ import annotations

import json
import os
import re
import tempfile
import time
from hashlib import sha1
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from open_novel.agents.cli_adapters import CliAgentService
from open_novel.core.ai_runtime import (
    AIAccountRepository,
    AIProtocol,
    AIRole,
    AIRuntimeService,
)
from open_novel.core.book_analysis import BookAnalysisService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.chapter_progress import calculate_chapter_progress
from open_novel.core.context_pack import ContextPackService
from open_novel.core.continuity import ContinuityService
from open_novel.core.diff import TextDiffService
from open_novel.core.editorial_profile import EditorialProfileService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.gate_recovery import GateRecoveryService
from open_novel.core.generation_artifacts import GenerationExecutionError
from open_novel.core.ideation_session import IdeationSessionService
from open_novel.core.issue_navigation import IssueNavigationService
from open_novel.core.jobs import JobController
from open_novel.core.knowledge_base import KnowledgeBaseService
from open_novel.core.local_training import LocalTrainingService
from open_novel.core.memory_topic import MemoryTopicService
from open_novel.core.model_comparison import ModelComparisonService
from open_novel.core.model_library import ModelLibraryService
from open_novel.core.models import ContextPack, NovelMetadata, SceneContract, utc_now
from open_novel.core.plot_direction import PlotDirectionService
from open_novel.core.polishing import ChapterPolishService
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.project_plan import ProjectPlanService
from open_novel.core.relationship_graph import RelationshipGraphService
from open_novel.core.revision_plan import RevisionPlanService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import StyleProfileService
from open_novel.core.workbench_repository import WorkbenchRepository
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.core.writing_assets import WritingAssetService
from open_novel.core.writing_formula import WritingFormulaService
from open_novel.core.writing_model import WritingModelService
from open_novel.core.writing_quality import WritingQualityService
from open_novel.exporters.service import ExportService
from open_novel.security.path_guard import PathGuard
from open_novel.web.app import app
from open_novel.web.workbench_calibration import WorkbenchCalibrationService
from open_novel.web.workbench_exports import WorkbenchExportService
from open_novel.web.workbench_generation import WorkbenchGenerationService
from open_novel.web.workbench_materials import WorkbenchMaterialService
from open_novel.web.workbench_model_library import WorkbenchModelLibraryService
from open_novel.web.workbench_models import WorkbenchModelService
from open_novel.web.workbench_profiles import WorkbenchProfileService
from open_novel.web.workbench_reviews import WorkbenchReviewService
from open_novel.web.workbench_runs import WorkbenchRunService
from open_novel.web.workbench_training import WorkbenchTrainingService

MaterialType = Literal["人物", "地点", "势力", "关系", "设定", "时间线", "伏笔", "写法"]
ExportKind = Literal["正文", "训练数据", "审稿报告", "资料包"]
GenerationMode = Literal["full_auto", "stage_confirm", "chapter_confirm", "deep_control"]
GenerationStatus = Literal["idle", "running", "waiting_confirm", "blocked", "paused", "completed"]
GenerationStage = Literal[
    "architecture",
    "blueprint",
    "contract",
    "context",
    "draft",
    "gate",
    "review",
    "accept",
    "memory",
    "next_chapter",
]


class NewBookDraft(BaseModel):
    title: str = ""
    platform: str = ""
    styleProfileId: str = "generic-web-serial"
    styleProfileLabel: str = "通用网文连载"
    genre: str = ""
    tagline: str = ""
    firstChapterTitle: str = ""
    seed: str = ""


class CreateBookRequest(BaseModel):
    draft: NewBookDraft
    existingBookCount: int = 0
    defaultModelId: str = ""
    interventionMode: GenerationMode = "stage_confirm"
    batchTarget: int = Field(default=1, ge=1, le=20)
    targetChapterCount: int = Field(default=200, ge=1, le=2000)
    targetWordsPerChapter: int = Field(default=2500, ge=500, le=20000)
    targetChaptersPerPlot: int = Field(default=10, ge=1, le=100)
    startGeneration: bool = False


class UpdateBookSettingsRequest(BaseModel):
    title: str
    genre: str
    tagline: str = ""
    styleProfileId: str
    styleProfileLabel: str = ""


class AIAccountRequest(BaseModel):
    name: str
    purpose: str = ""
    baseUrl: str
    apiKey: str | None = None
    model: str
    protocol: AIProtocol = "responses"
    maxContextTokens: int = Field(default=128000, ge=2048, le=2_000_000)
    enabled: bool = True


class AIAccountConnectionRequest(BaseModel):
    accountId: str = ""
    baseUrl: str
    apiKey: str | None = None
    model: str = ""
    protocol: AIProtocol = "responses"
    maxContextTokens: int = Field(default=128000, ge=2048, le=2_000_000)


class AIRoleBindingsRequest(BaseModel):
    writingAccountId: str = ""
    reviewAccountId: str = ""


class MaterialPayload(BaseModel):
    id: str
    bookId: str
    type: MaterialType
    title: str
    summary: str = ""
    influence: str = ""
    related: list[str] = Field(default_factory=list)
    confidence: int = 60
    details: dict[str, str] | None = None


class SetBookModelRequest(BaseModel):
    bookId: str
    modelId: str


class ValidateModelRequest(BaseModel):
    modelId: str


class ModelCompareRequest(BaseModel):
    bookId: str = ""
    baseProfileId: str = ""
    tunedProfileId: str = ""
    startChapterId: str = "001"
    chapterCount: int = 5
    includeReferenceAgent: bool = True
    referenceAgentId: str = "local-dry-run"


class ModelTrainingRunRequest(BaseModel):
    bookId: str = ""
    backend: Literal["custom", "mlx-lm", "llama-factory"] = "custom"
    baseModel: str = ""
    outputDir: str = "models/adapters/latest"
    modelProfileId: str = "latest-trained"
    inferenceCommandTemplate: str = ""
    minExamples: int | None = None
    trainCommand: str = ""
    force: bool = False
    timeoutSeconds: int = 3600


class ModelLibraryCreateRequest(BaseModel):
    name: str
    categoryId: str
    purpose: str = "综合模仿"
    description: str = ""


class ModelCategoryCreateRequest(BaseModel):
    label: str


class ModelBookSourceItem(BaseModel):
    bookId: str
    chapterId: str


class ModelBookSourcesRequest(BaseModel):
    items: list[ModelBookSourceItem] = Field(default_factory=list)


class ModelLibraryTrainingRequest(BaseModel):
    sourceIds: list[str] = Field(default_factory=list)
    bookId: str = ""
    backendId: str = "auto"
    confirm: bool = False


class WritingModelManageRequest(BaseModel):
    bookId: str = ""
    profileId: str
    label: str = ""
    baseModel: str = ""
    adapterPath: str = ""
    commandTemplate: str = ""
    timeoutSeconds: int = 600
    setDefault: bool = False
    notes: str = ""


class WritingModelDefaultRequest(BaseModel):
    bookId: str = ""
    profileId: str


class EditorialModelManageRequest(BaseModel):
    bookId: str = ""
    profileId: str
    backend: Literal["local", "command"] = "local"
    commandTemplate: str = ""
    label: str = ""
    reviewer: str = ""
    promptPreset: str = "generic-humanity"
    styleProfilePath: str = "story/style-profile.json"
    rubric: list[str] = Field(default_factory=list)
    timeoutSeconds: int = 600
    setDefault: bool = False
    notes: str = ""


class EditorialModelDefaultRequest(BaseModel):
    bookId: str = ""
    profileId: str


class ApplyStyleProfileRequest(BaseModel):
    bookId: str = ""
    profileId: str
    projectProfileId: str = ""
    label: str = ""
    path: str = "story/style-profile.json"


class PromoteModelCompareRequest(BaseModel):
    bookId: str = ""
    comparisonReportPath: str


class ApplyChapterDraftRequest(BaseModel):
    bookId: str
    chapterId: str
    nextContent: str


class UpdateChapterPlanningRequest(BaseModel):
    bookId: str
    chapterId: str
    tasks: list[str] = Field(default_factory=list)
    plotPoints: list[str] = Field(default_factory=list)


class LinkChapterMaterialsRequest(BaseModel):
    bookId: str
    chapterId: str
    materialIds: list[str] = Field(default_factory=list)
    mode: Literal["append", "replace"] = "append"


class ChapterPrepareRequest(BaseModel):
    bookId: str
    chapterId: str


class ChapterGateRequest(BaseModel):
    bookId: str
    chapterId: str


class AcceptChapterRequest(BaseModel):
    bookId: str
    chapterId: str
    force: bool = False


class ApplyReviewRepairRequest(BaseModel):
    bookId: str
    chapterId: str
    reviewId: str
    repairText: str


class RunReviewsRequest(BaseModel):
    bookId: str
    chapterId: str = ""


class PatchReviewRequest(BaseModel):
    bookId: str
    reviewId: str
    status: Literal["待处理", "处理中", "已确认"]


class ListChapterMemoryUpdatesRequest(BaseModel):
    bookId: str
    chapterId: str


class ApplyMemoryUpdateRequest(BaseModel):
    bookId: str
    chapterId: str = ""


class UpdateRelationshipEventRequest(BaseModel):
    bookId: str
    type: str = ""
    status: str
    pressure: str = ""
    unresolvedEmotion: str = ""
    evidence: list[str] | None = None


class MaintenanceActionRequest(BaseModel):
    bookId: str
    chapterId: str = ""


class ExportWorkbenchRequest(BaseModel):
    bookId: str
    kind: ExportKind
    range: str = "全书"
    rangeStart: str = ""
    rangeEnd: str = ""
    trainingChapterIds: list[str] = Field(default_factory=list)


class AgentAssistRequest(BaseModel):
    bookId: str
    scope: Literal["book", "chapter", "material", "review", "model"]
    action: str
    input: str = ""
    chapterId: str | None = None
    materialId: str | None = None
    materialType: MaterialType | None = None
    currentMaterial: MaterialPayload | None = None
    reviewId: str | None = None
    modelId: str | None = None
    bypassCache: bool = False


class ChapterContractUpdateRequest(BaseModel):
    bookId: str = ""
    chapterId: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)


class GenerationModeRequest(BaseModel):
    bookId: str = ""
    interventionMode: GenerationMode = "stage_confirm"
    batchTarget: int = Field(default=1, ge=1, le=20)
    autoStepLimit: int | None = Field(default=None, ge=1, le=148)


class GenerationActionRequest(BaseModel):
    bookId: str = ""
    optionId: str = ""
    requestId: str = ""


class GenerationCandidateSelectRequest(BaseModel):
    bookId: str = ""
    candidateId: str
    requestId: str = ""


class GenerationTakeoverRequest(BaseModel):
    bookId: str = ""
    target: Literal["writing", "library", "review"] = "writing"


class VolumeGoalUpdateRequest(BaseModel):
    bookId: str = ""
    volumeId: str
    goal: str
    chapterRange: str = ""


class ChapterLandingUpdateRequest(BaseModel):
    bookId: str = ""
    chapterId: str
    goal: str
    hook: str
    promiseProgression: str
    logicDependencies: list[str] = Field(default_factory=list)
    segmentId: str = ""


class LongFormReplanRequest(BaseModel):
    bookId: str = ""
    chapterId: str = ""


class ProjectPlanUpdateRequest(BaseModel):
    bookId: str = ""
    targetChapterCount: int = Field(ge=1, le=2000)
    targetWordsPerChapter: int = Field(ge=500, le=20000)
    targetChaptersPerPlot: int = Field(ge=1, le=100)


class CalibrationAnnotationRequest(BaseModel):
    bookId: str = ""
    chapterId: str
    label: Literal["acceptable", "repair", "block"]
    note: str = ""


class QualityThresholdConfigRequest(BaseModel):
    bookId: str = ""
    min_chars_blocker: int = 360
    min_chars_medium: int = 600
    max_chars_medium: int = 9000
    similarity_blocker: float = 0.86
    similarity_high: float = 0.72
    choice_marker_min: int = 2
    conflict_marker_min: int = 2
    emotion_marker_min: int = 1
    exposition_marker_max: int = 4
    min_recommended_examples: int = 20
    regression_gate_tolerance: float = 2.0


class CalibrationRescoreRequest(BaseModel):
    bookId: str = ""


class CalibrationRevertRequest(BaseModel):
    bookId: str = ""
    appliedAt: str


class PlotDirectionRequest(BaseModel):
    bookId: str = ""
    chapterId: str = ""
    userIntent: str = ""


class ApplyPlotDirectionRequest(BaseModel):
    bookId: str = ""
    chapterId: str = ""
    optionId: str


class KnowledgeSearchRequest(BaseModel):
    bookId: str = ""
    q: str = ""
    limit: int = Field(default=6, ge=1, le=20)
    source: str = ""
    chapterId: str = ""
    characterId: str = ""
    timeScope: str = ""


class WritingFormulaStatusRequest(BaseModel):
    bookId: str = ""
    formulaId: str
    status: Literal["active", "retired"]


class ChapterPolishRequest(BaseModel):
    bookId: str = ""
    chapterId: str = ""
    instruction: str = ""
    agentId: str = ""
    modelProfile: str | None = None
    preferTrainedModel: bool = True


class IdeationSessionRequest(BaseModel):
    bookId: str = ""
    title: str = ""
    focus: str = ""
    seed: str = ""


class IdeationTurnRequest(BaseModel):
    bookId: str = ""
    role: str = "user"
    content: str


class IdeationMaterializeRequest(BaseModel):
    bookId: str = ""
    sectionPath: str = "notes/ideas.md"
    heading: str = "创意会话沉淀"


class BookAnalysisRequest(BaseModel):
    bookId: str = ""
    startChapterId: str = "001"
    endChapterId: str = "001"


class PromoteWritingFormulaRequest(BaseModel):
    bookId: str = ""
    reportPath: str


class ExtractWritingFormulaRequest(BaseModel):
    bookId: str = ""
    sourceText: str = Field(min_length=1, max_length=50_000)
    sourceLabel: str = Field(min_length=1, max_length=200)
    agentId: str
    modelProfile: str | None = None


class PromoteExternalWritingFormulaRequest(BaseModel):
    bookId: str = ""
    candidatePath: str
    selectedIds: list[str] = Field(min_length=1)


class WorldRuleReviewRequest(BaseModel):
    bookId: str = ""
    ruleId: str
    rule: str
    forbidden: str
    evidence: list[str] = Field(default_factory=list)


class ChapterSequenceEvaluationRequest(BaseModel):
    bookId: str = ""
    startChapterId: str = "001"
    endChapterId: str = "001"
    preferDrafts: bool = True


class RevisionPlanRequest(BaseModel):
    bookId: str = ""
    startChapterId: str = "001"
    endChapterId: str = "001"
    maxChapters: int = Field(default=3, ge=1, le=20)


class WorkbenchPresenter:
    model_selection_path = "models/workbench-selection.json"
    chapter_state_path = "memory/workbench-chapter-states.json"
    generation_state_path = "memory/workbench-generation-state.json"
    architecture_path = "story/workbench-architecture.json"
    blueprint_path = "story/chapter-blueprint.json"

    def __init__(
        self,
        project_service: ProjectService | None = None,
        registry: WorkspaceRegistryService | None = None,
        plan_service: ProjectPlanService | None = None,
        style_profile_service: StyleProfileService | None = None,
        model_service: WritingModelService | None = None,
        cli_agent_service: CliAgentService | None = None,
        story_guidance_service: StoryGuidanceService | None = None,
        context_pack_service: ContextPackService | None = None,
        chapter_gate_service: ChapterGateService | None = None,
        writing_quality_service: WritingQualityService | None = None,
        editorial_review_service: EditorialReviewService | None = None,
        export_service: ExportService | None = None,
        ai_runtime_service: AIRuntimeService | None = None,
    ) -> None:
        initialize_fresh_workspace = not WorkspaceRegistryService.is_initialized()
        self.project_service = project_service or ProjectService()
        self.registry = registry or WorkspaceRegistryService(project_service=self.project_service)
        self.workbench_repository = WorkbenchRepository(self.registry.db_path)
        self.ai_runtime_service = ai_runtime_service or AIRuntimeService(
            AIAccountRepository(self.registry.db_path)
        )
        self.plan_service = plan_service or ProjectPlanService(self.project_service)
        self.style_profile_service = style_profile_service or StyleProfileService(
            self.project_service
        )
        self.model_service = model_service or WritingModelService(self.project_service)
        self.model_library_service = ModelLibraryService(self.registry.db_path)
        self.editorial_profile_service = EditorialProfileService(self.project_service)
        self.cli_agent_service = cli_agent_service or CliAgentService()
        self.story_guidance_service = story_guidance_service or StoryGuidanceService(
            self.project_service
        )
        self.context_pack_service = context_pack_service or ContextPackService(
            self.project_service,
            self.story_guidance_service,
        )
        self.chapter_gate_service = chapter_gate_service or ChapterGateService(
            self.project_service,
            self.story_guidance_service,
            self.context_pack_service,
        )
        self.writing_quality_service = writing_quality_service or WritingQualityService(
            self.project_service,
            self.story_guidance_service,
        )
        self.editorial_review_service = editorial_review_service or EditorialReviewService(
            self.project_service,
            self.story_guidance_service,
        )
        self.export_service = export_service or ExportService(self.project_service)
        self.model_comparison_service = ModelComparisonService(self.project_service)
        self.local_training_service = LocalTrainingService(
            self.project_service,
            self.export_service,
            self.model_service,
        )
        self.memory_topic_service = MemoryTopicService(self.project_service)
        self.relationship_graph_service = RelationshipGraphService(self.project_service)
        self.issue_navigation_service = IssueNavigationService()
        self.material_service = WorkbenchMaterialService(
            self.project_service,
            self.workbench_repository,
        )
        self.review_service = WorkbenchReviewService(
            self.project_service,
            self.workbench_repository,
        )
        self.workbench_model_service = WorkbenchModelService(self)
        self.workbench_model_library_service = WorkbenchModelLibraryService(self)
        self.workbench_profile_service = WorkbenchProfileService(self)
        self.workbench_export_service = WorkbenchExportService(self.export_service)
        self.calibration_service = WorkbenchCalibrationService(self)
        self.generation_service = WorkbenchGenerationService(self)
        self.run_service = WorkbenchRunService(self)
        self.training_service = WorkbenchTrainingService(self)
        self.knowledge_base_service = KnowledgeBaseService(self.project_service)
        self.writing_asset_service = WritingAssetService(self.project_service)
        self.plot_direction_service = PlotDirectionService(
            self.project_service,
            self.story_guidance_service,
            self.context_pack_service,
        )
        self.chapter_polish_service = ChapterPolishService(self.project_service)
        self.ideation_session_service = IdeationSessionService(self.project_service)
        self.book_analysis_service = BookAnalysisService(
            self.project_service,
            self.story_guidance_service,
        )
        self.writing_formula_service = WritingFormulaService(
            self.project_service,
            self.book_analysis_service,
        )
        self.sequence_evaluation_service = ChapterSequenceEvaluationService(
            self.project_service,
            self.writing_quality_service,
            self.chapter_gate_service,
        )
        self.revision_plan_service = RevisionPlanService(self.project_service)
        if initialize_fresh_workspace:
            self._ensure_starter_demo()

    def workspace(self) -> dict[str, Any]:
        roots = self._workspace_roots()
        books = [self.book_for_root(root) for root in roots]
        return {
            "books": books,
            "creationOptions": self.creation_options(),
            "materials": [material for root in roots for material in self.materials_for_root(root)],
            "reviews": [
                review for root in roots for review in self._workspace_reviews_for_root(root)
            ],
            "models": self.models_for_roots(roots),
            "exports": self.exports_for_roots(roots),
            "jobs": self.jobs_for_roots(roots),
            "runs": self.runs_for_roots(roots),
            "generationStates": [self.generation_state_for_root(root) for root in roots],
        }

    def book_workspace(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        return {
            "books": [self.book_for_root(root)],
            "creationOptions": self.creation_options(),
            "materials": self.materials_for_root(root),
            "reviews": self._workspace_reviews_for_root(root),
            "models": self.models_for_roots([root]),
            "exports": self.exports_for_root(root),
            "jobs": self.jobs_for_root(root),
            "runs": self.runs_for_root(root),
            "generationStates": [self.generation_state_for_root(root)],
        }

    def creation_options(self) -> dict[str, Any]:
        return self.workbench_profile_service.creation_options()

    def create_book(self, request: CreateBookRequest) -> dict[str, Any]:
        if request.startGeneration:
            try:
                self.ai_runtime_service.account_for_role("writing")
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="请先到模型页给写作角色分配一个已启用的 AI 账号。",
                ) from exc
        if not request.draft.genre.strip():
            raise HTTPException(
                status_code=400,
                detail="作品题材不能为空。",
            )
        title = request.draft.title.strip() or f"新书 {request.existingBookCount + 1}"
        root = self._new_project_root(title)
        project = self.project_service.create_project(
            root,
            title=title,
            language="zh-CN",
            database_only=True,
        )
        self._update_metadata(
            project.root,
            genre=[request.draft.genre.strip()] if request.draft.genre.strip() else [],
        )
        if request.draft.platform.strip():
            self.plan_service.write_plan(
                project.root,
                target_chapter_count=request.targetChapterCount,
                target_words_per_chapter=request.targetWordsPerChapter,
                target_chapters_per_plot=request.targetChaptersPerPlot,
                platform=request.draft.platform.strip(),
                notes=(
                    f"styleProfileId={request.draft.styleProfileId.strip() or 'generic-web-serial'}"
                ),
            )
        first_title = request.draft.firstChapterTitle.strip() or "第一章 新书开场"
        seed = request.draft.seed.strip()
        starter = seed or (
            "这里是新书第一章的开场占位。可以先让 AI 生成剧情钩子、主角登场和第一处冲突。"
        )
        content = f"# {first_title}\n\n{starter}\n"
        self.project_service.write_text(project.root, "chapters/001.md", content)
        if request.draft.tagline.strip():
            self.project_service.write_text(
                project.root, "notes/ideas.md", f"# Ideas\n\n{request.draft.tagline.strip()}\n"
            )
        builtin_style_ids = {
            profile.id for profile in self.style_profile_service.list_builtin_profiles()
        }
        selected_style_id = request.draft.styleProfileId.strip()
        if selected_style_id and selected_style_id in builtin_style_ids:
            self.style_profile_service.write_project_profile_from_builtin(
                project.root,
                selected_style_id,
                label=request.draft.styleProfileLabel.strip() or "Project style override",
            )
        self.registry.register_project(project.root)
        book = self.book_for_root(project.root)
        chapter = book["chapters"][0]
        self._write_chapter_status(project.root, str(chapter.get("id") or "001"), "待写")
        book = self.book_for_root(project.root)
        chapter = book["chapters"][0]
        review = self.reviews_for_root(project.root)[0]
        self._write_generation_state(
            project.root,
            self._generation_state_payload(
                project.root,
                stage="architecture",
                status="idle",
                active_chapter_id=str(chapter.get("id") or "001"),
                mode=request.interventionMode,
                batch_target=request.batchTarget,
                next_action=(
                    "正在生成作品方向候选。"
                    if request.startGeneration
                    else "填写方向或直接生成作品架构。"
                ),
                last_result=(
                    "已创建作品并完成生成准备。"
                    if request.startGeneration
                    else "已创建仅供人工准备的作品。"
                ),
            ),
        )
        generated = (
            self.generation_service.continue_generation(
                project.root.as_posix(), request_id=f"create-{project.root.name}"
            )
            if request.startGeneration
            else self.generation_service.generation_for_book(project.root.as_posix())
        )
        refreshed_book = self.book_for_root(project.root)
        return {
            "book": refreshed_book,
            "chapter": refreshed_book["chapters"][0],
            "review": review,
            "generationState": generated["generationState"],
            "authorMessage": (
                "作品已创建，首批方向候选已准备完成。"
                if request.startGeneration
                else "作品已创建，可以继续人工准备。"
            ),
        }

    def generation_for_book(self, book_id: str) -> dict[str, Any]:
        return self.generation_service.generation_for_book(book_id)

    def update_book_settings(
        self,
        book_id: str,
        request: UpdateBookSettingsRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        if not request.title.strip():
            raise HTTPException(status_code=400, detail="作品名称不能为空。")
        if not request.genre.strip():
            raise HTTPException(status_code=400, detail="作品题材不能为空。")
        try:
            profile = self.style_profile_service.get_builtin_profile(
                request.styleProfileId.strip()
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail="所选风格模板不存在。") from exc
        self._update_metadata(
            root,
            title=request.title.strip(),
            genre=[request.genre.strip()],
        )
        self._write_tagline(root, request.tagline.strip())
        self.style_profile_service.write_project_profile_from_builtin(
            root,
            profile.id,
            label=(
                request.styleProfileLabel.strip()
                or self.workbench_profile_service.style_option_label(profile.id, profile.label)
            ),
        )
        plan = self.plan_service.read_plan(root)
        self.plan_service.write_plan(
            root,
            target_chapter_count=plan.targetChapterCount,
            target_words_per_chapter=plan.targetWordsPerChapter,
            target_chapters_per_plot=plan.targetChaptersPerPlot,
            platform=profile.platform or plan.platform,
            cadence=plan.cadence,
            notes=self._with_style_profile_note(plan.notes, profile.id),
        )
        return {
            "bookId": book_id,
            "book": self.book_for_root(root),
            "authorMessage": "作品名称、题材、简介和风格已保存。",
        }

    def update_project_plan(
        self,
        book_id: str,
        request: ProjectPlanUpdateRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        existing = self.plan_service.read_plan(root)
        plan = self.plan_service.write_plan(
            root,
            target_chapter_count=request.targetChapterCount,
            target_words_per_chapter=request.targetWordsPerChapter,
            target_chapters_per_plot=request.targetChaptersPerPlot,
            platform=existing.platform,
            cadence=existing.cadence,
            notes=existing.notes,
        )
        return {
            "bookId": book_id,
            "plan": plan.model_dump(mode="json"),
            "book": self.book_for_root(root),
            "authorMessage": "作品写作参数已保存，后续规划与章节生成会使用新目标。",
        }

    def long_form_plan(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = self._latest_chapter_id(root)
        candidate = self.generation_service.artifacts.long_form_candidate(root, replan=True)
        return {
            "bookId": book_id,
            "plan": self.generation_service.long_form_planning.read_plan(root),
            "currentPosition": self.generation_service.long_form_planning.current_position(
                root,
                chapter_id,
            ),
            "chapterLandings": self.generation_service.long_form_planning.chapter_landings(root),
            "serialRisks": self.generation_service.long_form_planning.serial_risks(root),
            "replanCandidate": candidate,
        }

    def update_volume_goal(self, book_id: str, request: VolumeGoalUpdateRequest) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        if not request.goal.strip():
            raise HTTPException(status_code=400, detail="卷目标不能为空。")
        try:
            existing_plan = self.generation_service.long_form_planning.read_plan(root)
            current_volume = next(
                (
                    item
                    for item in existing_plan.get("volumes", [])
                    if item.get("volumeId") == request.volumeId
                ),
                {},
            )
            if not current_volume:
                raise FileNotFoundError(request.volumeId)
            if request.chapterRange.strip() and request.chapterRange.strip() != str(
                current_volume.get("chapterRange") or ""
            ):
                completed = [
                    item
                    for item in self._chapters_for_root(root)
                    if str(item.get("status") or "") == "完成"
                    and self.generation_service.long_form_planning.current_position(
                        root, str(item.get("id") or "")
                    ).get("volumeId")
                    == request.volumeId
                ]
                if completed:
                    raise HTTPException(
                        status_code=409,
                        detail="当前卷已有定稿章节，不能修改卷边界；可以调整未来章节落点。",
                    )
            plan = self.generation_service.long_form_planning.update_volume(
                root,
                request.volumeId,
                goal=request.goal,
                chapter_range=request.chapterRange,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="当前卷不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**self.long_form_plan(book_id), "plan": plan, "authorMessage": "卷目标已更新。"}

    def update_chapter_landing(
        self, book_id: str, request: ChapterLandingUpdateRequest
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        if self._stored_chapter_status(root, request.chapterId) == "完成":
            raise HTTPException(status_code=409, detail="已定稿章节的规划落点不能直接修改。")
        if not all(
            [request.goal.strip(), request.hook.strip(), request.promiseProgression.strip()]
        ):
            raise HTTPException(status_code=400, detail="章节目标、钩子和承诺推进不能为空。")
        try:
            landing = self.generation_service.long_form_planning.update_chapter_landing(
                root,
                request.chapterId,
                goal=request.goal,
                hook=request.hook,
                promise_progression=request.promiseProgression,
                logic_dependencies=[
                    item.strip() for item in request.logicDependencies if item.strip()
                ],
                segment_id=request.segmentId,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="当前章节落点不存在。") from exc
        return {"bookId": book_id, "landing": landing, "authorMessage": "章节落点已更新。"}

    def generate_long_form_replan(
        self,
        book_id: str,
        request: LongFormReplanRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = request.chapterId.strip() or self._latest_chapter_id(root)
        deviation = self.generation_service.long_form_planning.evaluate_deviation(
            root,
            chapter_id,
        )
        if not deviation["significant"]:
            return {
                "bookId": book_id,
                "deviation": deviation,
                "candidate": None,
                "authorMessage": "当前偏差不足以触发重规划，已保留现有卷计划。",
            }
        try:
            route = self.generation_service._resolve_route(root)
            candidate, _ = self.generation_service.artifacts.generate_long_form_plan(
                root,
                route,
                replan=True,
                deviation_report=deviation,
            )
        except GenerationExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.author_message) from exc
        return {
            "bookId": book_id,
            "deviation": deviation,
            "candidate": candidate,
            "authorMessage": "已生成未来章节重规划候选，确认前不会覆盖当前计划。",
        }

    def confirm_long_form_replan(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            plan = self.generation_service.artifacts.apply_long_form_plan(root, replan=True)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {**self.long_form_plan(book_id), "plan": plan, "authorMessage": "重规划候选已确认。"}

    def set_generation_mode(self, book_id: str, request: GenerationModeRequest) -> dict[str, Any]:
        return self.generation_service.set_generation_mode(book_id, request)

    def continue_generation(self, book_id: str, request_id: str = "") -> dict[str, Any]:
        return self.generation_service.continue_generation(book_id, request_id=request_id)

    def confirm_generation(self, book_id: str, request: GenerationActionRequest) -> dict[str, Any]:
        return self.generation_service.confirm_generation(book_id, request)

    def regenerate_generation_candidate(self, book_id: str, request_id: str = "") -> dict[str, Any]:
        try:
            return self.generation_service.regenerate_candidate(book_id, request_id=request_id)
        except GenerationExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.author_message) from exc

    def select_generation_candidate(
        self, book_id: str, candidate_id: str, request_id: str = ""
    ) -> dict[str, Any]:
        try:
            return self.generation_service.select_candidate(
                book_id, candidate_id, request_id=request_id
            )
        except GenerationExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.author_message) from exc

    def rollback_generation_candidate(self, book_id: str, request_id: str = "") -> dict[str, Any]:
        try:
            return self.generation_service.rollback_candidate(book_id, request_id=request_id)
        except GenerationExecutionError as exc:
            raise HTTPException(status_code=409, detail=exc.author_message) from exc

    def pause_generation(self, book_id: str) -> dict[str, Any]:
        return self.generation_service.pause_generation(book_id)

    def resume_generation(self, book_id: str) -> dict[str, Any]:
        return self.generation_service.resume_generation(book_id)

    def takeover_generation(
        self,
        book_id: str,
        request: GenerationTakeoverRequest,
    ) -> dict[str, Any]:
        return self.generation_service.takeover_generation(book_id, request)

    def accept_generation_chapter(self, book_id: str, chapter_id: str) -> dict[str, Any]:
        return self.accept_chapter(AcceptChapterRequest(bookId=book_id, chapterId=chapter_id))

    def create_material(self, material: MaterialPayload) -> dict[str, Any]:
        root = self._root_from_book_id(material.bookId)
        material_id = material.id.strip() or self._new_material_id(root, material)
        material = material.model_copy(update={"id": material_id})
        materials = [
            item for item in self.material_service.read_store(root) if item.get("id") != material.id
        ]
        material_data = material.model_dump(mode="json")
        materials.insert(0, material_data)
        self.material_service.write_store(root, materials)
        return {"material": material_data}

    def update_material(self, material: MaterialPayload) -> dict[str, Any]:
        root = self._root_from_book_id(material.bookId)
        materials = self.material_service.read_store(root)
        material_data = material.model_dump(mode="json")
        replaced = False
        next_materials: list[dict[str, Any]] = []
        for item in materials:
            if item.get("id") == material.id:
                next_materials.append(material_data)
                replaced = True
            else:
                next_materials.append(item)
        if not replaced:
            next_materials.insert(0, material_data)
        self.material_service.write_store(root, next_materials)
        return {"material": material_data}

    def delete_material(self, book_id: str, material_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        materials = self.material_service.read_store(root)
        next_materials = [item for item in materials if str(item.get("id")) != material_id]
        removed = len(next_materials) != len(materials)
        if removed:
            self.material_service.write_store(root, next_materials)
        affected_chapters = self._remove_material_from_chapter_briefs(root, material_id)
        return {
            "bookId": book_id,
            "materialId": material_id,
            "removed": removed,
            "affectedChapters": affected_chapters,
            "summary": (
                "已删除资料，并同步清理章节引用。" if removed else "资料不存在，已跳过删除。"
            ),
        }

    def set_book_model(self, request: SetBookModelRequest) -> dict[str, str]:
        return self.workbench_model_service.set_book_model(request)

    def list_model_library(self) -> dict[str, Any]:
        return self.workbench_model_library_service.list_models()

    def list_model_training_backends(self) -> dict[str, Any]:
        return self.workbench_model_library_service.list_training_backends()

    def create_model_library_item(
        self,
        request: ModelLibraryCreateRequest,
    ) -> dict[str, Any]:
        return self.workbench_model_library_service.create_model(request)

    def create_model_category(
        self,
        request: ModelCategoryCreateRequest,
    ) -> dict[str, Any]:
        return self.workbench_model_library_service.create_category(request)

    def model_library_detail(self, model_id: str) -> dict[str, Any]:
        return self.workbench_model_library_service.model_detail(model_id)

    def add_model_book_sources(
        self,
        model_id: str,
        request: ModelBookSourcesRequest,
    ) -> dict[str, Any]:
        return self.workbench_model_library_service.add_book_sources(model_id, request)

    def model_library_readiness(self, model_id: str) -> dict[str, Any]:
        return self.workbench_model_library_service.readiness(model_id)

    def start_model_library_training(
        self,
        model_id: str,
        request: ModelLibraryTrainingRequest,
    ) -> dict[str, Any]:
        return self.workbench_model_library_service.start_training(model_id, request)

    def delete_model_source(self, model_id: str, source_id: str) -> dict[str, Any]:
        return self.workbench_model_library_service.delete_source(model_id, source_id)

    def validate_model(self, request: ValidateModelRequest) -> dict[str, Any]:
        return self.workbench_model_service.validate_model(request)

    def model_training_readiness(self, book_id: str = "") -> dict[str, Any]:
        return self.training_service.model_training_readiness(book_id)

    def compare_models(self, request: ModelCompareRequest) -> dict[str, Any]:
        return self.workbench_model_service.compare_models(request)

    def run_model_training(self, request: ModelTrainingRunRequest) -> dict[str, Any]:
        return self.training_service.run_model_training(request)

    def annotate_calibration(self, request: CalibrationAnnotationRequest) -> dict[str, Any]:
        return self.calibration_service.annotate(request)

    def calibration_analysis(self, book_id: str = "") -> dict[str, Any]:
        return self.calibration_service.analysis(book_id)

    def apply_calibration(
        self,
        request: QualityThresholdConfigRequest,
    ) -> dict[str, Any]:
        return self.calibration_service.apply(request)

    def rescore_all_calibration(self, request: CalibrationRescoreRequest) -> dict[str, Any]:
        return self.calibration_service.rescore_all(request.bookId)

    def calibration_history(self, book_id: str = "") -> dict[str, Any]:
        return self.calibration_service.history(book_id)

    def revert_calibration(self, request: CalibrationRevertRequest) -> dict[str, Any]:
        return self.calibration_service.revert(request)

    def quality_distribution(self, book_id: str = "") -> dict[str, Any]:
        return self.workbench_model_service.quality_distribution(book_id)

    def list_writing_models(self, book_id: str = "") -> dict[str, Any]:
        return self.workbench_model_service.list_writing_models(book_id)

    def create_writing_model(self, request: WritingModelManageRequest) -> dict[str, Any]:
        return self.workbench_model_service.create_writing_model(request)

    def set_default_writing_model(self, request: WritingModelDefaultRequest) -> dict[str, Any]:
        return self.workbench_model_service.set_default_writing_model(request)

    def list_style_profiles(self, book_id: str = "") -> dict[str, Any]:
        return self.workbench_profile_service.list_style_profiles(book_id)

    def apply_style_profile(self, request: ApplyStyleProfileRequest) -> dict[str, Any]:
        return self.workbench_profile_service.apply_style_profile(request)

    def list_editorial_models(self, book_id: str = "") -> dict[str, Any]:
        return self.workbench_profile_service.list_editorial_models(book_id)

    def create_editorial_model(self, request: EditorialModelManageRequest) -> dict[str, Any]:
        return self.workbench_profile_service.create_editorial_model(request)

    def set_default_editorial_model(self, request: EditorialModelDefaultRequest) -> dict[str, Any]:
        return self.workbench_profile_service.set_default_editorial_model(request)

    def promote_model_compare(self, request: PromoteModelCompareRequest) -> dict[str, Any]:
        return self.workbench_model_service.promote_model_compare(request)

    def apply_chapter_draft(self, request: ApplyChapterDraftRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        title = self._chapter_title(root, chapter_id) or request.chapterId
        self.project_service.write_text(
            root,
            f"chapters/{chapter_id}.md",
            f"# {title}\n\n{request.nextContent.strip()}\n",
        )
        self._write_chapter_status(root, chapter_id, "草稿")
        chapter = self._chapter_for_file(root, PathGuard(root).resolve(f"chapters/{chapter_id}.md"))
        self.workbench_repository.upsert_chapter(root, chapter)
        return {"bookId": request.bookId, "chapter": chapter}

    def update_chapter_planning(self, request: UpdateChapterPlanningRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        brief = self._chapter_brief(root, chapter_id)
        next_tasks = self._unique_nonempty(request.tasks)
        next_plot_points = self._unique_nonempty(request.plotPoints)
        next_brief = {
            **brief,
            "workbenchTasks": next_tasks,
            "mustInclude": next_plot_points,
        }
        if not str(next_brief.get("focus") or "").strip():
            next_brief["focus"] = next_tasks[0] if next_tasks else "等待补全章节目标。"
        brief_path = f"story/chapter-briefs/{chapter_id}.json"
        self.project_service.write_text(
            root,
            brief_path,
            json.dumps(next_brief, ensure_ascii=False, indent=2) + "\n",
        )
        chapter_path = PathGuard(root).resolve(f"chapters/{chapter_id}.md")
        chapter = (
            self._chapter_for_file(root, chapter_path)
            if chapter_path.exists()
            else self._chapter_from_brief(root, chapter_id, next_brief)
        )
        self.workbench_repository.upsert_chapter(root, chapter)
        return {"bookId": request.bookId, "chapter": chapter}

    def link_chapter_materials(self, request: LinkChapterMaterialsRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        brief = self._chapter_brief(root, chapter_id)
        available_materials = {
            str(item.get("id")): item
            for item in self.materials_for_root(root)
            if str(item.get("id") or "").strip()
        }
        selected_ids = [
            material_id
            for material_id in self._unique_nonempty(request.materialIds)
            if material_id in available_materials
        ]
        existing_ids = self._linked_material_ids_from_brief(brief)
        next_ids = (
            selected_ids
            if request.mode == "replace"
            else self._unique_nonempty([*existing_ids, *selected_ids])
        )
        linked_materials = [available_materials[material_id] for material_id in next_ids]
        next_brief = dict(brief)
        next_brief["linkedMaterials"] = next_ids
        location = str(next_brief.get("location") or "").strip()
        if not location:
            location_material = next(
                (item for item in linked_materials if str(item.get("type")) == "地点"),
                None,
            )
            if location_material:
                next_brief["location"] = str(location_material.get("title") or "").strip()
        next_brief["mustInclude"] = self._unique_nonempty(
            [
                *self._string_list(next_brief.get("mustInclude")),
                *[str(item.get("title") or "").strip() for item in linked_materials],
            ]
        )
        if not str(next_brief.get("focus") or "").strip() and linked_materials:
            titles = "、".join(
                str(item.get("title") or "").strip()
                for item in linked_materials[:3]
                if str(item.get("title") or "").strip()
            )
            if titles:
                next_brief["focus"] = f"围绕 {titles} 推进本章冲突和证据释放。"
        brief_path = f"story/chapter-briefs/{chapter_id}.json"
        self.project_service.write_text(
            root,
            brief_path,
            json.dumps(next_brief, ensure_ascii=False, indent=2) + "\n",
        )
        chapter_path = PathGuard(root).resolve(f"chapters/{chapter_id}.md")
        chapter = (
            self._chapter_for_file(root, chapter_path)
            if chapter_path.exists()
            else self._chapter_from_brief(root, chapter_id, next_brief)
        )
        self.workbench_repository.upsert_chapter(root, chapter)
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "chapter": chapter,
            "linkedMaterials": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or ""),
                    "type": str(item.get("type") or ""),
                }
                for item in linked_materials
            ],
            "summary": (
                "已更新本章资料提示。" if linked_materials else "当前没有可纳入本章的资料。"
            ),
        }

    def chapter_materials(
        self,
        book_id: str,
        chapter_id: str,
        material_type: MaterialType | None = None,
        query: str = "",
        scope: Literal["related", "all"] = "related",
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = self.project_service.normalize_chapter_id(chapter_id)
        brief = self._chapter_brief(root, chapter_id)
        all_materials = self.materials_for_root(root)
        if material_type:
            all_materials = [
                item for item in all_materials if str(item.get("type") or "") == material_type
            ]
        query_text = query.strip().lower()
        if query_text:
            all_materials = [
                item
                for item in all_materials
                if query_text
                in " ".join(
                    [
                        str(item.get("title") or ""),
                        str(item.get("summary") or ""),
                        str(item.get("influence") or ""),
                        *[str(value) for value in item.get("related", []) if str(value).strip()],
                    ]
                ).lower()
            ]
        if scope == "all":
            return {
                "bookId": book_id,
                "chapterId": chapter_id,
                "type": material_type,
                "query": query,
                "scope": scope,
                "materials": all_materials,
                "summary": f"已返回 {len(all_materials)} 条资料。",
            }
        related_terms = self._chapter_related_terms(root, chapter_id, brief)
        ranked = sorted(
            [
                (self._material_related_score(item, related_terms, brief), item)
                for item in all_materials
            ],
            key=lambda pair: (-pair[0], str(pair[1].get("title") or "")),
        )
        materials = [item for score, item in ranked if score > 0]
        return {
            "bookId": book_id,
            "chapterId": chapter_id,
            "type": material_type,
            "query": query,
            "scope": scope,
            "materials": materials,
            "summary": f"已按当前章节整理 {len(materials)} 条相关资料。",
        }

    def prepare_chapter(self, request: ChapterPrepareRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        self._restore_scene_contract_from_repository(root, chapter_id)
        readiness = self.story_guidance_service.check_readiness(root, chapter_id)
        started_at = time.perf_counter()
        context_summary: dict[str, Any]
        if readiness.status == "block":
            context_summary = {
                "status": "skipped",
                "summary": "开写准备仍有阻断项，先补齐章节合同后再构建上下文包。",
                "includedCount": 0,
                "estimatedTokens": 0,
                "tokenBudget": ContextPackService.default_max_estimated_tokens,
                "items": [],
            }
        else:
            try:
                context_pack = self._build_context_pack(root, chapter_id)
                context_summary = {
                    "status": "ready",
                    "summary": self._context_pack_summary(context_pack),
                    "includedCount": len(context_pack.included),
                    "estimatedTokens": context_pack.estimatedTokens,
                    "tokenBudget": ContextPackService.default_max_estimated_tokens,
                    "items": self._context_pack_items(context_pack),
                }
            except FileNotFoundError:
                context_summary = {
                    "status": "missing",
                    "summary": "未找到章节合同，无法构建上下文包。",
                    "includedCount": 0,
                    "estimatedTokens": 0,
                    "tokenBudget": ContextPackService.default_max_estimated_tokens,
                    "items": [],
                }
        context_summary["buildDurationMs"] = int((time.perf_counter() - started_at) * 1000)
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "readiness": {
                "status": readiness.status,
                "score": readiness.score,
                "issues": [
                    {
                        "severity": issue.severity,
                        "field": issue.field,
                        "message": issue.message,
                        "quickFix": issue.quickFix,
                    }
                    for issue in readiness.issues
                ],
                "missingContext": readiness.missingContext,
                "recommendedNextAction": readiness.recommendedNextAction,
            },
            "contextPack": context_summary,
            "display": self._prepare_display(readiness.status, readiness.score),
        }

    def plot_directions(self, request: PlotDirectionRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        try:
            report = self.plot_direction_service.suggest_directions(
                root,
                chapter_id,
                request.userIntent,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=409,
                detail="当前章节还没有场景合同，请先点击“准备本章”，完成章节目标和上下文准备后再获取建议。",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "report": report.model_dump(mode="json"),
        }

    def apply_plot_direction(self, request: ApplyPlotDirectionRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        try:
            contract = self.plot_direction_service.apply_direction(
                root,
                chapter_id,
                request.optionId,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "optionId": request.optionId,
            "contract": contract.model_dump(mode="json"),
        }

    def rebuild_knowledge(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        index = self.knowledge_base_service.rebuild_index(root)
        return {
            "bookId": book_id,
            "chunkCount": len(index.chunks),
            "index": index.model_dump(mode="json"),
        }

    def search_knowledge(self, request: KnowledgeSearchRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        terms = set(self._search_terms(request.q))
        results = self.knowledge_base_service.search(
            root,
            terms,
            limit=request.limit,
            source=request.source,
            chapter_id=request.chapterId,
            character_id=request.characterId,
            time_scope=request.timeScope,
        )
        return {
            "bookId": request.bookId,
            "query": request.q,
            "results": [item.model_dump(mode="json") for item in results],
        }

    def writing_assets(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        return {"bookId": book_id, **self.writing_asset_service.list_assets(root)}

    def set_writing_formula_status(
        self, book_id: str, request: WritingFormulaStatusRequest
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            result = self.writing_asset_service.set_formula_status(
                root,
                request.formulaId,
                request.status,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="未找到该写作公式。") from exc
        return {"bookId": book_id, **result}

    async def polish_chapter(self, request: ChapterPolishRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        draft_path = f"drafts/{chapter_id}.generated.md"
        try:
            source_text = self.project_service.read_text(root, draft_path)
            source_path = draft_path
        except FileNotFoundError:
            source_path = f"chapters/{chapter_id}.md"
            source_text = self.project_service.read_text(root, source_path)
        prompt = (
            "请润色以下小说章节。保留所有剧情事实、人物关系和章节结构，只优化节奏、"
            "情绪、表达与可读性。直接返回完整润色正文，不要解释过程。\n\n"
            f"作者要求：{request.instruction.strip() or '保持原意并提升可读性。'}\n\n"
            f"原文：\n{source_text}"
        )
        try:
            completion = await self.ai_runtime_service.complete(
                role="writing",
                prompt=prompt,
                root=root.as_posix(),
                action="AI 润色全章",
                bypass_cache=False,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail="请先到模型页给写作角色分配可用 AI 账号。",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        polished_path = f"drafts/{chapter_id}.polished.md"
        candidate_text = completion.text.strip()
        self.project_service.write_text(root, polished_path, candidate_text + "\n")
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "sourcePath": source_path,
            "polishedPath": polished_path,
            "candidateText": candidate_text,
            "usage": completion.usage.payload(),
            "accountName": completion.account.name,
            "cacheHit": completion.cache_hit,
            "compressed": completion.compressed,
        }

    def create_ideation_session(self, request: IdeationSessionRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        session = self.ideation_session_service.create_session(
            root,
            request.title,
            request.focus,
            request.seed,
        )
        return {"bookId": request.bookId, "session": session.model_dump(mode="json")}

    def list_ideation_sessions(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        sessions = self.ideation_session_service.list_sessions(root, limit=12)
        return {
            "bookId": book_id,
            "sessions": [session.model_dump(mode="json") for session in sessions],
        }

    def append_ideation_turn(
        self,
        book_id: str,
        session_id: str,
        request: IdeationTurnRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            session = self.ideation_session_service.append_turn(
                root,
                session_id,
                role=request.role,
                content=request.content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": book_id, "session": session.model_dump(mode="json")}

    def materialize_ideation_session(
        self,
        book_id: str,
        session_id: str,
        request: IdeationMaterializeRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            content = self.ideation_session_service.append_session_to_section(
                root,
                session_id,
                section_path=request.sectionPath,
                heading=request.heading,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": book_id,
            "sessionId": session_id,
            "sectionPath": request.sectionPath,
            "content": content,
        }

    def analyze_book(self, request: BookAnalysisRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        report = self.book_analysis_service.analyze_range(
            root,
            request.startChapterId,
            request.endChapterId,
        )
        return {"bookId": request.bookId, "report": report.model_dump(mode="json")}

    def promote_writing_formulas(
        self,
        request: PromoteWritingFormulaRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        memory = self.writing_formula_service.promote_from_analysis(root, request.reportPath)
        return {"bookId": request.bookId, "memory": memory.model_dump(mode="json")}

    def extract_writing_formulas(
        self,
        request: ExtractWritingFormulaRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        try:
            artifact, path = self.writing_formula_service.extract_external_candidates(
                root,
                source_text=request.sourceText,
                source_label=request.sourceLabel,
                agent_id=request.agentId,
                model_profile=request.modelProfile,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": request.bookId,
            "candidatePath": path,
            "candidate": artifact.model_dump(mode="json"),
        }

    def promote_external_writing_formulas(
        self,
        request: PromoteExternalWritingFormulaRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        try:
            memory = self.writing_formula_service.promote_from_external_candidates(
                root,
                request.candidatePath,
                request.selectedIds,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": request.bookId, "memory": memory.model_dump(mode="json")}

    def add_world_rule_review(
        self,
        book_id: str,
        chapter_id: str,
        request: WorldRuleReviewRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            review = self._post_chapter_service().add_world_rule_review_item(
                root,
                chapter_id,
                rule_id=request.ruleId,
                rule=request.rule,
                forbidden=request.forbidden,
                evidence=request.evidence,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": book_id, "review": review.model_dump(mode="json")}

    def sequence_evaluation(
        self,
        request: ChapterSequenceEvaluationRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        try:
            report = self.sequence_evaluation_service.evaluate(
                root,
                request.startChapterId,
                request.endChapterId,
                prefer_drafts=request.preferDrafts,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": request.bookId, "report": report.model_dump(mode="json")}

    def revision_plan(self, request: RevisionPlanRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        try:
            sequence_report = self.sequence_evaluation_service.evaluate(
                root,
                request.startChapterId,
                request.endChapterId,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        report = self.revision_plan_service.build_for_sequence(
            root,
            sequence_report,
        )
        briefs = self.revision_plan_service.materialize_revision_briefs(
            root,
            report,
            max_chapters=request.maxChapters,
        )
        diagnosis = self.revision_plan_service.build_failure_diagnosis(root, report)
        return {
            "bookId": request.bookId,
            "sequence": sequence_report.model_dump(mode="json"),
            "plan": report,
            "briefs": briefs,
            "diagnosis": diagnosis,
        }

    def writing_lessons(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        data = self._read_json(root, "memory/writing-lessons.json")
        lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for lesson in lessons:
            if not isinstance(lesson, dict):
                continue
            category = str(lesson.get("category") or "general")
            grouped.setdefault(category, []).append(
                {
                    "id": str(lesson.get("id") or ""),
                    "category": category,
                    "lesson": str(lesson.get("lesson") or lesson.get("text") or ""),
                    "severity": str(lesson.get("severity") or ""),
                    "sourceChapters": [
                        str(value)
                        for value in lesson.get("sourceChapters", [])
                        if str(value).strip()
                    ]
                    if isinstance(lesson.get("sourceChapters"), list)
                    else [],
                    "status": str(lesson.get("status") or "active"),
                }
            )
        return {
            "bookId": book_id,
            "lessons": [item for items in grouped.values() for item in items],
            "groups": [
                {"category": category, "lessons": items}
                for category, items in sorted(grouped.items())
            ],
        }

    def characters_snapshot(self, book_id: str, chapter_id: str = "") -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        character_memory = self._read_json(root, "memory/character-states.json")
        relationship_memory = self._read_json(root, "memory/relationship-states.json")
        characters = (
            character_memory.get("characters", [])
            if isinstance(character_memory.get("characters"), list)
            else []
        )
        relationships = (
            relationship_memory.get("relationships", [])
            if isinstance(relationship_memory.get("relationships"), list)
            else []
        )
        items: list[dict[str, Any]] = []
        for character in characters:
            if not isinstance(character, dict):
                continue
            states = character.get("states") if isinstance(character.get("states"), list) else []
            latest_state = states[-1] if states and isinstance(states[-1], dict) else {}
            character_id = str(character.get("characterId") or character.get("id") or "")
            relation = self._latest_relationship_for_character(relationships, character_id)
            items.append(
                {
                    "id": character_id,
                    "name": str(character.get("name") or character_id or "未命名人物"),
                    "emotion": str(
                        latest_state.get("emotionalState")
                        or latest_state.get("emotion")
                        or latest_state.get("status")
                        or ""
                    ),
                    "goal": str(latest_state.get("goal") or latest_state.get("desire") or ""),
                    "relationshipScore": relation.get("quantifiedScore"),
                    "relationshipStatus": str(
                        relation.get("status") or relation.get("label") or ""
                    ),
                    "chapterId": str(latest_state.get("chapterId") or ""),
                }
            )
        return {"bookId": book_id, "chapterId": chapter_id, "characters": items}

    def chapter_contract(self, book_id: str, chapter_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        self._restore_scene_contract_from_repository(root, normalized)
        try:
            contract = self.story_guidance_service.read_scene_contract(root, normalized)
        except FileNotFoundError:
            contract = self.story_guidance_service.create_scene_contract(root, normalized)
        return {
            "bookId": book_id,
            "chapterId": normalized,
            "contract": contract.model_dump(mode="json"),
        }

    def update_chapter_contract(self, request: ChapterContractUpdateRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        normalized = self.project_service.normalize_chapter_id(request.chapterId)
        self._restore_scene_contract_from_repository(root, normalized)
        try:
            contract = self.story_guidance_service.read_scene_contract(root, normalized)
        except FileNotFoundError:
            contract = self.story_guidance_service.create_scene_contract(root, normalized)
        allowed = {
            "title",
            "focus",
            "goal",
            "conflict",
            "turn",
            "outcome",
            "hook",
            "openingHook",
            "emotionalBeat",
            "relationshipBeat",
            "internalNeed",
            "stakes",
            "cost",
            "subtext",
            "aftertaste",
        }
        updates = {
            key: value
            for key, value in request.fields.items()
            if key in allowed and isinstance(value, str)
        }
        updated = contract.model_copy(update=updates)
        self.story_guidance_service.write_scene_contract(root, updated)
        self.workbench_repository.upsert_scene_contract(root, updated)
        return {
            "bookId": request.bookId,
            "chapterId": normalized,
            "contract": updated.model_dump(mode="json"),
        }

    def check_chapter_gate(self, request: ChapterGateRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        report = self.chapter_gate_service.check_chapter(
            root,
            chapter_id,
            draft_path=self._preferred_gate_target_path(root, chapter_id),
        )
        if self._stored_chapter_status(root, chapter_id) != "完成":
            self._write_chapter_status(root, chapter_id, "审阅")
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "gate": {
                "status": report.status,
                "score": report.score,
                "issues": [
                    {
                        "severity": issue.severity,
                        "stage": issue.stage,
                        "type": issue.type,
                        "message": issue.message,
                        "evidence": issue.evidence[:3],
                        "textSnippet": issue.textSnippet,
                        "suggestionHint": issue.suggestionHint,
                    }
                    for issue in report.issues
                ],
                "recommendedNextAction": report.recommendedNextAction,
            },
            "display": self._gate_display(report.status, report.score),
        }

    def gate_recovery(self, book_id: str, chapter_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        normalized_chapter_id = self.project_service.normalize_chapter_id(chapter_id)
        source = self._preferred_diff_target_path(root, normalized_chapter_id)
        gate = self.chapter_gate_service.check_chapter(
            root,
            normalized_chapter_id,
            draft_path=source,
            include_draft=True,
            include_review=False,
        )
        if self._stored_chapter_status(root, normalized_chapter_id) != "完成":
            self._write_chapter_status(root, normalized_chapter_id, "审阅")
        recovery = self._gate_recovery_payload(normalized_chapter_id, gate)
        return {
            **recovery,
            "bookId": book_id,
        }

    def accept_chapter(self, request: AcceptChapterRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        draft_path = self._preferred_gate_target_path(root, chapter_id)
        chapter_path = f"chapters/{chapter_id}.md"
        if not self.project_service.file_exists(
            root, chapter_path
        ) and not self.project_service.file_exists(root, draft_path):
            raise HTTPException(status_code=404, detail=f"找不到章节：{request.chapterId}")
        gate = self.chapter_gate_service.check_chapter(root, chapter_id, draft_path=draft_path)
        if self._stored_chapter_status(root, chapter_id) != "完成":
            self._write_chapter_status(root, chapter_id, "审阅")
        if gate.status == "block" and not request.force:
            recovery = self._gate_recovery_payload(chapter_id, gate)
            raise HTTPException(
                status_code=409,
                detail={
                    "message": self._gate_display(gate.status, gate.score),
                    "gate": {
                        "status": gate.status,
                        "score": gate.score,
                        "issues": [
                            {
                                "severity": issue.severity,
                                "stage": issue.stage,
                                "type": issue.type,
                                "message": issue.message,
                                "evidence": issue.evidence[:3],
                                "textSnippet": issue.textSnippet,
                                "suggestionHint": issue.suggestionHint,
                            }
                            for issue in gate.issues[:6]
                        ],
                        "recommendedNextAction": gate.recommendedNextAction,
                    },
                    "recovery": recovery,
                },
            )
        accepted_path = (
            self.project_service.accept_draft(root, draft_path, chapter_id)
            if draft_path.startswith("drafts/")
            and self.project_service.file_exists(root, draft_path)
            else f"chapters/{chapter_id}.md"
        )
        self._write_chapter_status(root, chapter_id, "完成")
        chapter = self._chapter_for_file(root, PathGuard(root).resolve(accepted_path))
        self.workbench_repository.upsert_chapter(root, chapter)
        review = None
        patch_path = ""
        try:
            patch = self._post_chapter_service().build_review_and_patch(root, chapter_id)
            patch_path = self._post_chapter_service().patch_path(chapter_id)
            review = self._review_item(
                request.bookId,
                chapter_id,
                f"review-post-{chapter_id}",
                f"第 {chapter_id} 章接收后复盘",
                "中",
                ["承接", "记忆更新", "后续钩子"],
                f"本章已接收，可继续查看 {patch.sourceReview} 和记忆更新候选。",
                status="待处理",
            )
        except FileNotFoundError:
            review = None
        return {
            "bookId": request.bookId,
            "chapter": chapter,
            "gate": {
                "status": gate.status,
                "score": gate.score,
                "issues": [
                    {
                        "severity": issue.severity,
                        "stage": issue.stage,
                        "type": issue.type,
                        "message": issue.message,
                        "evidence": issue.evidence,
                        "textSnippet": issue.textSnippet,
                        "suggestionHint": issue.suggestionHint,
                    }
                    for issue in gate.issues[:6]
                ],
                "recommendedNextAction": gate.recommendedNextAction,
            },
            "review": review,
            "patchPath": patch_path,
        }

    def _gate_recovery_payload(self, chapter_id: str, gate: Any) -> dict[str, Any]:
        navigation = self.issue_navigation_service.build_navigation(
            chapter_id,
            {"gate": gate.model_dump(mode="json")},
        )
        return GateRecoveryService().recovery_plan(gate, navigation)

    def create_next_chapter(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapters = self._chapters_for_root(root)
        latest_chapter = chapters[-1] if chapters else None
        if latest_chapter and str(latest_chapter.get("status") or "") != "完成":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{latest_chapter.get('title') or '当前章节'}尚未正式完稿。"
                    "请先完成正文、通过接收前检查并正式接收，再开始下一章。"
                ),
            )
        next_id = self.project_service.next_chapter_id(root)
        title = f"第{int(next_id)}章 待命名章节"
        self.project_service.create_chapter(root, next_id, title=title)
        self._write_chapter_status(root, next_id, "待写")
        chapter = self._chapter_for_file(root, PathGuard(root).resolve(f"chapters/{next_id}.md"))
        self.workbench_repository.upsert_chapter(root, chapter)
        return {"chapter": chapter}

    def apply_review_repair(self, request: ApplyReviewRepairRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        relative_path = f"chapters/{chapter_id}.md"
        current = self.project_service.read_text(root, relative_path)
        self.project_service.write_text(
            root, relative_path, f"{current.rstrip()}\n\n{request.repairText.strip()}\n"
        )
        self._write_chapter_status(root, chapter_id, "草稿")
        chapter = self._chapter_for_file(root, PathGuard(root).resolve(relative_path))
        self.workbench_repository.upsert_chapter(root, chapter)
        return {"bookId": request.bookId, "reviewId": request.reviewId, "chapter": chapter}

    def run_reviews(self, request: RunReviewsRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(
            request.chapterId or self._latest_chapter_id(root)
        )
        source = f"chapters/{chapter_id}.md"
        reviews: list[dict[str, Any]] = []
        try:
            quality = self.writing_quality_service.evaluate_chapter(
                root,
                chapter_id,
                draft_path=source,
            )
            reviews.extend(
                self._quality_reviews(request.bookId, chapter_id, quality.issues, quality.score)
            )
        except FileNotFoundError as exc:
            reviews.append(
                self._review_item(
                    request.bookId,
                    chapter_id,
                    f"review-{chapter_id}-quality-source",
                    f"第 {chapter_id} 章审稿准备不足",
                    "高",
                    ["正文", "章节合同"],
                    f"重新审稿缺少必要文件：{exc.filename or source}。请先准备本章或保存草稿。",
                )
            )
        try:
            editorial = self.editorial_review_service.review_chapter(
                root,
                chapter_id,
                draft_path=source,
            )
            reviews.extend(
                self._editorial_reviews(
                    request.bookId, chapter_id, editorial.issues, editorial.score
                )
            )
        except FileNotFoundError:
            # Gate/readiness already reports missing contracts; avoid duplicate noisy cards.
            pass
        gate = self.chapter_gate_service.check_chapter(root, chapter_id)
        reviews.extend(self._gate_reviews(request.bookId, chapter_id, gate.issues, gate.score))
        if not reviews:
            reviews.append(
                self._review_item(
                    request.bookId,
                    chapter_id,
                    f"review-{chapter_id}-pass",
                    f"第 {chapter_id} 章审稿通过",
                    "低",
                    ["节奏", "线索", "接收"],
                    "本轮写作质量、编辑审查和 gate 未发现阻断项，可以进入接收或导出前检查。",
                    status="已确认",
                )
            )
        next_reviews = self.review_service.apply_states(root, reviews[:8])
        if self._stored_chapter_status(root, chapter_id) != "完成":
            self._write_chapter_status(root, chapter_id, "审阅")
        self.review_service.write_inbox(root, chapter_id, next_reviews)
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "reviews": next_reviews,
        }

    def book_reviews(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id, reviews = self.review_service.read_inbox(root)
        if reviews:
            return {
                "bookId": book_id,
                "chapterId": chapter_id or self._latest_chapter_id(root),
                "reviews": reviews,
            }
        fallback_reviews = self.reviews_for_root(root)
        fallback_chapter_id = (
            fallback_reviews[0]["chapterId"] if fallback_reviews else self._latest_chapter_id(root)
        )
        return {
            "bookId": book_id,
            "chapterId": fallback_chapter_id,
            "reviews": fallback_reviews,
        }

    def update_review_status(self, request: PatchReviewRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        review_id = request.reviewId.strip()
        if not review_id:
            raise HTTPException(status_code=400, detail="缺少审稿项编号。")
        states = self.review_service.read_states(root)
        states[review_id] = request.status
        self.review_service.write_states(root, states)
        inbox_chapter_id, inbox_reviews = self.review_service.read_inbox(root)
        patched_inbox = (
            self.review_service.apply_states(root, inbox_reviews) if inbox_reviews else []
        )
        review = next((item for item in patched_inbox if item["id"] == review_id), None)
        if review is not None and inbox_chapter_id:
            self.review_service.write_inbox(root, inbox_chapter_id, patched_inbox)
        if review is None:
            review = next(
                (
                    item
                    for item in self.review_service.apply_states(root, self.reviews_for_root(root))
                    if item["id"] == review_id
                ),
                None,
            )
        if review is None:
            review = self._review_item(
                request.bookId,
                "",
                review_id,
                "审稿项状态已更新",
                "中",
                ["状态"],
                "该审稿项来自最近一次审稿结果，状态已保存到当前书工作台。",
                status=request.status,
            )
        return {"bookId": request.bookId, "review": review}

    def chapter_memory_updates(self, request: ListChapterMemoryUpdatesRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        chapter_id = self.project_service.normalize_chapter_id(request.chapterId)
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "memoryUpdates": self._memory_updates_for_chapter(root, request.bookId, chapter_id),
        }

    def apply_memory_update(
        self, update_id: str, request: ApplyMemoryUpdateRequest
    ) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        normalized_update_id = update_id.strip()
        if not normalized_update_id:
            raise HTTPException(status_code=400, detail="缺少记忆更新编号。")
        chapter_id = self._chapter_id_from_memory_update(
            normalized_update_id,
            request.chapterId,
        )
        updates = self._memory_updates_for_chapter(root, request.bookId, chapter_id)
        selected = next(
            (item for item in updates if str(item.get("id")) == normalized_update_id),
            None,
        )
        if selected is None:
            raise HTTPException(
                status_code=404,
                detail=f"找不到记忆更新：{normalized_update_id}",
            )
        if not bool(selected.get("canApply")):
            raise HTTPException(
                status_code=409,
                detail=str(selected.get("blockedReason") or "当前候选不能直接应用。"),
            )
        service = self._post_chapter_service()
        patch = service.read_canon_patch(root, chapter_id)
        operation = next(
            (item for item in patch.operations if item.id == normalized_update_id),
            None,
        )
        if operation is None:
            raise HTTPException(
                status_code=404,
                detail=f"找不到记忆更新：{normalized_update_id}",
            )
        if operation.status != "applied":
            service.accept_canon_patch(root, chapter_id, operation_ids=[normalized_update_id])
            service.apply_canon_patch(root, chapter_id)
        refreshed = self._memory_updates_for_chapter(root, request.bookId, chapter_id)
        applied = next(
            (item for item in refreshed if str(item.get("id")) == normalized_update_id),
            selected,
        )
        return {
            "bookId": request.bookId,
            "chapterId": chapter_id,
            "memoryUpdate": applied,
            "summary": f"已应用记忆更新：{applied.get('title') or normalized_update_id}",
        }

    def library_relationships(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        graph = self.relationship_graph_service.build_graph(root)
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        return {
            "bookId": book_id,
            "nodeCount": int(graph.get("nodeCount") or 0),
            "edgeCount": int(graph.get("edgeCount") or 0),
            "edges": [
                {
                    "id": str(edge.get("id") or ""),
                    "fromLabel": self._character_label_from_id(
                        root,
                        str(edge.get("fromCharacterId") or "")
                    ),
                    "toLabel": self._character_label_from_id(
                        root,
                        str(edge.get("toCharacterId") or ""),
                    ),
                    "type": self._relationship_type_label(str(edge.get("type") or "")),
                    "status": str(edge.get("latestStatus") or ""),
                    "pressure": str(edge.get("latestPressure") or ""),
                    "chapterId": str(edge.get("latestChapterId") or ""),
                    "eventCount": int(edge.get("eventCount") or 0),
                    "transition": str(edge.get("latestTransition") or ""),
                }
                for edge in edges
                if isinstance(edge, dict)
            ],
        }

    def library_relationship_detail(self, book_id: str, edge_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        detail = self.relationship_graph_service.edge_detail(root, edge_id)
        edge = detail.get("edge") if isinstance(detail.get("edge"), dict) else {}
        timeline = detail.get("timeline") if isinstance(detail.get("timeline"), list) else []
        return {
            "bookId": book_id,
            "edge": {
                "id": str(edge.get("id") or ""),
                "fromLabel": self._character_label_from_id(
                    root,
                    str(edge.get("fromCharacterId") or ""),
                ),
                "toLabel": self._character_label_from_id(
                    root,
                    str(edge.get("toCharacterId") or ""),
                ),
                "type": self._relationship_type_label(str(edge.get("type") or "")),
                "status": str(edge.get("latestStatus") or ""),
                "pressure": str(edge.get("latestPressure") or ""),
                "unresolvedEmotion": str(edge.get("latestUnresolvedEmotion") or ""),
                "chapterId": str(edge.get("latestChapterId") or ""),
            },
            "timeline": [
                {
                    "eventId": str(item.get("eventId") or ""),
                    "chapterId": str(item.get("chapterId") or ""),
                    "status": str(item.get("status") or item.get("statusPreview") or ""),
                    "pressure": str(item.get("pressure") or item.get("pressurePreview") or ""),
                    "unresolvedEmotion": str(
                        item.get("unresolvedEmotion") or item.get("unresolvedEmotionPreview") or ""
                    ),
                    "transition": str(item.get("transition") or ""),
                    "quantifiedScore": float(item.get("quantifiedScore") or 5.0),
                    "scoreDelta": float(item.get("scoreDelta") or 0.0),
                    "evidence": [
                        str(value) for value in item.get("evidence", []) if str(value).strip()
                    ],
                    "signals": [
                        str(value) for value in item.get("signals", []) if str(value).strip()
                    ],
                    "needsReview": bool(item.get("needsReview")),
                    "reviewReason": str(item.get("reviewReason") or ""),
                }
                for item in timeline
                if isinstance(item, dict)
            ],
            "reviewSummary": detail.get("reviewSummary", {}),
        }

    def update_library_relationship_event(
        self,
        book_id: str,
        event_id: str,
        request: UpdateRelationshipEventRequest,
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        updated = self.relationship_graph_service.update_relationship_event(
            root,
            event_id,
            relationship_type=request.type,
            status=request.status,
            pressure=request.pressure,
            unresolved_emotion=request.unresolvedEmotion,
            evidence=request.evidence,
        )
        edge = updated.get("edge") if isinstance(updated.get("edge"), dict) else {}
        return {
            "bookId": book_id,
            "eventId": event_id,
            "edge": {
                "id": str(edge.get("id") or ""),
                "fromLabel": self._character_label_from_id(
                    root,
                    str(edge.get("fromCharacterId") or ""),
                ),
                "toLabel": self._character_label_from_id(
                    root,
                    str(edge.get("toCharacterId") or ""),
                ),
                "type": self._relationship_type_label(str(edge.get("type") or "")),
                "status": str(edge.get("latestStatus") or ""),
                "pressure": str(edge.get("latestPressure") or ""),
                "unresolvedEmotion": str(edge.get("latestUnresolvedEmotion") or ""),
                "chapterId": str(edge.get("latestChapterId") or ""),
            },
            "summary": "已更新关系事件状态。",
        }

    def _relationship_type_label(self, value: str) -> str:
        labels = {
            "alliance": "同盟",
            "family": "亲情",
            "friendship": "友情",
            "mentorship": "师徒",
            "rivalry": "竞争",
            "romance": "情感",
            "other": "其他",
        }
        normalized = value.strip()
        return labels.get(normalized.lower(), normalized or "关系")

    def library_topic_detail(
        self, book_id: str, topic_id: str, chapter_id: str = ""
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        detail = self.memory_topic_service.topic_detail(root, topic_id, chapter_id or None)
        topic = detail.get("topic") if isinstance(detail.get("topic"), dict) else {}
        return {
            "bookId": book_id,
            "topicId": str(detail.get("topicId") or topic_id),
            "topic": {
                "title": str(topic.get("title") or topic.get("label") or topic_id),
                "summary": str(topic.get("summary") or ""),
                "kind": str(topic.get("kind") or ""),
                "keywords": [
                    str(value) for value in detail.get("keywords", []) if str(value).strip()
                ],
            },
            "relatedEntities": detail.get("relatedEntities", []),
            "relatedTopics": detail.get("relatedTopics", []),
            "writingGuidance": detail.get("writingGuidance", []),
            "contextStatus": detail.get("contextStatus", {}),
        }

    def library_timeline(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        memory = self.project_service.read_timeline_events(root)
        return {
            "bookId": book_id,
            "eventCount": len(memory.events),
            "events": [
                {
                    "id": event.id,
                    "chapterId": event.chapterId,
                    "label": event.label,
                    "summary": event.summary,
                    "time": event.time,
                    "source": event.source,
                }
                for event in memory.events
            ],
        }

    def sync_library_timeline(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        memory = self.project_service.sync_timeline_events_from_markdown(root)
        return {
            "bookId": book_id,
            "eventCount": len(memory.events),
            "events": [
                {
                    "id": event.id,
                    "chapterId": event.chapterId,
                    "label": event.label,
                    "summary": event.summary,
                    "time": event.time,
                    "source": event.source,
                }
                for event in memory.events
            ],
            "summary": f"已同步时间线，共 {len(memory.events)} 条事件。",
        }

    def check_export(self, request: ExportWorkbenchRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        readiness = self._export_readiness(root, request.kind)
        return {"bookId": request.bookId, "readiness": readiness}

    def training_export_readiness(self, book_id: str = "") -> dict[str, Any]:
        root = self._target_root(book_id)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可导出训练数据的作品。")
        return self._export_readiness(root, "训练数据")

    def generate_export(self, request: ExportWorkbenchRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        readiness = self._export_readiness(root, request.kind)
        try:
            output = self.workbench_export_service.write_export(
                root,
                request.kind,
                self._export_reviews_for_root(root),
                self.materials_for_root(root),
                training_chapter_ids=request.trainingChapterIds,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result_name = output.name
        return {
            "bookId": request.bookId,
            "kind": request.kind,
            "resultName": result_name,
            "summary": f"{request.kind}已生成：{result_name}。",
            "readiness": {**readiness, "resultName": result_name},
        }

    def jobs_for_book(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        return {"bookId": book_id, "jobs": self.jobs_for_root(root)}

    def job_detail(self, book_id: str, job_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            job = JobController().get_job(root, job_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = self._job_summary(root, job)
        return {
            "bookId": book_id,
            "job": summary,
            "detail": {
                "title": summary["title"],
                "status": summary["status"],
                "summary": summary["result"],
                "events": self._job_events(job),
                "startedAt": summary["startedAt"],
                "finishedAt": self._short_datetime(job.finishedAt) if job.finishedAt else "",
            },
        }

    def job_events(self, book_id: str, job_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            job = JobController().get_job(root, job_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": book_id, "jobId": job_id, "events": self._job_events(job)}

    def runs_for_book(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        return {"bookId": book_id, "runs": self.runs_for_root(root)}

    def diff_for_book(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = self._latest_chapter_id(root)
        left_path = f"chapters/{chapter_id}.md"
        right_path = self._preferred_diff_target_path(root, chapter_id)
        if right_path == left_path:
            return {
                "bookId": book_id,
                "chapterId": chapter_id,
                "changed": False,
                "summary": "当前章节还没有可比较的候选稿。",
                "diff": "",
            }
        left_text = self.project_service.read_text(root, left_path)
        right_text = self.project_service.read_text(root, right_path)
        diff_text = TextDiffService().unified(left_text, right_text, left_path, right_path)
        additions = sum(
            1
            for line in diff_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        removals = sum(
            1
            for line in diff_text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        )
        changed = bool(diff_text.strip())
        if not changed:
            summary = "候选稿和当前正文没有可见差异。"
        else:
            summary = f"候选稿相对当前正文新增 {additions} 行，删除 {removals} 行。"
        return {
            "bookId": book_id,
            "chapterId": chapter_id,
            "changed": changed,
            "summary": summary,
            "diff": diff_text,
        }

    def diagnostics_for_book(self, book_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = self._latest_chapter_id(root)
        draft_path = self._preferred_diff_target_path(root, chapter_id)
        issues: list[str] = []
        try:
            continuity = ContinuityService().check_draft(root, chapter_id, draft_path=draft_path)
            issues.extend([issue.message for issue in continuity.issues[:4]])
        except (FileNotFoundError, ValueError) as exc:
            issues.append(f"连续性检查暂时不可用：{exc}")
            continuity = None
        try:
            gate = self.chapter_gate_service.check_chapter(root, chapter_id, draft_path=draft_path)
            issues.extend([issue.message for issue in gate.issues[:4]])
        except (FileNotFoundError, ValueError) as exc:
            issues.append(f"章节 gate 暂时不可用：{exc}")
            gate = None
        navigation = IssueNavigationService().build_navigation(
            chapter_id,
            {"continuity": continuity, "gate": gate},
        )
        issues.extend(
            [str(item.get("suggestedAction") or "") for item in navigation.get("items", [])[:3]]
        )
        issues = [*self._data_truth_diagnostics(root, chapter_id), *issues]
        deduped = [item for item in self._unique_nonempty(issues) if item][:6]
        return {
            "bookId": book_id,
            "chapterId": chapter_id,
            "summary": f"已汇总 {len(deduped)} 条诊断提示。",
            "items": deduped,
        }

    def _data_truth_diagnostics(self, root: Path, chapter_id: str) -> list[str]:
        coverage = self.workbench_repository.coverage_counts(root)
        chapter_files = self._chapter_file_count(root)
        stored_materials = len(self.material_service.read_store(root))
        _, inbox_reviews = self.review_service.read_inbox(root)
        run_count = len(self.project_service.list_runs(root, limit=50))
        memory_update_count = self._memory_update_file_count(root, chapter_id)
        items = [
            (
                "数据真源：SQLite 已覆盖章节 "
                f"{coverage['chapters']} 条、合同 {coverage['sceneContracts']} 条、"
                f"上下文包 {coverage['contextPacks']} 条；章节正文文件 {chapter_files} 个。"
            ),
            (
                "数据真源：生成状态"
                + ("已进入 SQLite。" if coverage["hasGenerationState"] else "尚未写入 SQLite。")
            ),
            (
                "数据真源：SQLite 已覆盖资料 "
                f"{coverage['materials']} 条、审稿 inbox {coverage['reviewInbox']} 条、"
                f"审稿状态 {coverage['reviewStates']} 条、记忆更新 {coverage['memoryUpdates']} 条、"
                f"运行摘要 {coverage['runs']} 条。"
            ),
            (
                "兼容文件：资料 "
                f"{stored_materials} 条、审稿 inbox {len(inbox_reviews)} 条、"
                f"记忆候选文件 {memory_update_count} 个、运行记录 {run_count} 条；"
                "完整运行证据和长期记忆落点继续保留在项目文件中。"
            ),
        ]
        return items

    def _chapter_file_count(self, root: Path) -> int:
        return len(
            [
                path
                for path in self.project_service.list_paths(root, "chapters")
                if path.endswith(".md")
            ]
        )

    def _memory_update_file_count(self, root: Path, chapter_id: str) -> int:
        service = self._post_chapter_service()
        candidates = [service.review_path(chapter_id), service.patch_path(chapter_id)]
        return sum(
            1 for candidate in candidates if self.project_service.file_exists(root, candidate)
        )

    def maintenance_action(
        self, book_id: str, action: str, request: MaintenanceActionRequest
    ) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        chapter_id = self.project_service.normalize_chapter_id(
            request.chapterId or self._latest_chapter_id(root)
        )
        action_key = action.strip()
        if action_key == "rebuild-context-pack":
            context_pack = self._build_context_pack(root, chapter_id)
            return {
                "bookId": book_id,
                "action": action_key,
                "chapterId": chapter_id,
                "title": "重建资料索引",
                "summary": (
                    f"已为第 {chapter_id} 章重建上下文包，纳入 "
                    f"{len(context_pack.included)} 项资料。"
                ),
                "items": [
                    f"上下文包：{context_pack.path}",
                    f"纳入资料 {len(context_pack.included)} 项",
                    f"预计 tokens {context_pack.estimatedTokens}",
                ],
            }
        if action_key == "refresh-diagnostics":
            diagnostics = self.diagnostics_for_book(book_id)
            return {
                "bookId": book_id,
                "action": action_key,
                "chapterId": diagnostics["chapterId"],
                "title": "刷新诊断缓存",
                "summary": diagnostics["summary"],
                "items": diagnostics["items"],
            }
        if action_key == "rebuild-review-inbox":
            review_result = self.run_reviews(
                RunReviewsRequest(bookId=book_id, chapterId=chapter_id)
            )
            return {
                "bookId": book_id,
                "action": action_key,
                "chapterId": review_result["chapterId"],
                "title": "重建最新审稿结果",
                "summary": (
                    f"已刷新第 {review_result['chapterId']} 章审稿 inbox，共 "
                    f"{len(review_result['reviews'])} 条。"
                ),
                "items": [str(item.get("title") or "") for item in review_result["reviews"][:4]],
            }
        raise HTTPException(status_code=404, detail=f"不支持的维护操作：{action_key}")

    def cancel_job(self, book_id: str, job_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        try:
            job = JobController().request_cancel(root, job_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": book_id, "job": self._job_summary(root, job)}

    def retry_job(self, book_id: str, job_id: str) -> dict[str, Any]:
        root = self._root_from_book_id(book_id)
        controller = JobController()
        try:
            original = controller.get_job(root, job_id)
            work = self._retry_job_work(root, original)
            if work is None:
                retry = controller._create(  # noqa: SLF001 - unsupported old jobs are recorded for manual handling.
                    root,
                    kind="revision-rerun",
                    title=f"重试：{original.title or original.kind}",
                    detail=original.detail or "重试任务已创建，等待处理。",
                    retry_of_job_id=original.jobId,
                    params=original.params,
                )
            else:
                retry = controller.retry_job(root, job_id, work)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"bookId": book_id, "job": self._job_summary(root, retry)}

    def _retry_job_work(self, root: Path, original: Any) -> Any | None:
        params = original.params if isinstance(original.params, dict) else {}
        if original.kind == "calibration-rescore":
            thresholds = self.workbench_repository.read_quality_thresholds(root)
            return lambda current_job: self.calibration_service._run_rescore(  # noqa: SLF001
                root,
                thresholds,
                current_job,
            )
        if original.kind == "local-training":
            return lambda current_job: self.local_training_service.run_local_tuning(
                root,
                backend=str(params.get("backend") or "custom"),
                base_model=str(params.get("baseModel") or ""),
                output_dir=str(params.get("outputDir") or "models/adapters/latest"),
                model_profile_id=str(params.get("modelProfileId") or "latest-trained"),
                inference_command_template=str(params.get("inferenceCommandTemplate") or "")
                or None,
                min_examples=int(params.get("minExamples") or 0),
                train_command=str(params.get("trainCommand") or "") or None,
                force=bool(params.get("force")),
                timeout_seconds=int(params.get("timeoutSeconds") or 3600),
                cancel_check=lambda: JobController().is_cancel_requested(root, current_job.jobId),
            )
        return None

    async def agent_assist(self, request: AgentAssistRequest) -> dict[str, Any]:
        root = self._root_from_book_id(request.bookId)
        role = self._agent_role(request)
        try:
            result = await self.ai_runtime_service.complete(
                role=role,
                prompt=self._agent_prompt(request),
                root=root.as_posix(),
                action=request.action,
                bypass_cache=request.bypassCache,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"请先到模型页给{self._role_label(role)}分配可用 AI 账号。",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            **self._agent_response_from_output(request, result.text),
            "usage": result.usage.payload(),
            "accountName": result.account.name,
            "cacheHit": result.cache_hit,
            "compressed": result.compressed,
        }

    async def stream_agent_assist(
        self,
        request: AgentAssistRequest,
        is_disconnected: Any | None = None,
    ) -> StreamingResponse:
        root = self._root_from_book_id(request.bookId)
        role = self._agent_role(request)

        async def events():
            stream = None
            try:
                stream = self.ai_runtime_service.stream(
                    role=role,
                    prompt=self._agent_prompt(request),
                    root=root.as_posix(),
                    action=request.action,
                    bypass_cache=request.bypassCache,
                )
                async for item in stream:
                    if is_disconnected is not None and await is_disconnected():
                        await stream.aclose()
                        stream = None
                        return
                    if item.event == "done":
                        result = item.data["result"]
                        response = {
                            **self._agent_response_from_output(request, result.text),
                            "usage": result.usage.payload(),
                            "accountName": result.account.name,
                            "cacheHit": result.cache_hit,
                            "compressed": result.compressed,
                        }
                        yield _workbench_sse_event("done", response)
                    else:
                        yield _workbench_sse_event(item.event, item.data)
            except FileNotFoundError:
                yield _workbench_sse_event(
                    "error",
                    {"message": f"请先到模型页给{self._role_label(role)}分配可用 AI 账号。"},
                )
            except RuntimeError as exc:
                yield _workbench_sse_event("error", {"message": str(exc)})
            finally:
                if stream is not None:
                    await stream.aclose()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    def ai_settings(self) -> dict[str, Any]:
        return self.ai_runtime_service.settings()

    def save_ai_account(
        self,
        request: AIAccountRequest,
        account_id: str = "",
    ) -> dict[str, Any]:
        try:
            account = self.ai_runtime_service.save_account(
                account_id=account_id,
                name=request.name,
                purpose=request.purpose,
                base_url=request.baseUrl,
                api_key=request.apiKey,
                model=request.model,
                protocol=request.protocol,
                max_context_tokens=request.maxContextTokens,
                enabled=request.enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"account": account, "settings": self.ai_runtime_service.settings()}

    def delete_ai_account(self, account_id: str) -> dict[str, Any]:
        try:
            self.ai_runtime_service.delete_account(account_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="AI 账号不存在。") from exc
        return {"removed": True, "settings": self.ai_runtime_service.settings()}

    def bind_ai_roles(self, request: AIRoleBindingsRequest) -> dict[str, Any]:
        try:
            self.ai_runtime_service.bind_roles(
                request.writingAccountId,
                request.reviewAccountId,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="所选 AI 账号不存在。") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.ai_runtime_service.settings()

    async def probe_ai_account(self, account_id: str) -> dict[str, Any]:
        try:
            return await self.ai_runtime_service.probe(account_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="AI 账号不存在。") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def probe_ai_configuration(
        self,
        request: AIAccountConnectionRequest,
    ) -> dict[str, Any]:
        try:
            return await self.ai_runtime_service.probe_configuration(
                account_id=request.accountId,
                base_url=request.baseUrl,
                api_key=request.apiKey,
                model=request.model,
                protocol=request.protocol,
                max_context_tokens=request.maxContextTokens,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def discover_ai_models(
        self,
        request: AIAccountConnectionRequest,
    ) -> dict[str, Any]:
        try:
            models = await self.ai_runtime_service.discover_models(
                account_id=request.accountId,
                base_url=request.baseUrl,
                api_key=request.apiKey,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"models": models}

    def _agent_role(self, request: AgentAssistRequest) -> AIRole:
        return "review" if request.scope == "review" else "writing"

    def _role_label(self, role: AIRole) -> str:
        return "审核角色" if role == "review" else "写作角色"

    def _agent_response_from_output(
        self,
        request: AgentAssistRequest,
        output: str,
    ) -> dict[str, Any]:
        material = self._material_candidate(request)
        if material is not None:
            material = {
                **material,
                "summary": output or material["summary"],
                "confidence": max(int(material["confidence"]), 78),
            }
        return {
            "title": f"AI 辅助 · {request.action}",
            "content": output or "AI 已生成候选建议。",
            "suggestions": ["先审阅候选", "确认是否影响当前章节", "再写入资料或章节"],
            "candidateText": output,
            "material": material,
        }

    def book_for_root(self, root: Path) -> dict[str, Any]:
        project = self.project_service.open_project(root)
        summary = self.plan_service.summarize(root)
        chapters = self._chapters_for_root(root)
        model_id = self._selected_model_id(root)
        genre = (
            " / ".join(project.metadata.genre) if project.metadata.genre else summary.plan.platform
        )
        tagline = (
            self._first_nonempty_line(root, "notes/ideas.md")
            or "通过 AI 辅助推进章节、资料和审稿闭环。"
        )
        return {
            "id": root.as_posix(),
            "title": project.metadata.title,
            "genre": genre,
            "platform": summary.plan.platform or "generic",
            "styleProfileId": self._style_profile_id(root),
            "styleProfileLabel": self._style_profile_label(root),
            "tagline": tagline,
            "progress": summary.chapterProgressPercent,
            "updatedAt": self._short_date(project.metadata.updatedAt.isoformat()),
            "nextAction": self._next_action(root, chapters),
            "currentModelId": model_id,
            "writingPlan": {
                "targetChapterCount": summary.plan.targetChapterCount,
                "targetWordsPerChapter": summary.plan.targetWordsPerChapter,
                "targetChaptersPerPlot": summary.plan.targetChaptersPerPlot,
            },
            "qualitySummary": self._quality_summary(root, chapters),
            "arcs": self._arc_summaries(root),
            "memoryInspection": self._memory_inspection(root),
            "chapters": chapters,
        }

    def _quality_summary(self, root: Path, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        completed = [chapter for chapter in chapters if chapter.get("status") == "完成"]
        scores = [
            int(chapter.get("qualityScore") or 0)
            for chapter in completed
            if int(chapter.get("qualityScore") or 0) > 0
        ]
        recent_scores = [
            int(chapter.get("qualityScore") or 0)
            for chapter in completed[-5:]
            if int(chapter.get("qualityScore") or 0) > 0
        ]
        try:
            readiness = self.export_service.training_readiness(root)
            eligible_count = readiness.eligibleCount
        except (FileNotFoundError, ValueError):
            eligible_count = 0
        training_jobs = [
            job for job in JobController().list_jobs(root, limit=20) if job.kind == "local-training"
        ]
        latest_training = (
            training_jobs[0].finishedAt or training_jobs[0].startedAt if training_jobs else None
        )
        return {
            "completedChapterCount": len(completed),
            "targetChapterCount": self.plan_service.summarize(root).plan.targetChapterCount,
            "averageQualityScore": round(sum(scores) / len(scores)) if scores else 0,
            "recentAverageQualityScore": (
                round(sum(recent_scores) / len(recent_scores)) if recent_scores else 0
            ),
            "trainingEligibleCount": eligible_count,
            "lastTrainingRunAt": self._short_datetime(latest_training) if latest_training else "",
            "coherenceScore": self._coherence_score(root),
            "tensionPoints": self._tension_points(root, chapters),
        }

    def _coherence_score(self, root: Path) -> int:
        issue_count = 0
        for relative_path in self.project_service.list_paths(root, "runs"):
            if not Path(relative_path).name.startswith(
                "writing-quality-"
            ) or not relative_path.endswith(".json"):
                continue
            data = self._read_json(root, relative_path)
            issues = data.get("issues") if isinstance(data.get("issues"), list) else []
            issue_count += sum(
                1
                for issue in issues
                if isinstance(issue, dict)
                and issue.get("type") in {"emotional_discontinuity", "character_name_inconsistency"}
            )
        materials = self._generated_materials(root)
        issue_count += sum(1 for material in materials if material.get("dueStatus") == "overdue")
        relationships = self.relationship_graph_service.build_graph(root)
        edges = relationships.get("edges") if isinstance(relationships.get("edges"), list) else []
        issue_count += sum(1 for edge in edges if edge.get("needsReview"))
        return max(0, 100 - issue_count * 12)

    def _tension_points(self, root: Path, chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for chapter in chapters[-20:]:
            chapter_id = str(chapter.get("id") or "")
            quality = self._read_json(root, f"runs/writing-quality-{chapter_id}.json")
            metrics = quality.get("metrics") if isinstance(quality.get("metrics"), dict) else {}
            conflict = int(metrics.get("conflictMarkers") or 0)
            score = int(quality.get("score") or chapter.get("qualityScore") or 0)
            points.append(
                {
                    "chapterId": chapter_id,
                    "qualityScore": score,
                    "conflictMarkers": conflict,
                    "warning": conflict < 2,
                }
            )
        return points

    def _arc_summaries(self, root: Path) -> list[dict[str, Any]]:
        arcs: list[dict[str, Any]] = []
        current_chapter = self._latest_chapter_id(root)
        for relative_path in self.project_service.list_paths(root, "story/arc-contracts"):
            if not relative_path.endswith(".json"):
                continue
            try:
                data = json.loads(self.project_service.read_text(root, relative_path))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            start, end = self._parse_chapter_range(str(data.get("chapterRange") or ""))
            progress = 0
            if start and end and current_chapter.isdigit():
                current = int(current_chapter)
                progress = round(
                    (min(max(current, start), end) - start + 1) * 100 / (end - start + 1)
                )
            arcs.append(
                {
                    "arcId": str(data.get("arcId") or Path(relative_path).stem),
                    "title": str(data.get("title") or Path(relative_path).stem),
                    "chapterRange": str(data.get("chapterRange") or ""),
                    "arcGoal": str(data.get("arcGoal") or ""),
                    "emotionalArc": str(data.get("emotionalArc") or ""),
                    "status": str(data.get("status") or "in_progress"),
                    "progress": max(0, min(100, progress)),
                }
            )
        return arcs

    def _memory_inspection(self, root: Path) -> dict[str, Any]:
        character_memory = self._read_json(root, "memory/character-states.json")
        relationship_graph = self.relationship_graph_service.build_graph(root)
        promise_materials = [
            material
            for material in self._generated_materials(root)
            if material.get("type") == "伏笔"
        ]
        return {
            "characters": character_memory.get("characters", [])
            if isinstance(character_memory.get("characters"), list)
            else [],
            "relationships": relationship_graph,
            "promises": promise_materials,
            "arcs": self._arc_summaries(root),
        }

    def _parse_chapter_range(self, value: str) -> tuple[int | None, int | None]:
        match = re.search(r"(\d+)\D+(\d+)", value)
        if not match:
            return None, None
        return int(match.group(1)), int(match.group(2))

    def materials_for_root(self, root: Path) -> list[dict[str, Any]]:
        generated = self._generated_materials(root)
        stored = self.material_service.read_store(root)
        stored_ids = {str(item.get("id")) for item in stored}
        return [*stored, *[item for item in generated if item["id"] not in stored_ids]]

    def reviews_for_root(self, root: Path) -> list[dict[str, Any]]:
        summary = self.plan_service.summarize(root)
        next_id = summary.nextChapterId
        chapter_ids = [chapter["id"] for chapter in self._chapters_for_root(root)]
        chapter_id = chapter_ids[-1] if chapter_ids else next_id
        return self.review_service.apply_states(
            root,
            [
                {
                    "id": f"review-{chapter_id}",
                    "bookId": root.as_posix(),
                    "title": f"第 {chapter_id} 章审稿建议",
                    "status": "待处理",
                    "priority": "中",
                    "chapterId": chapter_id,
                    "focus": ["目标", "冲突", "钩子"],
                    "suggestion": (
                        "检查本章目标、阻碍、转折和结尾钩子是否清晰，避免一次性解释过多设定。"
                    ),
                }
            ],
        )

    def _workspace_reviews_for_root(self, root: Path) -> list[dict[str, Any]]:
        _, inbox_reviews = self.review_service.read_inbox(root)
        if inbox_reviews:
            return self.review_service.apply_states(root, inbox_reviews)
        return self.reviews_for_root(root)

    def _export_reviews_for_root(self, root: Path) -> list[dict[str, Any]]:
        return self._workspace_reviews_for_root(root)

    def _next_action(self, root: Path, chapters: list[dict[str, Any]]) -> str:
        latest_chapter = chapters[-1] if chapters else None
        chapter_id = str(latest_chapter.get("id") or "") if latest_chapter else ""
        chapter_title = str(latest_chapter.get("title") or chapter_id) if latest_chapter else ""
        chapter_status = str(latest_chapter.get("status") or "") if latest_chapter else ""
        reviews = self._workspace_reviews_for_root(root)
        open_reviews = [item for item in reviews if item.get("status") != "已确认"]
        materials = self.materials_for_root(root)
        ready_materials = [item for item in materials if int(item.get("confidence", 0) or 0) >= 75]
        running_job = next(
            (job for job in self.jobs_for_root(root) if job.get("status") in {"运行中", "等待中"}),
            None,
        )
        if running_job:
            return str(running_job.get("result") or running_job.get("title") or "有任务正在进行。")
        if not self._has_architecture(root):
            return "填写方向或直接生成作品架构。"
        if not self._has_blueprint(root):
            return "生成前 10 章蓝图。"
        if chapter_status == "完成":
            return f"{chapter_title or '当前章节'} 已完成，可以开始下一章。"
        if open_reviews:
            return (
                f"先处理 {len(open_reviews)} 条待确认审稿，再决定是否接收 "
                f"{chapter_title or '当前章节'}。"
            )
        if chapter_status == "审阅":
            return f"{chapter_title or '当前章节'} 正在审阅，确认候选后再接收正文。"
        if not ready_materials:
            return f"先补齐 {chapter_title or '当前章节'} 的资料，再继续生成候选。"
        if chapter_status == "待写":
            return f"开始准备 {chapter_title or '当前章节'}，先生成候选稿。"
        if chapter_status == "草稿":
            return f"继续润色 {chapter_title or '当前章节'} 草稿，准备进入审阅。"
        if chapter_id:
            return f"继续推进第 {chapter_id} 章，先确认资料和审稿建议。"
        return "继续推进当前作品，先确认资料和审稿建议。"

    def generation_state_for_root(self, root: Path) -> dict[str, Any]:
        stored = self._read_generation_state(root)
        if stored:
            payload = self._generation_state_payload(
                root,
                stage=str(stored.get("stage") or self._derived_generation_stage(root)),
                status=str(stored.get("status") or "idle"),
                mode=self._generation_mode(stored),
                batch_target=self._generation_batch_target(stored),
                batch_done=int(stored.get("batchDone") or 0),
                auto_step_limit=self._generation_auto_step_limit(stored),
                auto_steps_used=int(stored.get("autoStepsUsed") or 0),
                active_chapter_id=str(
                    stored.get("activeChapterId") or self._latest_chapter_id(root)
                ),
                next_action=str(stored.get("nextAction") or "继续生成。"),
                blockers=self._string_list(stored.get("blockers")),
                confirmations=self._string_list(stored.get("confirmations")),
                last_result=str(stored.get("lastResult") or ""),
                active_artifact_type=str(stored.get("activeArtifactType") or ""),
                active_run_status=str(stored.get("activeRunStatus") or ""),
                source_model_label=str(stored.get("sourceModelLabel") or ""),
                retry_count=int(stored.get("retryCount") or 0),
                can_retry=bool(stored.get("canRetry")),
                can_confirm=bool(stored.get("canConfirm")),
                can_takeover=bool(stored.get("canTakeover", True)),
                recovery_summary=str(stored.get("recoverySummary") or ""),
                candidate_options=(
                    stored.get("candidateOptions")
                    if isinstance(stored.get("candidateOptions"), list)
                    else []
                ),
                selected_option_id=str(stored.get("selectedOptionId") or ""),
            )
            payload["artifact"] = self.generation_service.current_artifact(root)
            return payload
        payload = self._generation_state_payload(
            root,
            stage=self._derived_generation_stage(root),
            status="idle",
            next_action=self._next_action(root, self._chapters_for_root(root)),
            last_result="生成状态已准备。",
        )
        payload["artifact"] = self.generation_service.current_artifact(root)
        return payload

    def _generation_response(self, root: Path, author_message: str) -> dict[str, Any]:
        return {
            "generationState": self.generation_state_for_root(root),
            "book": self.book_for_root(root),
            "activeChapter": self._active_generation_chapter(root),
            "jobs": self.jobs_for_root(root),
            "runs": self.runs_for_root(root),
            "authorMessage": author_message,
            "generationArtifact": self.generation_service.current_artifact(root),
        }

    def _advance_generation_once(
        self,
        root: Path,
        *,
        mode: GenerationMode,
        batch_target: int,
        batch_done: int,
    ) -> tuple[dict[str, Any], str, bool]:
        return self.generation_service.advance_once(
            root,
            mode=mode,
            batch_target=batch_target,
            batch_done=batch_done,
        )

    def _generation_state_payload(
        self,
        root: Path,
        *,
        stage: str,
        status: str,
        mode: GenerationMode = "stage_confirm",
        batch_target: int = 1,
        batch_done: int = 0,
        auto_step_limit: int | None = None,
        auto_steps_used: int = 0,
        active_chapter_id: str = "",
        next_action: str = "",
        blockers: list[str] | None = None,
        confirmations: list[str] | None = None,
        last_result: str = "",
        active_artifact_type: str = "",
        active_run_status: str = "",
        source_model_label: str = "",
        retry_count: int = 0,
        can_retry: bool = False,
        can_confirm: bool = False,
        can_takeover: bool = True,
        recovery_summary: str = "",
        candidate_options: list[dict[str, str]] | None = None,
        selected_option_id: str = "",
    ) -> dict[str, Any]:
        stage_labels = self._generation_stage_labels()
        status_labels = self._generation_status_labels()
        mode_labels = self._generation_mode_labels()
        safe_stage = stage if stage in stage_labels else "draft"
        safe_status = status if status in status_labels else "idle"
        safe_mode = mode if mode in mode_labels else "stage_confirm"
        safe_batch_target = max(1, min(20, int(batch_target or 1)))
        default_step_limit = safe_batch_target * 7 + 8 if safe_mode == "full_auto" else 1
        safe_step_limit = (
            default_step_limit
            if auto_step_limit is None
            else max(1, min(default_step_limit, int(auto_step_limit)))
        )
        chapter_id = active_chapter_id or self._latest_chapter_id(root)
        return {
            "bookId": root.as_posix(),
            "stage": safe_stage,
            "stageLabel": stage_labels[safe_stage],
            "status": safe_status,
            "statusLabel": status_labels[safe_status],
            "interventionMode": safe_mode,
            "interventionModeLabel": mode_labels[safe_mode],
            "paused": safe_status == "paused",
            "batchTarget": safe_batch_target,
            "batchDone": max(0, int(batch_done or 0)),
            "autoStepLimit": safe_step_limit,
            "autoStepsUsed": max(0, min(safe_step_limit, int(auto_steps_used or 0))),
            "activeChapterId": chapter_id,
            "nextAction": next_action or "继续生成。",
            "blockers": blockers or [],
            "confirmations": confirmations or [],
            "lastResult": last_result,
            "activeArtifactType": active_artifact_type,
            "activeRunStatus": active_run_status,
            "sourceModelLabel": source_model_label,
            "retryCount": max(0, int(retry_count or 0)),
            "canRetry": can_retry,
            "canConfirm": can_confirm,
            "canTakeover": can_takeover,
            "recoverySummary": recovery_summary,
            "candidateOptions": candidate_options or [],
            "selectedOptionId": selected_option_id,
            "longFormPosition": self.generation_service.long_form_planning.current_position(
                root,
                chapter_id,
            ),
            "updatedAt": utc_now().isoformat(),
        }

    def _read_generation_state(self, root: Path) -> dict[str, Any]:
        stored = self.workbench_repository.read_generation_state(root)
        if stored:
            return stored
        data = self._read_json(root, self.generation_state_path)
        state = data.get("state") if isinstance(data, dict) else None
        return state if isinstance(state, dict) else {}

    def _write_generation_state(self, root: Path, state: dict[str, Any]) -> None:
        self.workbench_repository.write_generation_state(root, state)
        self.project_service.write_text(
            root,
            self.generation_state_path,
            json.dumps({"schemaVersion": 1, "state": state}, ensure_ascii=False, indent=2) + "\n",
        )

    def _generation_mode(self, state: dict[str, Any]) -> GenerationMode:
        mode = str(state.get("interventionMode") or "stage_confirm")
        return mode if mode in self._generation_mode_labels() else "stage_confirm"

    def _generation_batch_target(self, state: dict[str, Any]) -> int:
        try:
            return max(1, min(20, int(state.get("batchTarget") or 1)))
        except (TypeError, ValueError):
            return 1

    def _generation_auto_step_limit(
        self,
        state: dict[str, Any],
        *,
        mode: GenerationMode | None = None,
        batch_target: int | None = None,
    ) -> int:
        resolved_mode = mode or self._generation_mode(state)
        resolved_batch_target = batch_target or self._generation_batch_target(state)
        default_limit = resolved_batch_target * 7 + 8 if resolved_mode == "full_auto" else 1
        try:
            return max(1, min(default_limit, int(state.get("autoStepLimit") or default_limit)))
        except (TypeError, ValueError):
            return default_limit

    def _derived_generation_stage(self, root: Path) -> str:
        if not self._has_architecture(root):
            return "architecture"
        if not self._has_blueprint(root):
            return "blueprint"
        chapter = self._active_generation_chapter(root)
        status = str(chapter.get("status") or "待写")
        if status == "完成":
            return "next_chapter"
        if status == "待写":
            return "contract"
        if status == "草稿":
            return "draft"
        return "gate"

    def _active_generation_chapter(self, root: Path) -> dict[str, Any]:
        chapters = self._chapters_for_root(root)
        for chapter in reversed(chapters):
            if chapter.get("status") != "完成":
                return chapter
        return chapters[-1] if chapters else self._chapter_from_brief(root, "001", {})

    def _has_architecture(self, root: Path) -> bool:
        return self.generation_service.has_architecture(root)

    def _has_blueprint(self, root: Path) -> bool:
        return self.generation_service.has_blueprint(root)

    def _restore_scene_contract_from_repository(self, root: Path, chapter_id: str) -> bool:
        return self.generation_service.restore_scene_contract_from_repository(root, chapter_id)

    def _scene_contract_complete(self, contract: SceneContract) -> bool:
        return self.generation_service.scene_contract_complete(contract)

    def _build_context_pack(self, root: Path, chapter_id: str) -> ContextPack:
        return self.generation_service.build_context_pack(root, chapter_id)

    def _upsert_context_pack_if_exists(self, root: Path, chapter_id: str) -> None:
        self.generation_service.upsert_context_pack_if_exists(root, chapter_id)

    def _generation_stage_labels(self) -> dict[str, str]:
        return {
            "architecture": "作品架构",
            "blueprint": "章节蓝图",
            "contract": "当前章合同",
            "context": "上下文包",
            "draft": "章节草稿候选",
            "gate": "接收前检查",
            "review": "审稿与修复候选",
            "accept": "定稿接收",
            "memory": "记忆和资料更新",
            "next_chapter": "下一章准备",
        }

    def _generation_status_labels(self) -> dict[str, str]:
        return {
            "idle": "待推进",
            "running": "生成中",
            "waiting_confirm": "待确认",
            "blocked": "已阻断",
            "paused": "已暂停",
            "completed": "本次完成",
        }

    def _generation_mode_labels(self) -> dict[str, str]:
        return {
            "full_auto": "全自动",
            "stage_confirm": "阶段确认",
            "chapter_confirm": "逐章确认",
            "deep_control": "深度干预",
        }

    def _review_item(
        self,
        book_id: str,
        chapter_id: str,
        review_id: str,
        title: str,
        priority: str,
        focus: list[str],
        suggestion: str,
        status: str = "待处理",
    ) -> dict[str, Any]:
        return {
            "id": review_id,
            "bookId": book_id,
            "title": title,
            "status": status,
            "priority": priority if priority in {"高", "中", "低"} else "中",
            "chapterId": chapter_id,
            "focus": focus,
            "suggestion": suggestion,
        }

    def _quality_reviews(
        self,
        book_id: str,
        chapter_id: str,
        issues: list[Any],
        score: int,
    ) -> list[dict[str, Any]]:
        return [
            self._review_item(
                book_id,
                chapter_id,
                f"review-{chapter_id}-quality-{index}-{issue.type}",
                f"文笔质量：{issue.message[:24]}",
                self._priority_from_severity(issue.severity),
                ["文笔质量", issue.type, f"{score}分"],
                " ".join(issue.suggestions[:2]) or issue.message,
            )
            for index, issue in enumerate(issues[:4], start=1)
        ]

    def _editorial_reviews(
        self,
        book_id: str,
        chapter_id: str,
        issues: list[Any],
        score: int,
    ) -> list[dict[str, Any]]:
        return [
            self._review_item(
                book_id,
                chapter_id,
                f"review-{chapter_id}-editorial-{index}-{issue.type}",
                f"编辑审稿：{issue.message[:24]}",
                self._priority_from_severity(issue.severity),
                ["编辑审稿", issue.dimension, f"{score}分"],
                " ".join(issue.suggestions[:2]) or issue.message,
            )
            for index, issue in enumerate(issues[:4], start=1)
        ]

    def _gate_reviews(
        self,
        book_id: str,
        chapter_id: str,
        issues: list[Any],
        score: int,
    ) -> list[dict[str, Any]]:
        return [
            self._review_item(
                book_id,
                chapter_id,
                f"review-{chapter_id}-gate-{index}-{issue.stage}-{issue.type}",
                f"接收门禁：{issue.message[:24]}",
                self._priority_from_severity(issue.severity),
                ["接收门禁", issue.stage, f"{score}分"],
                issue.message,
            )
            for index, issue in enumerate(issues[:4], start=1)
        ]

    def _priority_from_severity(self, severity: str) -> str:
        if severity in {"blocker", "high"}:
            return "高"
        if severity == "medium":
            return "中"
        return "低"

    def models_for_roots(self, roots: list[Path]) -> list[dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {
            "codex-cli": {
                "id": "codex-cli",
                "name": "Codex CLI",
                "source": "builtin",
                "sourceLabel": "工作台内置",
                "status": "待验证",
                "coverage": 50,
                "purpose": "用于生成章节、资料和审稿候选。",
                "statusNote": "需要先完成一次验证，确认本机 CLI 环境可以稳定返回工作台候选。",
                "samples": ["章节续写", "资料补全", "修复建议"],
                "checks": ["候选内容结构清晰", "保留用户确认", "隐藏运行细节"],
                "actions": [
                    {
                        "key": "validate",
                        "label": "验证模型",
                        "description": "检查当前 profile 是否可供工作台使用。",
                    },
                    {
                        "key": "apply",
                        "label": "用于当前书",
                        "description": "保存为当前书默认写作模型。",
                    },
                ],
            },
        }
        for root in roots:
            registry = self.model_service.read_registry(root)
            validation_evidence = self._model_validation_evidence(root)
            for profile in registry.profiles:
                if profile.id in models:
                    continue
                is_trained = bool(profile.trainingRunPath.strip())
                can_apply = not is_trained or registry.defaultProfileId == profile.id
                checks = (
                    ["已登记训练产物", "需要多章节模型对比", "通过 promote 后才能用于当前书"]
                    if is_trained and not can_apply
                    else ["可用于当前书", "保留作者确认"]
                )
                if validation_evidence["checks"]:
                    checks = validation_evidence["checks"]
                models[profile.id] = {
                    "id": profile.id,
                    "name": profile.label or profile.id,
                    "source": "project",
                    "sourceLabel": "项目已注册",
                    "status": "可使用" if can_apply else "待验证",
                    "coverage": 80 if can_apply else 62,
                    "purpose": profile.notes or "项目已注册的本地写作模型。",
                    "statusNote": (
                        "训练产出的模型已登记，但需要先通过多章节模型对比后才能用于当前书。"
                        if is_trained and not can_apply
                        else "这类模型来自项目写作模型配置，适合直接绑定到当前书。"
                    ),
                    "samples": validation_evidence["samples"] or [profile.baseModel or "本地样本"],
                    "checks": checks,
                    "actions": self._model_actions(can_apply),
                    "recommendedNextAction": (
                        "先运行五章模型对比，确认没有质量或 gate 退化后再提升为默认模型。"
                        if is_trained and not can_apply
                        else "可以验证后用于当前书。"
                    ),
                }
        return list(models.values())

    def _model_validation_evidence(self, root: Path) -> dict[str, list[str]]:
        chapters = [
            chapter
            for chapter in self.workbench_repository.list_chapters(root)
            if str(chapter.get("status") or "") == "完成"
        ][-5:]
        scored = [chapter for chapter in chapters if int(chapter.get("qualityScore") or 0) > 0]
        if not scored:
            return {"checks": [], "samples": []}
        scores = [int(chapter.get("qualityScore") or 0) for chapter in scored]
        blockers = sum(1 for chapter in scored if str(chapter.get("gateStatus") or "") == "block")
        checks = [
            (
                f"验证章节数={len(scored)}，最低分={min(scores)}，"
                f"平均分={round(sum(scores) / len(scores))}，阻断问题数={blockers}"
            )
        ]
        checks.extend(
            (
                f"章节 {chapter.get('id')}：gate={chapter.get('gateStatus') or 'unknown'}，"
                f"质量分={int(chapter.get('qualityScore') or 0)}，"
                f"高优问题数={1 if str(chapter.get('gateStatus') or '') == 'block' else 0}"
            )
            for chapter in scored
        )
        return {
            "checks": checks,
            "samples": [str(chapter.get("id") or "") for chapter in scored],
        }

    def _model_actions(self, can_apply: bool) -> list[dict[str, str]]:
        actions = [
            {
                "key": "validate",
                "label": "验证模型",
                "description": "检查当前 profile 是否可供工作台使用。",
            },
        ]
        if can_apply:
            actions.append(
                {
                    "key": "apply",
                    "label": "用于当前书",
                    "description": "保存为当前书默认写作模型。",
                }
            )
        return actions

    def exports_for_roots(self, roots: list[Path]) -> list[dict[str, Any]]:
        return [item for root in roots for item in self.exports_for_root(root)]

    def exports_for_root(self, root: Path) -> list[dict[str, Any]]:
        return [
            self._export_readiness(root, kind)
            for kind in ["正文", "训练数据", "审稿报告", "资料包"]
        ]

    def jobs_for_roots(self, roots: list[Path]) -> list[dict[str, Any]]:
        return [job for root in roots for job in self.jobs_for_root(root)]

    def jobs_for_root(self, root: Path) -> list[dict[str, Any]]:
        return [self._job_summary(root, job) for job in JobController().list_jobs(root, limit=50)]

    def runs_for_roots(self, roots: list[Path]) -> list[dict[str, Any]]:
        return self.run_service.runs_for_roots(roots)

    def runs_for_root(self, root: Path) -> list[dict[str, Any]]:
        return self.run_service.runs_for_root(root)

    def _workspace_roots(self) -> list[Path]:
        roots = [
            Path(str(item["root"])).expanduser().resolve()
            for item in self.registry.list_projects()
            if item.get("available", True)
        ]
        if os.environ.get("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "").lower() not in {
            "1",
            "true",
            "yes",
        }:
            starter_demo_root = (
                Path.cwd() / ".open-novel" / "projects" / "starter-demo"
            ).resolve()
            roots = [
                root
                for root in roots
                if root == starter_demo_root or not self._is_temp_project_root(root)
            ]
        if roots:
            return roots
        return []

    def _ensure_starter_demo(self) -> Path:
        root = (Path.cwd() / ".open-novel" / "projects" / "starter-demo").resolve()
        if not self.project_service.project_exists(root):
            self.project_service.create_project(
                root,
                title="示例作品",
                language="zh-CN",
                database_only=True,
            )
            self._update_metadata(root, genre=["悬疑"])
            self.project_service.write_text(
                root,
                "notes/ideas.md",
                "# 创作灵感\n\n一封寄给失踪者的信，在十年后送到了主角手中。\n",
            )
            self.project_service.write_text(
                root,
                "chapters/001.md",
                (
                    "# 第一章 迟到的信\n\n"
                    "雨停后，林岚在旧邮箱里发现一封没有邮戳的信。收件人是她失踪十年的哥哥，"
                    "落款日期却是昨天。她拆开信封，里面只有一句话：不要去钟楼。\n"
                ),
            )
            self.plan_service.write_plan(
                root,
                target_chapter_count=30,
                target_words_per_chapter=2500,
                target_chapters_per_plot=6,
                platform="通用网文",
                notes="styleProfileId=generic-web-serial",
            )
            self.style_profile_service.write_project_profile_from_builtin(
                root,
                "generic-web-serial",
            )
            chapter = self._chapter_for_file(
                root,
                PathGuard(root).resolve("chapters/001.md"),
            )
            chapter["status"] = "草稿"
            chapter["progress"] = self._chapter_progress(
                root,
                "草稿",
                int(chapter["wordCount"]),
            )
            self.workbench_repository.upsert_chapter(root, chapter)
        self.registry.register_project(root)
        return root

    def _is_temp_project_root(self, root: Path) -> bool:
        temp_root = Path(tempfile.gettempdir()).resolve()
        try:
            root.relative_to(temp_root)
        except ValueError:
            return False
        return True

    def _new_project_root(self, title: str) -> Path:
        slug = self._safe_slug(title, "book")
        root = (Path.cwd() / ".open-novel" / "projects" / slug).resolve()
        if not root.exists() and not self.project_service.project_exists(root):
            return root
        index = 2
        while (root.parent / f"{slug}-{index}").exists() or self.project_service.project_exists(
            root.parent / f"{slug}-{index}"
        ):
            index += 1
        return root.parent / f"{slug}-{index}"

    def _root_from_book_id(self, book_id: str) -> Path:
        root = Path(book_id).expanduser().resolve()
        try:
            self.project_service.open_project(root)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"找不到作品：{book_id}") from exc
        return root

    def _update_metadata(
        self,
        root: Path,
        *,
        genre: list[str],
        title: str | None = None,
    ) -> None:
        metadata = NovelMetadata.model_validate_json(
            self.project_service.read_text(root, "novel.json")
        )
        updates: dict[str, Any] = {"genre": genre, "updatedAt": utc_now()}
        if title is not None:
            updates["title"] = title
        metadata = metadata.model_copy(update=updates)
        self.project_service.write_text(
            root,
            "novel.json",
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def _write_tagline(self, root: Path, tagline: str) -> None:
        lines = (
            self.project_service.read_text(root, "notes/ideas.md").splitlines()
            if self.project_service.file_exists(root, "notes/ideas.md")
            else ["# Ideas"]
        )
        content_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip() and not line.lstrip().startswith("#")
            ),
            None,
        )
        if content_index is None:
            if tagline:
                lines.extend(["", tagline])
        elif tagline:
            lines[content_index] = tagline
        else:
            lines.pop(content_index)
        self.project_service.write_text(
            root,
            "notes/ideas.md",
            "\n".join(lines).rstrip() + "\n",
        )

    def _with_style_profile_note(self, notes: str, profile_id: str) -> str:
        marker = f"styleProfileId={profile_id}"
        if re.search(r"styleProfileId=[A-Za-z0-9_-]+", notes):
            return re.sub(r"styleProfileId=[A-Za-z0-9_-]+", marker, notes)
        return "\n".join(part for part in [notes.strip(), marker] if part)

    def _chapters_for_root(self, root: Path) -> list[dict[str, Any]]:
        stored_chapters = self.workbench_repository.list_chapters(root)
        if stored_chapters:
            target_word_count = self.plan_service.summarize(
                root
            ).plan.targetWordsPerChapter
            for chapter in stored_chapters:
                original_title = str(chapter.get("title") or "")
                chapter["title"] = self._display_chapter_title(
                    str(chapter.get("id") or ""),
                    original_title,
                )
                expected_progress = calculate_chapter_progress(
                    str(chapter.get("status") or "待写"),
                    int(chapter.get("wordCount") or 0),
                    target_word_count,
                )
                progress_changed = chapter.get("progress") != expected_progress
                target_changed = chapter.get("targetWordCount") != target_word_count
                chapter["progress"] = expected_progress
                chapter["targetWordCount"] = target_word_count
                if chapter["title"] != original_title or progress_changed or target_changed:
                    self.workbench_repository.upsert_chapter(root, chapter)
            return stored_chapters
        chapter_files = [
            PathGuard(root).resolve(relative_path)
            for relative_path in self.project_service.list_paths(root, "chapters")
            if relative_path.endswith(".md")
        ]
        chapters = [self._chapter_for_file(root, path) for path in chapter_files]
        if chapters:
            for chapter in chapters:
                self.workbench_repository.upsert_chapter(root, chapter)
            return chapters
        return [
            {
                "id": "001",
                "title": "第一章",
                "status": "待写",
                "wordCount": 0,
                "progress": self._chapter_progress(root, "待写", 0),
                "targetWordCount": self._chapter_target_word_count(root),
                "summary": "等待 AI 生成首章方向。",
                "content": "",
                "tasks": ["确定本章目标", "选择出场人物", "设计结尾钩子"],
                "plotPoints": ["确定开场剧情点"],
                "people": [],
                "clues": [],
                "review": ["等待候选稿"],
            }
        ]

    def _chapter_for_file(self, root: Path, path: Path) -> dict[str, Any]:
        relative_path = path.relative_to(PathGuard(root).root).as_posix()
        text = self.project_service.read_text(root, relative_path)
        title = self._title_from_markdown(text) or path.stem
        content = self._body_without_heading(text)
        chapter_id = self.project_service.normalize_chapter_id(path.stem)
        brief = self._chapter_brief(root, chapter_id)
        word_count = self._word_count(content)
        tasks = self._chapter_tasks_from_brief(brief)
        status = self._chapter_status(root, chapter_id, word_count)
        return {
            "id": chapter_id,
            "title": self._display_chapter_title(chapter_id, title),
            "status": status,
            "wordCount": word_count,
            "progress": self._chapter_progress(root, status, word_count),
            "targetWordCount": self._chapter_target_word_count(root),
            "summary": brief.get("focus") or self._summary_from_content(content),
            "content": content or "这里是章节占位。可以先让 AI 生成目标、冲突和结尾钩子。",
            "tasks": tasks,
            "plotPoints": (
                brief.get("mustInclude") or brief.get("readerPromises") or ["本章剧情点待补充"]
            ),
            "people": self._people_for_root(root),
            "clues": brief.get("readerPromises") or brief.get("mustInclude") or [],
            "linkedMaterialIds": self._linked_material_ids_from_brief(brief),
            "review": brief.get("mustAvoid") or ["检查信息披露节奏"],
        }

    def _model_profile_label(self, root: Path, profile_id: str) -> str:
        return self.workbench_model_service.model_profile_label(root, profile_id)

    def _chapter_from_brief(
        self, root: Path, chapter_id: str, brief: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": chapter_id,
            "title": f"第{int(chapter_id)}章 待命名章节" if chapter_id.isdigit() else chapter_id,
            "status": "待写",
            "wordCount": 0,
            "progress": self._chapter_progress(root, "待写", 0),
            "targetWordCount": self._chapter_target_word_count(root),
            "summary": brief.get("focus") or "等待补全章节摘要。",
            "content": "这里是章节占位。可以先让 AI 生成目标、冲突和结尾钩子。",
            "tasks": self._chapter_tasks_from_brief(brief),
            "plotPoints": brief.get("mustInclude") or ["本章剧情点待补充"],
            "people": self._people_for_root(root),
            "clues": brief.get("readerPromises") or brief.get("mustInclude") or [],
            "linkedMaterialIds": self._linked_material_ids_from_brief(brief),
            "review": brief.get("mustAvoid") or ["检查信息披露节奏"],
        }

    def _chapter_tasks_from_brief(self, brief: dict[str, Any]) -> list[str]:
        workbench_tasks = brief.get("workbenchTasks")
        if isinstance(workbench_tasks, list):
            tasks = self._unique_nonempty(workbench_tasks)
            if tasks:
                return tasks
        return [
            value
            for value in [brief.get("goal"), brief.get("conflict"), brief.get("hook")]
            if isinstance(value, str) and value.strip()
        ] or ["明确本章目标", "制造阻碍", "留下钩子"]

    def _chapter_title(self, root: Path, chapter_id: str) -> str:
        relative_path = f"chapters/{self.project_service.normalize_chapter_id(chapter_id)}.md"
        if not self.project_service.file_exists(root, relative_path):
            return ""
        return self._title_from_markdown(self.project_service.read_text(root, relative_path))

    def _display_chapter_title(self, chapter_id: str, title: str) -> str:
        normalized_title = title.strip()
        if normalized_title.startswith("第"):
            return normalized_title
        if normalized_title == chapter_id or normalized_title == f"{chapter_id} {chapter_id}":
            number = int(chapter_id) if chapter_id.isdigit() else 1
            return f"第{number}章 待命名章节"
        return f"{chapter_id} {normalized_title}"

    def _stored_chapter_status(self, root: Path, chapter_id: str) -> str:
        repository_status = self.workbench_repository.chapter_status(root, chapter_id)
        if repository_status in {"待写", "草稿", "审阅", "完成"}:
            return repository_status
        states = self._read_json(root, self.chapter_state_path)
        chapters = states.get("chapters") if isinstance(states, dict) else None
        if not isinstance(chapters, dict):
            return ""
        status = str(chapters.get(chapter_id) or "").strip()
        return status if status in {"待写", "草稿", "审阅", "完成"} else ""

    def _latest_chapter_id(self, root: Path) -> str:
        chapters = self._chapters_for_root(root)
        return chapters[-1]["id"] if chapters else self.project_service.next_chapter_id(root)

    def _chapter_brief(self, root: Path, chapter_id: str) -> dict[str, Any]:
        relative_path = f"story/chapter-briefs/{chapter_id}.json"
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _generated_materials(self, root: Path) -> list[dict[str, Any]]:
        materials: list[dict[str, Any]] = []
        memory = self._read_json(root, "memory/long-term-memory.json")
        for entity in (
            memory.get("entityIndex", []) if isinstance(memory.get("entityIndex"), list) else []
        ):
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name") or entity.get("entityId") or "未命名人物")
            materials.append(
                self._material(
                    root,
                    f"entity-{entity.get('entityId') or name}",
                    "人物",
                    name,
                    self._topic_summary(memory, entity.get("topicIds")),
                    "可用于判断当前章节的人物动机、伤口和行动边界。",
                    ["长期记忆"],
                )
            )
        promises = self._read_json(root, "memory/promises.json")
        for promise in (
            promises.get("promises", []) if isinstance(promises.get("promises"), list) else []
        ):
            if not isinstance(promise, dict):
                continue
            text = str(promise.get("text") or "未命名伏笔")
            due_status = self._memory_due_status(promise, self._latest_chapter_id(root))
            materials.append(
                self._material(
                    root,
                    f"promise-{promise.get('id')}",
                    "伏笔",
                    text[:24],
                    text,
                    self._promise_influence(due_status),
                    ["伏笔"],
                    details={"到期状态": self._due_status_label(due_status)},
                    due_status=due_status,
                )
            )
        open_loops = self._read_json(root, "memory/open-loops.json")
        for loop in (
            open_loops.get("loops", []) if isinstance(open_loops.get("loops"), list) else []
        ):
            if not isinstance(loop, dict):
                continue
            text = str(loop.get("text") or loop.get("readerQuestion") or "未命名伏笔")
            due_status = self._memory_due_status(loop, self._latest_chapter_id(root))
            materials.append(
                self._material(
                    root,
                    f"loop-{loop.get('id')}",
                    "伏笔",
                    text[:24],
                    text,
                    self._promise_influence(due_status),
                    ["伏笔"],
                    details={"到期状态": self._due_status_label(due_status)},
                    due_status=due_status,
                )
            )
        brief_locations = self._brief_location_materials(root)
        lessons = self._read_json(root, "memory/writing-lessons.json")
        for lesson in (
            lessons.get("lessons", []) if isinstance(lessons.get("lessons"), list) else []
        ):
            if not isinstance(lesson, dict):
                continue
            materials.append(
                self._material(
                    root,
                    f"lesson-{lesson.get('id')}",
                    "写法",
                    str(lesson.get("category") or "写法经验"),
                    str(lesson.get("lesson") or ""),
                    "润色和续写时作为风格约束。",
                    ["写法经验"],
                )
            )
        return [*materials, *brief_locations]

    def _memory_due_status(self, item: dict[str, Any], chapter_id: str) -> str:
        if str(item.get("status") or "open") not in {"open", "partial"}:
            return "resolved"
        start, end = ContextPackService()._parse_payoff_window(  # noqa: SLF001
            str(item.get("expectedPayoffWindow") or "")
        )
        current = int(chapter_id) if chapter_id.isdigit() else None
        if current is None or start is None or end is None:
            return "on_track"
        if current > end:
            return "overdue"
        if current >= max(start, end - 2):
            return "at_risk"
        return "on_track"

    def _promise_influence(self, due_status: str) -> str:
        if due_status == "overdue":
            return "承诺已过期未兑现，后续章节需要优先安排回收或解释。"
        if due_status == "at_risk":
            return "承诺即将到期，后续章节需要准备兑现或推进。"
        return "提醒后续章节安排承诺兑现和误导。"

    def _due_status_label(self, due_status: str) -> str:
        return {
            "overdue": "已过期",
            "at_risk": "即将到期",
            "resolved": "已处理",
            "on_track": "正常",
        }.get(due_status, "正常")

    def _brief_location_materials(self, root: Path) -> list[dict[str, Any]]:
        materials: list[dict[str, Any]] = []
        seen: set[str] = set()
        for relative_path in self.project_service.list_paths(root, "story/chapter-briefs"):
            if not relative_path.endswith(".json"):
                continue
            chapter_id = Path(relative_path).stem
            brief = self._chapter_brief(root, chapter_id)
            location = str(brief.get("location") or "").strip()
            if not location or location in seen:
                continue
            seen.add(location)
            materials.append(
                self._material(
                    root,
                    f"location-{self._safe_slug(location, 'location')}",
                    "地点",
                    location,
                    f"{location} 是第 {chapter_id} 章的场景地点。",
                    "可以为本章提供空间压力、行动限制和可见证据。",
                    [f"第 {chapter_id} 章"],
                    details={"视觉特征": "待补充", "危险点": "待补充", "所属势力": "待补充"},
                )
            )
        return materials

    def _chapter_related_terms(
        self, root: Path, chapter_id: str, brief: dict[str, Any]
    ) -> set[str]:
        terms = {
            chapter_id.lower(),
            str(brief.get("focus") or "").lower(),
            str(brief.get("location") or "").lower(),
            *[item.lower() for item in self._people_for_root(root)],
            *[item.lower() for item in self._string_list(brief.get("mustInclude"))],
            *[item.lower() for item in self._string_list(brief.get("readerPromises"))],
            *[item.lower() for item in self._linked_material_ids_from_brief(brief)],
        }
        return {term.strip() for term in terms if term and term.strip()}

    def _material_related_score(
        self, material: dict[str, Any], related_terms: set[str], brief: dict[str, Any]
    ) -> int:
        haystack = " ".join(
            [
                str(material.get("id") or ""),
                str(material.get("title") or ""),
                str(material.get("summary") or ""),
                str(material.get("influence") or ""),
                *[str(value) for value in material.get("related", []) if str(value).strip()],
            ]
        ).lower()
        score = 0
        for term in related_terms:
            if term and term in haystack:
                score += 2
        linked_ids = self._linked_material_ids_from_brief(brief)
        if str(material.get("id") or "") in linked_ids:
            score += 4
        return score

    def _material(
        self,
        root: Path,
        material_id: str,
        material_type: MaterialType,
        title: str,
        summary: str,
        influence: str,
        related: list[str],
        details: dict[str, str] | None = None,
        due_status: str = "",
    ) -> dict[str, Any]:
        return {
            "id": material_id,
            "bookId": root.as_posix(),
            "type": material_type,
            "title": title,
            "summary": summary or "待继续补全。",
            "influence": influence,
            "related": related,
            "confidence": 72,
            "details": details,
            "dueStatus": due_status,
        }

    def _material_candidate(self, request: AgentAssistRequest) -> dict[str, Any] | None:
        if request.scope != "material" or request.materialType is None:
            return None
        title = (
            request.currentMaterial.title
            if request.currentMaterial
            else f"AI 生成{request.materialType}"
        )
        seed = request.input.strip() or title
        return {
            "id": request.materialId or f"candidate-{self._safe_slug(seed, 'material')}",
            "bookId": request.bookId,
            "type": request.materialType,
            "title": title,
            "summary": (
                f"围绕「{seed}」生成的{request.materialType}候选：补全它的目标、限制和可触发冲突。"
            ),
            "influence": "可用于下一章的目标、阻碍、证据或情绪压力。",
            "related": ["当前章节", "AI 候选"],
            "confidence": 76,
            "details": self._candidate_details(request.materialType),
        }

    def _agent_prompt(self, request: AgentAssistRequest) -> str:
        context = {
            "scope": request.scope,
            "action": request.action,
            "input": request.input,
            "chapterId": request.chapterId,
            "materialType": request.materialType,
            "reviewId": request.reviewId,
            "modelId": request.modelId,
        }
        return (
            "你是小说创作辅助 agent。请只返回作者可直接审阅的中文候选内容，"
            "不要返回 JSON、路径、日志、run id、agent id 或命令细节。\n\n"
            f"任务上下文：{json.dumps(context, ensure_ascii=False)}"
        )

    def _clean_cli_output(self, stdout: str) -> str:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            return ""
        for line in reversed(lines):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for key in ["content", "output", "text", "message"]:
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return "\n".join(lines).strip()

    def _candidate_details(self, material_type: MaterialType) -> dict[str, str]:
        labels = {
            "人物": ["身份", "目标", "秘密"],
            "地点": ["视觉特征", "危险点", "所属势力"],
            "势力": ["目标", "资源", "弱点"],
            "关系": ["主体", "对象", "矛盾"],
            "设定": ["规则", "代价", "例外"],
            "时间线": ["时间", "地点", "影响"],
            "伏笔": ["首次出现", "回收窗口", "误导方向"],
            "写法": ["适用场景", "避免项", "成功样例"],
        }[material_type]
        return {label: "AI 建议继续补全" for label in labels}

    def _post_chapter_service(self) -> PostChapterService:
        return PostChapterService(
            self.project_service,
            self.story_guidance_service,
            self.context_pack_service,
        )

    def _memory_updates_for_chapter(
        self, root: Path, book_id: str, chapter_id: str
    ) -> list[dict[str, Any]]:
        service = self._post_chapter_service()
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        review_path = service.review_path(normalized)
        patch_path = service.patch_path(normalized)
        stored_updates = self.workbench_repository.list_memory_updates(root, normalized)
        if stored_updates and (
            not self.project_service.file_exists(root, review_path)
            or not self.project_service.file_exists(root, patch_path)
        ):
            return stored_updates
        if not self.project_service.file_exists(
            root, review_path
        ) or not self.project_service.file_exists(root, patch_path):
            chapter_path = f"chapters/{normalized}.md"
            contract_path = f"story/chapter-briefs/{normalized}.json"
            if not self.project_service.file_exists(
                root, chapter_path
            ) or not self.project_service.file_exists(root, contract_path):
                return []
            service.build_review_and_patch(root, normalized)
        review = service.read_review(root, normalized)
        patch = service.read_canon_patch(root, normalized)
        review_items = {item.id: item for item in review.items}
        updates = [
            self._memory_update_item(book_id, normalized, operation, review_items)
            for operation in patch.operations
        ]
        self.workbench_repository.replace_memory_updates(root, normalized, updates)
        return self.workbench_repository.list_memory_updates(root, normalized)

    def _memory_update_item(
        self,
        book_id: str,
        chapter_id: str,
        operation: Any,
        review_items: dict[str, Any],
    ) -> dict[str, Any]:
        review_item_id = (
            str(operation.source).split("#", 1)[1] if "#" in str(operation.source) else ""
        )
        review_item = review_items.get(review_item_id)
        summary = ""
        if review_item is not None:
            summary = str(getattr(review_item, "text", "") or "").strip()
        if not summary:
            summary = self._memory_update_summary(operation.payload)
        can_apply = operation.action != "defer" and operation.status in {"proposed", "accepted"}
        blocked_reason = ""
        if operation.action == "defer":
            blocked_reason = "当前候选证据不足，建议先人工确认，再决定是否写入长期记忆。"
        elif operation.status == "applied":
            blocked_reason = "这条记忆更新已经写入长期记忆。"
        elif operation.status == "rejected":
            blocked_reason = "这条记忆更新已被跳过。"
        status_label = (
            "需人工确认"
            if operation.action == "defer"
            else self._memory_update_status_label(str(operation.status))
        )
        return {
            "id": operation.id,
            "bookId": book_id,
            "chapterId": chapter_id,
            "title": self._memory_update_title(review_item, operation),
            "summary": summary,
            "targetLabel": self._memory_update_target_label(str(operation.target)),
            "action": operation.action,
            "actionLabel": self._memory_update_action_label(str(operation.action)),
            "status": operation.status,
            "statusLabel": status_label,
            "canApply": can_apply,
            "blockedReason": blocked_reason,
            "evidence": [str(item) for item in operation.evidence[:3]],
        }

    def _memory_update_title(self, review_item: Any, operation: Any) -> str:
        kind = str(getattr(review_item, "kind", "") or "")
        kind_labels = {
            "summary": "更新章节摘要",
            "fact": "补充事实记忆",
            "timeline_event": "补充时间线事件",
            "character_state": "记录人物状态变化",
            "relationship_state": "记录关系变化",
            "open_loop": "更新伏笔或未解问题",
            "promise_update": "更新读者承诺",
            "emotional_beat": "记录情绪轨迹",
        }
        return kind_labels.get(kind, self._memory_update_target_label(str(operation.target)))

    def _memory_update_summary(self, payload: dict[str, Any]) -> str:
        fields = [
            payload.get("summary"),
            payload.get("text"),
            payload.get("label"),
            payload.get("status"),
            payload.get("readerQuestion"),
        ]
        state = payload.get("state")
        if isinstance(state, dict):
            fields.extend([state.get("summary"), state.get("status")])
        for field in fields:
            value = str(field or "").strip()
            if value:
                return value
        return "当前章节生成了一条可写入长期记忆的候选。"

    def _memory_update_target_label(self, target: str) -> str:
        labels = {
            "memory/chapter-summaries.json": "章节摘要",
            "memory/facts.json": "事实",
            "memory/timeline-events.json": "时间线",
            "memory/character-states.json": "人物状态",
            "memory/relationship-states.json": "关系状态",
            "memory/open-loops.json": "伏笔与未解问题",
            "memory/promises.json": "读者承诺",
            "memory/emotional-arcs.json": "情绪轨迹",
        }
        return labels.get(target, "长期记忆")

    def _memory_update_action_label(self, action: str) -> str:
        labels = {
            "add": "新增",
            "update": "更新",
            "close": "回收",
            "defer": "待人工确认",
        }
        return labels.get(action, action)

    def _memory_update_status_label(self, status: str) -> str:
        labels = {
            "proposed": "待确认",
            "accepted": "可写入",
            "rejected": "已跳过",
            "applied": "已应用",
        }
        return labels.get(status, status)

    def _chapter_id_from_memory_update(self, update_id: str, fallback: str = "") -> str:
        match = re.search(r"op_review_(\d+)_", update_id)
        if match:
            return self.project_service.normalize_chapter_id(match.group(1))
        if str(fallback).strip():
            return self.project_service.normalize_chapter_id(fallback)
        raise HTTPException(status_code=400, detail="这条记忆更新缺少章节编号。")

    def _remove_material_from_chapter_briefs(
        self, root: Path, material_id: str
    ) -> list[dict[str, Any]]:
        affected_chapters: list[dict[str, Any]] = []
        for relative_path in self.project_service.list_paths(root, "story/chapter-briefs"):
            if not relative_path.endswith(".json"):
                continue
            chapter_id = Path(relative_path).stem
            brief = self._chapter_brief(root, chapter_id)
            linked_ids = self._linked_material_ids_from_brief(brief)
            if material_id not in linked_ids:
                continue
            next_brief = dict(brief)
            next_brief["linkedMaterials"] = [
                item_id for item_id in linked_ids if item_id != material_id
            ]
            self.project_service.write_text(
                root,
                f"story/chapter-briefs/{chapter_id}.json",
                json.dumps(next_brief, ensure_ascii=False, indent=2) + "\n",
            )
            chapter_path = f"chapters/{chapter_id}.md"
            chapter = (
                self._chapter_for_file(root, PathGuard(root).resolve(chapter_path))
                if self.project_service.file_exists(root, chapter_path)
                else self._chapter_from_brief(root, chapter_id, next_brief)
            )
            self.workbench_repository.upsert_chapter(root, chapter)
            affected_chapters.append(chapter)
        return affected_chapters

    def _chapter_status(self, root: Path, chapter_id: str, word_count: int) -> str:
        repository_status = self.workbench_repository.chapter_status(root, chapter_id)
        if repository_status in {"待写", "草稿", "审阅", "完成"}:
            return repository_status
        states = self._read_json(root, self.chapter_state_path)
        chapters = states.get("chapters") if isinstance(states, dict) else None
        if isinstance(chapters, dict):
            status = str(chapters.get(chapter_id) or "").strip()
            if status in {"待写", "草稿", "审阅", "完成"}:
                return status
        return "完成" if word_count else "待写"

    def _chapter_progress(self, root: Path, status: str, word_count: int) -> int:
        target_word_count = self._chapter_target_word_count(root)
        return calculate_chapter_progress(status, word_count, target_word_count)

    def _chapter_target_word_count(self, root: Path) -> int:
        return self.plan_service.summarize(root).plan.targetWordsPerChapter

    def _write_chapter_status(self, root: Path, chapter_id: str, status: str) -> None:
        self.workbench_repository.update_chapter_status(root, chapter_id, status)
        states = self._read_json(root, self.chapter_state_path)
        chapters = states.get("chapters") if isinstance(states, dict) else None
        next_chapters = dict(chapters) if isinstance(chapters, dict) else {}
        next_chapters[chapter_id] = status
        self.project_service.write_text(
            root,
            self.chapter_state_path,
            json.dumps(
                {"schemaVersion": 1, "chapters": next_chapters},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def _export_readiness(self, root: Path, kind: ExportKind) -> dict[str, Any]:
        return self.workbench_export_service.readiness(
            root,
            kind,
            self.book_for_root(root),
            self._export_reviews_for_root(root),
            self.materials_for_root(root),
            self.generation_state_for_root(root),
        )

    def _job_summary(self, root: Path, job: Any) -> dict[str, Any]:
        status = {
            "queued": "等待中",
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "失败",
            "interrupted": "失败",
        }.get(job.status, "等待中")
        progress = job.progress.get("percent") if isinstance(job.progress, dict) else None
        if not isinstance(progress, int):
            progress = (
                100
                if job.status == "completed"
                else 8
                if job.status == "queued"
                else 24
                if job.status == "running"
                else 0
            )
        result = self._job_result_text(job)
        events = self._job_events(job)
        return {
            "id": job.jobId,
            "bookId": root.as_posix(),
            "title": job.title or self._job_kind_label(job.kind),
            "status": status,
            "progress": max(0, min(100, progress)),
            "startedAt": self._short_datetime(job.startedAt or job.createdAt),
            "result": result,
            "events": events,
        }

    def _job_events(self, job: Any) -> list[str]:
        result = self._job_result_text(job)
        logs = [str(item) for item in getattr(job, "logs", [])[-6:] if str(item).strip()]
        status_line = {
            "queued": "任务等待执行。",
            "running": "任务正在运行。",
            "completed": "任务已完成。",
            "failed": "任务失败。",
            "cancelled": "任务已取消。",
            "interrupted": "任务被中断。",
        }.get(job.status, "任务状态已更新。")
        events = [*logs, status_line, result]
        deduped: list[str] = []
        for event in events:
            if event and event not in deduped:
                deduped.append(event)
        return deduped

    def _preferred_diff_target_path(self, root: Path, chapter_id: str) -> str:
        candidates = [
            f"drafts/{chapter_id}.generated.md",
            f"drafts/{chapter_id}.polished.md",
            f"chapters/{chapter_id}.md",
        ]
        for path in candidates:
            if self.project_service.file_exists(root, path):
                return path
        return f"chapters/{chapter_id}.md"

    def _preferred_gate_target_path(self, root: Path, chapter_id: str) -> str:
        candidates = [
            f"drafts/{chapter_id}.generated.md",
            f"drafts/{chapter_id}.polished.md",
            f"chapters/{chapter_id}.md",
        ]
        existing = [
            (path, self.project_service.modified_at(root, path))
            for path in candidates
            if self.project_service.file_exists(root, path)
        ]
        if not existing:
            return f"chapters/{chapter_id}.md"
        return max(existing, key=lambda item: item[1])[0]

    def _job_result_text(self, job: Any) -> str:
        if job.error:
            return str(job.error)
        if isinstance(job.result, dict):
            for key in ["message", "summary", "outputPath", "draftPath", "reportPath"]:
                value = job.result.get(key)
                if value:
                    return str(value)
        if job.detail:
            return str(job.detail)
        return {
            "queued": "任务等待执行。",
            "running": "任务正在运行。",
            "completed": "任务已完成。",
            "failed": "任务失败，可查看详情或重试。",
            "cancelled": "任务已取消。",
            "interrupted": "任务被中断。",
        }.get(job.status, "任务状态已更新。")

    def _job_kind_label(self, kind: str) -> str:
        return {
            "skill-run": "运行写作技能",
            "local-training": "本地模型训练",
            "five-chapter-regression": "五章回归检查",
            "model-comparison": "模型对比",
            "style-profile-promotion": "风格模板评估",
            "chapter-draft": "章节候选生成",
            "line-polish": "段落润色",
            "revision-rerun": "重试任务",
        }.get(kind, kind)

    def _short_datetime(self, value: Any) -> str:
        if value is None:
            return "未知时间"
        text = value.isoformat() if hasattr(value, "isoformat") else str(value)
        return self._short_date(text)

    def _context_pack_summary(self, context_pack: Any) -> str:
        included = len(getattr(context_pack, "included", []))
        tokens = int(getattr(context_pack, "estimatedTokens", 0) or 0)
        return f"已汇总 {included} 组上下文，预估 {tokens} token。"

    def _context_pack_items(self, context_pack: ContextPack) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in context_pack.included:
            data = item.data if isinstance(item.data, dict) else {}
            items.append(
                {
                    "source": item.source,
                    "type": self._context_source_type(item.source),
                    "reason": item.reason,
                    "tokenEstimate": max(1, round(len(json.dumps(data, ensure_ascii=False)) / 4)),
                }
            )
        return items

    def _context_source_type(self, source: str) -> str:
        if source.startswith("memory/"):
            return "memory"
        if source.startswith("story/"):
            return "story"
        if source.startswith("chapters/"):
            return "chapter"
        return "reference"

    def _latest_relationship_for_character(
        self,
        relationships: list[Any],
        character_id: str,
    ) -> dict[str, Any]:
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            values = json.dumps(relationship, ensure_ascii=False)
            if character_id and character_id in values:
                history = relationship.get("history")
                if isinstance(history, list) and history and isinstance(history[-1], dict):
                    return {**relationship, **history[-1]}
                return relationship
        return {}

    def _prepare_display(self, status: str, score: int) -> str:
        if status == "pass":
            return f"本章准备通过，准备度 {score} 分，可以生成候选。"
        if status == "warn":
            return f"本章准备有提醒，准备度 {score} 分，建议先看提示再生成候选。"
        return f"本章准备被阻断，准备度 {score} 分，请先补齐关键章节合同。"

    def _gate_display(self, status: str, score: int) -> str:
        if status == "pass":
            return f"接收前检查通过，评分 {score}。"
        if status == "warn":
            return f"接收前检查有风险，评分 {score}，建议先处理高优先级问题。"
        return f"接收前检查阻断，评分 {score}，需要先修复关键问题。"

    def _selected_model_id(self, root: Path) -> str:
        data = self._read_json(root, self.model_selection_path)
        if isinstance(data, dict) and "modelId" in data:
            return str(data.get("modelId") or "").strip()
        registry = self.model_service.read_registry(root)
        return registry.defaultProfileId or ""

    def _style_profile_id(self, root: Path) -> str:
        data = self._read_json(root, "story/style-profile.json")
        if isinstance(data, dict):
            value = str(data.get("extends") or data.get("id") or "").strip()
        else:
            value = ""
        if value:
            return value
        plan = self.plan_service.summarize(root).plan
        match = re.search(r"styleProfileId=([A-Za-z0-9_-]+)", plan.notes or "")
        return match.group(1) if match else "generic-web-serial"

    def _style_profile_label(self, root: Path) -> str:
        data = self._read_json(root, "story/style-profile.json")
        if isinstance(data, dict):
            extends = str(data.get("extends") or "").strip()
            if extends:
                try:
                    builtin = self.style_profile_service.get_builtin_profile(extends)
                    return self.workbench_profile_service.style_option_label(
                        builtin.id, builtin.label
                    )
                except FileNotFoundError:
                    pass
            label = str(data.get("label") or data.get("name") or "").strip()
            if label:
                return label
        return "通用网文连载"

    def _target_root(self, book_id: str = "") -> Path | None:
        book_id = (book_id or "").strip()
        if book_id:
            return self._root_from_book_id(book_id)
        roots = self._workspace_roots()
        if not roots:
            return None
        return roots[0]

    def _character_label_from_id(self, root: Path, character_id: str) -> str:
        normalized_id = character_id.strip()
        character_memory = self._read_json(root, "memory/character-states.json")
        characters = character_memory.get("characters")
        if isinstance(characters, list):
            for character in characters:
                if not isinstance(character, dict):
                    continue
                item_id = str(character.get("characterId") or character.get("id") or "").strip()
                if item_id == normalized_id:
                    name = str(character.get("name") or "").strip()
                    if name:
                        return name
        for material in self.materials_for_root(root):
            if str(material.get("type") or "") != "人物":
                continue
            if str(material.get("id") or "").strip() == normalized_id:
                title = str(material.get("title") or "").strip()
                if title:
                    return title
        if re.search(r"[\u4e00-\u9fff]", normalized_id):
            return normalized_id
        return "未命名角色"

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _unique_nonempty(self, values: list[Any]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value).strip()
            if item and item not in seen:
                items.append(item)
                seen.add(item)
        return items

    def _search_terms(self, query: str) -> list[str]:
        compact = query.strip()
        if not compact:
            return []
        terms = re.split(r"[\s,，。；;、:：!?！？]+", compact)
        terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", compact))
        return self._unique_nonempty(terms)

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return self._unique_nonempty(value)

    def _linked_material_ids_from_brief(self, brief: dict[str, Any]) -> list[str]:
        return self._string_list(brief.get("linkedMaterials"))

    def _topic_summary(self, memory: dict[str, Any], topic_ids: Any) -> str:
        ids = set(topic_ids if isinstance(topic_ids, list) else [])
        topics = memory.get("topics") if isinstance(memory.get("topics"), list) else []
        summaries = [
            str(topic.get("summary") or "")
            for topic in topics
            if isinstance(topic, dict) and topic.get("id") in ids
        ]
        return " ".join(summary for summary in summaries if summary).strip()

    def _people_for_root(self, root: Path) -> list[str]:
        memory = self._read_json(root, "memory/long-term-memory.json")
        entities = memory.get("entityIndex") if isinstance(memory.get("entityIndex"), list) else []
        return [
            str(entity.get("name"))
            for entity in entities
            if isinstance(entity, dict) and entity.get("name")
        ] or ["待选择人物"]

    def _first_nonempty_line(self, root: Path, relative_path: str) -> str:
        try:
            text = self.project_service.read_text(root, relative_path)
        except FileNotFoundError:
            return ""
        for line in text.splitlines():
            value = line.strip().lstrip("#").strip()
            if value and value.lower() != "ideas":
                return value
        return ""

    def _title_from_markdown(self, text: str) -> str:
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                return line.lstrip("#").strip()
        return ""

    def _body_without_heading(self, text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("#"):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _summary_from_content(self, content: str) -> str:
        compact = re.sub(r"\s+", " ", content).strip()
        return (
            compact[:90] + ("..." if len(compact) > 90 else "") if compact else "等待补全章节摘要。"
        )

    def _word_count(self, text: str) -> int:
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_words = len(re.findall(r"[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*", text))
        return cjk_chars + latin_words

    def _short_date(self, value: str) -> str:
        return value.split("T", 1)[0] if "T" in value else value

    def _safe_slug(self, value: str, fallback_prefix: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-").lower()
        if normalized:
            return normalized[:48]
        digest = sha1(value.encode("utf-8")).hexdigest()[:10]
        return f"{fallback_prefix}-{digest}"

    def _new_material_id(self, root: Path, material: MaterialPayload) -> str:
        seed = material.title.strip() or material.type
        base = self._safe_slug(seed, "material")
        if not base.startswith("material-"):
            base = f"material-{base}"
        existing_ids = {
            str(item.get("id") or "") for item in self.material_service.read_store(root)
        }
        if base not in existing_ids:
            return base
        index = 2
        while f"{base}-{index}" in existing_ids:
            index += 1
        return f"{base}-{index}"


def _presenter() -> WorkbenchPresenter:
    return WorkbenchPresenter()


def _workbench_sse_event(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_workbench_job_events(root: Path, job_id: str):
    terminal = {"completed", "failed", "cancelled", "interrupted"}
    last_payload = ""
    while True:
        try:
            job = JobController().get_job(root, job_id)
        except FileNotFoundError:
            yield _workbench_sse_event("error", {"jobId": job_id, "message": "找不到任务。"})
            return
        payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if payload != last_payload:
            yield _workbench_sse_event(
                "job",
                {
                    "jobId": job.jobId,
                    "status": job.status,
                    "progress": job.progress,
                    "result": job.result,
                    "error": job.error,
                },
            )
            last_payload = payload
        if job.status in terminal:
            yield _workbench_sse_event("end", {"jobId": job.jobId, "status": job.status})
            return
        time.sleep(0.5)


@app.get("/api/workspace")
def api_workspace() -> dict[str, Any]:
    return _presenter().workspace()


@app.get("/api/books/{book_id:path}/workspace")
def api_book_workspace(book_id: str) -> dict[str, Any]:
    return _presenter().book_workspace(book_id)


@app.get("/api/books/{book_id:path}/generation")
def api_book_generation(book_id: str) -> dict[str, Any]:
    return _presenter().generation_for_book(book_id)


@app.put("/api/books/{book_id:path}/plan")
def api_update_project_plan(
    book_id: str,
    request: ProjectPlanUpdateRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().update_project_plan(book_id, request)


@app.get("/api/books/{book_id:path}/long-form-plan")
def api_long_form_plan(book_id: str) -> dict[str, Any]:
    return _presenter().long_form_plan(book_id)


@app.put("/api/books/{book_id:path}/long-form-plan/volumes/{volume_id}")
def api_update_volume_goal(
    book_id: str,
    volume_id: str,
    request: VolumeGoalUpdateRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "volumeId": volume_id})
    return _presenter().update_volume_goal(book_id, request)


@app.put("/api/books/{book_id:path}/long-form-plan/chapters/{chapter_id}")
def api_update_chapter_landing(
    book_id: str,
    chapter_id: str,
    request: ChapterLandingUpdateRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().update_chapter_landing(book_id, request)


@app.post("/api/books/{book_id:path}/long-form-plan/replan")
def api_generate_long_form_replan(
    book_id: str,
    request: LongFormReplanRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().generate_long_form_replan(book_id, request)


@app.post("/api/books/{book_id:path}/long-form-plan/replan/confirm")
def api_confirm_long_form_replan(
    book_id: str,
    request: LongFormReplanRequest,
) -> dict[str, Any]:
    _ = request.model_copy(update={"bookId": book_id})
    return _presenter().confirm_long_form_replan(book_id)


@app.put("/api/books/{book_id:path}/generation/mode")
def api_set_generation_mode(book_id: str, request: GenerationModeRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().set_generation_mode(book_id, request)


@app.post("/api/books/{book_id:path}/generation/continue")
def api_continue_generation(book_id: str, request: GenerationActionRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().continue_generation(book_id, request.requestId)


@app.post("/api/books/{book_id:path}/generation/confirm")
def api_confirm_generation(book_id: str, request: GenerationActionRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().confirm_generation(book_id, request)


@app.post("/api/books/{book_id:path}/generation/candidates/regenerate")
def api_regenerate_generation_candidate(
    book_id: str, request: GenerationActionRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().regenerate_generation_candidate(book_id, request.requestId)


@app.put("/api/books/{book_id:path}/generation/candidates/current")
def api_select_generation_candidate(
    book_id: str, request: GenerationCandidateSelectRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().select_generation_candidate(book_id, request.candidateId, request.requestId)


@app.post("/api/books/{book_id:path}/generation/candidates/rollback")
def api_rollback_generation_candidate(
    book_id: str, request: GenerationActionRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().rollback_generation_candidate(book_id, request.requestId)


@app.post("/api/books/{book_id:path}/generation/pause")
def api_pause_generation(book_id: str, request: GenerationActionRequest) -> dict[str, Any]:
    _ = request.model_copy(update={"bookId": book_id})
    return _presenter().pause_generation(book_id)


@app.post("/api/books/{book_id:path}/generation/resume")
def api_resume_generation(book_id: str, request: GenerationActionRequest) -> dict[str, Any]:
    _ = request.model_copy(update={"bookId": book_id})
    return _presenter().resume_generation(book_id)


@app.post("/api/books/{book_id:path}/generation/takeover")
def api_takeover_generation(book_id: str, request: GenerationTakeoverRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().takeover_generation(book_id, request)


@app.post("/api/books")
def api_create_book(request: CreateBookRequest) -> dict[str, Any]:
    return _presenter().create_book(request)


@app.put("/api/books/{book_id:path}/settings")
def api_update_book_settings(
    book_id: str,
    request: UpdateBookSettingsRequest,
) -> dict[str, Any]:
    return _presenter().update_book_settings(book_id, request)


@app.post("/api/books/{book_id:path}/materials")
def api_create_material(book_id: str, material: MaterialPayload) -> dict[str, Any]:
    if material.bookId != book_id:
        material = material.model_copy(update={"bookId": book_id})
    return _presenter().create_material(material)


@app.put("/api/books/{book_id:path}/materials/{material_id}")
def api_update_material(
    book_id: str, material_id: str, material: MaterialPayload
) -> dict[str, Any]:
    material = material.model_copy(update={"bookId": book_id, "id": material_id})
    return _presenter().update_material(material)


@app.delete("/api/books/{book_id:path}/materials/{material_id}")
def api_delete_material(book_id: str, material_id: str) -> dict[str, Any]:
    return _presenter().delete_material(book_id, material_id)


@app.put("/api/books/{book_id:path}/model")
def api_set_book_model(book_id: str, request: SetBookModelRequest) -> dict[str, str]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().set_book_model(request)


@app.get("/api/model-library")
def api_model_library() -> dict[str, Any]:
    return _presenter().list_model_library()


@app.get("/api/model-library-training-backends")
def api_model_training_backends() -> dict[str, Any]:
    return _presenter().list_model_training_backends()


@app.post("/api/model-library")
def api_create_model_library_item(
    request: ModelLibraryCreateRequest,
) -> dict[str, Any]:
    return _presenter().create_model_library_item(request)


@app.post("/api/model-library/categories")
def api_create_model_category(
    request: ModelCategoryCreateRequest,
) -> dict[str, Any]:
    return _presenter().create_model_category(request)


@app.get("/api/model-library/{model_id}")
def api_model_library_detail(model_id: str) -> dict[str, Any]:
    return _presenter().model_library_detail(model_id)


@app.post("/api/model-library/{model_id}/sources/upload")
async def api_upload_model_sources(
    model_id: str,
    files: Annotated[list[UploadFile], File()],
) -> dict[str, Any]:
    payloads = [
        (file.filename or "未命名文件", await file.read())
        for file in files
    ]
    return _presenter().workbench_model_library_service.upload_sources(
        model_id,
        payloads,
    )


@app.post("/api/model-library/{model_id}/sources/from-books")
def api_add_model_book_sources(
    model_id: str,
    request: ModelBookSourcesRequest,
) -> dict[str, Any]:
    return _presenter().add_model_book_sources(model_id, request)


@app.delete("/api/model-library/{model_id}/sources/{source_id}")
def api_delete_model_source(model_id: str, source_id: str) -> dict[str, Any]:
    return _presenter().delete_model_source(model_id, source_id)


@app.get("/api/model-library/{model_id}/readiness")
def api_model_library_readiness(model_id: str) -> dict[str, Any]:
    return _presenter().model_library_readiness(model_id)


@app.post("/api/model-library/{model_id}/training")
def api_start_model_library_training(
    model_id: str,
    request: ModelLibraryTrainingRequest,
) -> dict[str, Any]:
    return _presenter().start_model_library_training(model_id, request)


@app.post("/api/models/{model_id}/validate")
def api_validate_model(model_id: str, request: ValidateModelRequest) -> dict[str, Any]:
    return _presenter().validate_model(request.model_copy(update={"modelId": model_id}))


@app.post("/api/models/training/readiness")
def api_model_training_readiness(bookId: str = "") -> dict[str, Any]:
    return _presenter().model_training_readiness(bookId)


@app.post("/api/models/compare")
def api_compare_models(request: ModelCompareRequest) -> dict[str, Any]:
    return _presenter().compare_models(request)


@app.post("/api/models/training/run")
def api_run_model_training(request: ModelTrainingRunRequest) -> dict[str, Any]:
    return _presenter().run_model_training(request)


@app.post("/api/calibration/annotate")
def api_annotate_calibration(request: CalibrationAnnotationRequest) -> dict[str, Any]:
    return _presenter().annotate_calibration(request)


@app.get("/api/calibration/analysis")
def api_calibration_analysis(bookId: str = "") -> dict[str, Any]:
    return _presenter().calibration_analysis(bookId)


@app.post("/api/calibration/apply")
def api_apply_calibration(request: QualityThresholdConfigRequest) -> dict[str, Any]:
    return _presenter().apply_calibration(request)


@app.post("/api/calibration/rescore-all")
def api_rescore_all_calibration(request: CalibrationRescoreRequest) -> dict[str, Any]:
    return _presenter().rescore_all_calibration(request)


@app.get("/api/calibration/history")
def api_calibration_history(bookId: str = "") -> dict[str, Any]:
    return _presenter().calibration_history(bookId)


@app.post("/api/calibration/revert")
def api_revert_calibration(request: CalibrationRevertRequest) -> dict[str, Any]:
    return _presenter().revert_calibration(request)


@app.get("/api/calibration/rescore-all/{job_id}/events")
def api_rescore_all_calibration_events(
    job_id: str,
    bookId: str = "",
) -> StreamingResponse:
    presenter = _presenter()
    root = presenter._target_root(bookId)
    if root is None:
        raise HTTPException(status_code=400, detail="当前工作区还没有可校准的作品。")
    return StreamingResponse(
        _stream_workbench_job_events(root, job_id),
        media_type="text/event-stream",
    )


@app.get("/api/models/quality-distribution")
def api_quality_distribution(bookId: str = "") -> dict[str, Any]:
    return _presenter().quality_distribution(bookId)


@app.get("/api/export/training-readiness")
def api_workbench_training_export_readiness(bookId: str = "") -> dict[str, Any]:
    return _presenter().training_export_readiness(bookId)


@app.get("/api/models/writing")
def api_list_writing_models(bookId: str = "") -> dict[str, Any]:
    return _presenter().list_writing_models(bookId)


@app.post("/api/models/writing")
def api_create_writing_model(request: WritingModelManageRequest) -> dict[str, Any]:
    return _presenter().create_writing_model(request)


@app.patch("/api/models/writing/default")
def api_set_default_writing_model(request: WritingModelDefaultRequest) -> dict[str, Any]:
    return _presenter().set_default_writing_model(request)


@app.get("/api/models/style-profiles")
def api_list_style_profiles(bookId: str = "") -> dict[str, Any]:
    return _presenter().list_style_profiles(bookId)


@app.post("/api/models/style-profiles/apply")
def api_apply_style_profile(request: ApplyStyleProfileRequest) -> dict[str, Any]:
    return _presenter().apply_style_profile(request)


@app.get("/api/models/editorial")
def api_list_editorial_models(bookId: str = "") -> dict[str, Any]:
    return _presenter().list_editorial_models(bookId)


@app.post("/api/models/editorial")
def api_create_editorial_model(request: EditorialModelManageRequest) -> dict[str, Any]:
    return _presenter().create_editorial_model(request)


@app.patch("/api/models/editorial/default")
def api_set_default_editorial_model(request: EditorialModelDefaultRequest) -> dict[str, Any]:
    return _presenter().set_default_editorial_model(request)


@app.post("/api/models/compare/promote")
def api_promote_model_compare(request: PromoteModelCompareRequest) -> dict[str, Any]:
    return _presenter().promote_model_compare(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/draft")
def api_apply_chapter_draft(
    book_id: str, chapter_id: str, request: ApplyChapterDraftRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().apply_chapter_draft(request)


@app.put("/api/books/{book_id:path}/chapters/{chapter_id}/planning")
def api_update_chapter_planning(
    book_id: str, chapter_id: str, request: UpdateChapterPlanningRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().update_chapter_planning(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/materials/link")
def api_link_chapter_materials(
    book_id: str, chapter_id: str, request: LinkChapterMaterialsRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().link_chapter_materials(request)


@app.get("/api/books/{book_id:path}/chapters/{chapter_id}/materials")
def api_chapter_materials(
    book_id: str,
    chapter_id: str,
    type: MaterialType | None = None,
    q: str = "",
    scope: Literal["related", "all"] = "related",
) -> dict[str, Any]:
    return _presenter().chapter_materials(book_id, chapter_id, type, q, scope)


@app.get("/api/books/{book_id:path}/chapters/{chapter_id}/characters/snapshot")
def api_chapter_characters_snapshot(book_id: str, chapter_id: str) -> dict[str, Any]:
    return _presenter().characters_snapshot(book_id, chapter_id)


@app.get("/api/books/{book_id:path}/writing-lessons")
def api_writing_lessons(book_id: str) -> dict[str, Any]:
    return _presenter().writing_lessons(book_id)


@app.post("/api/books/{book_id:path}/knowledge/rebuild")
def api_rebuild_knowledge(book_id: str) -> dict[str, Any]:
    return _presenter().rebuild_knowledge(book_id)


@app.get("/api/books/{book_id:path}/knowledge/search")
def api_search_knowledge(
    book_id: str,
    q: str = "",
    limit: int = 6,
    source: str = "",
    chapter_id: str = "",
    character_id: str = "",
    time_scope: str = "",
) -> dict[str, Any]:
    return _presenter().search_knowledge(
        KnowledgeSearchRequest(
            bookId=book_id,
            q=q,
            limit=limit,
            source=source,
            chapterId=chapter_id,
            characterId=character_id,
            timeScope=time_scope,
        )
    )


@app.get("/api/books/{book_id:path}/writing-assets")
def api_writing_assets(book_id: str) -> dict[str, Any]:
    return _presenter().writing_assets(book_id)


@app.put("/api/books/{book_id:path}/writing-assets/formulas/{formula_id}")
def api_set_writing_formula_status(
    book_id: str,
    formula_id: str,
    request: WritingFormulaStatusRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"formulaId": formula_id, "bookId": book_id})
    return _presenter().set_writing_formula_status(book_id, request)


@app.post("/api/books/{book_id:path}/ideation")
def api_create_ideation(book_id: str, request: IdeationSessionRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().create_ideation_session(request)


@app.get("/api/books/{book_id:path}/ideation")
def api_list_ideation(book_id: str) -> dict[str, Any]:
    return _presenter().list_ideation_sessions(book_id)


@app.post("/api/books/{book_id:path}/ideation/{session_id}/turns")
def api_append_ideation_turn(
    book_id: str,
    session_id: str,
    request: IdeationTurnRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().append_ideation_turn(book_id, session_id, request)


@app.post("/api/books/{book_id:path}/ideation/{session_id}/materialize")
def api_materialize_ideation(
    book_id: str,
    session_id: str,
    request: IdeationMaterializeRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().materialize_ideation_session(book_id, session_id, request)


@app.post("/api/books/{book_id:path}/analysis")
def api_analyze_book(book_id: str, request: BookAnalysisRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().analyze_book(request)


@app.post("/api/books/{book_id:path}/analysis/promote-formulas")
def api_promote_writing_formulas(
    book_id: str,
    request: PromoteWritingFormulaRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().promote_writing_formulas(request)


@app.post("/api/books/{book_id:path}/writing-assets/formula-candidates")
def api_extract_writing_formulas(
    book_id: str,
    request: ExtractWritingFormulaRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().extract_writing_formulas(request)


@app.post("/api/books/{book_id:path}/writing-assets/formula-candidates/promote")
def api_promote_external_writing_formulas(
    book_id: str,
    request: PromoteExternalWritingFormulaRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().promote_external_writing_formulas(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/reviews/world-rules")
def api_add_world_rule_review(
    book_id: str,
    chapter_id: str,
    request: WorldRuleReviewRequest,
) -> dict[str, Any]:
    return _presenter().add_world_rule_review(book_id, chapter_id, request)


@app.post("/api/books/{book_id:path}/sequence-evaluation")
def api_sequence_evaluation(
    book_id: str,
    request: ChapterSequenceEvaluationRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().sequence_evaluation(request)


@app.post("/api/books/{book_id:path}/revision-plan")
def api_revision_plan(book_id: str, request: RevisionPlanRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().revision_plan(request)


@app.get("/api/books/{book_id:path}/chapters/{chapter_id}/contract")
def api_chapter_contract(book_id: str, chapter_id: str) -> dict[str, Any]:
    return _presenter().chapter_contract(book_id, chapter_id)


@app.put("/api/books/{book_id:path}/chapters/{chapter_id}/contract")
def api_update_chapter_contract(
    book_id: str,
    chapter_id: str,
    request: ChapterContractUpdateRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().update_chapter_contract(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/prepare")
def api_prepare_chapter(
    book_id: str, chapter_id: str, request: ChapterPrepareRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().prepare_chapter(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/plot-directions")
def api_plot_directions(
    book_id: str,
    chapter_id: str,
    request: PlotDirectionRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().plot_directions(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/plot-directions/apply")
def api_apply_plot_direction(
    book_id: str,
    chapter_id: str,
    request: ApplyPlotDirectionRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().apply_plot_direction(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/polish")
async def api_polish_chapter(
    book_id: str,
    chapter_id: str,
    request: ChapterPolishRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return await _presenter().polish_chapter(request)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/gate")
def api_check_chapter_gate(
    book_id: str, chapter_id: str, request: ChapterGateRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().check_chapter_gate(request)


@app.get("/api/books/{book_id:path}/chapters/{chapter_id}/gate/recovery")
def api_chapter_gate_recovery(book_id: str, chapter_id: str) -> dict[str, Any]:
    return _presenter().gate_recovery(book_id, chapter_id)


@app.post("/api/books/{book_id:path}/chapters/{chapter_id}/accept")
def api_accept_chapter(
    book_id: str, chapter_id: str, request: AcceptChapterRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "chapterId": chapter_id})
    return _presenter().accept_chapter(request)


@app.post("/api/books/{book_id:path}/chapters/next")
def api_create_next_chapter(book_id: str) -> dict[str, Any]:
    return _presenter().create_next_chapter(book_id)


@app.post("/api/books/{book_id:path}/reviews/{review_id}/repair")
def api_apply_review_repair(
    book_id: str, review_id: str, request: ApplyReviewRepairRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "reviewId": review_id})
    return _presenter().apply_review_repair(request)


@app.post("/api/books/{book_id:path}/reviews/run")
def api_run_reviews(book_id: str, request: RunReviewsRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().run_reviews(request)


@app.get("/api/books/{book_id:path}/reviews")
def api_book_reviews(book_id: str) -> dict[str, Any]:
    return _presenter().book_reviews(book_id)


@app.patch("/api/books/{book_id:path}/reviews/{review_id}")
def api_update_review_status(
    book_id: str, review_id: str, request: PatchReviewRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id, "reviewId": review_id})
    return _presenter().update_review_status(request)


@app.get("/api/books/{book_id:path}/chapters/{chapter_id}/memory-updates")
def api_chapter_memory_updates(book_id: str, chapter_id: str) -> dict[str, Any]:
    return _presenter().chapter_memory_updates(
        ListChapterMemoryUpdatesRequest(bookId=book_id, chapterId=chapter_id)
    )


@app.post("/api/books/{book_id:path}/memory-updates/{update_id}/apply")
def api_apply_memory_update(
    book_id: str, update_id: str, request: ApplyMemoryUpdateRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().apply_memory_update(update_id, request)


@app.get("/api/books/{book_id:path}/library/relationships")
def api_library_relationships(book_id: str) -> dict[str, Any]:
    return _presenter().library_relationships(book_id)


@app.get("/api/books/{book_id:path}/library/relationships/{edge_id}")
def api_library_relationship_detail(book_id: str, edge_id: str) -> dict[str, Any]:
    return _presenter().library_relationship_detail(book_id, edge_id)


@app.post("/api/books/{book_id:path}/library/relationship-events/{event_id}")
def api_update_library_relationship_event(
    book_id: str,
    event_id: str,
    request: UpdateRelationshipEventRequest,
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().update_library_relationship_event(book_id, event_id, request)


@app.get("/api/books/{book_id:path}/library/topics/{topic_id}")
def api_library_topic_detail(book_id: str, topic_id: str, chapterId: str = "") -> dict[str, Any]:
    return _presenter().library_topic_detail(book_id, topic_id, chapterId)


@app.get("/api/books/{book_id:path}/library/timeline")
def api_library_timeline(book_id: str) -> dict[str, Any]:
    return _presenter().library_timeline(book_id)


@app.post("/api/books/{book_id:path}/library/timeline/sync")
def api_sync_library_timeline(book_id: str) -> dict[str, Any]:
    return _presenter().sync_library_timeline(book_id)


@app.post("/api/books/{book_id:path}/exports/check")
def api_check_export(book_id: str, request: ExportWorkbenchRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().check_export(request)


@app.post("/api/books/{book_id:path}/exports")
def api_generate_export(book_id: str, request: ExportWorkbenchRequest) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().generate_export(request)


@app.get("/api/books/{book_id:path}/jobs")
def api_book_jobs(book_id: str) -> dict[str, Any]:
    return _presenter().jobs_for_book(book_id)


@app.get("/api/books/{book_id:path}/jobs/{job_id}")
def api_job_detail(book_id: str, job_id: str) -> dict[str, Any]:
    return _presenter().job_detail(book_id, job_id)


@app.get("/api/books/{book_id:path}/jobs/{job_id}/events")
def api_job_events(book_id: str, job_id: str) -> dict[str, Any]:
    return _presenter().job_events(book_id, job_id)


@app.post("/api/books/{book_id:path}/jobs/{job_id}/cancel")
def api_cancel_job(book_id: str, job_id: str) -> dict[str, Any]:
    return _presenter().cancel_job(book_id, job_id)


@app.post("/api/books/{book_id:path}/jobs/{job_id}/retry")
def api_retry_job(book_id: str, job_id: str) -> dict[str, Any]:
    return _presenter().retry_job(book_id, job_id)


@app.get("/api/books/{book_id:path}/runs")
def api_book_runs(book_id: str) -> dict[str, Any]:
    return _presenter().runs_for_book(book_id)


@app.get("/api/books/{book_id:path}/diff")
def api_book_diff(book_id: str) -> dict[str, Any]:
    return _presenter().diff_for_book(book_id)


@app.get("/api/books/{book_id:path}/diagnostics")
def api_book_diagnostics(book_id: str) -> dict[str, Any]:
    return _presenter().diagnostics_for_book(book_id)


@app.post("/api/books/{book_id:path}/maintenance/{action}")
def api_book_maintenance(
    book_id: str, action: str, request: MaintenanceActionRequest
) -> dict[str, Any]:
    request = request.model_copy(update={"bookId": book_id})
    return _presenter().maintenance_action(book_id, action, request)


@app.post("/api/agent/assist")
async def api_agent_assist(request: AgentAssistRequest) -> dict[str, Any]:
    return await _presenter().agent_assist(request)


@app.post("/api/agent/assist/stream")
async def api_agent_assist_stream(
    request: AgentAssistRequest,
    http_request: Request,
) -> StreamingResponse:
    return await _presenter().stream_agent_assist(
        request,
        is_disconnected=http_request.is_disconnected,
    )


@app.get("/api/ai/settings")
def api_ai_settings() -> dict[str, Any]:
    return _presenter().ai_settings()


@app.post("/api/ai/accounts")
def api_create_ai_account(request: AIAccountRequest) -> dict[str, Any]:
    return _presenter().save_ai_account(request)


@app.put("/api/ai/accounts/{account_id}")
def api_update_ai_account(
    account_id: str,
    request: AIAccountRequest,
) -> dict[str, Any]:
    return _presenter().save_ai_account(request, account_id)


@app.delete("/api/ai/accounts/{account_id}")
def api_delete_ai_account(account_id: str) -> dict[str, Any]:
    return _presenter().delete_ai_account(account_id)


@app.post("/api/ai/accounts/{account_id}/probe")
async def api_probe_ai_account(account_id: str) -> dict[str, Any]:
    return await _presenter().probe_ai_account(account_id)


@app.post("/api/ai/models/discover")
async def api_discover_ai_models(
    request: AIAccountConnectionRequest,
) -> dict[str, Any]:
    return await _presenter().discover_ai_models(request)


@app.post("/api/ai/probe")
async def api_probe_ai_configuration(
    request: AIAccountConnectionRequest,
) -> dict[str, Any]:
    return await _presenter().probe_ai_configuration(request)


@app.put("/api/ai/roles")
def api_bind_ai_roles(request: AIRoleBindingsRequest) -> dict[str, Any]:
    return _presenter().bind_ai_roles(request)
