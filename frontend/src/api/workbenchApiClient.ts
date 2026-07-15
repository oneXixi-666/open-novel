import type { AISettings, Material, MaterialType, WorkspaceData } from "../types";
import {
  normalizeAcceptChapterBlockedDetail,
  normalizeAcceptChapterResponse,
  normalizeAgentAssistResponse,
  normalizeChapterGateRecoveryResponse,
  normalizeChapterGateResponse,
  normalizeChapterPrepareResponse,
  normalizeChapterDraftResponse,
  normalizeChapterPlanningResponse,
  normalizeCreateBookResponse,
  normalizeCreateNextChapterResponse,
  normalizeDeleteMaterialResponse,
  normalizeGenerationResponse,
  normalizeLinkChapterMaterialsResponse,
  normalizeMaterial,
  normalizeMaterialMutationResponse,
  normalizeMaterialType,
  normalizeApplyMemoryUpdateResponse,
  normalizeBookReviewsResponse,
  normalizeChapterMemoryUpdatesResponse,
  normalizeReviewRepairResponse,
  normalizeRunReviewsResponse,
  normalizeSetBookModelResponse,
  normalizeBook,
  normalizeUpdateReviewStatusResponse,
  normalizeValidationResult,
  normalizeWorkspace
} from "./workbenchNormalizers";
import { asArray, safeDisplayText } from "./workbenchNormalizerUtils";
import {
  normalizeExportCheckResponse,
  normalizeExportGenerateResponse,
  normalizeJobDetailResponse,
  normalizeJobEventsResponse,
  normalizeJobMutationResponse,
  normalizeJobsResponse,
  normalizeRunsResponse
} from "./workbenchOperationNormalizers";
import type {
  AcceptChapterRequest,
  AcceptChapterResponse,
  AgentAssistRequest,
  AgentAssistResponse,
  AIAccountInput,
  AIProbeResponse,
  ModelLibraryCategory,
  ModelLibraryItem,
  ModelLibraryMutationResponse,
  ModelLibraryReadiness,
  ModelLibraryResponse,
  ModelLibrarySourcesResponse,
  ModelLibraryTrainingResponse,
  ModelTrainingBackend,
  ModelTrainingRunRequest,
  ModelTrainingRunResponse,
  ApplyChapterDraftRequest,
  ApplyChapterDraftResponse,
  ApplyMemoryUpdateRequest,
  ApplyMemoryUpdateResponse,
  ApplyReviewRepairRequest,
  ApplyReviewRepairResponse,
  ChapterMemoryUpdatesResponse,
  ChapterContractResponse,
  ChapterMaterialsResponse,
  ChapterPolishRequest,
  ChapterPolishResponse,
  CharacterSnapshotResponse,
  ChapterGateRequest,
  ChapterGateRecoveryResponse,
  ChapterGateResponse,
  ChapterPrepareRequest,
  ChapterPrepareResponse,
  ApplyPlotDirectionRequest,
  ApplyPlotDirectionResponse,
  BookAnalysisResponse,
  CreateBookRequest,
  CreateBookResponse,
  DeleteMaterialResponse,
  CreateNextChapterResponse,
  ExportCheckResponse,
  ExportGenerateResponse,
  ExportRequest,
  FetchBookWorkspaceResponse,
  FetchWorkspaceResponse,
  GenerationActionRequest,
  GenerationModeRequest,
  GenerationResponse,
  GenerationTakeoverRequest,
  JobDetailResponse,
  JobEventsResponse,
  JobMutationResponse,
  KnowledgeRebuildResponse,
  KnowledgeSearchResponse,
  LinkChapterMaterialsRequest,
  LinkChapterMaterialsResponse,
  LongFormPlanResponse,
  LongFormReplanResponse,
  JobsResponse,
  MaterialMutationResponse,
  BookReviewsResponse,
  RunReviewsRequest,
  RunReviewsResponse,
  RunsResponse,
  IdeationSessionResponse,
  IdeationSessionsResponse,
  PlotDirectionResponse,
  RevisionPlanResponse,
  SequenceEvaluationResponse,
  SetBookModelRequest,
  SetBookModelResponse,
  SystemUpdateAutoDetect,
  SystemUpdateInfo,
  SystemUpdatePreparation,
  SystemUpdateStatus,
  UpdateProjectPlanRequest,
  UpdateProjectPlanResponse,
  UpdateBookSettingsRequest,
  UpdateBookSettingsResponse,
  UpdateChapterPlanningRequest,
  UpdateChapterPlanningResponse,
  UpdateChapterContractRequest,
  UpdateReviewStatusRequest,
  UpdateReviewStatusResponse,
  ValidateModelRequest,
  ValidateModelResponse,
  WorkbenchClient,
  WritingAssetsResponse,
  WritingLessonsResponse
} from "./contracts";

export class ApiRequestError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

