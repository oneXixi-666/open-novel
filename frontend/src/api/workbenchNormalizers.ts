import { bookCreationOptions } from "../config/bookCreationOptions";
import type { ArcSummary, Book, BookCreationOptions, Chapter, ChapterStatus, GenerationMode, GenerationStage, GenerationState, GenerationStatus, Material, MaterialType, MemoryInspection, MemoryUpdateItem, ModelProfile, ModelSource, ReviewItem, ReviewStatus, TensionPoint, WorkspaceData } from "../types";
import type {
  AcceptChapterRequest,
  AcceptChapterResponse,
  ApplyChapterDraftRequest,
  ApplyChapterDraftResponse,
  ChapterGateIssue,
  ChapterGateRequest,
  ChapterGateRecoveryResponse,
  ChapterGateRecoveryStep,
  ChapterGateResponse,
  ChapterPrepareRequest,
  ChapterPrepareResponse,
  ChapterReadinessIssue,
  ApplyMemoryUpdateResponse,
  ApplyReviewRepairRequest,
  ApplyReviewRepairResponse,
  AgentAssistResponse,
  AcceptChapterBlockedDetail,
  BookReviewsResponse,
  ChapterMemoryUpdatesResponse,
  CreateBookRequest,
  CreateBookResponse,
  CreateNextChapterResponse,
  DeleteMaterialResponse,
  GenerationResponse,
  LinkChapterMaterialsRequest,
  LinkChapterMaterialsResponse,
  MaterialMutationResponse,
  RunReviewsRequest,
  RunReviewsResponse,
  SetBookModelRequest,
  SetBookModelResponse,
  UpdateChapterPlanningRequest,
  UpdateChapterPlanningResponse,
  UpdateReviewStatusRequest,
  UpdateReviewStatusResponse,
  ValidateModelResponse
} from "./contracts";
import {
  asArray,
  normalizeDetails,
  normalizeIdList,
  normalizeNonNegativeNumber,
  normalizePercent,
  normalizeStringList,
  safeDisplayText
} from "./workbenchNormalizerUtils";
import {
  isFirstVersionExportKind,
  normalizeExportReadiness,
  normalizeJob,
  normalizeRun
} from "./workbenchOperationNormalizers";

