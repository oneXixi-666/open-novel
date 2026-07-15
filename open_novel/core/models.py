from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class NovelMetadata(BaseModel):
    schemaVersion: int = 1
    title: str = "Untitled Novel"
    language: str = "zh-CN"
    genre: list[str] = Field(default_factory=list)
    qualityThresholds: dict[str, object] = Field(default_factory=dict)
    targetReaders: str = ""
    chapterWordTarget: int = 2500
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class NovelProject(BaseModel):
    root: Path
    metadata: NovelMetadata


class ProjectPlan(BaseModel):
    schemaVersion: int = 1
    targetChapterCount: int = 100
    targetWordsPerChapter: int = 2500
    targetChaptersPerPlot: int = 10
    platform: str = "通用网文"
    cadence: str = "稳定连载"
    notes: str = ""
    updatedAt: datetime = Field(default_factory=utc_now)


class ProjectPlanSummary(BaseModel):
    plan: ProjectPlan
    completedChapterCount: int = 0
    acceptedWordCount: int = 0
    targetTotalWords: int = 250000
    nextChapterId: str = "001"
    chapterProgressPercent: int = 0
    wordProgressPercent: int = 0
    averageWordsPerCompletedChapter: int = 0


class StyleProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 1
    id: str = "generic-web-serial"
    label: str = "Generic web serial"
    extends: str = ""
    platform: str = "generic"
    genres: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    readerExpectations: list[str] = Field(default_factory=list)
    plotRhythm: list[str] = Field(default_factory=list)
    emotionGuidance: list[str] = Field(default_factory=list)
    descriptionGuidance: list[str] = Field(default_factory=list)
    taboo: list[str] = Field(default_factory=list)
    editorialFocus: list[str] = Field(default_factory=list)
    notes: str = ""


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    order: int
    label: str
    time: str = ""
    chapterId: str | None = None
    source: str = "timeline.md"
    evidence: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    summary: str = ""


class TimelineEventsMemory(BaseModel):
    schemaVersion: int = 1
    events: list[TimelineEvent] = Field(default_factory=list)


