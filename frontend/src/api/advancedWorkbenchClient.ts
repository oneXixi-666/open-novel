import type {
  BookDiffSummaryResponse,
  BookDiagnosticsResponse,
  LibraryRelationshipDetailResponse,
  LibraryRelationshipEventInput,
  LibraryRelationshipsResponse,
  LibraryTimelineResponse,
  ModelQualityDistributionResponse,
  ModelTrainingReadiness
} from "./advancedContracts";

const MAX_SAFE_TEXT_LENGTH = 240;

type RawLibraryRelationshipEdge = {
  id?: unknown;
  fromLabel?: unknown;
  toLabel?: unknown;
  type?: unknown;
  status?: unknown;
  pressure?: unknown;
  chapterId?: unknown;
  eventCount?: unknown;
  transition?: unknown;
  unresolvedEmotion?: unknown;
};

type RawLibraryRelationshipsResponse = {
  nodeCount?: unknown;
  edgeCount?: unknown;
  edges?: RawLibraryRelationshipEdge[];
};

type RawLibraryRelationshipTimelineItem = {
  eventId?: unknown;
  chapterId?: unknown;
  status?: unknown;
  pressure?: unknown;
  unresolvedEmotion?: unknown;
  transition?: unknown;
  evidence?: unknown;
  signals?: unknown;
  needsReview?: unknown;
  reviewReason?: unknown;
};

type RawLibraryRelationshipDetailResponse = {
  edge?: RawLibraryRelationshipEdge;
  timeline?: RawLibraryRelationshipTimelineItem[];
};

type RawLibraryTimelineResponse = {
  eventCount?: unknown;
  events?: {
    chapterId?: unknown;
    label?: unknown;
    summary?: unknown;
    time?: unknown;
  }[];
};

type RawDiffResponse = {
  chapterId?: unknown;
  changed?: unknown;
  summary?: unknown;
  diff?: unknown;
};

type RawDiagnosticsResponse = {
  chapterId?: unknown;
  summary?: unknown;
  items?: unknown;
};

type RawModelTrainingReadinessItem = {
  chapterId?: unknown;
  eligible?: unknown;
  reason?: unknown;
  reasonLabel?: unknown;
  qualityScore?: unknown;
  gateStatus?: unknown;
  gateScore?: unknown;
  issueCount?: unknown;
  blockerCount?: unknown;
  previousSimilarity?: unknown;
  issueTypes?: unknown;
  actionSuggestion?: unknown;
};

type RawModelTrainingReadiness = Omit<Partial<ModelTrainingReadiness>, "items"> & {
  items?: RawModelTrainingReadinessItem[];
};

type RawModelQualityDistributionItem = {
  chapterId?: unknown;
  score?: unknown;
  similarity?: unknown;
  gateStatus?: unknown;
  eligible?: unknown;
  label?: unknown;
};

type RawModelQualityDistributionResponse = {
  bookId?: unknown;
  currentThresholds?: Record<string, unknown>;
  items?: RawModelQualityDistributionItem[];
};

