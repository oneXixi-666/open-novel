import type { ChapterStatus } from "../types";

const chapterStageProgress: Record<ChapterStatus, number> = {
  待写: 0,
  草稿: 10,
  审阅: 90,
  完成: 100
};

export const INITIAL_BOOK_PROGRESS = 0;

export function progressForChapterStatus(status: ChapterStatus) {
  return chapterStageProgress[status];
}
