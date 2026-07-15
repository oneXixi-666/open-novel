import type { AIAccount, AIProtocol, AISettings, Book, BookCreationSetup, Chapter, CharacterSnapshot, ExportKind, ExportReadiness, GenerationArtifact, GenerationMode, GenerationState, JobSummary, LongFormPosition, Material, MaterialType, MemoryUpdateItem, ModelProfile, ModelValidationResult, NewBookDraft, ReviewItem, ReviewStatus, RunSummary, WorkspaceData, WritingLesson } from "../types";

export type FetchWorkspaceResponse = WorkspaceData;
export type FetchBookWorkspaceResponse = WorkspaceData;

export type SystemUpdateInfo = {
  checkSucceeded: boolean;
  currentVersion: string;
  latestVersion: string;
  updateAvailable: boolean;
  downloadReady: boolean;
  status: "已是最新版本" | "发现新版本" | "检查失败";
  message: string;
  releaseName: string;
  releaseNotes: string;
  publishedAt: string;
  releaseUrl: string;
  packageUrl: string;
  checksumUrl: string;
  deploymentMode: "source" | "compose";
  deploymentLabel: "源码单机" | "Docker Compose";
  automaticUpdateReady: boolean;
  automaticUpdateMessage: string;
};

export type SystemUpdateAutoDetect = SystemUpdateInfo & {
  checkedAt: string;
  pollIntervalSeconds: number;
};

export type SystemUpdatePreparation = {
  status: string;
  message: string;
  currentVersion: string;
  targetVersion: string;
  planPath: string;
  packagePath: string;
  databaseBackupPath: string;
  restartRequired: boolean;
  deploymentMode: "source" | "compose";
  shutdownRequired: boolean;
};

export type SystemUpdateStatus = {
  phase: "idle" | "prepared" | "waiting_host" | "waiting_restart" | "applying" | "syncing_dependencies" | "building" | "restarting" | "rolling_back" | "success" | "rolled_back" | "failed" | string;
  status: string;
  message: string;
  currentVersion: string;
  targetVersion: string;
  deploymentMode: "source" | "compose";
  finished: boolean;
  succeeded: boolean;
  rolledBack: boolean;
  updatedAt: string;
};

export type CreateBookRequest = {
  draft: NewBookDraft;
  existingBookCount: number;
  defaultModelId: string;
  startGeneration: true;
} & Omit<BookCreationSetup, "modelId">;

export type CreateBookResponse = {
  book: Book;
  chapter: Chapter;
  review: ReviewItem;
  generationState?: GenerationState;
  authorMessage?: string;
};

export type UpdateBookSettingsRequest = {
  bookId: string;
  title: string;
  genre: string;
  tagline: string;
  styleProfileId: string;
  styleProfileLabel: string;
};

export type UpdateBookSettingsResponse = {
  bookId: string;
  book: Book;
  authorMessage: string;
};

export type AIAccountInput = {
  name: string;
  purpose: string;
  baseUrl: string;
  apiKey?: string | null;
  model: string;
  protocol: AIProtocol;
  maxContextTokens: number;
  enabled: boolean;
};

export type AIAccountMutationResponse = {
  account: AIAccount;
  settings: AISettings;
};

export type AIProbeResponse = {
  accountId: string;
  success: boolean;
  text: string;
  usage: AgentUsage;
  latencyMs: number;
};

export type AIAccountConnectionInput = {
  accountId?: string;
  baseUrl: string;
  apiKey?: string | null;
  model?: string;
  protocol?: AIProtocol;
  maxContextTokens?: number;
};

export type ModelTrainingRunRequest = {
  bookId: string;
  backend: "custom" | "mlx-lm" | "llama-factory";
  baseModel: string;
  outputDir: string;
  modelProfileId: string;
  inferenceCommandTemplate: string;
  minExamples?: number;
  trainCommand: string;
  force: boolean;
  timeoutSeconds: number;
};

export type ModelTrainingRunResponse = {
  bookId: string;
  summary: string;
  job: { id: string; title: string; status: string };
};