export const advancedWorkbenchClient = {
  async fetchModelQualityDistribution(bookId: string): Promise<ModelQualityDistributionResponse> {
    const query = new URLSearchParams({ bookId }).toString();
    const data = await request<RawModelQualityDistributionResponse>(`/api/models/quality-distribution?${query}`);
    return {
      bookId: safeText(data.bookId) || bookId,
      currentThresholds: normalizeNumberRecord(data.currentThresholds),
      items: (data.items ?? []).map((item) => ({
        chapterId: safeText(item.chapterId),
        score: Number(item.score) || 0,
        similarity: Number(item.similarity) || 0,
        gateStatus: safeText(item.gateStatus),
        eligible: Boolean(item.eligible),
        label: safeText(item.label)
      }))
    };
  },

  async fetchModelTrainingReadiness(bookId: string): Promise<ModelTrainingReadiness> {
    const query = new URLSearchParams({ bookId }).toString();
    const data = await request<RawModelTrainingReadiness>(`/api/models/training/readiness?${query}`, {
      method: "POST"
    });
    return {
      status: safeText(data.status),
      eligibleCount: Number(data.eligibleCount) || 0,
      skippedCount: Number(data.skippedCount) || 0,
      minRecommendedExamples: Number(data.minRecommendedExamples) || 0,
      checks: safeTextList(data.checks),
      warnings: safeTextList(data.warnings),
      recommendedNextAction: safeText(data.recommendedNextAction),
      maturity: safeText(data.maturity),
      items: (data.items ?? []).map((item) => ({
        chapterId: safeText(item.chapterId),
        eligible: Boolean(item.eligible),
        reason: safeText(item.reason),
        reasonLabel: safeText(item.reasonLabel),
        qualityScore: Number(item.qualityScore) || 0,
        gateStatus: safeText(item.gateStatus),
        gateScore: Number(item.gateScore) || 0,
        issueCount: Number(item.issueCount) || 0,
        blockerCount: Number(item.blockerCount) || 0,
        previousSimilarity: Number(item.previousSimilarity) || 0,
        issueTypes: safeTextList(item.issueTypes),
        actionSuggestion: safeText(item.actionSuggestion)
      }))
    };
  },

  async fetchLibraryRelationships(bookId: string): Promise<LibraryRelationshipsResponse> {
    const data = await request<RawLibraryRelationshipsResponse>(`/api/books/${bookPath(bookId)}/library/relationships`);
    return {
      bookId,
      nodeCount: Number(data.nodeCount) || 0,
      edgeCount: Number(data.edgeCount) || 0,
      edges: (data.edges ?? []).map((edge) => ({
        id: safeText(edge.id),
        fromLabel: safeText(edge.fromLabel),
        toLabel: safeText(edge.toLabel),
        type: safeText(edge.type),
        status: safeText(edge.status),
        pressure: safeText(edge.pressure),
        chapterLabel: chapterLabel(edge.chapterId),
        eventCount: Number(edge.eventCount) || 0,
        transition: safeText(edge.transition)
      }))
    };
  },

  async fetchLibraryRelationshipDetail(bookId: string, edgeId: string): Promise<LibraryRelationshipDetailResponse> {
    const data = await request<RawLibraryRelationshipDetailResponse>(
      `/api/books/${bookPath(bookId)}/library/relationships/${encodeURIComponent(edgeId)}`
    );
    return {
      bookId,
      edge: {
        id: safeText(data.edge?.id),
        fromLabel: safeText(data.edge?.fromLabel),
        toLabel: safeText(data.edge?.toLabel),
        type: safeText(data.edge?.type),
        status: safeText(data.edge?.status),
        pressure: safeText(data.edge?.pressure),
        chapterLabel: chapterLabel(data.edge?.chapterId),
        eventCount: Number(data.edge?.eventCount) || 0,
        transition: safeText(data.edge?.transition),
        unresolvedEmotion: safeText(data.edge?.unresolvedEmotion)
      },
      timeline: (data.timeline ?? []).map((item) => ({
        id: safeText(item.eventId),
        chapterLabel: chapterLabel(item.chapterId),
        status: safeText(item.status),
        pressure: safeText(item.pressure),
        unresolvedEmotion: safeText(item.unresolvedEmotion),
        transition: safeText(item.transition),
        evidenceCount: safeTextList(item.evidence).length,
        needsReview: Boolean(item.needsReview),
        reviewReason: safeText(item.reviewReason)
      }))
    };
  },

  async updateLibraryRelationshipEvent(
    bookId: string,
    eventId: string,
    input: LibraryRelationshipEventInput
  ): Promise<{ edge?: { type: string; status: string; pressure: string; unresolvedEmotion: string } }> {
    const data = await request<RawLibraryRelationshipDetailResponse>(
      `/api/books/${bookPath(bookId)}/library/relationship-events/${encodeURIComponent(eventId)}`,
      {
      method: "POST",
      body: { bookId, ...input }
      }
    );
    return data.edge
      ? {
          edge: {
            type: safeText(data.edge.type),
            status: safeText(data.edge.status),
            pressure: safeText(data.edge.pressure),
            unresolvedEmotion: safeText(data.edge.unresolvedEmotion)
          }
        }
      : {};
  },

  async fetchLibraryTimeline(bookId: string): Promise<LibraryTimelineResponse> {
    const data = await request<RawLibraryTimelineResponse>(`/api/books/${bookPath(bookId)}/library/timeline`);
    return {
      bookId,
      eventCount: Number(data.eventCount) || 0,
      events: (data.events ?? []).map((event) => ({
        chapterLabel: chapterLabel(event.chapterId),
        label: safeText(event.label),
        summary: safeText(event.summary),
        time: safeText(event.time)
      }))
    };
  },

  async fetchDiffSummary(bookId: string): Promise<BookDiffSummaryResponse> {
    const data = await request<RawDiffResponse>(`/api/books/${bookPath(bookId)}/diff`);
    const diffStats = countDiffLines(data.diff);
    return {
      bookId,
      chapterLabel: chapterLabel(data.chapterId),
      changed: Boolean(data.changed),
      summary: safeText(data.summary),
      additions: diffStats.additions,
      removals: diffStats.removals
    };
  },

  async fetchDiagnostics(bookId: string): Promise<BookDiagnosticsResponse> {
    const data = await request<RawDiagnosticsResponse>(`/api/books/${bookPath(bookId)}/diagnostics`);
    return {
      bookId,
      chapterLabel: chapterLabel(data.chapterId),
      summary: safeText(data.summary),
      items: safeTextList(data.items)
    };
  }
};

async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: options.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function errorMessage(response: Response) {
  try {
    const data = await response.json();
    if (typeof data?.detail === "string") {
      return safeText(data.detail);
    }
    if (typeof data?.message === "string") {
      return safeText(data.message);
    }
  } catch {
    // Fall through to status text.
  }
  return safeText(response.statusText) || "高级能力加载失败。";
}

function apiBase() {
  return (import.meta.env.VITE_WORKBENCH_API_BASE ?? "").replace(/\/$/, "");
}

function bookPath(bookId: string) {
  return encodeURIComponent(bookId);
}

function chapterLabel(value: unknown) {
  const text = safeText(value);
  if (!text) {
    return "-";
  }
  return text.startsWith("第") ? text : `第 ${text} 章`;
}

function safeText(value: unknown) {
  const text = String(value ?? "").trim();
  if (/token|password|secret|bearer/i.test(text)) {
    return "[已隐藏敏感内容]";
  }
  if (/(^|[\s(["'：:])(?:\/Users\/|\/private\/|\/var\/|\/tmp\/|[A-Za-z]:\\)/.test(text)) {
    return "[已隐藏本地路径]";
  }
  return text.length > MAX_SAFE_TEXT_LENGTH ? `${text.slice(0, MAX_SAFE_TEXT_LENGTH)}...` : text;
}

function safeTextList(value: unknown) {
  return Array.isArray(value) ? value.map(safeText).filter(Boolean) : [];
}

function normalizeNumberRecord(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => [safeText(key), Number(item)])
      .filter(([key, item]) => key && Number.isFinite(item as number))
  ) as Record<string, number>;
}

function countDiffLines(value: unknown) {
  const lines = typeof value === "string" ? value.split("\n") : [];
  return {
    additions: lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length,
    removals: lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length
  };
}
