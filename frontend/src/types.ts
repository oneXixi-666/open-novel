export type ModuleKey = "shelf" | "accounts" | "today" | "writing" | "library" | "review" | "export" | "more" | "model";
export type ChapterStatus = "待写" | "草稿" | "审阅" | "完成";
export type MaterialType = "人物" | "地点" | "势力" | "关系" | "设定" | "时间线" | "伏笔" | "写法";
export type ReviewStatus = "待处理" | "处理中" | "已确认";
export type ModelStatus = "可使用" | "待验证";
export type ModelSource = "builtin" | "project";
export type AIProtocol = "responses" | "chat_completions";
export type JobStatus = "运行中" | "已完成" | "失败" | "等待中";
export type ExportKind = "正文" | "训练数据" | "审稿报告" | "资料包";
export type GenerationStage = "architecture" | "blueprint" | "contract" | "context" | "draft" | "gate" | "review" | "accept" | "memory" | "next_chapter";
export type GenerationStatus = "idle" | "running" | "waiting_confirm" | "blocked" | "paused" | "completed";
export type GenerationMode = "full_auto" | "stage_confirm" | "chapter_confirm" | "deep_control";

export type BookCreationSetup = {
  modelId: string;
  interventionMode: GenerationMode;
  batchTarget: number;
  targetChapterCount: number;
  targetWordsPerChapter: number;
  targetChaptersPerPlot: number;
};

export type GenerationCandidateOption = {
  id: string;
  title: string;
  summary: string;
  readerExperience: string;
  recommendation: string;
};

export type GenerationCandidateVersion = {
  id: string;
  version: number;
  title: string;
  summary: string;
  createdAt: string;
  selected: boolean;
  detail: Record<string, unknown>;
};

export type GenerationArtifact = {
  artifactType: string;
  status: string;
  sourceModelLabel: string;
  candidateId: string;
  version: number;
  recommendedOptionId?: string;
  selectedOptionId?: string;
  options?: GenerationCandidateOption[];
  chapterCount?: number;
  summary?: string;
  detail: Record<string, unknown>;
  versions: GenerationCandidateVersion[];
};

export type LongFormPosition = {
  volumeId: string;
  volumeTitle: string;
  volumeGoal: string;
  segmentId: string;
  segmentTitle: string;
  segmentPurpose: string;
  chapterRange: string;
};

export type Chapter = {
  id: string;
  title: string;
  status: ChapterStatus;
  wordCount: number;
  progress: number;
  summary: string;
  content: string;
  tasks: string[];
  plotPoints: string[];
  people: string[];
  clues: string[];
  linkedMaterialIds?: string[];
  targetWordCount?: number;
  review: string[];
};

export type Book = {
  id: string;
  title: string;
  genre: string;
  platform: string;
  styleProfileId: string;
  styleProfileLabel: string;
  tagline: string;
  progress: number;
  updatedAt: string;
  nextAction: string;
  currentModelId: string;
  writingPlan: BookWritingPlan;
  qualitySummary?: BookQualitySummary;
  arcs: ArcSummary[];
  memoryInspection: MemoryInspection;
  chapters: Chapter[];
};

export type AIAccount = {
  id: string;
  name: string;
  purpose: string;
  baseUrl: string;
  model: string;
  protocol: AIProtocol;
  maxContextTokens: number;
  enabled: boolean;
  hasApiKey: boolean;
  updatedAt: string;
};

export type AIRoleBindings = {
  writingAccountId: string;
  reviewAccountId: string;
};

export type AIUsageSummary = {
  callCount: number;
  totalTokens: number;
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
  reasoningTokens: number;
  cacheHits: number;
};

export type AIUsageEvent = {
  id: number;
  requestId: string;
  bookId: string;
  role: "writing" | "review";
  action: string;
  accountId: string;
  model: string;
  protocol: AIProtocol;
  status: string;
  cacheHit: boolean;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedInputTokens: number;
  reasoningTokens: number;
  usageSource: string;
  latencyMs: number;
  error: string;
  compressed: boolean;
  originalEstimatedTokens: number;
  sentEstimatedTokens: number;
  createdAt: string;
};

export type AISettings = {
  accounts: AIAccount[];
  roles: AIRoleBindings;
  usageSummary: AIUsageSummary;
  usageEvents: AIUsageEvent[];
};

export type BookWritingPlan = {
  targetChapterCount: number;
  targetWordsPerChapter: number;
  targetChaptersPerPlot: number;
};

export type BookQualitySummary = {
  completedChapterCount: number;
  targetChapterCount: number;
  averageQualityScore: number;
  recentAverageQualityScore: number;
  trainingEligibleCount: number;
  lastTrainingRunAt: string;
  coherenceScore: number;
  tensionPoints: TensionPoint[];
};

export type TensionPoint = {
  chapterId: string;
  qualityScore: number;
  conflictMarkers: number;
  warning: boolean;
};

export type ArcSummary = {
  arcId: string;
  title: string;
  chapterRange: string;
  arcGoal: string;
  emotionalArc: string;
  status: string;
  progress: number;
};

export type MemoryInspection = {
  characters: unknown[];
  relationships: {
    nodeCount?: number;
    edgeCount?: number;
    edges?: unknown[];
  };
  promises: Material[];
  arcs: ArcSummary[];
};

export type WritingLesson = {
  id: string;
  category: string;
  lesson: string;
  severity: string;
  sourceChapters: string[];
  status: string;
};

export type CharacterSnapshot = {
  id: string;
  name: string;
  emotion: string;
  goal: string;
  relationshipScore?: number | null;
  relationshipStatus: string;
  chapterId: string;
};

