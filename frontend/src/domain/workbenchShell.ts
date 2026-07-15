import type { Book, BookCreationOptions, Chapter, ExportReadiness, GenerationState, Material, MaterialDeleteAction, MaterialLinkAction, ReviewItem, WorkspaceData } from "../types";
import { authorText } from "../utils/authorText";

export const fallbackChapter: Chapter = {
  id: "empty-chapter",
  title: "第一章 待创建",
  status: "待写",
  wordCount: 0,
  progress: 0,
  summary: "这本书还没有章节，先创建第一章再开始写作。",
  content: "",
  tasks: ["创建第一章"],
  plotPoints: ["确定开场剧情点"],
  people: [],
  clues: [],
  review: ["等待首章草稿"]
};

export const fallbackBook: Book = {
  id: "empty-book",
  title: "还没有作品",
  genre: "待定题材",
  platform: "generic",
  styleProfileId: "generic-web-serial",
  styleProfileLabel: "通用网文连载",
  tagline: "创建一本书后，这里会变成你的当前书工作台。",
  progress: 0,
  updatedAt: "未开始",
  nextAction: "创建第一本书",
  currentModelId: "",
  writingPlan: {
    targetChapterCount: 100,
    targetWordsPerChapter: 2500,
    targetChaptersPerPlot: 10
  },
  arcs: [],
  memoryInspection: { characters: [], relationships: {}, promises: [], arcs: [] },
  chapters: []
};

export const emptyCreationOptions: BookCreationOptions = {
  platformStyles: [],
  genres: [],
  platformLabels: {}
};

export const fallbackGenerationState: GenerationState = {
  bookId: fallbackBook.id,
  stage: "contract",
  stageLabel: "章节规划",
  status: "idle",
  statusLabel: "待推进",
  interventionMode: "stage_confirm",
  interventionModeLabel: "阶段确认",
  paused: false,
  batchTarget: 1,
  batchDone: 0,
  autoStepLimit: 1,
  autoStepsUsed: 0,
  activeChapterId: fallbackChapter.id,
  nextAction: "创建一本书后开始生成。",
  blockers: [],
  confirmations: [],
  lastResult: "等待创建作品。",
  activeArtifactType: "",
  activeRunStatus: "",
  sourceModelLabel: "",
  retryCount: 0,
  canRetry: false,
  canConfirm: false,
  canTakeover: true,
  recoverySummary: "",
  candidateOptions: [],
  selectedOptionId: "",
  longFormPosition: {
    volumeId: "",
    volumeTitle: "",
    volumeGoal: "",
    segmentId: "",
    segmentTitle: "",
    segmentPurpose: "",
    chapterRange: ""
  },
  updatedAt: "未开始"
};

export function actionErrorText(error: unknown, fallback: string) {
  return authorText(error instanceof Error ? error.message : fallback);
}

export function attachBookIdToExports(bookId: string, exports: ExportReadiness[]) {
  return exports.reduce(
    (current, item) => replaceExportReadiness(current, { ...item, bookId }),
    [] as ExportReadiness[]
  );
}

export function groupExportsByBookId(exports: ExportReadiness[], books: Book[]) {
  const grouped: Record<string, ExportReadiness[]> = {};
  books.forEach((book) => {
    grouped[book.id] = [];
  });
  exports.forEach((item) => {
    if (!item.bookId) {
      return;
    }
    grouped[item.bookId] = replaceExportReadiness(grouped[item.bookId] ?? [], item);
  });
  return grouped;
}

export type WorkspaceSelection = {
  activeBookId: string;
  activeChapterId: string;
  activeMaterialId: string;
  activeReviewId: string;
};

export type WorkspaceSelectionInput = {
  activeBookId: string;
  activeChapterId: string;
  activeMaterialId: string;
  activeReviewId: string;
};

export type WorkspaceSelectionOptions = {
  preferredBookId?: string;
  preferredChapterId?: string;
  preferredMaterialId?: string;
  preferredReviewId?: string;
};

export function selectWorkspaceState(
  workspace: WorkspaceData,
  current: WorkspaceSelectionInput,
  options: WorkspaceSelectionOptions = {}
): WorkspaceSelection {
  const nextBook =
    workspace.books.find((book) => book.id === (options.preferredBookId ?? current.activeBookId)) ??
    workspace.books[0] ??
    fallbackBook;
  return {
    activeBookId: nextBook.id,
    activeChapterId: selectChapterId(nextBook, current.activeChapterId, options.preferredChapterId),
    activeMaterialId: selectMaterialId(workspace.materials, nextBook.id, current.activeMaterialId, options.preferredMaterialId),
    activeReviewId: selectReviewId(workspace.reviews, nextBook.id, current.activeReviewId, options.preferredReviewId)
  };
}