export type ModelLibraryCategory = {
  id: string;
  label: string;
  builtin: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ModelLibraryTemplate = {
  id: string;
  name: string;
  categoryId: string;
  genre: string;
  style: string;
  purpose: string;
  description: string;
};

export type ModelLibrarySource = {
  id: string;
  modelId: string;
  sourceType: "upload" | "book_chapter";
  sourceBookId: string;
  sourceChapterId: string;
  originalName: string;
  format: "txt" | "docx" | "chapter";
  wordCount: number;
  status: "eligible" | "skipped" | "failed";
  reasonCode: string;
  reasonLabel: string;
  createdAt: string;
};

export type ModelLibraryVersion = {
  id: string;
  modelId: string;
  versionNumber: number;
  status: string;
  sourceIds: string[];
  artifactPath: string;
  baseModel: string;
  trainingRunId: string;
  createdAt: string;
};

export type ModelLibraryItem = {
  id: string;
  name: string;
  categoryId: string;
  categoryLabel: string;
  purpose: string;
  description: string;
  visibility: "workspace";
  status: string;
  activeVersionId: string;
  sourceCount: number;
  eligibleCount: number;
  totalCharacters: number;
  createdAt: string;
  updatedAt: string;
  sources?: ModelLibrarySource[];
  versions?: ModelLibraryVersion[];
  usedByBooks?: string[];
};

export type ModelLibraryResponse = {
  categories: ModelLibraryCategory[];
  templates: ModelLibraryTemplate[];
  models: ModelLibraryItem[];
};

export type ModelLibraryReadiness = {
  modelId: string;
  status: "ready" | "block";
  eligibleCount: number;
  skippedCount: number;
  totalCharacters: number;
  minRecommendedExamples: number;
  items: ModelLibrarySource[];
  recommendedNextAction: string;
};

export type ModelLibraryMutationResponse = {
  model: ModelLibraryItem;
  summary: string;
};

export type ModelLibrarySourcesResponse = ModelLibraryMutationResponse & {
  items: ModelLibrarySource[];
};

export type ModelLibraryTrainingResponse = {
  modelId: string;
  summary: string;
  job: { id: string; title: string; status: string };
};

export type ModelTrainingBackend = {
  id: string;
  label: string;
  available: boolean;
  recommended: boolean;
};

export type MaterialMutationResponse = {
  material: Material;
};

export type DeleteMaterialResponse = {
  bookId: string;
  materialId: string;
  removed: boolean;
  affectedChapters: Chapter[];
  summary: string;
};

export type SetBookModelRequest = {
  bookId: string;
  modelId: string;
};

export type SetBookModelResponse = SetBookModelRequest;

export type UpdateProjectPlanRequest = {
  bookId: string;
  targetChapterCount: number;
  targetWordsPerChapter: number;
  targetChaptersPerPlot: number;
};

export type UpdateProjectPlanResponse = {
  bookId: string;
  plan: Book["writingPlan"];
  book: Book;
  authorMessage: string;
};

export type ValidateModelRequest = {
  modelId: string;
};

export type ValidateModelResponse = {
  modelId: string;
  status: ModelValidationResult["status"];
  coverage: number;
  checks: string[];
  warnings: string[];
  recommendedNextAction: string;
};

export type ApplyChapterDraftRequest = {
  bookId: string;
  chapterId: string;
  nextContent: string;
};

export type ApplyChapterDraftResponse = {
  bookId: string;
  chapter: Chapter;
};

export type UpdateChapterPlanningRequest = {
  bookId: string;
  chapterId: string;
  tasks: string[];
  plotPoints: string[];
};

export type UpdateChapterPlanningResponse = {
  bookId: string;
  chapter: Chapter;
};

export type LinkChapterMaterialsRequest = {
  bookId: string;
  chapterId: string;
  materialIds: string[];
  mode?: "append" | "replace";
};

export type LinkChapterMaterialsResponse = {
  bookId: string;
  chapterId: string;
  chapter: Chapter;
  linkedMaterials: {
    id: string;
    title: string;
    type: string;
  }[];
  summary: string;
};

export type ChapterMaterialsResponse = {
  bookId: string;
  chapterId: string;
  type?: MaterialType;
  query: string;
  scope: "related" | "all";
  materials: Material[];
  summary: string;
};

export type ChapterReadinessIssue = {
  severity: "low" | "medium" | "high" | "blocker";
  field: string;
  message: string;
  quickFix: string;
};

export type ChapterPrepareRequest = {
  bookId: string;
  chapterId: string;
};

export type ChapterPrepareResponse = {
  bookId: string;
  chapterId: string;
  readiness: {
    status: "pass" | "warn" | "block";
    score: number;
    issues: ChapterReadinessIssue[];
    missingContext: string[];
    recommendedNextAction: string;
  };
  contextPack: {
    status: "ready" | "skipped" | "missing";
    summary: string;
    includedCount: number;
    estimatedTokens: number;
    tokenBudget: number;
    buildDurationMs?: number;
    items: {
      source: string;
      type: string;
      reason: string;
      tokenEstimate: number;
    }[];
  };
  display: string;
};

export type PlotDirectionOption = {
  id: string;
  label: string;
  recommendation: "recommended" | "viable" | "risky";
  focus: string;
  likelyOutcome: string;
  emotionalImpact: string;
  logicCost: string;
  readerPromiseImpact: string;
  risks: string[];
  nextContractUpdates: Record<string, unknown>;
};

export type PlotDirectionResponse = {
  bookId: string;
  chapterId: string;
  report: {
    chapterId: string;
    userIntent: string;
    basis: string[];
    options: PlotDirectionOption[];
    recommendedOptionId: string;
  };
};

export type ApplyPlotDirectionRequest = {
  bookId: string;
  chapterId: string;
  optionId: string;
};

export type ApplyPlotDirectionResponse = {
  bookId: string;
  chapterId: string;
  optionId: string;
  contract: Record<string, unknown>;
};

export type KnowledgeSearchResult = {
  id: string;
  source: string;
  title: string;
  excerpt: string;
  score: number;
  matchedTerms: string[];
  matchReasons: string[];
  enteredContext: boolean;
};

export type KnowledgeSearchResponse = {
  bookId: string;
  query: string;
  results: KnowledgeSearchResult[];
};

export type KnowledgeRebuildResponse = {
  bookId: string;
  chunkCount: number;
};

export type WritingFormulaAsset = {
  id: string;
  title: string;
  guidance: string;
  status: "suggested" | "active" | "retired";
  evidenceChapters: string[];
  sourceAnalysis: string;
};

export type WritingAssetsResponse = {
  bookId: string;
  effective: Record<string, unknown>;
  formulas: WritingFormulaAsset[];
};

export type ChapterPolishRequest = {
  bookId: string;
  chapterId: string;
  instruction?: string;
  agentId?: string;
  modelProfile?: string | null;
  preferTrainedModel?: boolean;
};

export type ChapterPolishResponse = {
  bookId: string;
  chapterId: string;
  sourcePath: string;
  polishedPath: string;
  candidateText: string;
  usage?: AgentUsage;
  accountName?: string;
  cacheHit?: boolean;
  compressed?: boolean;
};

export type IdeationSession = {
  sessionId: string;
  title: string;
  focus: string;
  status: string;
  path: string;
  turns: { role: string; content: string; createdAt: string }[];
  createdAt: string;
  updatedAt: string;
};

export type IdeationSessionResponse = {
  bookId: string;
  session: IdeationSession;
};

export type IdeationSessionsResponse = {
  bookId: string;
  sessions: IdeationSession[];
};

export type BookAnalysisResponse = {
  bookId: string;
  report: Record<string, unknown>;
};

export type SequenceEvaluationResponse = {
  bookId: string;
  report: Record<string, unknown>;
};

export type RevisionPlanResponse = {
  bookId: string;
  sequence: Record<string, unknown>;
  plan: Record<string, unknown>;
  briefs: Record<string, unknown>[];
  diagnosis: Record<string, unknown>;
};

export type WritingLessonsResponse = {
  bookId: string;
  lessons: WritingLesson[];
  groups: {
    category: string;
    lessons: WritingLesson[];
  }[];
};

export type CharacterSnapshotResponse = {
  bookId: string;
  chapterId: string;
  characters: CharacterSnapshot[];
};

export type ChapterContractResponse = {
  bookId: string;
  chapterId: string;
  contract: Record<string, unknown>;
};

export type UpdateChapterContractRequest = {
  bookId: string;
  chapterId: string;
  fields: Record<string, string>;
};

export type ChapterGateIssue = {
  severity: "low" | "medium" | "high" | "blocker";
  stage: "readiness" | "memory" | "context" | "continuity" | "quality" | "editorial" | "review";
  type: string;
  message: string;
  evidence: string[];
  textSnippet: string;
  suggestionHint: string;
};

export type ChapterGateRequest = {
  bookId: string;
  chapterId: string;
};

export type ChapterGateResponse = {
  bookId: string;
  chapterId: string;
  gate: {
    status: "pass" | "warn" | "block";
    score: number;
    issues: ChapterGateIssue[];
    recommendedNextAction: string;
  };
  display: string;
};

export type ChapterGateRecoveryTarget = {
  kind: string;
  path: string;
  field: string;
  label: string;
};

export type ChapterGateRecoveryStep = {
  stage: "readiness" | "memory" | "context" | "continuity" | "quality" | "editorial" | "review";
  severity: "low" | "medium" | "high" | "blocker" | "";
  issueCount: number;
  types: string[];
  targets: ChapterGateRecoveryTarget[];
  action: string;
};

export type ChapterGateRecoveryResponse = {
  schemaVersion: number;
  bookId: string;
  chapterId: string;
  status: "pass" | "warn" | "block";
  score: number;
  blocked: boolean;
  issueCount: number;
  steps: ChapterGateRecoveryStep[];
  recommendedNextAction: string;
};

export type AcceptChapterRequest = {
  bookId: string;
  chapterId: string;
  force?: boolean;
};

export type AcceptChapterResponse = {
  bookId: string;
  chapter: Chapter;
  gate?: {
    status: "pass" | "warn" | "block";
    score: number;
    issues?: ChapterGateIssue[];
    recommendedNextAction?: string;
  };
  review?: ReviewItem;
  patchPath?: string;
};

export type AcceptChapterBlockedDetail = {
  message: string;
  gate: {
    status: "pass" | "warn" | "block";
    score: number;
    issues: ChapterGateIssue[];
    recommendedNextAction?: string;
  };
  recovery?: ChapterGateRecoveryResponse;
};

export type ApplyReviewRepairRequest = {
  bookId: string;
  chapterId: string;
  reviewId: string;
  repairText: string;
};

export type ApplyReviewRepairResponse = {
  bookId: string;
  reviewId: string;
  chapter: Chapter;
};

export type RunReviewsRequest = {
  bookId: string;
  chapterId?: string;
};

export type RunReviewsResponse = {
  bookId: string;
  chapterId: string;
  reviews: ReviewItem[];
};

export type BookReviewsResponse = RunReviewsResponse;

export type UpdateReviewStatusRequest = {
  bookId: string;
  reviewId: string;
  status: ReviewStatus;
};

export type UpdateReviewStatusResponse = {
  bookId: string;
  review: ReviewItem;
};

export type ChapterMemoryUpdatesResponse = {
  bookId: string;
  chapterId: string;
  memoryUpdates: MemoryUpdateItem[];
};

export type ApplyMemoryUpdateRequest = {
  bookId: string;
  chapterId?: string;
};

export type ApplyMemoryUpdateResponse = {
  bookId: string;
  chapterId: string;
  memoryUpdate: MemoryUpdateItem;
  summary: string;
};

export type ExportRequest = {
  bookId: string;
  kind: ExportKind;
  range: string;
  rangeStart?: string;
  rangeEnd?: string;
  trainingChapterIds?: string[];
};

export type ExportCheckResponse = {
  bookId: string;
  readiness: ExportReadiness;
};

export type ExportGenerateResponse = {
  bookId: string;
  kind: ExportKind;
  resultName: string;
  summary: string;
  readiness: ExportReadiness;
};

export type JobsResponse = {
  bookId: string;
  jobs: JobSummary[];
};

export type JobMutationResponse = {
  bookId: string;
  job: JobSummary;
};

export type JobDetailResponse = {
  bookId: string;
  job: JobSummary;
  detail: {
    title: string;
    status: JobSummary["status"];
    summary: string;
    events: string[];
    startedAt: string;
    finishedAt?: string;
  };
};

export type JobEventsResponse = {
  bookId: string;
  jobId: string;
  events: string[];
};

export type RunsResponse = {
  bookId: string;
  runs: RunSummary[];
};

export type GenerationModeRequest = {
  bookId: string;
  interventionMode: GenerationMode;
  batchTarget: number;
  autoStepLimit: number;
};

export type GenerationActionRequest = {
  bookId: string;
  optionId?: string;
  requestId?: string;
};

export type GenerationTakeoverRequest = {
  bookId: string;
  target: "writing" | "library" | "review";
};

export type GenerationResponse = {
  generationState: GenerationState;
  book: Book;
  activeChapter: Chapter;
  jobs: JobSummary[];
  runs: RunSummary[];
  authorMessage: string;
  generationArtifact?: GenerationArtifact;
  target?: "writing" | "library" | "review";
};

export type LongFormBeatSegment = {
  segmentId: string;
  title: string;
  chapterRange: string;
  purpose: string;
  pressure: string;
  payoff: string;
  density: string;
};

export type LongFormVolume = {
  volumeId: string;
  title: string;
  chapterRange: string;
  goal: string;
  mainConflict: string;
  payoffs: string[];
  endingChange: string;
  failureCondition: string;
  beatSegments: LongFormBeatSegment[];
};

export type LongFormPlan = {
  mainline: string;
  endingDirection: string;
  longTermOpposition: string;
  corePromises: string[];
  estimatedVolumes: number;
  currentVolumeId: string;
  volumes: LongFormVolume[];
};

export type LongFormPlanResponse = {
  bookId: string;
  plan: LongFormPlan;
  currentPosition: LongFormPosition;
  chapterLandings: ChapterLanding[];
  serialRisks: SerialRiskSignal[];
  replanCandidate?: {
    candidateId?: string;
    version?: number;
    plan?: LongFormPlan & { chapterAdjustments?: ChapterLanding[] };
  } | null;
  authorMessage?: string;
};

export type ChapterLanding = {
  chapterId: string;
  title: string;
  status: string;
  goal: string;
  hook: string;
  characterChange?: string;
  promiseProgression: string;
  logicDependencies: string[];
  segmentId: string;
};

export type SerialRiskSignal = {
  key: "weak_hooks" | "promise_pressure" | "rhythm_imbalance" | "character_stagnation" | "volume_deviation";
  title: string;
  status: "risk" | "clear" | "insufficient";
  evidenceChapters: string[];
  reason: string;
  impact: string;
  action: string;
};

export type LongFormReplanResponse = {
  bookId: string;
  deviation: Record<string, unknown>;
  candidate: Record<string, unknown> | null;
  authorMessage: string;
};

export type CreateNextChapterResponse = {
  chapter: Chapter;
};

export type AgentAssistRequest = {
  bookId: string;
  scope: "book" | "chapter" | "material" | "review" | "model";
  action: string;
  input?: string;
  chapterId?: string;
  materialId?: string;
  materialType?: MaterialType;
  currentMaterial?: Material;
  reviewId?: string;
  modelId?: string;
  bypassCache?: boolean;
};

export type AgentUsage = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedInputTokens: number;
  reasoningTokens: number;
  source: string;
};

