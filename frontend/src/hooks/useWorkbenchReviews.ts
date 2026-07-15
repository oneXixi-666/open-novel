import { useCallback, useState } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { markChapterReviewingInBooks, markReviewProcessing, replaceChapterInBooks } from "../domain/workbenchActions";
import { actionErrorText } from "../domain/workbenchShell";
import type { Book, Chapter, MemoryUpdateItem, ModuleKey, ReviewItem } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchReviews({
  activeBook,
  activeBookIdRef,
  activeChapter,
  setBooks,
  setReviews,
  setActiveChapterId,
  setActiveReviewId,
  setModuleKey,
  setLoadingAction,
  runAction,
  syncBookWorkspaceAfterWrite
}: {
  activeBook: Book;
  activeBookIdRef: RefObject<string>;
  activeChapter: Chapter;
  setBooks: Dispatch<SetStateAction<Book[]>>;
  setReviews: Dispatch<SetStateAction<ReviewItem[]>>;
  setActiveChapterId: Dispatch<SetStateAction<string>>;
  setActiveReviewId: Dispatch<SetStateAction<string>>;
  setModuleKey: Dispatch<SetStateAction<ModuleKey>>;
  setLoadingAction: Dispatch<SetStateAction<string | null>>;
  runAction: <T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) => Promise<T>;
  syncBookWorkspaceAfterWrite: (bookId: string, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }, fallback?: () => void) => Promise<void>;
}) {
  const [chapterMemoryUpdates, setChapterMemoryUpdates] = useState<Record<string, MemoryUpdateItem[]>>({});

  async function applyReviewRepair(
    review: ReviewItem,
    repairText: string,
    options: { stayOnReview?: boolean; silent?: boolean } = {}
  ) {
    const requestBookId = activeBook.id;
    const targetChapter = activeBook.chapters.find((chapter) => chapter.id === review.chapterId) ?? activeChapter;
    const result = await runAction(`review-repair-${review.id}`, () =>
      workbenchClient.applyReviewRepair({
        bookId: requestBookId,
        chapterId: targetChapter.id,
        reviewId: review.id,
        repairText
      }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id,
      preferredReviewId: result.reviewId
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    setActiveChapterId(result.chapter.id);
    setReviews((current) => markReviewProcessing(current, result.reviewId));
    setActiveReviewId(result.reviewId);
    if (!options.stayOnReview) {
      setModuleKey("writing");
    }
    if (!options.silent) {
      message.success(
        options.stayOnReview
          ? "审稿修复候选已应用。"
          : "审稿修复候选已应用，并切换到对应章节。"
      );
    }
  }

  async function runReviews() {
    const requestBookId = activeBook.id;
    const result = await runAction("review-run", () =>
      workbenchClient.runReviews({ bookId: requestBookId, chapterId: activeChapter.id }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    const preferredReviewId = result.reviews[0]?.id;
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: activeChapter.id,
      preferredReviewId
    }, () => {
      setReviews((current) => [
        ...result.reviews,
        ...current.filter((item) => item.bookId !== result.bookId)
      ]);
      setBooks((current) => markChapterReviewingInBooks(current, result.bookId, result.chapterId));
      if (preferredReviewId) {
        setActiveReviewId(preferredReviewId);
      }
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    message.success("重新审稿完成，已更新审稿列表。");
  }

  async function confirmReview(review: ReviewItem, options: { silent?: boolean } = {}) {
    const requestBookId = activeBook.id;
    const result = await runAction(`review-confirm-${review.id}`, () =>
      workbenchClient.updateReviewStatus({
        bookId: requestBookId,
        reviewId: review.id,
        status: "已确认"
      }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.review.chapterId,
      preferredReviewId: result.review.id
    }, () => {
      setReviews((current) =>
        current.map((item) => (item.id === result.review.id ? result.review : item))
      );
      setActiveReviewId(result.review.id);
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    if (!options.silent) {
      message.success("审稿项已确认。");
    }
  }

  const loadChapterMemoryUpdates = useCallback(async (chapterId: string) => {
    const requestBookId = activeBook.id;
    const cacheKey = memoryUpdateCacheKey(requestBookId, chapterId);
    const actionKey = `memory-updates-${cacheKey}`;
    setLoadingAction(actionKey);
    try {
      const result = await workbenchClient.fetchChapterMemoryUpdates(requestBookId, chapterId);
      setChapterMemoryUpdates((current) => ({ ...current, [cacheKey]: result.memoryUpdates }));
      return result.memoryUpdates;
    } catch (error) {
      throw new Error(actionErrorText(error, "记忆更新候选加载失败，请稍后重试。"));
    } finally {
      setLoadingAction((current) => (current === actionKey ? null : current));
    }
  }, [activeBook.id, setLoadingAction]);

  const applyMemoryUpdate = useCallback(async (update: MemoryUpdateItem) => {
    const result = await runAction(`memory-apply-${update.id}`, () =>
      workbenchClient.applyMemoryUpdate(update.id, {
        bookId: update.bookId,
        chapterId: update.chapterId
      }),
      { shouldReportError: () => activeBookIdRef.current === update.bookId }
    );
    const cacheKey = memoryUpdateCacheKey(result.bookId, result.chapterId);
    setChapterMemoryUpdates((current) => ({
      ...current,
      [cacheKey]: (current[cacheKey] ?? []).map((item) =>
        item.id === result.memoryUpdate.id ? result.memoryUpdate : item
      )
    }));
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapterId
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    message.success(authorText(result.summary));
  }, [activeBook.id, runAction, syncBookWorkspaceAfterWrite]);

  return {
    chapterMemoryUpdates,
    applyReviewRepair,
    runReviews,
    confirmReview,
    loadChapterMemoryUpdates,
    applyMemoryUpdate
  };
}

export function memoryUpdateCacheKey(bookId: string, chapterId: string) {
  return `${bookId}:${chapterId}`;
}