export function selectBookWorkspaceState(
  workspace: WorkspaceData,
  current: Omit<WorkspaceSelectionInput, "activeBookId">,
  options: Omit<WorkspaceSelectionOptions, "preferredBookId"> = {}
): Omit<WorkspaceSelection, "activeBookId"> | null {
  const nextBook = workspace.books[0];
  if (!nextBook) {
    return null;
  }
  return {
    activeChapterId: selectChapterId(nextBook, current.activeChapterId, options.preferredChapterId),
    activeMaterialId: selectScopedItemId(workspace.materials, current.activeMaterialId, options.preferredMaterialId),
    activeReviewId: selectScopedItemId(workspace.reviews, current.activeReviewId, options.preferredReviewId)
  };
}

export function replaceBookWorkspaceItems<T extends { bookId: string }>(current: T[], nextItems: T[], bookId: string) {
  return [
    ...nextItems,
    ...current.filter((item) => item.bookId !== bookId)
  ];
}

export function replaceExportReadiness(current: ExportReadiness[], nextItem: ExportReadiness) {
  return [nextItem, ...current.filter((item) => item.kind !== nextItem.kind)];
}

function selectChapterId(book: Book, currentChapterId: string, preferredChapterId?: string) {
  if (preferredChapterId && book.chapters.some((chapter) => chapter.id === preferredChapterId)) {
    return preferredChapterId;
  }
  return book.chapters.some((chapter) => chapter.id === currentChapterId)
    ? currentChapterId
    : book.chapters[0]?.id ?? fallbackChapter.id;
}

function selectMaterialId(materials: Material[], bookId: string, currentMaterialId: string, preferredMaterialId?: string) {
  if (preferredMaterialId && materials.some((material) => material.id === preferredMaterialId)) {
    return preferredMaterialId;
  }
  if (materials.some((material) => material.id === currentMaterialId)) {
    return currentMaterialId;
  }
  return materials.find((material) => material.bookId === bookId)?.id ?? "";
}

function selectReviewId(reviews: ReviewItem[], bookId: string, currentReviewId: string, preferredReviewId?: string) {
  if (preferredReviewId && reviews.some((review) => review.id === preferredReviewId)) {
    return preferredReviewId;
  }
  if (reviews.some((review) => review.id === currentReviewId)) {
    return currentReviewId;
  }
  return reviews.find((review) => review.bookId === bookId)?.id ?? "";
}

function selectScopedItemId<T extends { id: string }>(items: T[], currentId: string, preferredId?: string) {
  if (preferredId && items.some((item) => item.id === preferredId)) {
    return preferredId;
  }
  if (items.some((item) => item.id === currentId)) {
    return currentId;
  }
  return items[0]?.id ?? "";
}

export function materialLinkKey(materialIds: string[], mode: "append" | "replace") {
  return [mode, ...materialIds].join("::");
}

export function parseMaterialLinkAction(action: string | null): MaterialLinkAction {
  const prefix = "chapter-material-link-";
  if (!action?.startsWith(prefix)) {
    return null;
  }
  const [mode, ...materialIds] = action.slice(prefix.length).split("::");
  return mode === "append" || mode === "replace" ? { mode, materialIds } : null;
}

export function parseMaterialDeleteAction(action: string | null): MaterialDeleteAction {
  const prefix = "material-delete-";
  if (!action?.startsWith(prefix)) {
    return null;
  }
  return { materialId: action.slice(prefix.length) };
}

export function parseModelAction(action: string | null): { modelId: string; action: "apply" | "validate" } | null {
  if (action?.startsWith("model-apply-")) {
    return { modelId: action.slice("model-apply-".length), action: "apply" };
  }
  if (action?.startsWith("model-validate-")) {
    return { modelId: action.slice("model-validate-".length), action: "validate" };
  }
  return null;
}

export function parseAcceptAction(action: string | null): "normal" | "force" | null {
  if (action === "chapter-accept-normal") {
    return "normal";
  }
  if (action === "chapter-accept-force") {
    return "force";
  }
  return null;
}

export function exportSelectionKey(kind: ExportReadiness["kind"], range: string, rangeStart?: string, rangeEnd?: string) {
  return [kind, range, rangeStart ?? "", rangeEnd ?? ""].join("::");
}

export function uniqueCleanList(items: string[]) {
  return Array.from(new Set(items.map((item) => item.trim()).filter(Boolean)));
}