export const apiWorkbenchClient: WorkbenchClient = {
  async fetchWorkspace(): Promise<FetchWorkspaceResponse> {
    const data = await request<Partial<WorkspaceData>>("/api/workspace");
    return normalizeWorkspace(data);
  },

  async fetchBookWorkspace(bookId: string): Promise<FetchBookWorkspaceResponse> {
    const data = await request<Partial<WorkspaceData>>(`/api/books/${bookPath(bookId)}/workspace`);
    return normalizeWorkspace(data);
  },

  async fetchSystemUpdate(): Promise<SystemUpdateInfo> {
    return request<SystemUpdateInfo>("/api/system/update");
  },

  async autoDetectSystemUpdate(): Promise<SystemUpdateAutoDetect> {
    return request<SystemUpdateAutoDetect>("/api/system/update/auto-detect");
  },

  async fetchSystemUpdateStatus(): Promise<SystemUpdateStatus> {
    return request<SystemUpdateStatus>("/api/system/update/status");
  },

  async prepareSystemUpdate(): Promise<SystemUpdatePreparation> {
    return request<SystemUpdatePreparation>("/api/system/update/install", {
      method: "POST"
    });
  },

  async createBook(requestBody: CreateBookRequest): Promise<CreateBookResponse> {
    const response = await request<Partial<CreateBookResponse>>("/api/books", {
      method: "POST",
      body: requestBody
    });
    return normalizeCreateBookResponse(response, requestBody);
  },

  async updateBookSettings(requestBody: UpdateBookSettingsRequest): Promise<UpdateBookSettingsResponse> {
    const response = await request<Partial<UpdateBookSettingsResponse>>(
      `/api/books/${bookPath(requestBody.bookId)}/settings`,
      {
        method: "PUT",
        body: requestBody
      }
    );
    return {
      bookId: String(response.bookId ?? requestBody.bookId),
      book: normalizeBook(response.book ?? requestBody),
      authorMessage: safeDisplayText(response.authorMessage) || "作品设置已保存。"
    };
  },

  async createMaterial(material: Material): Promise<MaterialMutationResponse> {
    const response = await request<Partial<MaterialMutationResponse>>(`/api/books/${bookPath(material.bookId)}/materials`, {
      method: "POST",
      body: material
    });
    return normalizeMaterialMutationResponse(response, material);
  },

  async updateMaterial(material: Material): Promise<MaterialMutationResponse> {
    const response = await request<Partial<MaterialMutationResponse>>(
      `/api/books/${bookPath(material.bookId)}/materials/${encodeURIComponent(material.id)}`,
      {
        method: "PUT",
        body: material
      }
    );
    return normalizeMaterialMutationResponse(response, material);
  },

  async deleteMaterial(bookId: string, materialId: string): Promise<DeleteMaterialResponse> {
    const response = await request<Partial<DeleteMaterialResponse>>(
      `/api/books/${bookPath(bookId)}/materials/${encodeURIComponent(materialId)}`,
      {
        method: "DELETE"
      }
    );
    return normalizeDeleteMaterialResponse(response, bookId, materialId);
  },

  async setBookModel(requestBody: SetBookModelRequest): Promise<SetBookModelResponse> {
    const response = await request<Partial<SetBookModelResponse>>(`/api/books/${bookPath(requestBody.bookId)}/model`, {
      method: "PUT",
      body: requestBody
    });
    return normalizeSetBookModelResponse(response, requestBody);
  },

  async updateProjectPlan(requestBody: UpdateProjectPlanRequest): Promise<UpdateProjectPlanResponse> {
    const response = await request<Partial<UpdateProjectPlanResponse>>(
      `/api/books/${bookPath(requestBody.bookId)}/plan`,
      {
        method: "PUT",
        body: requestBody
      }
    );
    return {
      bookId: String(response.bookId ?? requestBody.bookId),
      plan: {
        targetChapterCount: Number(response.plan?.targetChapterCount ?? requestBody.targetChapterCount),
        targetWordsPerChapter: Number(response.plan?.targetWordsPerChapter ?? requestBody.targetWordsPerChapter),
        targetChaptersPerPlot: Number(response.plan?.targetChaptersPerPlot ?? requestBody.targetChaptersPerPlot)
      },
      book: normalizeBook(response.book ?? {
        id: requestBody.bookId,
        writingPlan: requestBody
      }),
      authorMessage: safeDisplayText(response.authorMessage) || "作品写作参数已保存。"
    };
  },

  async validateModel(requestBody: ValidateModelRequest): Promise<ValidateModelResponse> {
    const response = await request<ValidateModelResponse>(`/api/models/${encodeURIComponent(requestBody.modelId)}/validate`, {
      method: "POST",
      body: requestBody
    });
    return normalizeValidationResult(response);
  },

  async applyChapterDraft(requestBody: ApplyChapterDraftRequest): Promise<ApplyChapterDraftResponse> {
    const response = await request<Partial<ApplyChapterDraftResponse>>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/draft`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeChapterDraftResponse(response, requestBody);
  },

  async updateChapterPlanning(requestBody: UpdateChapterPlanningRequest): Promise<UpdateChapterPlanningResponse> {
    const response = await request<Partial<UpdateChapterPlanningResponse>>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/planning`,
      {
        method: "PUT",
        body: requestBody
      }
    );
    return normalizeChapterPlanningResponse(response, requestBody);
  },

  async linkChapterMaterials(requestBody: LinkChapterMaterialsRequest): Promise<LinkChapterMaterialsResponse> {
    const response = await request<Partial<LinkChapterMaterialsResponse>>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/materials/link`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeLinkChapterMaterialsResponse(response, requestBody);
  },

  async fetchChapterMaterials(
    bookId: string,
    chapterId: string,
    options?: { type?: MaterialType; q?: string; scope?: "related" | "all" }
  ): Promise<ChapterMaterialsResponse> {
    const params = new URLSearchParams();
    if (options?.type) {
      params.set("type", options.type);
    }
    if (options?.q) {
      params.set("q", options.q);
    }
    if (options?.scope) {
      params.set("scope", options.scope);
    }
    const query = params.toString();
    const response = await request<ChapterMaterialsResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/materials${query ? `?${query}` : ""}`
    );
    return {
      ...response,
      bookId: String(response.bookId ?? bookId),
      chapterId: String(response.chapterId ?? chapterId),
      type: response.type ? normalizeMaterialType(response.type) : undefined,
      query: safeDisplayText(response.query),
      scope: response.scope === "all" ? "all" : "related",
      materials: asArray(response.materials).map(normalizeMaterial),
      summary: safeDisplayText(response.summary)
    };
  },

  async fetchWritingLessons(bookId: string): Promise<WritingLessonsResponse> {
    const response = await request<WritingLessonsResponse>(`/api/books/${bookPath(bookId)}/writing-lessons`);
    return {
      bookId: String(response.bookId ?? bookId),
      lessons: asArray(response.lessons).map((lesson) => ({
        id: String(lesson.id ?? ""),
        category: safeDisplayText(lesson.category) || "通用",
        lesson: safeDisplayText(lesson.lesson),
        severity: safeDisplayText(lesson.severity),
        sourceChapters: asArray(lesson.sourceChapters).map((item) => String(item)),
        status: safeDisplayText(lesson.status)
      })),
      groups: asArray(response.groups).map((group) => ({
        category: safeDisplayText(group.category) || "通用",
        lessons: asArray(group.lessons).map((lesson) => ({
          id: String(lesson.id ?? ""),
          category: safeDisplayText(lesson.category) || safeDisplayText(group.category) || "通用",
          lesson: safeDisplayText(lesson.lesson),
          severity: safeDisplayText(lesson.severity),
          sourceChapters: asArray(lesson.sourceChapters).map((item) => String(item)),
          status: safeDisplayText(lesson.status)
        }))
      }))
    };
  },

  async fetchCharacterSnapshot(bookId: string, chapterId: string): Promise<CharacterSnapshotResponse> {
    const response = await request<CharacterSnapshotResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/characters/snapshot`
    );
    return {
      bookId: String(response.bookId ?? bookId),
      chapterId: String(response.chapterId ?? chapterId),
      characters: asArray(response.characters).map((character) => ({
        id: String(character.id ?? ""),
        name: safeDisplayText(character.name) || "未命名人物",
        emotion: safeDisplayText(character.emotion),
        goal: safeDisplayText(character.goal),
        relationshipScore: typeof character.relationshipScore === "number" ? character.relationshipScore : null,
        relationshipStatus: safeDisplayText(character.relationshipStatus),
        chapterId: String(character.chapterId ?? chapterId)
      }))
    };
  },

  async fetchChapterContract(bookId: string, chapterId: string): Promise<ChapterContractResponse> {
    const response = await request<ChapterContractResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/contract`
    );
    return {
      bookId: String(response.bookId ?? bookId),
      chapterId: String(response.chapterId ?? chapterId),
      contract: response.contract ?? {}
    };
  },

  async updateChapterContract(requestBody: UpdateChapterContractRequest): Promise<ChapterContractResponse> {
    const response = await request<ChapterContractResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/contract`,
      {
        method: "PUT",
        body: requestBody
      }
    );
    return {
      bookId: String(response.bookId ?? requestBody.bookId),
      chapterId: String(response.chapterId ?? requestBody.chapterId),
      contract: response.contract ?? {}
    };
  },

  async prepareChapter(requestBody: ChapterPrepareRequest): Promise<ChapterPrepareResponse> {
    const response = await request<ChapterPrepareResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/prepare`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeChapterPrepareResponse(response, requestBody);
  },

  async fetchPlotDirections(bookId: string, chapterId: string, userIntent = ""): Promise<PlotDirectionResponse> {
    return request<PlotDirectionResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/plot-directions`,
      {
        method: "POST",
        body: { bookId, chapterId, userIntent }
      }
    );
  },

  async applyPlotDirection(requestBody: ApplyPlotDirectionRequest): Promise<ApplyPlotDirectionResponse> {
    return request<ApplyPlotDirectionResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/plot-directions/apply`,
      {
        method: "POST",
        body: requestBody
      }
    );
  },

  async rebuildKnowledge(bookId: string): Promise<KnowledgeRebuildResponse> {
    return request<KnowledgeRebuildResponse>(`/api/books/${bookPath(bookId)}/knowledge/rebuild`, {
      method: "POST"
    });
  },

  async searchKnowledge(bookId: string, q: string, limit = 6): Promise<KnowledgeSearchResponse> {
    const params = new URLSearchParams({ q, limit: String(limit) });
    return request<KnowledgeSearchResponse>(`/api/books/${bookPath(bookId)}/knowledge/search?${params.toString()}`);
  },

  async fetchWritingAssets(bookId: string): Promise<WritingAssetsResponse> {
    return request<WritingAssetsResponse>(`/api/books/${bookPath(bookId)}/writing-assets`);
  },

  async setWritingFormulaStatus(bookId: string, formulaId: string, status: "active" | "retired"): Promise<WritingAssetsResponse> {
    return request<WritingAssetsResponse>(
      `/api/books/${bookPath(bookId)}/writing-assets/formulas/${encodeURIComponent(formulaId)}`,
      { method: "PUT", body: { bookId, formulaId, status } }
    );
  },

  async polishChapter(requestBody: ChapterPolishRequest): Promise<ChapterPolishResponse> {
    return request<ChapterPolishResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/polish`,
      {
        method: "POST",
        body: requestBody
      }
    );
  },

  async createIdeationSession(requestBody: { bookId: string; title: string; focus?: string; seed?: string }): Promise<IdeationSessionResponse> {
    return request<IdeationSessionResponse>(`/api/books/${bookPath(requestBody.bookId)}/ideation`, {
      method: "POST",
      body: requestBody
    });
  },

  async fetchIdeationSessions(bookId: string): Promise<IdeationSessionsResponse> {
    return request<IdeationSessionsResponse>(`/api/books/${bookPath(bookId)}/ideation`);
  },

  async appendIdeationTurn(bookId: string, sessionId: string, requestBody: { role?: string; content: string }): Promise<IdeationSessionResponse> {
    return request<IdeationSessionResponse>(
      `/api/books/${bookPath(bookId)}/ideation/${encodeURIComponent(sessionId)}/turns`,
      {
        method: "POST",
        body: { ...requestBody, bookId }
      }
    );
  },

  async analyzeBook(requestBody: { bookId: string; startChapterId: string; endChapterId: string }): Promise<BookAnalysisResponse> {
    return request<BookAnalysisResponse>(`/api/books/${bookPath(requestBody.bookId)}/analysis`, {
      method: "POST",
      body: requestBody
    });
  },

  async promoteWritingFormulas(requestBody: { bookId: string; reportPath: string }): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(`/api/books/${bookPath(requestBody.bookId)}/analysis/promote-formulas`, {
      method: "POST",
      body: requestBody
    });
  },

  async evaluateSequence(requestBody: { bookId: string; startChapterId: string; endChapterId: string; preferDrafts?: boolean }): Promise<SequenceEvaluationResponse> {
    return request<SequenceEvaluationResponse>(`/api/books/${bookPath(requestBody.bookId)}/sequence-evaluation`, {
      method: "POST",
      body: requestBody
    });
  },

  async buildRevisionPlan(requestBody: { bookId: string; startChapterId: string; endChapterId: string; maxChapters?: number }): Promise<RevisionPlanResponse> {
    return request<RevisionPlanResponse>(`/api/books/${bookPath(requestBody.bookId)}/revision-plan`, {
      method: "POST",
      body: requestBody
    });
  },

  async checkChapterGate(requestBody: ChapterGateRequest): Promise<ChapterGateResponse> {
    const response = await request<ChapterGateResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/gate`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeChapterGateResponse(response, requestBody);
  },

  async fetchChapterGateRecovery(bookId: string, chapterId: string): Promise<ChapterGateRecoveryResponse> {
    const response = await request<ChapterGateRecoveryResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/gate/recovery`
    );
    return normalizeChapterGateRecoveryResponse(response, bookId, chapterId);
  },

  async acceptChapter(requestBody: AcceptChapterRequest): Promise<AcceptChapterResponse> {
    let response;
    try {
      response = await request<AcceptChapterResponse>(
        `/api/books/${bookPath(requestBody.bookId)}/chapters/${encodeURIComponent(requestBody.chapterId)}/accept`,
        {
          method: "POST",
          body: requestBody
        }
      );
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409) {
        const blockedDetail = normalizeAcceptChapterBlockedDetail(error.detail, requestBody.bookId, requestBody.chapterId);
        if (blockedDetail) {
          throw new ApiRequestError(error.message, error.status, blockedDetail);
        }
      }
      throw error;
    }
    return normalizeAcceptChapterResponse(response, requestBody);
  },

  async createNextChapter(bookId: string): Promise<CreateNextChapterResponse> {
    const response = await request<Partial<CreateNextChapterResponse>>(`/api/books/${bookPath(bookId)}/chapters/next`, {
      method: "POST"
    });
    return normalizeCreateNextChapterResponse(response);
  },

  async applyReviewRepair(requestBody: ApplyReviewRepairRequest): Promise<ApplyReviewRepairResponse> {
    const response = await request<ApplyReviewRepairResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/reviews/${encodeURIComponent(requestBody.reviewId)}/repair`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeReviewRepairResponse(response, requestBody);
  },

  async fetchBookReviews(bookId: string): Promise<BookReviewsResponse> {
    const response = await request<BookReviewsResponse>(`/api/books/${bookPath(bookId)}/reviews`);
    return normalizeBookReviewsResponse(response, bookId);
  },

  async runReviews(requestBody: RunReviewsRequest): Promise<RunReviewsResponse> {
    const response = await request<RunReviewsResponse>(`/api/books/${bookPath(requestBody.bookId)}/reviews/run`, {
      method: "POST",
      body: requestBody
    });
    return normalizeRunReviewsResponse(response, requestBody);
  },

  async updateReviewStatus(requestBody: UpdateReviewStatusRequest): Promise<UpdateReviewStatusResponse> {
    const response = await request<UpdateReviewStatusResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/reviews/${encodeURIComponent(requestBody.reviewId)}`,
      {
        method: "PATCH",
        body: requestBody
      }
    );
    return normalizeUpdateReviewStatusResponse(response, requestBody);
  },

  async checkExport(requestBody: ExportRequest): Promise<ExportCheckResponse> {
    const response = await request<ExportCheckResponse>(`/api/books/${bookPath(requestBody.bookId)}/exports/check`, {
      method: "POST",
      body: requestBody
    });
    return normalizeExportCheckResponse(response, requestBody);
  },

  async generateExport(requestBody: ExportRequest): Promise<ExportGenerateResponse> {
    const response = await request<ExportGenerateResponse>(`/api/books/${bookPath(requestBody.bookId)}/exports`, {
      method: "POST",
      body: requestBody
    });
    return normalizeExportGenerateResponse(response, requestBody);
  },

  async fetchJobs(bookId: string): Promise<JobsResponse> {
    const response = await request<JobsResponse>(`/api/books/${bookPath(bookId)}/jobs`);
    return normalizeJobsResponse(response, bookId);
  },

  async fetchJobDetail(bookId: string, jobId: string): Promise<JobDetailResponse> {
    const response = await request<JobDetailResponse>(`/api/books/${bookPath(bookId)}/jobs/${encodeURIComponent(jobId)}`);
    return normalizeJobDetailResponse(response, bookId, jobId);
  },

  async fetchJobEvents(bookId: string, jobId: string): Promise<JobEventsResponse> {
    const response = await request<JobEventsResponse>(`/api/books/${bookPath(bookId)}/jobs/${encodeURIComponent(jobId)}/events`);
    return normalizeJobEventsResponse(response, bookId, jobId);
  },

  async cancelJob(bookId: string, jobId: string): Promise<JobMutationResponse> {
    const response = await request<JobMutationResponse>(`/api/books/${bookPath(bookId)}/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST"
    });
    return normalizeJobMutationResponse(response, bookId);
  },

  async retryJob(bookId: string, jobId: string): Promise<JobMutationResponse> {
    const response = await request<JobMutationResponse>(`/api/books/${bookPath(bookId)}/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST"
    });
    return normalizeJobMutationResponse(response, bookId);
  },

  async fetchRuns(bookId: string): Promise<RunsResponse> {
    const response = await request<RunsResponse>(`/api/books/${bookPath(bookId)}/runs`);
    return normalizeRunsResponse(response, bookId);
  },

  async fetchChapterMemoryUpdates(bookId: string, chapterId: string): Promise<ChapterMemoryUpdatesResponse> {
    const response = await request<ChapterMemoryUpdatesResponse>(
      `/api/books/${bookPath(bookId)}/chapters/${encodeURIComponent(chapterId)}/memory-updates`
    );
    return normalizeChapterMemoryUpdatesResponse(response, bookId, chapterId);
  },

  async applyMemoryUpdate(updateId: string, requestBody: ApplyMemoryUpdateRequest): Promise<ApplyMemoryUpdateResponse> {
    const response = await request<ApplyMemoryUpdateResponse>(
      `/api/books/${bookPath(requestBody.bookId)}/memory-updates/${encodeURIComponent(updateId)}/apply`,
      {
        method: "POST",
        body: requestBody
      }
    );
    return normalizeApplyMemoryUpdateResponse(response, updateId, requestBody.bookId, requestBody.chapterId);
  },

  async fetchGeneration(bookId: string): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(bookId)}/generation`);
    return normalizeGenerationResponse(response, bookId);
  },

  async fetchLongFormPlan(bookId: string): Promise<LongFormPlanResponse> {
    return request<LongFormPlanResponse>(`/api/books/${bookPath(bookId)}/long-form-plan`);
  },

  async updateVolumeGoal(bookId: string, volumeId: string, goal: string, chapterRange = ""): Promise<LongFormPlanResponse> {
    return request<LongFormPlanResponse>(
      `/api/books/${bookPath(bookId)}/long-form-plan/volumes/${encodeURIComponent(volumeId)}`,
      { method: "PUT", body: { bookId, volumeId, goal, chapterRange } }
    );
  },

  async updateChapterLanding(bookId, landing) {
    return request<{ bookId: string; landing: typeof landing; authorMessage: string }>(`/api/books/${bookPath(bookId)}/long-form-plan/chapters/${encodeURIComponent(landing.chapterId)}`, {
      method: "PUT",
      body: { bookId, ...landing }
    });
  },

  async generateLongFormReplan(bookId: string, chapterId = ""): Promise<LongFormReplanResponse> {
    return request<LongFormReplanResponse>(`/api/books/${bookPath(bookId)}/long-form-plan/replan`, {
      method: "POST",
      body: { bookId, chapterId }
    });
  },

  async confirmLongFormReplan(bookId: string): Promise<LongFormPlanResponse> {
    return request<LongFormPlanResponse>(`/api/books/${bookPath(bookId)}/long-form-plan/replan/confirm`, {
      method: "POST",
      body: { bookId }
    });
  },

  async setGenerationMode(requestBody: GenerationModeRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/mode`, {
      method: "PUT",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async continueGeneration(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/continue`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async confirmGeneration(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/confirm`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async regenerateGenerationCandidate(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/candidates/regenerate`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async selectGenerationCandidate(bookId: string, candidateId: string, requestId = ""): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(bookId)}/generation/candidates/current`, {
      method: "PUT",
      body: { bookId, candidateId, requestId }
    });
    return normalizeGenerationResponse(response, bookId);
  },

  async rollbackGenerationCandidate(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/candidates/rollback`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async pauseGeneration(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/pause`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async resumeGeneration(requestBody: GenerationActionRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/resume`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async takeoverGeneration(requestBody: GenerationTakeoverRequest): Promise<GenerationResponse> {
    const response = await request<Partial<GenerationResponse>>(`/api/books/${bookPath(requestBody.bookId)}/generation/takeover`, {
      method: "POST",
      body: requestBody
    });
    return normalizeGenerationResponse(response, requestBody.bookId);
  },

  async runAgentAssist(requestBody: AgentAssistRequest): Promise<AgentAssistResponse> {
    const response = await request<AgentAssistResponse>("/api/agent/assist", {
      method: "POST",
      body: requestBody
    });
    return normalizeAgentAssistResponse(response);
  },

  async streamAgentAssist(
    requestBody: AgentAssistRequest,
    onToken: (text: string) => void,
    signal?: AbortSignal
  ): Promise<AgentAssistResponse> {
    const response = await fetch(`${apiBase()}/api/agent/assist/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
      signal
    });
    if (!response.ok) {
      const { message, detail } = await errorPayload(response);
      throw new ApiRequestError(message, response.status, detail);
    }
    if (!response.body) {
      throw new ApiRequestError("当前浏览器不支持流式生成。", response.status, null);
    }
    const decoder = new TextDecoder();
    const reader = response.body.getReader();
    let buffer = "";
    let donePayload: Partial<AgentAssistResponse> | null = null;
    let streamError = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";
      for (const event of events) {
        const parsed = parseSseEvent(event);
        if (parsed.event === "token") {
          onToken(String(parsed.data?.text ?? ""));
        }
        if (parsed.event === "done") {
          donePayload = parsed.data as Partial<AgentAssistResponse>;
        }
        if (parsed.event === "error") {
          streamError = safeDisplayText(parsed.data?.message) || "AI 候选生成失败，请稍后重试。";
        }
      }
    }
    if (buffer.trim()) {
      const parsed = parseSseEvent(buffer);
      if (parsed.event === "done") {
        donePayload = parsed.data as Partial<AgentAssistResponse>;
      }
      if (parsed.event === "error") {
        streamError = safeDisplayText(parsed.data?.message) || "AI 候选生成失败，请稍后重试。";
      }
    }
    if (streamError) {
      throw new ApiRequestError(streamError, response.status, streamError);
    }
    return normalizeAgentAssistResponse(donePayload ?? {});
  },

  async fetchAISettings(): Promise<AISettings> {
    return normalizeAISettings(await request<Partial<AISettings>>("/api/ai/settings"));
  },

  async createAIAccount(requestBody: AIAccountInput): Promise<AISettings> {
    const response = await request<{ settings?: Partial<AISettings> }>("/api/ai/accounts", {
      method: "POST",
      body: requestBody
    });
    return normalizeAISettings(response.settings ?? {});
  },

  async updateAIAccount(accountId: string, requestBody: AIAccountInput): Promise<AISettings> {
    const response = await request<{ settings?: Partial<AISettings> }>(
      `/api/ai/accounts/${encodeURIComponent(accountId)}`,
      {
        method: "PUT",
        body: requestBody
      }
    );
    return normalizeAISettings(response.settings ?? {});
  },

  async deleteAIAccount(accountId: string): Promise<AISettings> {
    const response = await request<{ settings?: Partial<AISettings> }>(
      `/api/ai/accounts/${encodeURIComponent(accountId)}`,
      { method: "DELETE" }
    );
    return normalizeAISettings(response.settings ?? {});
  },

  async bindAIRoles(writingAccountId: string, reviewAccountId: string): Promise<AISettings> {
    return normalizeAISettings(await request<Partial<AISettings>>("/api/ai/roles", {
      method: "PUT",
      body: { writingAccountId, reviewAccountId }
    }));
  },

  async probeAIAccount(accountId: string): Promise<AIProbeResponse> {
    const response = await request<AIProbeResponse>(
      `/api/ai/accounts/${encodeURIComponent(accountId)}/probe`,
      { method: "POST" }
    );
    return {
      accountId: String(response.accountId ?? accountId),
      success: Boolean(response.success),
      text: safeDisplayText(response.text),
      usage: {
        inputTokens: Number(response.usage?.inputTokens) || 0,
        outputTokens: Number(response.usage?.outputTokens) || 0,
        totalTokens: Number(response.usage?.totalTokens) || 0,
        cachedInputTokens: Number(response.usage?.cachedInputTokens) || 0,
        reasoningTokens: Number(response.usage?.reasoningTokens) || 0,
        source: safeDisplayText(response.usage?.source)
      },
      latencyMs: Number(response.latencyMs) || 0
    };
  },

  async discoverAIModels(requestBody): Promise<string[]> {
    const response = await request<{ models?: unknown[] }>("/api/ai/models/discover", {
      method: "POST",
      body: requestBody
    });
    return Array.isArray(response.models)
      ? response.models.map((item) => safeDisplayText(item)).filter(Boolean)
      : [];
  },

  async probeAIConfiguration(requestBody): Promise<AIProbeResponse> {
    const response = await request<AIProbeResponse>("/api/ai/probe", {
      method: "POST",
      body: requestBody
    });
    return {
      accountId: safeDisplayText(response.accountId),
      success: Boolean(response.success),
      text: safeDisplayText(response.text),
      usage: {
        inputTokens: Number(response.usage?.inputTokens) || 0,
        outputTokens: Number(response.usage?.outputTokens) || 0,
        totalTokens: Number(response.usage?.totalTokens) || 0,
        cachedInputTokens: Number(response.usage?.cachedInputTokens) || 0,
        reasoningTokens: Number(response.usage?.reasoningTokens) || 0,
        source: safeDisplayText(response.usage?.source)
      },
      latencyMs: Number(response.latencyMs) || 0
    };
  },

  async runModelTraining(requestBody: ModelTrainingRunRequest): Promise<ModelTrainingRunResponse> {
    const response = await request<Partial<ModelTrainingRunResponse>>("/api/models/training/run", {
      method: "POST",
      body: requestBody
    });
    return {
      bookId: String(response.bookId ?? requestBody.bookId),
      summary: safeDisplayText(response.summary),
      job: {
        id: String(response.job?.id ?? ""),
        title: safeDisplayText(response.job?.title) || "本地模型训练",
        status: safeDisplayText(response.job?.status)
      }
    };
  },

  async fetchModelLibrary(): Promise<ModelLibraryResponse> {
    return request<ModelLibraryResponse>("/api/model-library");
  },

  async fetchModelTrainingBackends(): Promise<ModelTrainingBackend[]> {
    const response = await request<{ backends?: ModelTrainingBackend[] }>(
      "/api/model-library-training-backends"
    );
    return Array.isArray(response.backends) ? response.backends : [];
  },

  async fetchModelLibraryDetail(modelId: string): Promise<ModelLibraryItem> {
    return request<ModelLibraryItem>(`/api/model-library/${encodeURIComponent(modelId)}`);
  },

  async createModelLibraryItem(requestBody): Promise<ModelLibraryMutationResponse> {
    return request<ModelLibraryMutationResponse>("/api/model-library", {
      method: "POST",
      body: requestBody
    });
  },

  async createModelCategory(label: string): Promise<ModelLibraryCategory> {
    const response = await request<{ category: ModelLibraryCategory }>(
      "/api/model-library/categories",
      {
        method: "POST",
        body: { label }
      }
    );
    return response.category;
  },

  async uploadModelSources(modelId: string, files: File[]): Promise<ModelLibrarySourcesResponse> {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<ModelLibrarySourcesResponse>(
      `/api/model-library/${encodeURIComponent(modelId)}/sources/upload`,
      {
        method: "POST",
        body
      }
    );
  },

  async addModelBookSources(modelId: string, items): Promise<ModelLibrarySourcesResponse> {
    return request<ModelLibrarySourcesResponse>(
      `/api/model-library/${encodeURIComponent(modelId)}/sources/from-books`,
      {
        method: "POST",
        body: { items }
      }
    );
  },

  async deleteModelSource(modelId: string, sourceId: string): Promise<ModelLibraryMutationResponse> {
    return request<ModelLibraryMutationResponse>(
      `/api/model-library/${encodeURIComponent(modelId)}/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" }
    );
  },

  async fetchModelLibraryReadiness(modelId: string): Promise<ModelLibraryReadiness> {
    return request<ModelLibraryReadiness>(
      `/api/model-library/${encodeURIComponent(modelId)}/readiness`
    );
  },

  async startModelLibraryTraining(modelId: string, requestBody): Promise<ModelLibraryTrainingResponse> {
    return request<ModelLibraryTrainingResponse>(
      `/api/model-library/${encodeURIComponent(modelId)}/training`,
      {
        method: "POST",
        body: requestBody
      }
    );
  }
};

function normalizeAISettings(value: Partial<AISettings>): AISettings {
  return {
    accounts: asArray(value.accounts).map((account) => ({
      id: String(account.id ?? ""),
      name: safeDisplayText(account.name),
      purpose: safeDisplayText(account.purpose),
      baseUrl: String(account.baseUrl ?? ""),
      model: String(account.model ?? ""),
      protocol: account.protocol === "chat_completions" ? "chat_completions" : "responses",
      maxContextTokens: Number(account.maxContextTokens) || 128000,
      enabled: Boolean(account.enabled),
      hasApiKey: Boolean(account.hasApiKey),
      updatedAt: String(account.updatedAt ?? "")
    })),
    roles: {
      writingAccountId: String(value.roles?.writingAccountId ?? ""),
      reviewAccountId: String(value.roles?.reviewAccountId ?? "")
    },
    usageSummary: {
      callCount: Number(value.usageSummary?.callCount) || 0,
      totalTokens: Number(value.usageSummary?.totalTokens) || 0,
      inputTokens: Number(value.usageSummary?.inputTokens) || 0,
      outputTokens: Number(value.usageSummary?.outputTokens) || 0,
      cachedInputTokens: Number(value.usageSummary?.cachedInputTokens) || 0,
      reasoningTokens: Number(value.usageSummary?.reasoningTokens) || 0,
      cacheHits: Number(value.usageSummary?.cacheHits) || 0
    },
    usageEvents: asArray(value.usageEvents).map((event) => ({
      id: Number(event.id) || 0,
      requestId: String(event.requestId ?? ""),
      bookId: String(event.bookId ?? ""),
      role: event.role === "review" ? "review" : "writing",
      action: safeDisplayText(event.action),
      accountId: String(event.accountId ?? ""),
      model: String(event.model ?? ""),
      protocol: event.protocol === "chat_completions" ? "chat_completions" : "responses",
      status: String(event.status ?? ""),
      cacheHit: Boolean(event.cacheHit),
      inputTokens: Number(event.inputTokens) || 0,
      outputTokens: Number(event.outputTokens) || 0,
      totalTokens: Number(event.totalTokens) || 0,
      cachedInputTokens: Number(event.cachedInputTokens) || 0,
      reasoningTokens: Number(event.reasoningTokens) || 0,
      usageSource: String(event.usageSource ?? ""),
      latencyMs: Number(event.latencyMs) || 0,
      error: safeDisplayText(event.error),
      compressed: Boolean(event.compressed),
      originalEstimatedTokens: Number(event.originalEstimatedTokens) || 0,
      sentEstimatedTokens: Number(event.sentEstimatedTokens) || 0,
      createdAt: String(event.createdAt ?? "")
    }))
  };
}

async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const formData = options.body instanceof FormData;
  let requestBody: BodyInit | undefined;
  if (options.body instanceof FormData) {
    requestBody = options.body;
  } else if (options.body !== undefined) {
    requestBody = JSON.stringify(options.body);
  }
  const response = await fetch(`${apiBase()}${path}`, {
    method: options.method ?? "GET",
    headers: options.body === undefined || formData ? undefined : { "Content-Type": "application/json" },
    body: requestBody
  });
  if (!response.ok) {
    const { message, detail } = await errorPayload(response);
    throw new ApiRequestError(message, response.status, detail);
  }
  return response.json() as Promise<T>;
}

async function errorPayload(response: Response): Promise<{ message: string; detail: unknown }> {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") {
      const message = safeDisplayText(data.detail);
      return { message, detail: message };
    }
    if (data.detail?.message) {
      return { message: safeDisplayText(data.detail.message), detail: data.detail };
    }
    return { message: `${response.status} ${response.statusText || "请求失败"}`, detail: data.detail ?? data };
  } catch {
    // Ignore parse errors and use the status line below.
  }
  return { message: `${response.status} ${response.statusText || "请求失败"}`, detail: null };
}

function apiBase() {
  return (import.meta.env.VITE_WORKBENCH_API_BASE ?? "").replace(/\/$/, "");
}

function bookPath(bookId: string) {
  return encodeURIComponent(bookId);
}

function parseSseEvent(raw: string): { event: string; data: Record<string, unknown> | null } {
  const event = raw.split(/\r?\n/).find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const dataText = raw
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");
  if (!dataText) {
    return { event, data: null };
  }
  try {
    return { event, data: JSON.parse(dataText) as Record<string, unknown> };
  } catch {
    return { event, data: { text: dataText } };
  }
}
