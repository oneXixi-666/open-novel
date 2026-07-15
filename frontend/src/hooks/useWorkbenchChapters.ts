import type { Dispatch, RefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { ApiRequestError, isAcceptChapterBlockedDetail } from "../api/workbenchClient";
import { markChapterReviewingInBooks, replaceChapterInBooks, upsertChapterInBooks } from "../domain/workbenchActions";
import { materialLinkKey, uniqueCleanList } from "../domain/workbenchShell";
import type { Book, Chapter, ModuleKey, ReviewItem } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchChapters({
  activeBook,
  activeBookIdRef,
  activeChapter,
  setBooks,
  setReviews,
  setActiveChapterId,
  setActiveReviewId,
  setModuleKey,
  loadChapterMemoryUpdates,
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
  loadChapterMemoryUpdates: (chapterId: string) => Promise<unknown>;
  runAction: <T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) => Promise<T>;
  syncBookWorkspaceAfterWrite: (bookId: string, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }, fallback?: () => void) => Promise<void>;
}) {
  function isCurrentBook(bookId: string) {
    return activeBookIdRef.current === bookId;
  }

  async function applyChapterDraft(chapterId: string, nextContent: string) {
    const requestBookId = activeBook.id;
    const result = await runAction("chapter-draft-apply", () =>
      workbenchClient.applyChapterDraft({ bookId: requestBookId, chapterId, nextContent }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (!isCurrentBook(result.bookId)) {
      return;
    }
    message.success("AI 候选已应用到当前章节草稿。");
  }

  async function saveChapterDraft(chapterId: string, nextContent: string) {
    const requestBookId = activeBook.id;
    const result = await runAction("chapter-draft-save", () =>
      workbenchClient.applyChapterDraft({ bookId: requestBookId, chapterId, nextContent }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (!isCurrentBook(result.bookId)) {
      return;
    }
    message.success("章节草稿已保存。");
  }

  async function acceptChapter(chapterId: string, force = false) {
    let result;
    const actionKey = force ? "chapter-accept-force" : "chapter-accept-normal";
    const requestBookId = activeBook.id;
    try {
      result = await runAction(
        actionKey,
        () => workbenchClient.acceptChapter({ bookId: requestBookId, chapterId, force }),
        { shouldReportError: () => isCurrentBook(requestBookId) }
      );
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 409 && isAcceptChapterBlockedDetail(error.detail)) {
        await syncBookWorkspaceAfterWrite(activeBook.id, {
          preferredChapterId: chapterId
        });
        return error.detail;
      }
      throw error;
    }
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id,
      preferredReviewId: result.review?.id
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (result.review) {
      if (!isCurrentBook(result.bookId)) {
        return result;
      }
      setReviews((current) => [
        result.review!,
        ...current.filter((item) => item.id !== result.review!.id)
      ]);
      setActiveReviewId(result.review.id);
      void loadChapterMemoryUpdates(result.review.chapterId).catch(() => undefined);
      setModuleKey("review");
    }
    if (!isCurrentBook(result.bookId)) {
      return result;
    }
    message.success(result.patchPath ? "当前章节已接收，并生成了复盘与记忆更新候选。" : "当前章节已接收为正文。");
    return result;
  }

  async function createNextChapter() {
    const requestBookId = activeBook.id;
    const { chapter: nextChapter } = await runAction(
      "chapter-next",
      () => workbenchClient.createNextChapter(requestBookId),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(requestBookId, {
      preferredChapterId: nextChapter.id
    }, () => {
      setBooks((current) => upsertChapterInBooks(current, requestBookId, nextChapter));
    });
    if (!isCurrentBook(requestBookId)) {
      return;
    }
    setActiveChapterId(nextChapter.id);
    setModuleKey("writing");
    message.success(authorText(`已创建${nextChapter.title}。`));
  }

  async function updateChapterPlanning(tasks: string[], plotPoints: string[]) {
    const requestBookId = activeBook.id;
    const result = await runAction("chapter-planning", () =>
      workbenchClient.updateChapterPlanning({
        bookId: requestBookId,
        chapterId: activeChapter.id,
        tasks: uniqueCleanList(tasks),
        plotPoints: uniqueCleanList(plotPoints)
      }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (!isCurrentBook(result.bookId)) {
      return;
    }
    message.success("章节任务和剧情点已更新。");
  }

  async function prepareChapter(chapterId: string) {
    const requestBookId = activeBook.id;
    const result = await runAction("chapter-prepare", () =>
      workbenchClient.prepareChapter({ bookId: requestBookId, chapterId }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    if (!isCurrentBook(requestBookId)) {
      return result;
    }
    message.success("本章准备检查已完成。");
    return result;
  }

  async function checkChapterGate(chapterId: string) {
    const requestBookId = activeBook.id;
    const result = await runAction("chapter-gate", () =>
      workbenchClient.checkChapterGate({ bookId: requestBookId, chapterId }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapterId
    }, () => {
      setBooks((current) => markChapterReviewingInBooks(current, result.bookId, result.chapterId));
    });
    if (!isCurrentBook(result.bookId)) {
      return result;
    }
    message.success("接收前检查已完成。");
    return result;
  }

  async function linkChapterMaterials(chapterId: string, materialIds: string[], mode: "append" | "replace" = "append") {
    const linkKey = materialLinkKey(materialIds, mode);
    const requestBookId = activeBook.id;
    const result = await runAction(`chapter-material-link-${linkKey}`, () =>
      workbenchClient.linkChapterMaterials({
        bookId: requestBookId,
        chapterId,
        materialIds,
        mode
      }),
      { shouldReportError: () => isCurrentBook(requestBookId) }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {
      preferredChapterId: result.chapter.id
    }, () => {
      setBooks((current) => replaceChapterInBooks(current, result.bookId, result.chapter));
    });
    if (!isCurrentBook(result.bookId)) {
      return result;
    }
    message.success(authorText(result.summary));
    return result;
  }

  return {
    applyChapterDraft,
    saveChapterDraft,
    acceptChapter,
    createNextChapter,
    updateChapterPlanning,
    prepareChapter,
    checkChapterGate,
    linkChapterMaterials
  };
}