const materialTypeValues: MaterialType[] = ["人物", "地点", "势力", "关系", "设定", "时间线", "伏笔", "写法"];
const chapterStatusValues: ChapterStatus[] = ["待写", "草稿", "审阅", "完成"];
const reviewStatusValues: ReviewStatus[] = ["待处理", "处理中", "已确认"];
const memoryUpdateActions = ["add", "update", "close", "defer"] as const;
const memoryUpdateStatuses = ["proposed", "accepted", "rejected", "applied"] as const;
const gateStatusValues = ["pass", "warn", "block"] as const;
const generationStages: GenerationStage[] = ["architecture", "blueprint", "contract", "context", "draft", "gate", "review", "accept", "memory", "next_chapter"];
const generationStatuses: GenerationStatus[] = ["idle", "running", "waiting_confirm", "blocked", "paused", "completed"];
const generationModes: GenerationMode[] = ["full_auto", "stage_confirm", "chapter_confirm", "deep_control"];
const issueSeverityValues = ["low", "medium", "high", "blocker"] as const;
const issueStageValues = ["readiness", "memory", "context", "continuity", "quality", "editorial", "review"] as const;
const agentInternalLinePattern =
  /^\s*(?:```)?\s*(?:prompt|output|raw|log|logs|command|cmd|stderr|stdout|path|run\s*id|job\s*id|agent\s*id)\s*[:：=]/i;
const hiddenInternalTextPattern = /已隐藏本地路径|路径已隐藏|已隐藏运行编号|任务编号已隐藏/i;
const authorActionLabels: Record<string, string> = {
  "review-readiness-warnings-before-drafting": "先处理准备提醒，再生成章节候选。",
  "review-gate-warnings": "先处理接收前提示，再决定是否接收正文。",
  "ready-to-accept": "可以确认接收正文。",
  "review-post-chapter-summary": "接收后查看复盘和记忆更新候选。",
  "resolve-continuity-issues-and-rerun-chapter-gate": "先处理连续性问题，再重新运行接收前检查。",
  "fix-blocking-chapter-issues": "先修复阻断问题，再重新检查。"
};

export function normalizeWorkspace(data: Partial<WorkspaceData>): WorkspaceData {
  return {
    books: asArray(data.books).map(normalizeBook),
    creationOptions: normalizeCreationOptions(data.creationOptions),
    materials: asArray(data.materials).map(normalizeMaterial),
    reviews: asArray(data.reviews).map(normalizeReview),
    models: asArray(data.models).map(normalizeModel),
    exports: asArray(data.exports)
      .filter((item) => isFirstVersionExportKind(item.kind))
      .map(normalizeExportReadiness),
    jobs: asArray(data.jobs).map(normalizeJob),
    runs: asArray(data.runs).map(normalizeRun),
    generationStates: asArray(data.generationStates).map(normalizeGenerationState)
  };
}

export function normalizeGenerationState(state: Partial<GenerationState> = {}): GenerationState {
  const stage = generationStages.includes(state.stage as GenerationStage) ? state.stage as GenerationStage : "contract";
  const status = generationStatuses.includes(state.status as GenerationStatus) ? state.status as GenerationStatus : "idle";
  const mode = generationModes.includes(state.interventionMode as GenerationMode) ? state.interventionMode as GenerationMode : "stage_confirm";
  const batchTarget = Math.max(1, normalizeNonNegativeNumber(state.batchTarget) || 1);
  const defaultStepLimit = mode === "full_auto" ? batchTarget * 7 + 8 : 1;
  const autoStepLimit = Math.max(1, Math.min(defaultStepLimit, normalizeNonNegativeNumber(state.autoStepLimit) || defaultStepLimit));
  return {
    bookId: String(state.bookId ?? ""),
    stage,
    stageLabel: safeDisplayText(state.stageLabel) || generationStageLabel(stage),
    status,
    statusLabel: safeDisplayText(state.statusLabel) || generationStatusLabel(status),
    interventionMode: mode,
    interventionModeLabel: safeDisplayText(state.interventionModeLabel) || generationModeLabel(mode),
    paused: Boolean(state.paused || status === "paused"),
    batchTarget,
    batchDone: normalizeNonNegativeNumber(state.batchDone),
    autoStepLimit,
    autoStepsUsed: Math.min(autoStepLimit, normalizeNonNegativeNumber(state.autoStepsUsed)),
    activeChapterId: String(state.activeChapterId ?? ""),
    nextAction: safeAuthorActionText(state.nextAction, "继续生成。"),
    blockers: normalizeStringList(state.blockers).map((item) => safeDisplayText(item)).filter(Boolean),
    confirmations: normalizeStringList(state.confirmations).map((item) => safeDisplayText(item)).filter(Boolean),
    lastResult: safeDisplayText(state.lastResult),
    activeArtifactType: safeDisplayText(state.activeArtifactType),
    activeRunStatus: safeDisplayText(state.activeRunStatus),
    sourceModelLabel: safeDisplayText(state.sourceModelLabel),
    retryCount: normalizeNonNegativeNumber(state.retryCount),
    canRetry: Boolean(state.canRetry),
    canConfirm: Boolean(state.canConfirm),
    canTakeover: state.canTakeover !== false,
    recoverySummary: safeDisplayText(state.recoverySummary),
    candidateOptions: asArray(state.candidateOptions).map((option) => ({
      id: String(option.id ?? ""),
      title: safeDisplayText(option.title),
      summary: safeDisplayText(option.summary),
      readerExperience: safeDisplayText(option.readerExperience),
      recommendation: safeDisplayText(option.recommendation)
    })).filter((option) => option.id && option.title),
    selectedOptionId: String(state.selectedOptionId ?? ""),
    longFormPosition: {
      volumeId: String(state.longFormPosition?.volumeId ?? ""),
      volumeTitle: safeDisplayText(state.longFormPosition?.volumeTitle),
      volumeGoal: safeDisplayText(state.longFormPosition?.volumeGoal),
      segmentId: String(state.longFormPosition?.segmentId ?? ""),
      segmentTitle: safeDisplayText(state.longFormPosition?.segmentTitle),
      segmentPurpose: safeDisplayText(state.longFormPosition?.segmentPurpose),
      chapterRange: safeDisplayText(state.longFormPosition?.chapterRange)
    },
    updatedAt: safeDisplayText(state.updatedAt),
    artifact: state.artifact ? normalizeGenerationArtifact(state.artifact) : undefined
  };
}

export function normalizeGenerationResponse(response: Partial<GenerationResponse>, bookId: string): GenerationResponse {
  const state = normalizeGenerationState({
    ...response.generationState,
    bookId: response.generationState?.bookId || bookId
  });
  return {
    generationState: state,
    book: normalizeBook(response.book ?? { id: bookId }),
    activeChapter: normalizeChapter(response.activeChapter ?? { id: state.activeChapterId }),
    jobs: asArray(response.jobs).map(normalizeJob),
    runs: asArray(response.runs).map(normalizeRun),
    authorMessage: safeAuthorActionText(response.authorMessage, "生成状态已更新。"),
    generationArtifact: response.generationArtifact
      ? normalizeGenerationArtifact(response.generationArtifact)
      : state.artifact,
    target: response.target === "library" || response.target === "review" || response.target === "writing" ? response.target : undefined
  };
}

function normalizeGenerationArtifact(artifact: NonNullable<GenerationState["artifact"]>): NonNullable<GenerationState["artifact"]> {
  return {
    artifactType: safeDisplayText(artifact.artifactType),
    status: safeDisplayText(artifact.status),
    sourceModelLabel: safeDisplayText(artifact.sourceModelLabel),
    candidateId: String(artifact.candidateId ?? ""),
    version: normalizeNonNegativeNumber(artifact.version) || 1,
    recommendedOptionId: String(artifact.recommendedOptionId ?? ""),
    selectedOptionId: String(artifact.selectedOptionId ?? ""),
    options: asArray(artifact.options).map((option) => ({
      id: String(option.id ?? ""),
      title: safeDisplayText(option.title),
      summary: safeDisplayText(option.summary),
      readerExperience: safeDisplayText(option.readerExperience),
      recommendation: safeDisplayText(option.recommendation)
    })).filter((option) => option.id && option.title),
    chapterCount: normalizeNonNegativeNumber(artifact.chapterCount),
    summary: safeDisplayText(artifact.summary),
    detail: sanitizeArtifactValue(artifact.detail) as Record<string, unknown>,
    versions: asArray(artifact.versions).map((version) => ({
      id: String(version.id ?? ""),
      version: normalizeNonNegativeNumber(version.version) || 1,
      title: safeDisplayText(version.title),
      summary: safeDisplayText(version.summary),
      createdAt: safeDisplayText(version.createdAt),
      selected: Boolean(version.selected),
      detail: sanitizeArtifactValue(version.detail) as Record<string, unknown>
    })).filter((version) => version.id)
  };
}

function sanitizeArtifactValue(value: unknown): unknown {
  if (typeof value === "string") {
    return safeDisplayText(value);
  }
  if (Array.isArray(value)) {
    return value.map(sanitizeArtifactValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, sanitizeArtifactValue(item)])
    );
  }
  return value;
}

function normalizeCreationOptions(options?: BookCreationOptions): BookCreationOptions {
  if (!options?.platformStyles?.length || !options?.genres?.length) {
    return bookCreationOptions;
  }
  return {
    platformStyles: asArray(options.platformStyles).map((style) => ({
      ...style,
      id: String(style.id ?? ""),
      label: safeDisplayText(style.label),
      platform: String(style.platform ?? "generic"),
      status: style.status === "active" || style.status === "candidate" || style.status === "planned" ? style.status : "candidate",
      genres: normalizeStringList(style.genres),
      summary: safeDisplayText(style.summary)
    })),
    genres: asArray(options.genres).map((genre) => ({
      ...genre,
      label: safeDisplayText(genre.label),
      value: safeDisplayText(genre.value),
      platformHints: normalizeStringList(genre.platformHints)
    })),
    platformLabels: {
      ...bookCreationOptions.platformLabels,
      ...options.platformLabels
    }
  };
}

export function normalizeBook(book: Partial<Book>): Book {
  return {
    id: String(book.id ?? ""),
    title: safeDisplayText(book.title) || "未命名作品",
    genre: safeDisplayText(book.genre) || "待定题材",
    platform: book.platform ?? "generic",
    styleProfileId: book.styleProfileId ?? "generic-web-serial",
    styleProfileLabel: safeDisplayText(book.styleProfileLabel) || "通用网文连载",
    tagline: safeDisplayText(book.tagline),
    progress: normalizePercent(book.progress),
    updatedAt: safeDisplayText(book.updatedAt),
    nextAction: safeAuthorActionText(book.nextAction, ""),
    currentModelId: String(book.currentModelId ?? ""),
    writingPlan: {
      targetChapterCount: normalizePositiveNumber(book.writingPlan?.targetChapterCount, 100),
      targetWordsPerChapter: normalizePositiveNumber(book.writingPlan?.targetWordsPerChapter, 2500),
      targetChaptersPerPlot: normalizePositiveNumber(book.writingPlan?.targetChaptersPerPlot, 10)
    },
    qualitySummary: normalizeBookQualitySummary(book.qualitySummary),
    arcs: asArray(book.arcs).map(normalizeArcSummary),
    memoryInspection: normalizeMemoryInspection(book.memoryInspection),
    chapters: asArray(book.chapters).map(normalizeChapter)
  };
}

function normalizeBookQualitySummary(value: Book["qualitySummary"] | undefined): Book["qualitySummary"] {
  return {
    completedChapterCount: normalizeNonNegativeNumber(value?.completedChapterCount),
    targetChapterCount: normalizeNonNegativeNumber(value?.targetChapterCount),
    averageQualityScore: normalizePercent(value?.averageQualityScore),
    recentAverageQualityScore: normalizePercent(value?.recentAverageQualityScore),
    trainingEligibleCount: normalizeNonNegativeNumber(value?.trainingEligibleCount),
    lastTrainingRunAt: safeDisplayText(value?.lastTrainingRunAt),
    coherenceScore: normalizePercent(value?.coherenceScore),
    tensionPoints: asArray(value?.tensionPoints).map(normalizeTensionPoint)
  };
}

function normalizeTensionPoint(value: Partial<TensionPoint>): TensionPoint {
  return {
    chapterId: String(value.chapterId ?? ""),
    qualityScore: normalizePercent(value.qualityScore),
    conflictMarkers: normalizeNonNegativeNumber(value.conflictMarkers),
    warning: Boolean(value.warning)
  };
}

function normalizeArcSummary(value: Partial<ArcSummary>): ArcSummary {
  return {
    arcId: String(value.arcId ?? ""),
    title: safeDisplayText(value.title) || "未命名弧线",
    chapterRange: safeDisplayText(value.chapterRange),
    arcGoal: safeDisplayText(value.arcGoal),
    emotionalArc: safeDisplayText(value.emotionalArc),
    status: safeDisplayText(value.status) || "in_progress",
    progress: normalizePercent(value.progress)
  };
}

function normalizeMemoryInspection(value: Partial<MemoryInspection> | undefined): MemoryInspection {
  return {
    characters: asArray(value?.characters),
    relationships: {
      nodeCount: normalizeNonNegativeNumber(value?.relationships?.nodeCount),
      edgeCount: normalizeNonNegativeNumber(value?.relationships?.edgeCount),
      edges: asArray(value?.relationships?.edges)
    },
    promises: asArray(value?.promises).map(normalizeMaterial),
    arcs: asArray(value?.arcs).map(normalizeArcSummary)
  };
}

export function normalizeChapter(chapter: Partial<Chapter> = {}): Chapter {
  return {
    id: String(chapter.id ?? ""),
    title: safeDisplayText(chapter.title) || "未命名章节",
    status: normalizeChapterStatus(chapter.status),
    wordCount: normalizeNonNegativeNumber(chapter.wordCount),
    progress: normalizePercent(chapter.progress),
    summary: safeDisplayText(chapter.summary),
    content: String(chapter.content ?? ""),
    tasks: normalizeStringList(chapter.tasks),
    plotPoints: normalizeStringList(chapter.plotPoints),
    people: normalizeStringList(chapter.people),
    clues: normalizeStringList(chapter.clues),
    linkedMaterialIds: normalizeIdList(chapter.linkedMaterialIds),
    targetWordCount: Math.max(1, normalizeNonNegativeNumber(chapter.targetWordCount) || 3000),
    review: normalizeStringList(chapter.review)
  };
}

export function normalizeMaterial(material: Partial<Material>): Material {
  return {
    id: String(material.id ?? ""),
    bookId: String(material.bookId ?? ""),
    type: normalizeMaterialType(material.type),
    title: safeDisplayText(material.title) || "未命名资料",
    summary: safeDisplayText(material.summary),
    influence: safeDisplayText(material.influence),
    related: normalizeStringList(material.related),
    confidence: normalizePercent(material.confidence),
    dueStatus: normalizeDueStatus(material.dueStatus),
    details: normalizeDetails(material.details)
  };
}

function normalizeDueStatus(value: Material["dueStatus"] | undefined): Material["dueStatus"] {
  return value === "at_risk" || value === "overdue" || value === "resolved" ? value : "on_track";
}

export function normalizeReview(review: Partial<ReviewItem>): ReviewItem {
  return {
    id: String(review.id ?? ""),
    bookId: String(review.bookId ?? ""),
    title: safeDisplayText(review.title) || "未命名审稿项",
    status: normalizeReviewStatus(review.status),
    priority: review.priority === "高" || review.priority === "低" ? review.priority : "中",
    chapterId: String(review.chapterId ?? ""),
    focus: normalizeStringList(review.focus),
    suggestion: safeDisplayText(review.suggestion)
  };
}

export function normalizeCreateBookResponse(
  response: Partial<CreateBookResponse>,
  requestBody: CreateBookRequest
): CreateBookResponse {
  const book = normalizeBook({
    title: requestBody.draft.title,
    genre: requestBody.draft.genre,
    platform: requestBody.draft.platform,
    styleProfileId: requestBody.draft.styleProfileId,
    styleProfileLabel: requestBody.draft.styleProfileLabel,
    tagline: requestBody.draft.tagline,
    currentModelId: requestBody.defaultModelId,
    ...(response.book ?? {})
  });
  const chapter = normalizeChapter({
    id: "001",
    title: requestBody.draft.firstChapterTitle,
    ...(response.chapter ?? {})
  });
  const responseReview: Partial<ReviewItem> = response.review ?? {};
  return {
    book,
    chapter,
    review: normalizeReview({
      ...responseReview,
      bookId: responseReview.bookId ?? book.id,
      chapterId: responseReview.chapterId ?? chapter.id
    }),
    generationState: response.generationState
      ? normalizeGenerationState({ ...response.generationState, bookId: response.generationState.bookId || book.id })
      : undefined,
    authorMessage: safeDisplayText(response.authorMessage)
  };
}

export function normalizeMaterialMutationResponse(
  response: Partial<MaterialMutationResponse>,
  requestMaterial: Material
): MaterialMutationResponse {
  return {
    material: normalizeMaterial({
      ...requestMaterial,
      ...(response.material ?? {}),
      bookId: response.material?.bookId ?? requestMaterial.bookId
    })
  };
}

export function normalizeDeleteMaterialResponse(
  response: Partial<DeleteMaterialResponse>,
  bookId: string,
  materialId: string
): DeleteMaterialResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    materialId: String(response.materialId ?? materialId),
    removed: Boolean(response.removed),
    affectedChapters: asArray(response.affectedChapters).map(normalizeChapter),
    summary: safeDisplayText(response.summary)
  };
}

export function normalizeSetBookModelResponse(
  response: Partial<SetBookModelResponse>,
  requestBody: SetBookModelRequest
): SetBookModelResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    modelId: String(response.modelId ?? requestBody.modelId)
  };
}

export function normalizeChapterDraftResponse(
  response: Partial<ApplyChapterDraftResponse>,
  requestBody: ApplyChapterDraftRequest
): ApplyChapterDraftResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapter: normalizeChapter({
      id: requestBody.chapterId,
      content: requestBody.nextContent,
      ...(response.chapter ?? {})
    })
  };
}

export function normalizeChapterPlanningResponse(
  response: Partial<UpdateChapterPlanningResponse>,
  requestBody: UpdateChapterPlanningRequest
): UpdateChapterPlanningResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapter: normalizeChapter({
      id: requestBody.chapterId,
      tasks: requestBody.tasks,
      plotPoints: requestBody.plotPoints,
      ...(response.chapter ?? {})
    })
  };
}

export function normalizeLinkChapterMaterialsResponse(
  response: Partial<LinkChapterMaterialsResponse>,
  requestBody: LinkChapterMaterialsRequest
): LinkChapterMaterialsResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapterId: String(response.chapterId ?? requestBody.chapterId),
    chapter: normalizeChapter({
      id: requestBody.chapterId,
      linkedMaterialIds: requestBody.materialIds,
      ...(response.chapter ?? {})
    }),
    linkedMaterials: asArray(response.linkedMaterials).map((material) => ({
      id: String(material.id ?? ""),
      title: safeDisplayText(material.title),
      type: safeDisplayText(material.type)
    })),
    summary: safeDisplayText(response.summary)
  };
}

export function normalizeAcceptChapterResponse(
  response: Partial<AcceptChapterResponse>,
  requestBody: AcceptChapterRequest
): AcceptChapterResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapter: normalizeChapter({
      id: requestBody.chapterId,
      ...(response.chapter ?? {})
    }),
    gate: response.gate ? normalizeGatePayload(response.gate) : undefined,
    review: response.review ? normalizeReview(response.review) : undefined,
    patchPath: response.patchPath ? "[已生成接收后复盘]" : ""
  };
}

export function normalizeCreateNextChapterResponse(
  response: Partial<CreateNextChapterResponse>
): CreateNextChapterResponse {
  return {
    chapter: normalizeChapter(response.chapter)
  };
}

export function normalizeReviewRepairResponse(
  response: Partial<ApplyReviewRepairResponse>,
  requestBody: ApplyReviewRepairRequest
): ApplyReviewRepairResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    reviewId: String(response.reviewId ?? requestBody.reviewId),
    chapter: normalizeChapter(response.chapter)
  };
}

export function normalizeBookReviewsResponse(
  response: Partial<BookReviewsResponse>,
  bookId: string
): BookReviewsResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    chapterId: String(response.chapterId ?? ""),
    reviews: asArray(response.reviews).map(normalizeReview)
  };
}

export function normalizeRunReviewsResponse(
  response: Partial<RunReviewsResponse>,
  requestBody: RunReviewsRequest
): RunReviewsResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapterId: String(response.chapterId ?? requestBody.chapterId ?? ""),
    reviews: asArray(response.reviews).map(normalizeReview)
  };
}

export function normalizeUpdateReviewStatusResponse(
  response: Partial<UpdateReviewStatusResponse>,
  requestBody: UpdateReviewStatusRequest
): UpdateReviewStatusResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    review: normalizeReview({
      id: requestBody.reviewId,
      bookId: requestBody.bookId,
      status: requestBody.status,
      ...response.review
    })
  };
}

export function normalizeChapterMemoryUpdatesResponse(
  response: Partial<ChapterMemoryUpdatesResponse>,
  bookId: string,
  chapterId: string
): ChapterMemoryUpdatesResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    chapterId: String(response.chapterId ?? chapterId),
    memoryUpdates: asArray(response.memoryUpdates).map((item) => normalizeMemoryUpdate(item, bookId, chapterId))
  };
}

export function normalizeApplyMemoryUpdateResponse(
  response: Partial<ApplyMemoryUpdateResponse>,
  updateId: string,
  bookId: string,
  chapterId = ""
): ApplyMemoryUpdateResponse {
  const nextChapterId = String(response.chapterId ?? chapterId);
  return {
    bookId: String(response.bookId ?? bookId),
    chapterId: nextChapterId,
    memoryUpdate: normalizeMemoryUpdate(response.memoryUpdate, bookId, nextChapterId, updateId),
    summary: safeAuthorActionText(response.summary, "")
  };
}

export function normalizeAgentAssistResponse(response: Partial<AgentAssistResponse>): AgentAssistResponse {
  const content = safeAgentText(response.content, "AI 已生成候选建议。");
  const candidateText = response.candidateText
    ? safeAgentText(response.candidateText, content)
    : undefined;
  return {
    title: safeAgentText(response.title, "AI 候选"),
    content,
    suggestions: normalizeAgentTextList(response.suggestions),
    candidateText,
    material: response.material ? normalizeMaterial(response.material) : undefined,
    model: response.model ? normalizeModel(response.model) : undefined,
    usage: response.usage ? {
      inputTokens: normalizeNonNegativeNumber(response.usage.inputTokens),
      outputTokens: normalizeNonNegativeNumber(response.usage.outputTokens),
      totalTokens: normalizeNonNegativeNumber(response.usage.totalTokens),
      cachedInputTokens: normalizeNonNegativeNumber(response.usage.cachedInputTokens),
      reasoningTokens: normalizeNonNegativeNumber(response.usage.reasoningTokens),
      source: safeDisplayText(response.usage.source)
    } : undefined,
    accountName: safeDisplayText(response.accountName),
    cacheHit: Boolean(response.cacheHit),
    compressed: Boolean(response.compressed)
  };
}

export function normalizeAcceptChapterBlockedDetail(
  detail: unknown,
  bookId: string,
  chapterId: string
): AcceptChapterBlockedDetail | null {
  if (!detail || typeof detail !== "object") {
    return null;
  }
  const candidate = detail as Partial<AcceptChapterBlockedDetail>;
  if (!candidate.gate || candidate.gate.status !== "block") {
    return null;
  }
  const gate = normalizeGatePayload(candidate.gate);
  return {
    message: safeDisplayText(candidate.message) || "接收前检查仍有阻断项。",
    gate: {
      ...gate,
      status: "block"
    },
    recovery: candidate.recovery
      ? normalizeChapterGateRecoveryResponse(candidate.recovery, bookId, chapterId)
      : undefined
  };
}

function normalizeMemoryUpdate(
  item: Partial<MemoryUpdateItem> | undefined,
  bookId: string,
  chapterId: string,
  fallbackId = ""
): MemoryUpdateItem {
  const action = normalizeMemoryUpdateAction(item?.action);
  const status = normalizeMemoryUpdateStatus(item?.status);
  return {
    id: String(item?.id ?? fallbackId),
    bookId: String(item?.bookId ?? bookId),
    chapterId: String(item?.chapterId ?? chapterId),
    title: safeDisplayText(item?.title) || "记忆更新候选",
    summary: safeDisplayText(item?.summary),
    targetLabel: safeDisplayText(item?.targetLabel),
    action,
    actionLabel: safeDisplayText(item?.actionLabel) || memoryActionLabel(action),
    status,
    statusLabel: safeDisplayText(item?.statusLabel) || memoryStatusLabel(status),
    canApply: Boolean(item?.canApply) && status !== "applied" && status !== "rejected" && action !== "defer",
    blockedReason: safeDisplayText(item?.blockedReason),
    evidence: normalizeStringList(item?.evidence).slice(0, 3)
  };
}

export function normalizeChapterPrepareResponse(
  response: Partial<ChapterPrepareResponse>,
  requestBody: ChapterPrepareRequest
): ChapterPrepareResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapterId: String(response.chapterId ?? requestBody.chapterId),
    readiness: {
      status: normalizeGateStatus(response.readiness?.status),
      score: normalizePercent(response.readiness?.score),
      issues: asArray(response.readiness?.issues).map(normalizeReadinessIssue),
      missingContext: normalizeStringList(response.readiness?.missingContext),
      recommendedNextAction: safeAuthorActionText(response.readiness?.recommendedNextAction, "")
    },
    contextPack: {
      status: normalizeContextPackStatus(response.contextPack?.status),
      summary: safeDisplayText(response.contextPack?.summary),
      includedCount: normalizeNonNegativeNumber(response.contextPack?.includedCount),
      estimatedTokens: normalizeNonNegativeNumber(response.contextPack?.estimatedTokens),
      tokenBudget: Math.max(1, normalizeNonNegativeNumber(response.contextPack?.tokenBudget) || 1),
      buildDurationMs: normalizeNonNegativeNumber(response.contextPack?.buildDurationMs),
      items: asArray(response.contextPack?.items).map((item) => ({
        source: safeDisplayText(item.source),
        type: safeDisplayText(item.type) || "context",
        reason: safeDisplayText(item.reason),
        tokenEstimate: normalizeNonNegativeNumber(item.tokenEstimate)
      }))
    },
    display: safeDisplayText(response.display)
  };
}

export function normalizeChapterGateResponse(
  response: Partial<ChapterGateResponse>,
  requestBody: ChapterGateRequest
): ChapterGateResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    chapterId: String(response.chapterId ?? requestBody.chapterId),
    gate: normalizeGatePayload(response.gate),
    display: safeDisplayText(response.display)
  };
}

export function normalizeChapterGateRecoveryResponse(
  response: Partial<ChapterGateRecoveryResponse>,
  bookId: string,
  chapterId: string
): ChapterGateRecoveryResponse {
  const status = normalizeGateStatus(response.status);
  return {
    schemaVersion: normalizeNonNegativeNumber(response.schemaVersion || 1),
    bookId: String(response.bookId ?? bookId),
    chapterId: String(response.chapterId ?? chapterId),
    status,
    score: normalizePercent(response.score),
    blocked: response.blocked ?? status === "block",
    issueCount: normalizeNonNegativeNumber(response.issueCount),
    steps: asArray(response.steps).map(normalizeRecoveryStep),
    recommendedNextAction: safeAuthorActionText(response.recommendedNextAction, "")
  };
}

export function normalizeGatePayload(gate: AcceptChapterResponse["gate"] | ChapterGateResponse["gate"] | undefined): ChapterGateResponse["gate"] {
  return {
    status: normalizeGateStatus(gate?.status),
    score: normalizePercent(gate?.score),
    issues: asArray(gate?.issues).map(normalizeGateIssue),
    recommendedNextAction: safeAuthorActionText(gate?.recommendedNextAction, "")
  };
}

function normalizeReadinessIssue(issue: Partial<ChapterReadinessIssue>): ChapterReadinessIssue {
  return {
    severity: normalizeIssueSeverity(issue.severity),
    field: safeDisplayText(issue.field),
    message: safeDisplayText(issue.message),
    quickFix: safeDisplayText(issue.quickFix)
  };
}

function normalizeGateIssue(issue: Partial<ChapterGateIssue>): ChapterGateIssue {
  return {
    severity: normalizeIssueSeverity(issue.severity),
    stage: normalizeIssueStage(issue.stage),
    type: safeDisplayText(issue.type),
    message: safeDisplayText(issue.message),
    evidence: normalizeStringList(issue.evidence).slice(0, 3),
    textSnippet: safeDisplayText(issue.textSnippet),
    suggestionHint: safeDisplayText(issue.suggestionHint)
  };
}

function normalizeRecoveryStep(step: Partial<ChapterGateRecoveryStep>): ChapterGateRecoveryStep {
  return {
    stage: normalizeIssueStage(step.stage),
    severity: step.severity === "" ? "" : normalizeIssueSeverity(step.severity),
    issueCount: normalizeNonNegativeNumber(step.issueCount),
    types: normalizeStringList(step.types),
    targets: asArray(step.targets).map((target) => ({
      kind: safeDisplayText(target.kind),
      path: target.path ? "[已隐藏本地路径]" : "",
      field: safeDisplayText(target.field),
      label: safeDisplayText(target.label)
    })),
    action: safeDisplayText(step.action)
  };
}

function safeAgentText(value: unknown, fallback: string): string {
  const text = safeDisplayText(value);
  if (!text) {
    return fallback;
  }
  const lines = text
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line && !agentInternalLinePattern.test(line) && !hiddenInternalTextPattern.test(line));
  return lines.join("\n").trim() || fallback;
}

function generationStageLabel(stage: GenerationStage) {
  return {
    architecture: "作品架构",
    blueprint: "章节蓝图",
    contract: "章节规划",
    context: "上下文包",
    draft: "章节草稿候选",
    gate: "接收前检查",
    review: "审稿与修复候选",
    accept: "定稿接收",
    memory: "记忆和资料更新",
    next_chapter: "下一章准备"
  }[stage];
}

function generationStatusLabel(status: GenerationStatus) {
  return {
    idle: "待推进",
    running: "生成中",
    waiting_confirm: "待确认",
    blocked: "已阻断",
    paused: "已暂停",
    completed: "本次完成"
  }[status];
}

function generationModeLabel(mode: GenerationMode) {
  return {
    full_auto: "全自动",
    stage_confirm: "阶段确认",
    chapter_confirm: "逐章确认",
    deep_control: "深度干预"
  }[mode];
}

function normalizeAgentTextList(value: unknown): string[] {
  return normalizeStringList(value)
    .map((item) => safeAgentText(item, ""))
    .filter(Boolean);
}

function safeAuthorActionText(value: unknown, fallback: string): string {
  const text = safeDisplayText(value);
  if (!text) {
    return fallback;
  }
  const mapped = authorActionLabels[text];
  if (mapped) {
    return mapped;
  }
  if (/^[a-z][a-z0-9]*(?:-[a-z0-9]+){1,}$/i.test(text)) {
    return fallback || "请按当前提示处理后再继续。";
  }
  return text;
}

function safeModelActionText(value: unknown): string {
  return safeAuthorActionText(safeModelText(value), "请先处理模型提示，再重新验证。");
}

function normalizeModelTextList(value: unknown): string[] {
  return normalizeStringList(value).map(safeModelText).filter(Boolean);
}

function safeModelText(value: unknown): string {
  const text = safeDisplayText(value);
  if (!text) {
    return "";
  }
  if (/^codex cli$/i.test(text)) {
    return text;
  }
  if (/modelId is required/i.test(text)) {
    return "请选择要验证的模型。";
  }
  const projectRegisteredText = "项目" + "已注册";
  if (text.includes(projectRegisteredText)) {
    return text === projectRegisteredText ? "项目模型" : "项目模型，可用于当前书候选生成。";
  }
  if (/已在项目模型注册表中找到 profile/i.test(text)) {
    return "已找到项目模型配置。";
  }
  if (/当前工作区没有找到对应模型 profile/i.test(text)) {
    return "当前工作区没有找到对应模型配置。";
  }
  if (/当前 profile 还没有 inference command template/i.test(text)) {
    return "当前模型还缺少调用配置。";
  }
  if (/已配置 inference command template/i.test(text)) {
    return "已找到模型调用配置。";
  }
  if (/检查当前 profile 是否可供工作台使用/i.test(text)) {
    return "检查当前模型是否可供工作台使用。";
  }
  if (/^已找到 CLI[:：]/i.test(text)) {
    return "写作工具可用。";
  }
  if (/未找到 codex CLI 可执行文件/i.test(text)) {
    return "写作工具暂不可用。";
  }
  if (/先安装或修复 codex CLI/i.test(text)) {
    return "先准备写作工具，再重新验证。";
  }
  if (/本机 CLI 环境|codex CLI/i.test(text)) {
    return text.replace(/本机 CLI 环境/gi, "写作工具环境").replace(/codex CLI/gi, "写作工具");
  }
  if (/尚未填写 base model 或 adapter path/i.test(text)) {
    return "当前模型信息还不完整。";
  }
  if (/^base model[:：]/i.test(text)) {
    return "基础模型信息已填写。";
  }
  if (/^adapter[:：]/i.test(text)) {
    return "模型适配信息已填写。";
  }
  if (/已找到 adapter 路径/i.test(text)) {
    return "模型文件可用。";
  }
  if (/adapter path 当前不存在/i.test(text)) {
    return "模型文件暂不可用，验证未通过。";
  }
  if (/超时设置[:：]/i.test(text)) {
    return "模型响应时间限制已配置。";
  }
  if (/^命令入口可解析[:：]/.test(text)) {
    return "模型调用入口可用。";
  }
  if (/命令模板缺少占位符/.test(text)) {
    return "模型调用配置缺少必要内容。";
  }
  if (/命令模板已配置|执行入口不存在|不在 PATH 中/.test(text)) {
    return "模型调用入口暂不可用。";
  }
  if (/命令模板当前无法解析/.test(text)) {
    return "模型调用配置暂不可用。";
  }
  if (/先修复命令模板、执行入口或模型路径/.test(text)) {
    return "先修复模型调用配置或模型文件，再重新验证。";
  }
  if (/旧模型标识|尚未注册该模型|模型注册状态/.test(text)) {
    return text.replace(/旧模型标识，或当前书尚未注册该模型。/, "这个模型暂不可用于当前书。")
      .replace("先确认模型注册状态，再重新验证。", "先确认模型是否可用于当前书，再重新验证。");
  }
  if (/profile/i.test(text)) {
    return text.replace(/\bprofile\b/gi, "模型配置");
  }
  if (/adapter path|adapter/i.test(text)) {
    return text.replace(/adapter path/gi, "模型文件").replace(/adapter/gi, "模型文件");
  }
  if (/command template|inference/i.test(text)) {
    return "模型调用配置需要检查。";
  }
  return text;
}

export function normalizeModel(model: ModelProfile): ModelProfile {
  return {
    ...model,
    name: safeModelText(model.name),
    source: normalizeModelSource(model.source),
    sourceLabel: safeModelText(model.sourceLabel ?? ""),
    status: normalizeModelStatus(model.status),
    coverage: normalizePercent(model.coverage),
    purpose: safeModelText(model.purpose),
    statusNote: safeModelText(model.statusNote ?? ""),
    samples: normalizeModelTextList(model.samples),
    checks: normalizeModelTextList(model.checks),
    warnings: normalizeModelTextList(model.warnings),
    recommendedNextAction: safeModelActionText(model.recommendedNextAction ?? ""),
    actions: asArray(model.actions)
      .filter((action) => action.key === "apply" || action.key === "validate")
      .map((action) => ({
        key: action.key,
        label: safeModelText(action.label),
        description: safeModelText(action.description)
      }))
  };
}

export function normalizeValidationResult(result: ValidateModelResponse): ValidateModelResponse {
  return {
    ...result,
    status: normalizeModelStatus(result.status),
    checks: normalizeModelTextList(result.checks),
    warnings: normalizeModelTextList(result.warnings),
    recommendedNextAction: safeModelActionText(result.recommendedNextAction ?? "")
  };
}

function normalizeModelStatus(status: string | undefined): ModelProfile["status"] {
  return status === "可使用" ? "可使用" : "待验证";
}

function normalizePositiveNumber(value: unknown, fallback: number) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.round(number) : fallback;
}

function normalizeGateStatus(status: string | undefined): "pass" | "warn" | "block" {
  return gateStatusValues.includes(status as "pass" | "warn" | "block") ? status as "pass" | "warn" | "block" : "warn";
}

function normalizeIssueSeverity(severity: string | undefined): "low" | "medium" | "high" | "blocker" {
  return issueSeverityValues.includes(severity as "low" | "medium" | "high" | "blocker")
    ? severity as "low" | "medium" | "high" | "blocker"
    : "medium";
}

function normalizeIssueStage(stage: string | undefined): ChapterGateIssue["stage"] {
  return issueStageValues.includes(stage as ChapterGateIssue["stage"])
    ? stage as ChapterGateIssue["stage"]
    : "quality";
}

function normalizeContextPackStatus(status: string | undefined): ChapterPrepareResponse["contextPack"]["status"] {
  return status === "ready" || status === "missing" ? status : "skipped";
}

function normalizeModelSource(source: ModelSource | undefined): ModelSource {
  return source === "project" ? "project" : "builtin";
}

function normalizeChapterStatus(status: ChapterStatus | undefined): ChapterStatus {
  return chapterStatusValues.includes(status as ChapterStatus) ? status as ChapterStatus : "待写";
}

function normalizeReviewStatus(status: ReviewStatus | undefined): ReviewStatus {
  return reviewStatusValues.includes(status as ReviewStatus) ? status as ReviewStatus : "待处理";
}

export function normalizeMaterialType(type: MaterialType | undefined): MaterialType {
  return materialTypeValues.includes(type as MaterialType) ? type as MaterialType : "设定";
}

function normalizeMemoryUpdateAction(action: string | undefined): MemoryUpdateItem["action"] {
  return memoryUpdateActions.includes(action as MemoryUpdateItem["action"]) ? action as MemoryUpdateItem["action"] : "update";
}

function normalizeMemoryUpdateStatus(status: string | undefined): MemoryUpdateItem["status"] {
  return memoryUpdateStatuses.includes(status as MemoryUpdateItem["status"]) ? status as MemoryUpdateItem["status"] : "proposed";
}

function memoryActionLabel(action: MemoryUpdateItem["action"]) {
  return {
    add: "新增",
    update: "更新",
    close: "关闭",
    defer: "暂缓"
  }[action];
}

function memoryStatusLabel(status: MemoryUpdateItem["status"]) {
  return {
    proposed: "待确认",
    accepted: "可写入",
    rejected: "已跳过",
    applied: "已应用"
  }[status];
}