export type Material = {
  id: string;
  bookId: string;
  type: MaterialType;
  title: string;
  summary: string;
  influence: string;
  related: string[];
  confidence: number;
  dueStatus?: "on_track" | "at_risk" | "overdue" | "resolved";
  details?: Record<string, string>;
};

export type MaterialSaveAction = { type: "create" } | { type: "update"; materialId: string } | null;
export type MaterialLinkAction = { mode: "append" | "replace"; materialIds: string[] } | null;
export type MaterialDeleteAction = { materialId: string } | null;

export type ReviewItem = {
  id: string;
  bookId: string;
  title: string;
  status: ReviewStatus;
  priority: "高" | "中" | "低";
  chapterId: string;
  focus: string[];
  suggestion: string;
};

export type MemoryUpdateItem = {
  id: string;
  bookId: string;
  chapterId: string;
  title: string;
  summary: string;
  targetLabel: string;
  action: "add" | "update" | "close" | "defer";
  actionLabel: string;
  status: "proposed" | "accepted" | "rejected" | "applied";
  statusLabel: string;
  canApply: boolean;
  blockedReason: string;
  evidence: string[];
};

export type ModelProfile = {
  id: string;
  name: string;
  source: ModelSource;
  sourceLabel: string;
  status: ModelStatus;
  coverage: number;
  purpose: string;
  statusNote: string;
  samples: string[];
  checks: string[];
  warnings?: string[];
  recommendedNextAction?: string;
  actions: {
    key: "apply" | "validate";
    label: string;
    description: string;
  }[];
};

export type ModelValidationResult = {
  modelId: string;
  status: ModelStatus;
  coverage: number;
  checks: string[];
  warnings: string[];
  recommendedNextAction: string;
};

export type ExportReadiness = {
  bookId?: string;
  kind: ExportKind;
  chapterIds: string[];
  ready: boolean;
  summary: string;
  checks: string[];
  risks: string[];
  resultName?: string;
  trainingPreview?: TrainingExportPreview;
};

export type TrainingExportPreview = {
  eligibleCount: number;
  skippedCount: number;
  items: TrainingExportPreviewItem[];
};

export type TrainingExportPreviewItem = {
  chapterId: string;
  eligible: boolean;
  reason: string;
  reasonLabel: string;
  qualityScore: number;
  gateStatus: string;
  gateScore: number;
  previousSimilarity: number;
  batchSimilarity: number;
  batchDuplicateOf: string;
  actionSuggestion: string;
};

export type JobSummary = {
  id: string;
  bookId: string;
  title: string;
  status: JobStatus;
  progress: number;
  startedAt: string;
  result: string;
  events?: string[];
};

export type RunSummary = {
  id: string;
  bookId: string;
  title: string;
  kind: "生成" | "审稿" | "导出" | "模型";
  status: "成功" | "警告" | "失败";
  createdAt: string;
  summary: string;
};

export type NewBookDraft = {
  title: string;
  platform: string;
  styleProfileId: string;
  styleProfileLabel: string;
  genre: string;
  tagline: string;
  firstChapterTitle: string;
  seed: string;
};

export type PlatformStyleOption = {
  id: string;
  label: string;
  platform: string;
  status: "active" | "candidate" | "planned";
  genres: string[];
  summary: string;
};

export type GenreOption = {
  label: string;
  value: string;
  platformHints: string[];
};

export type BookCreationOptions = {
  platformStyles: PlatformStyleOption[];
  genres: GenreOption[];
  platformLabels: Record<string, string>;
};

export type MaterialAiSuggestion = {
  targetId?: string;
  type: MaterialType;
  title: string;
  summary: string;
  influence: string;
  details: Record<string, string>;
};

export type MaterialLibrary = Record<MaterialType, Material[]>;

export type TodayNextStep = {
  title: string;
  action: string;
  kind: "task" | "library" | "review" | "writing";
  reason: string;
  color: "processing" | "warning" | "blue" | "success";
};

export type TodayState = {
  nextStep: TodayNextStep;
  openReviewCount: number;
  readyMaterialCount: number;
  overduePromiseCount: number;
};

export type GenerationState = {
  bookId: string;
  stage: GenerationStage;
  stageLabel: string;
  status: GenerationStatus;
  statusLabel: string;
  interventionMode: GenerationMode;
  interventionModeLabel: string;
  paused: boolean;
  batchTarget: number;
  batchDone: number;
  autoStepLimit: number;
  autoStepsUsed: number;
  activeChapterId: string;
  nextAction: string;
  blockers: string[];
  confirmations: string[];
  lastResult: string;
  activeArtifactType: string;
  activeRunStatus: string;
  sourceModelLabel: string;
  retryCount: number;
  canRetry: boolean;
  canConfirm: boolean;
  canTakeover: boolean;
  recoverySummary: string;
  candidateOptions: GenerationCandidateOption[];
  selectedOptionId: string;
  longFormPosition: LongFormPosition;
  updatedAt: string;
  artifact?: GenerationArtifact;
};

export type BookWorkspace = {
  book: Book;
  chapters: Chapter[];
  today: TodayState;
  materials: Material[];
  materialLibrary: MaterialLibrary;
  reviews: ReviewItem[];
  exports: ExportReadiness[];
  jobs: JobSummary[];
  runs: RunSummary[];
  generationState: GenerationState;
  model?: ModelProfile;
};

export type WorkspaceData = {
  books: Book[];
  creationOptions: BookCreationOptions;
  materials: Material[];
  reviews: ReviewItem[];
  models: ModelProfile[];
  exports: ExportReadiness[];
  jobs: JobSummary[];
  runs: RunSummary[];
  generationStates: GenerationState[];
};