export type AgentAssistResponse = {
  title: string;
  content: string;
  suggestions: string[];
  candidateText?: string;
  material?: Material;
  model?: ModelProfile;
  usage?: AgentUsage;
  accountName?: string;
  cacheHit?: boolean;
  compressed?: boolean;
};

export type WorkbenchClient = {
  fetchWorkspace: () => Promise<FetchWorkspaceResponse>;
  fetchBookWorkspace: (bookId: string) => Promise<FetchBookWorkspaceResponse>;
  fetchSystemUpdate: () => Promise<SystemUpdateInfo>;
  autoDetectSystemUpdate: () => Promise<SystemUpdateAutoDetect>;
  fetchSystemUpdateStatus: () => Promise<SystemUpdateStatus>;
  prepareSystemUpdate: () => Promise<SystemUpdatePreparation>;
  createBook: (request: CreateBookRequest) => Promise<CreateBookResponse>;
  updateBookSettings: (request: UpdateBookSettingsRequest) => Promise<UpdateBookSettingsResponse>;
  createMaterial: (material: Material) => Promise<MaterialMutationResponse>;
  updateMaterial: (material: Material) => Promise<MaterialMutationResponse>;
  deleteMaterial: (bookId: string, materialId: string) => Promise<DeleteMaterialResponse>;
  setBookModel: (request: SetBookModelRequest) => Promise<SetBookModelResponse>;
  updateProjectPlan: (request: UpdateProjectPlanRequest) => Promise<UpdateProjectPlanResponse>;
  validateModel: (request: ValidateModelRequest) => Promise<ValidateModelResponse>;
  applyChapterDraft: (request: ApplyChapterDraftRequest) => Promise<ApplyChapterDraftResponse>;
  updateChapterPlanning: (request: UpdateChapterPlanningRequest) => Promise<UpdateChapterPlanningResponse>;
  linkChapterMaterials: (request: LinkChapterMaterialsRequest) => Promise<LinkChapterMaterialsResponse>;
  fetchChapterMaterials: (bookId: string, chapterId: string, options?: { type?: MaterialType; q?: string; scope?: "related" | "all" }) => Promise<ChapterMaterialsResponse>;
  fetchWritingLessons: (bookId: string) => Promise<WritingLessonsResponse>;
  fetchCharacterSnapshot: (bookId: string, chapterId: string) => Promise<CharacterSnapshotResponse>;
  fetchChapterContract: (bookId: string, chapterId: string) => Promise<ChapterContractResponse>;
  updateChapterContract: (request: UpdateChapterContractRequest) => Promise<ChapterContractResponse>;
  prepareChapter: (request: ChapterPrepareRequest) => Promise<ChapterPrepareResponse>;
  fetchPlotDirections: (bookId: string, chapterId: string, userIntent?: string) => Promise<PlotDirectionResponse>;
  applyPlotDirection: (request: ApplyPlotDirectionRequest) => Promise<ApplyPlotDirectionResponse>;
  rebuildKnowledge: (bookId: string) => Promise<KnowledgeRebuildResponse>;
  searchKnowledge: (bookId: string, q: string, limit?: number) => Promise<KnowledgeSearchResponse>;
  fetchWritingAssets: (bookId: string) => Promise<WritingAssetsResponse>;
  setWritingFormulaStatus: (bookId: string, formulaId: string, status: "active" | "retired") => Promise<WritingAssetsResponse>;
  polishChapter: (request: ChapterPolishRequest) => Promise<ChapterPolishResponse>;
  createIdeationSession: (request: { bookId: string; title: string; focus?: string; seed?: string }) => Promise<IdeationSessionResponse>;
  fetchIdeationSessions: (bookId: string) => Promise<IdeationSessionsResponse>;
  appendIdeationTurn: (bookId: string, sessionId: string, request: { role?: string; content: string }) => Promise<IdeationSessionResponse>;
  analyzeBook: (request: { bookId: string; startChapterId: string; endChapterId: string }) => Promise<BookAnalysisResponse>;
  promoteWritingFormulas: (request: { bookId: string; reportPath: string }) => Promise<Record<string, unknown>>;
  evaluateSequence: (request: { bookId: string; startChapterId: string; endChapterId: string; preferDrafts?: boolean }) => Promise<SequenceEvaluationResponse>;
  buildRevisionPlan: (request: { bookId: string; startChapterId: string; endChapterId: string; maxChapters?: number }) => Promise<RevisionPlanResponse>;
  checkChapterGate: (request: ChapterGateRequest) => Promise<ChapterGateResponse>;
  fetchChapterGateRecovery: (bookId: string, chapterId: string) => Promise<ChapterGateRecoveryResponse>;
  acceptChapter: (request: AcceptChapterRequest) => Promise<AcceptChapterResponse>;
  createNextChapter: (bookId: string) => Promise<CreateNextChapterResponse>;
  applyReviewRepair: (request: ApplyReviewRepairRequest) => Promise<ApplyReviewRepairResponse>;
  fetchBookReviews: (bookId: string) => Promise<BookReviewsResponse>;
  runReviews: (request: RunReviewsRequest) => Promise<RunReviewsResponse>;
  updateReviewStatus: (request: UpdateReviewStatusRequest) => Promise<UpdateReviewStatusResponse>;
  checkExport: (request: ExportRequest) => Promise<ExportCheckResponse>;
  generateExport: (request: ExportRequest) => Promise<ExportGenerateResponse>;
  fetchJobs: (bookId: string) => Promise<JobsResponse>;
  fetchJobDetail: (bookId: string, jobId: string) => Promise<JobDetailResponse>;
  fetchJobEvents: (bookId: string, jobId: string) => Promise<JobEventsResponse>;
  cancelJob: (bookId: string, jobId: string) => Promise<JobMutationResponse>;
  retryJob: (bookId: string, jobId: string) => Promise<JobMutationResponse>;
  fetchRuns: (bookId: string) => Promise<RunsResponse>;
  fetchGeneration: (bookId: string) => Promise<GenerationResponse>;
  setGenerationMode: (request: GenerationModeRequest) => Promise<GenerationResponse>;
  continueGeneration: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  confirmGeneration: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  regenerateGenerationCandidate: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  selectGenerationCandidate: (bookId: string, candidateId: string, requestId?: string) => Promise<GenerationResponse>;
  rollbackGenerationCandidate: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  pauseGeneration: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  resumeGeneration: (request: GenerationActionRequest) => Promise<GenerationResponse>;
  takeoverGeneration: (request: GenerationTakeoverRequest) => Promise<GenerationResponse>;
  fetchLongFormPlan: (bookId: string) => Promise<LongFormPlanResponse>;
  updateVolumeGoal: (bookId: string, volumeId: string, goal: string, chapterRange?: string) => Promise<LongFormPlanResponse>;
  updateChapterLanding: (bookId: string, landing: ChapterLanding) => Promise<{ bookId: string; landing: ChapterLanding; authorMessage: string }>;
  generateLongFormReplan: (bookId: string, chapterId?: string) => Promise<LongFormReplanResponse>;
  confirmLongFormReplan: (bookId: string) => Promise<LongFormPlanResponse>;
  fetchChapterMemoryUpdates: (bookId: string, chapterId: string) => Promise<ChapterMemoryUpdatesResponse>;
  applyMemoryUpdate: (updateId: string, request: ApplyMemoryUpdateRequest) => Promise<ApplyMemoryUpdateResponse>;
  runAgentAssist: (request: AgentAssistRequest) => Promise<AgentAssistResponse>;
  streamAgentAssist: (request: AgentAssistRequest, onToken: (text: string) => void, signal?: AbortSignal) => Promise<AgentAssistResponse>;
  fetchAISettings: () => Promise<AISettings>;
  createAIAccount: (request: AIAccountInput) => Promise<AISettings>;
  updateAIAccount: (accountId: string, request: AIAccountInput) => Promise<AISettings>;
  deleteAIAccount: (accountId: string) => Promise<AISettings>;
  bindAIRoles: (writingAccountId: string, reviewAccountId: string) => Promise<AISettings>;
  probeAIAccount: (accountId: string) => Promise<AIProbeResponse>;
  discoverAIModels: (request: AIAccountConnectionInput) => Promise<string[]>;
  probeAIConfiguration: (request: AIAccountConnectionInput) => Promise<AIProbeResponse>;
  runModelTraining: (request: ModelTrainingRunRequest) => Promise<ModelTrainingRunResponse>;
  fetchModelLibrary: () => Promise<ModelLibraryResponse>;
  fetchModelTrainingBackends: () => Promise<ModelTrainingBackend[]>;
  fetchModelLibraryDetail: (modelId: string) => Promise<ModelLibraryItem>;
  createModelLibraryItem: (request: {
    name: string;
    categoryId: string;
    purpose: string;
    description?: string;
  }) => Promise<ModelLibraryMutationResponse>;
  createModelCategory: (label: string) => Promise<ModelLibraryCategory>;
  uploadModelSources: (modelId: string, files: File[]) => Promise<ModelLibrarySourcesResponse>;
  addModelBookSources: (
    modelId: string,
    items: { bookId: string; chapterId: string }[]
  ) => Promise<ModelLibrarySourcesResponse>;
  deleteModelSource: (modelId: string, sourceId: string) => Promise<ModelLibraryMutationResponse>;
  fetchModelLibraryReadiness: (modelId: string) => Promise<ModelLibraryReadiness>;
  startModelLibraryTraining: (
    modelId: string,
    request: { sourceIds: string[]; bookId: string; backendId: string; confirm: boolean }
  ) => Promise<ModelLibraryTrainingResponse>;
};
