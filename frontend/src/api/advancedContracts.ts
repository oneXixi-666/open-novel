export type ModelTrainingReadiness = {
  status: string;
  eligibleCount: number;
  skippedCount: number;
  minRecommendedExamples: number;
  checks: string[];
  warnings: string[];
  recommendedNextAction: string;
  maturity: string;
  items: ModelTrainingReadinessItem[];
};

export type ModelTrainingReadinessItem = {
  chapterId: string;
  eligible: boolean;
  reason: string;
  reasonLabel: string;
  qualityScore: number;
  gateStatus: string;
  gateScore: number;
  issueCount: number;
  blockerCount: number;
  previousSimilarity: number;
  issueTypes: string[];
  actionSuggestion: string;
};

export type ModelQualityDistributionItem = {
  chapterId: string;
  score: number;
  similarity: number;
  gateStatus: string;
  eligible: boolean;
  label: string;
};

export type ModelQualityDistributionResponse = {
  bookId: string;
  currentThresholds: Record<string, number>;
  items: ModelQualityDistributionItem[];
};

export type LibraryRelationshipEdge = {
  id: string;
  fromLabel: string;
  toLabel: string;
  type: string;
  status: string;
  pressure: string;
  chapterLabel: string;
  eventCount: number;
  transition: string;
};

export type LibraryRelationshipsResponse = {
  bookId: string;
  nodeCount: number;
  edgeCount: number;
  edges: LibraryRelationshipEdge[];
};

export type LibraryRelationshipTimelineItem = {
  id: string;
  chapterLabel: string;
  status: string;
  pressure: string;
  unresolvedEmotion: string;
  transition: string;
  evidenceCount: number;
  needsReview: boolean;
  reviewReason: string;
};

export type LibraryRelationshipEventInput = {
  type: string;
  status: string;
  pressure: string;
  unresolvedEmotion: string;
};

export type LibraryRelationshipDetailResponse = {
  bookId: string;
  edge: LibraryRelationshipEdge & {
    unresolvedEmotion: string;
  };
  timeline: LibraryRelationshipTimelineItem[];
};

export type LibraryTimelineEvent = {
  chapterLabel: string;
  label: string;
  summary: string;
  time: string;
};

export type LibraryTimelineResponse = {
  bookId: string;
  eventCount: number;
  events: LibraryTimelineEvent[];
};

export type BookDiffSummaryResponse = {
  bookId: string;
  chapterLabel: string;
  changed: boolean;
  summary: string;
  additions: number;
  removals: number;
};

export type BookDiagnosticsResponse = {
  bookId: string;
  chapterLabel: string;
  summary: string;
  items: string[];
};