class CharacterContinuityAnchor(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim: str
    forbiddenDraftPatterns: list[str] = Field(default_factory=list)
    allowedTransitionMarkers: list[str] = Field(default_factory=list)


class CharacterStateEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    chapterId: str = ""
    externalGoal: str = ""
    emotion: str = ""
    relationshipChanges: list[str] = Field(default_factory=list)
    source: str = ""
    evidence: list[str] = Field(default_factory=list)
    continuityAnchors: list[CharacterContinuityAnchor] = Field(default_factory=list)


class CharacterStatesRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    characterId: str
    name: str = ""
    states: list[CharacterStateEntry] = Field(default_factory=list)


class CharacterStatesMemory(BaseModel):
    schemaVersion: int = 1
    characters: list[CharacterStatesRecord] = Field(default_factory=list)


class RelationshipStateEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    fromCharacterId: str = ""
    toCharacterId: str = ""
    type: Literal[
        "trust",
        "debt",
        "fear",
        "misunderstanding",
        "rivalry",
        "protection",
        "suspicion",
        "respect",
        "hostility",
        "other",
    ] = "other"
    status: str = ""
    pressure: str = ""
    unresolvedEmotion: str = ""
    chapterId: str = ""
    source: str = ""
    evidence: list[str] = Field(default_factory=list)
    history: list[dict[str, object]] = Field(default_factory=list)


class RelationshipStatesMemory(BaseModel):
    schemaVersion: int = 1
    relationships: list[RelationshipStateEntry] = Field(default_factory=list)


class WritingLesson(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    category: Literal[
        "focus",
        "emotion",
        "relationship",
        "hook",
        "reader_promise",
        "continuity",
        "style",
    ]
    lesson: str
    source: str = ""
    evidence: list[str] = Field(default_factory=list)
    appliesTo: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "blocker"] = "medium"
    status: Literal["active", "retired"] = "active"
    successCount: int = 0
    failureCount: int = 1


class WritingLessonsMemory(BaseModel):
    schemaVersion: int = 1
    lessons: list[WritingLesson] = Field(default_factory=list)


class ActiveProhibition(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    rule: str
    forbidden: str
    source: str = ""
    chapterId: str = ""
    evidence: list[str] = Field(default_factory=list)


class ActiveProhibitionsMemory(BaseModel):
    schemaVersion: int = 1
    items: list[ActiveProhibition] = Field(default_factory=list)


class MemoryValidationIssue(BaseModel):
    severity: Literal["low", "medium", "high", "blocker"]
    path: str
    type: str
    message: str
    evidence: list[str] = Field(default_factory=list)


class MemoryValidationReport(BaseModel):
    schemaVersion: int = 1
    status: Literal["pass", "warn", "block"]
    score: int
    issues: list[MemoryValidationIssue] = Field(default_factory=list)


class MemoryRepairOperation(BaseModel):
    id: str
    action: Literal["create_file", "add_missing_list", "manual_fix"]
    target: str
    source: str
    reason: str
    payload: dict[str, object] = Field(default_factory=dict)
    status: Literal["proposed", "applied", "skipped"] = "proposed"
    message: str = ""


class MemoryRepairProposal(BaseModel):
    schemaVersion: int = 1
    sourceReport: str
    operations: list[MemoryRepairOperation] = Field(default_factory=list)


class MemoryDistillationReport(BaseModel):
    schemaVersion: int = 1
    currentChapterId: str
    hotWindowChapters: int
    sourceFiles: list[str] = Field(default_factory=list)
    topicCount: int = 0
    entityCount: int = 0
    writingGuidanceCount: int = 0
    outputPath: str = "memory/long-term-memory.json"
    recommendedNextAction: str = ""


class SceneContract(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    title: str = ""
    pov: str = ""
    time: str = ""
    location: str = ""
    focus: str = ""
    goal: str = ""
    conflict: str = ""
    turn: str = ""
    outcome: str = ""
    hook: str = ""
    emotionalBeat: str = ""
    relationshipBeat: str = ""
    internalNeed: str = ""
    woundOrFear: str = ""
    stakes: str = ""
    cost: str = ""
    subtext: str = ""
    aftertaste: str = ""
    logicDependencies: list[str] = Field(default_factory=list)
    mustInclude: list[str] = Field(default_factory=list)
    mustAvoid: list[str] = Field(default_factory=list)
    readerPromises: list[str] = Field(default_factory=list)


class ReadinessIssue(BaseModel):
    severity: Literal["low", "medium", "high", "blocker"]
    field: str
    message: str
    quickFix: str


class ReadinessReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    status: Literal["pass", "warn", "block"]
    score: int
    issues: list[ReadinessIssue] = Field(default_factory=list)
    missingContext: list[str] = Field(default_factory=list)
    recommendedNextAction: str = ""


class ContextPackItem(BaseModel):
    source: str
    reason: str
    data: object


class ContextPack(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    path: str
    included: list[ContextPackItem] = Field(default_factory=list)
    excluded: list[ContextPackItem] = Field(default_factory=list)
    estimatedTokens: int = 0


class ChapterReviewItem(BaseModel):
    id: str
    kind: Literal[
        "summary",
        "fact",
        "timeline_event",
        "character_state",
        "relationship_state",
        "emotional_beat",
        "open_loop",
        "promise_update",
        "continuity_risk",
        "world_rule",
    ]
    text: str
    evidence: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class PostChapterReview(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    source: str
    summary: str = ""
    items: list[ChapterReviewItem] = Field(default_factory=list)


class CanonPatchOperation(BaseModel):
    id: str
    action: Literal["add", "update", "close", "defer"]
    target: str
    source: str
    evidence: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)
    status: Literal["proposed", "accepted", "rejected", "applied"] = "proposed"


class CanonPatch(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    sourceReview: str
    operations: list[CanonPatchOperation] = Field(default_factory=list)


class ContinuityIssue(BaseModel):
    type: Literal[
        "missing_must_include",
        "violated_must_avoid",
        "focus_drift",
        "outcome_drift",
        "hook_drift",
        "emotional_discontinuity",
        "relationship_discontinuity",
        "reader_promise_drift",
        "character_state_contradiction",
        "relationship_state_contradiction",
        "relationship_transition_needs_review",
        "payoff_due_soon",
        "payoff_overdue",
        "ungrounded_logic_dependency",
        "timeline_order_conflict",
    ]
    severity: Literal["low", "medium", "high", "blocker"]
    evidence: list[str] = Field(default_factory=list)
    message: str
    suggestions: list[str] = Field(default_factory=list)


class ContinuityReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    source: str
    score: int
    issues: list[ContinuityIssue] = Field(default_factory=list)


class WritingQualityIssue(BaseModel):
    type: Literal[
        "too_short",
        "paragraph_too_long",
        "missing_dialogue",
        "missing_choice",
        "weak_emotional_grounding",
        "weak_conflict_escalation",
        "weak_ending_hook",
        "focus_not_supported",
        "missing_stakes",
        "missing_cost",
        "weak_subtext",
        "weak_aftertaste",
        "reader_promise_not_advanced",
        "over_exposition",
        "too_similar_to_previous",
        "chapter_goal_not_advanced",
        "word_count_out_of_range",
        "emotional_discontinuity",
        "character_name_inconsistency",
        "dialogue_ratio_out_of_range",
        "scene_switch_too_frequent",
        "anti_ai_trace",
    ]
    severity: Literal["low", "medium", "high", "blocker"]
    evidence: list[str] = Field(default_factory=list)
    message: str
    suggestions: list[str] = Field(default_factory=list)


class WritingQualityReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    source: str
    styleProfile: str = "tomato"
    score: int
    issues: list[WritingQualityIssue] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)


class EditorialReviewIssue(BaseModel):
    type: Literal[
        "emotion_told_not_felt",
        "emotion_lacks_specificity",
        "abstract_human_core",
        "motivation_not_personal",
        "relationship_turn_unearned",
        "scene_lacks_pressure",
        "payoff_without_cost",
        "dialogue_lacks_subtext",
        "ending_lacks_aftertaste",
        "description_outweighs_drama",
        "reader_focus_diffuse",
    ]
    severity: Literal["low", "medium", "high", "blocker"]
    dimension: Literal[
        "emotion",
        "character",
        "conflict",
        "payoff",
        "subtext",
        "aftertaste",
        "pacing",
    ]
    evidence: list[str] = Field(default_factory=list)
    message: str
    suggestions: list[str] = Field(default_factory=list)


class EditorialReviewReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    source: str
    reviewer: str = "local-editor-v1"
    score: int
    status: Literal["pass", "warn", "block"]
    issues: list[EditorialReviewIssue] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)
    recommendedNextAction: str = ""


class EditorialProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str = ""
    backend: Literal["local", "command"] = "local"
    reviewer: str = ""
    commandTemplate: str = ""
    timeoutSeconds: int = 600
    styleProfilePath: str = "story/style-profile.json"
    promptPreset: str = "generic-humanity"
    rubric: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)
    notes: str = ""


class EditorialPromptPreset(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    focus: list[str] = Field(default_factory=list)
    rubric: list[str] = Field(default_factory=list)


class EditorialProfileRegistry(BaseModel):
    schemaVersion: int = 1
    defaultProfileId: str = ""
    profiles: list[EditorialProfile] = Field(default_factory=list)


class ChapterSequenceEvaluationItem(BaseModel):
    chapterId: str
    qualityScore: int
    qualityIssueCount: int
    gateStatus: Literal["pass", "warn", "block"]
    gateScore: int
    gateIssueCount: int


class ChapterSequenceEvaluationReport(BaseModel):
    schemaVersion: int = 1
    startChapterId: str
    endChapterId: str
    status: Literal["pass", "warn", "block"]
    chapters: list[ChapterSequenceEvaluationItem] = Field(default_factory=list)
    minQualityScore: int = 0
    minGateScore: int = 0
    recommendedNextAction: str = ""


class TrainingReadinessItem(BaseModel):
    chapterId: str
    eligible: bool
    reason: str = ""
    qualityScore: int = 0
    gateStatus: Literal["pass", "warn", "block"] | None = None
    gateScore: int = 0
    issueCount: int = 0
    blockerCount: int = 0
    previousSimilarity: float = 0.0
    batchSimilarity: float = 0.0
    batchDuplicateOf: str = ""
    issueTypes: list[str] = Field(default_factory=list)
    actionSuggestion: str = ""


class TrainingReadinessReport(BaseModel):
    schemaVersion: int = 1
    status: Literal["ready", "warn", "block"]
    eligibleCount: int
    skippedCount: int
    minRecommendedExamples: int = 20
    items: list[TrainingReadinessItem] = Field(default_factory=list)
    recommendedNextAction: str = ""


class WritingModelProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str = ""
    backend: Literal["local-command"] = "local-command"
    agentId: str = "local-model"
    baseModel: str = ""
    adapterPath: str = ""
    commandTemplate: str = ""
    timeoutSeconds: int = 600
    trainingRunPath: str = ""
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)
    notes: str = ""


class WritingModelRegistry(BaseModel):
    schemaVersion: int = 1
    defaultProfileId: str = ""
    profiles: list[WritingModelProfile] = Field(default_factory=list)


class ModelComparisonEditorialSummary(BaseModel):
    minScore: int = 0
    averageScore: float = 0.0
    issueCount: int = 0
    highOrBlockerCount: int = 0
    blockerCount: int = 0
    chapterCount: int = 0
    styleProfileIds: list[str] = Field(default_factory=list)
    reportPaths: list[str] = Field(default_factory=list)


class ModelComparisonCandidateReport(BaseModel):
    label: str
    candidateId: str
    agentId: str
    modelProfileId: str = ""
    scratchRoot: str
    runIds: list[str] = Field(default_factory=list)
    sequenceReportPath: str
    sequence: ChapterSequenceEvaluationReport
    editorial: ModelComparisonEditorialSummary = Field(
        default_factory=ModelComparisonEditorialSummary
    )


class ModelComparisonSummary(BaseModel):
    bestCandidateId: str = ""
    bestCandidateLabel: str = ""
    bestStatus: Literal["pass", "warn", "block"] = "warn"
    bestQualityScore: int = 0
    bestGateScore: int = 0
    baseCandidateId: str = ""
    baseQualityScore: int = 0
    baseGateScore: int = 0
    tunedCandidateId: str = ""
    tunedQualityScore: int = 0
    tunedGateScore: int = 0
    baseAverageGateScore: float = 0.0
    tunedAverageGateScore: float = 0.0
    regressionPassed: bool = True
    qualityDelta: int = 0
    gateDelta: int = 0
    baseEditorialScore: int = 0
    tunedEditorialScore: int = 0
    editorialDelta: int = 0
    baseEditorialHighOrBlockerCount: int = 0
    tunedEditorialHighOrBlockerCount: int = 0
    editorialHighOrBlockerDelta: int = 0
    referenceCandidateId: str = ""
    referenceQualityScore: int = 0
    referenceGateScore: int = 0
    referenceEditorialScore: int = 0
    referenceDeltaQualityVsTuned: int = 0
    referenceDeltaGateVsTuned: int = 0
    referenceDeltaEditorialVsTuned: int = 0
    promotionDecision: str = ""
    promotionReasons: list[str] = Field(default_factory=list)
    safeToSetDefault: bool = False


class ModelComparisonReport(BaseModel):
    schemaVersion: int = 1
    comparisonId: str
    sourceProject: str
    startChapterId: str
    endChapterId: str
    chapterCount: int = 5
    createdAt: datetime = Field(default_factory=utc_now)
    baseProfileId: str = ""
    tunedProfileId: str = ""
    referenceAgentId: str = ""
    candidates: list[ModelComparisonCandidateReport] = Field(default_factory=list)
    summary: ModelComparisonSummary = Field(default_factory=ModelComparisonSummary)
    recommendedNextAction: str = ""


class ModelComparisonRequest(BaseModel):
    root: Path
    startChapterId: str = "001"
    chapterCount: int = 5
    baseProfileId: str = ""
    tunedProfileId: str = ""
    referenceAgentId: str = "local-dry-run"
    includeReferenceAgent: bool = True


class ModelComparisonPromotionRequest(BaseModel):
    root: Path
    comparisonReportPath: str


class LocalTuningPlan(BaseModel):
    schemaVersion: int = 1
    status: Literal["ready", "warn", "block"]
    backend: Literal["custom", "mlx-lm", "llama-factory"] = "custom"
    datasetPath: str
    outputDir: str
    modelProfileId: str = "latest-trained"
    baseModel: str = ""
    inferenceCommandTemplate: str = ""
    eligibleCount: int = 0
    minRecommendedExamples: int = 20
    command: list[str] = Field(default_factory=list)
    commandPreview: str = ""
    suggestedCommands: list[list[str]] = Field(default_factory=list)
    reportPath: str = "exports/local-tuning-plan.json"
    recommendedNextAction: str = ""


class LocalTuningRun(BaseModel):
    schemaVersion: int = 1
    status: Literal["completed", "failed", "skipped", "cancelled"]
    planPath: str = "exports/local-tuning-plan.json"
    command: list[str] = Field(default_factory=list)
    exitCode: int | None = None
    stdout: str = ""
    stderr: str = ""
    outputPath: str = "runs/local-tuning-run.json"
    modelProfilePath: str = ""
    modelProfileId: str = ""
    message: str = ""


class JobRecord(BaseModel):
    schemaVersion: int = 1
    jobId: str
    kind: Literal[
        "skill-run",
        "local-training",
        "five-chapter-regression",
        "model-comparison",
        "style-profile-promotion",
        "chapter-draft",
        "line-polish",
        "revision-rerun",
        "calibration-rescore",
    ]
    status: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    title: str = ""
    detail: str = ""
    createdAt: datetime = Field(default_factory=utc_now)
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    requestedCancelAt: datetime | None = None
    retryOfJobId: str = ""
    parentJobId: str = ""
    progress: dict[str, object] = Field(default_factory=dict)
    params: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)
    error: str = ""
    logs: list[str] = Field(default_factory=list)


class ChapterGateIssue(BaseModel):
    severity: Literal["low", "medium", "high", "blocker"]
    stage: Literal[
        "readiness",
        "memory",
        "context",
        "continuity",
        "quality",
        "editorial",
        "review",
    ]
    type: str
    message: str
    evidence: list[str] = Field(default_factory=list)
    textSnippet: str = ""
    suggestionHint: str = ""


class ChapterGateReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    status: Literal["pass", "warn", "block"]
    score: int
    issues: list[ChapterGateIssue] = Field(default_factory=list)
    generatedArtifacts: list[str] = Field(default_factory=list)
    recommendedNextAction: str = ""


class PlotDirectionOption(BaseModel):
    id: str
    label: str
    recommendation: Literal["recommended", "viable", "risky"]
    focus: str
    likelyOutcome: str
    emotionalImpact: str
    logicCost: str
    readerPromiseImpact: str
    risks: list[str] = Field(default_factory=list)
    nextContractUpdates: dict[str, object] = Field(default_factory=dict)


class PlotDirectionReport(BaseModel):
    schemaVersion: int = 1
    chapterId: str
    userIntent: str
    basis: list[str] = Field(default_factory=list)
    options: list[PlotDirectionOption] = Field(default_factory=list)
    recommendedOptionId: str = ""


class SkillManifest(BaseModel):
    id: str
    name: str
    category: str = "general"
    priority: Literal["p0", "p1", "p2"] = "p1"
    description: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    mode: str = "markdown"
    writePolicy: Literal["read-only", "draft-only", "proposal-only", "workspace-write"] = (
        "proposal-only"
    )
    defaultAgent: str = "local-dry-run"
    allowedAgents: list[str] = Field(default_factory=lambda: ["local-dry-run"])
    requiresReview: bool = True
    qualityGates: list[str] = Field(default_factory=list)


class AgentDetectionResult(BaseModel):
    id: str
    displayName: str
    command: str
    installed: bool
    path: str | None = None
    version: str | None = None
    error: str | None = None


class AgentPermissions(BaseModel):
    filesystem: Literal["read-only", "draft-only", "proposal-only", "workspace-write"] = "read-only"
    network: Literal["off", "on"] = "off"
    allowShell: bool = False
    allowedPaths: list[str] = Field(default_factory=list)


class CliRunResult(BaseModel):
    command: list[str]
    cwd: Path
    exitCode: int
    stdout: str
    stderr: str
    timedOut: bool = False
    cancelled: bool = False


class SkillRunRequest(BaseModel):
    projectRoot: Path
    skillId: str
    variables: dict[str, str] = Field(default_factory=dict)
    agentId: str = "local-dry-run"
    modelProfile: str | None = None
    runId: str | None = None
    bypassCache: bool = False


class SkillRunResult(BaseModel):
    runId: str
    skillId: str
    agentId: str
    modelProfile: str | None = None
    outputPath: str | None = None
    runDir: Path
    promptPath: Path
    outputText: str
