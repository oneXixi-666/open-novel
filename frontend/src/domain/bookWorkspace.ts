import type { Book, BookWorkspace, ExportReadiness, GenerationState, JobSummary, Material, MaterialLibrary, MaterialType, ModelProfile, ReviewItem, RunSummary, TodayNextStep } from "../types";

export const materialTypes: MaterialType[] = ["人物", "地点", "势力", "关系", "设定", "时间线", "伏笔", "写法"];

export const materialDetailLabels = {
  地点: ["视觉特征", "危险点", "所属势力"],
  势力: ["目标", "资源", "弱点"],
  人物: ["身份", "目标", "秘密"],
  关系: ["主体", "对象", "矛盾"],
  设定: ["规则", "限制", "代价"],
  时间线: ["时间", "地点", "影响"],
  伏笔: ["首次出现", "回收窗口", "误导方向"],
  写法: ["适用场景", "避免项", "成功样例"]
} satisfies Record<MaterialType, [string, string, string]>;

export function createEmptyMaterialLibrary(): MaterialLibrary {
  return materialTypes.reduce((library, type) => {
    library[type] = [];
    return library;
  }, {} as MaterialLibrary);
}

export function buildMaterialLibrary(materials: Material[]): MaterialLibrary {
  const library = createEmptyMaterialLibrary();
  materials.forEach((material) => {
    library[material.type].push(material);
  });
  return library;
}

export function buildBookWorkspace({
  book,
  activeChapterId,
  materials,
  reviews,
  models,
  jobs,
  runs,
  exports,
  generationState
}: {
  book: Book;
  activeChapterId?: string;
  materials: Material[];
  reviews: ReviewItem[];
  models: ModelProfile[];
  jobs: JobSummary[];
  runs: RunSummary[];
  exports: ExportReadiness[];
  generationState: GenerationState;
}): BookWorkspace {
  const bookMaterials = materials.filter((material) => material.bookId === book.id);
  const bookReviews = reviews.filter((review) => review.bookId === book.id);
  const bookJobs = jobs.filter((job) => job.bookId === book.id);
  const bookRuns = runs.filter((run) => run.bookId === book.id);
  const fallbackChapter = book.chapters[0] ?? {
    id: "empty-chapter",
    title: "第一章 待创建",
    status: "待写" as const,
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
  const activeChapter = book.chapters.find((chapter) => chapter.id === activeChapterId) ?? fallbackChapter;
  const chapterReviews = bookReviews.filter((review) => review.chapterId === activeChapter.id);
  const openReviews = chapterReviews.filter((review) => review.status !== "已确认");
  const readyMaterials = bookMaterials.filter((material) => material.confidence >= 75);
  const overduePromiseCount = bookMaterials.filter((material) => material.dueStatus === "overdue").length;
  const activeModel = models.find((model) => model.id === book.currentModelId);
  return {
    book,
    chapters: book.chapters,
    today: {
      nextStep: buildTodayNextStep({
        book,
        chapter: activeChapter,
        openReviewCount: openReviews.length,
        readyMaterialCount: readyMaterials.length,
        jobs: bookJobs
      }),
      openReviewCount: openReviews.length,
      readyMaterialCount: readyMaterials.length,
      overduePromiseCount
    },
    materials: bookMaterials,
    materialLibrary: buildMaterialLibrary(bookMaterials),
    reviews: bookReviews,
    exports,
    jobs: bookJobs,
    runs: bookRuns,
    generationState,
    model: activeModel
  };
}

function buildTodayNextStep({
  book,
  chapter,
  openReviewCount,
  readyMaterialCount,
  jobs
}: {
  book: Book;
  chapter: Book["chapters"][number];
  openReviewCount: number;
  readyMaterialCount: number;
  jobs: JobSummary[];
}): TodayNextStep {
  const runningJob = jobs.find((job) => job.status === "运行中" || job.status === "等待中");
  if (runningJob) {
    return {
      title: runningJob.result || runningJob.title,
      action: "查看任务状态",
      kind: "task",
      reason: "处理任务进行中",
      color: "processing"
    };
  }
  if (chapter.status === "完成") {
    return {
      title: book.nextAction || "本章已完成，可以开始下一章。",
      action: "开始下一章",
      kind: "writing",
      reason: "章节完成",
      color: "success"
    };
  }
  if (openReviewCount > 0) {
    return {
      title: book.nextAction || "处理阻断问题后再接收正文。",
      action: "处理审稿",
      kind: "review",
      reason: "审稿未清",
      color: "warning"
    };
  }
  if (chapter.status === "审阅") {
    return {
      title: book.nextAction || "当前候选待确认。",
      action: "审阅候选",
      kind: "review",
      reason: "候选待确认",
      color: "blue"
    };
  }
  if (!readyMaterialCount) {
    return {
      title: book.nextAction || "先准备本章资料，再生成候选。",
      action: "检查资料",
      kind: "library",
      reason: "资料不足",
      color: "warning"
    };
  }
  if (chapter.status === "待写") {
    return {
      title: book.nextAction || "生成当前章节候选稿。",
      action: "开始创作",
      kind: "writing",
      reason: "还没有候选稿",
      color: "processing"
    };
  }
  return {
    title: book.nextAction || "继续处理当前章节。",
    action: "继续处理",
    kind: "writing",
    reason: "草稿推进中",
    color: "processing"
  };
}
