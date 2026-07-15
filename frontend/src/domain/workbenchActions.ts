import type { Book, Chapter, Material, ModelProfile, ModelValidationResult, NewBookDraft, ReviewItem } from "../types";
import { INITIAL_BOOK_PROGRESS, progressForChapterStatus } from "./chapterProgress";

export function prependMaterial(materials: Material[], material: Material) {
  return [material, ...materials];
}

export function replaceMaterial(materials: Material[], material: Material) {
  return materials.map((item) => (item.id === material.id ? material : item));
}

export function removeMaterial(materials: Material[], materialId: string) {
  return materials.filter((item) => item.id !== materialId);
}

export function validateModelProfiles(models: ModelProfile[], result: ModelValidationResult) {
  return models.map((model) =>
    model.id === result.modelId
      ? {
          ...model,
          status: result.status,
          coverage: result.coverage,
          checks: result.checks,
          warnings: result.warnings,
          recommendedNextAction: result.recommendedNextAction
        }
      : model
  );
}

export function replaceChapterInBooks(books: Book[], bookId: string, nextChapter: Chapter) {
  return books.map((book) => {
    if (book.id !== bookId) {
      return book;
    }
    return {
      ...book,
      chapters: book.chapters.map((chapter) => (chapter.id === nextChapter.id ? nextChapter : chapter))
    };
  });
}

export function upsertChapterInBooks(books: Book[], bookId: string, nextChapter: Chapter) {
  return books.map((book) => {
    if (book.id !== bookId) {
      return book;
    }
    const hasChapter = book.chapters.some((chapter) => chapter.id === nextChapter.id);
    return {
      ...book,
      chapters: hasChapter
        ? book.chapters.map((chapter) => (chapter.id === nextChapter.id ? nextChapter : chapter))
        : [...book.chapters, nextChapter]
    };
  });
}

export function markChapterReviewingInBooks(books: Book[], bookId: string, chapterId: string) {
  return books.map((book) => {
    if (book.id !== bookId) {
      return book;
    }
    return {
      ...book,
      chapters: book.chapters.map((chapter) =>
        chapter.id === chapterId && chapter.status !== "完成"
          ? {
              ...chapter,
              status: "审阅" as const,
              progress: progressForChapterStatus("审阅")
            }
          : chapter
      )
    };
  });
}

export function replaceChaptersInBooks(books: Book[], bookId: string, nextChapters: Chapter[]) {
  if (!nextChapters.length) {
    return books;
  }
  const chapterMap = new Map(nextChapters.map((chapter) => [chapter.id, chapter]));
  return books.map((book) => {
    if (book.id !== bookId) {
      return book;
    }
    return {
      ...book,
      chapters: book.chapters.map((chapter) => chapterMap.get(chapter.id) ?? chapter)
    };
  });
}

export function buildNextChapter(book: Pick<Book, "chapters">): Chapter {
  const lastChapter = book.chapters[book.chapters.length - 1];
  const nextOrder = lastChapter ? Number.parseInt(lastChapter.id, 10) + 1 || book.chapters.length + 1 : 1;
  const nextChapterId = String(nextOrder).padStart(3, "0");
  return {
    id: nextChapterId,
    title: `第${nextOrder}章 待命名章节`,
    status: "待写",
    wordCount: 0,
    progress: progressForChapterStatus("待写"),
    summary: "新章节已创建。建议先让 AI 根据当前书资料整理章节目标、冲突和结尾钩子。",
    content: "这一章还没有正式正文。\n\n可以先补任务和剧情点，再让 AI 生成第一版候选稿；也可以直接在这里写下开场场景。",
    tasks: ["确定本章目标", "选择出场人物", "选择地点和势力压力"],
    plotPoints: ["本章目标尚未确定"],
    people: ["待选择人物"],
    clues: ["待选择伏笔"],
    review: ["等待候选稿"]
  };
}

export function markReviewProcessing(reviews: ReviewItem[], reviewId: string) {
  return reviews.map((review) => (review.id === reviewId ? { ...review, status: "处理中" as const } : review));
}

export function buildNewBookBundle({
  draft,
  existingBookCount,
  defaultModelId,
  idSeed = Date.now()
}: {
  draft: NewBookDraft;
  existingBookCount: number;
  defaultModelId: string;
  idSeed?: number;
}) {
  const nextBookId = `book-${idSeed}`;
  const title = draft.title.trim() || `新书 ${existingBookCount + 1}`;
  const platform = draft.platform.trim() || "generic";
  const styleProfileId = draft.styleProfileId.trim() || "generic-web-serial";
  const styleProfileLabel = draft.styleProfileLabel.trim() || "通用网文连载";
  const genre = draft.genre.trim() || "待定题材";
  const tagline = draft.tagline.trim() || "通过 AI 辅助完善题材、主角、地点和势力。";
  const firstChapterTitle = draft.firstChapterTitle.trim() || "第一章 新书开场";
  const seed = draft.seed.trim();
  const chapter: Chapter = {
    id: "001",
    title: firstChapterTitle,
    status: "待写",
    wordCount: 0,
    progress: progressForChapterStatus("待写"),
    summary: seed
      ? `AI 已根据「${seed}」准备开场方向，下一步可以补全人物、地点和势力。`
      : "AI 已为新书整理了开场方向，下一步可以进入创作页补全人物、地点和势力。",
    content: seed
      ? `《${title}》第一章可以从这里开始。\n\nAI 初始方向：${seed}\n\n可以继续让 AI 生成剧情钩子、主角登场和第一处冲突。`
      : "第一章可以从这里开始。你可以先写开场场景，也可以让 AI 生成剧情钩子、主角登场和第一处冲突。",
    tasks: ["确定主角", "补首章地点", "设计第一处冲突"],
    plotPoints: ["主角登场", "第一处冲突", "首章结尾钩子"],
    people: ["待创建主角"],
    clues: ["待创建伏笔"],
    review: ["等待首版候选稿"]
  };
  const book: Book = {
    id: nextBookId,
    title,
    genre,
    platform,
    styleProfileId,
    styleProfileLabel,
    tagline,
    progress: INITIAL_BOOK_PROGRESS,
    updatedAt: "刚刚",
    nextAction: "先让 AI 辅助生成新书设定和第一章方向。",
    currentModelId: defaultModelId,
    writingPlan: {
      targetChapterCount: 100,
      targetWordsPerChapter: 2500,
      targetChaptersPerPlot: 10
    },
    arcs: [],
    memoryInspection: { characters: [], relationships: {}, promises: [], arcs: [] },
    chapters: [chapter]
  };
  const review: ReviewItem = {
    id: `review-${nextBookId}`,
    bookId: nextBookId,
    title: "第一章开场审稿准备",
    status: "待处理",
    priority: "中",
    chapterId: chapter.id,
    focus: ["主角登场", "首章钩子", "世界入口"],
    suggestion: "先让 AI 生成首章候选，再检查主角目标、地点压力和结尾钩子是否明确。"
  };
  return { book, chapter, review };
}
