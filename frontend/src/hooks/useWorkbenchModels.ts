import type { Dispatch, RefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { validateModelProfiles } from "../domain/workbenchActions";
import type { Book, ModelProfile } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchModels({
  activeBook,
  activeBookIdRef,
  models,
  setBooks,
  setModels,
  setPageError,
  runAction,
  syncBookWorkspaceAfterWrite
}: {
  activeBook: Book;
  activeBookIdRef: RefObject<string>;
  models: ModelProfile[];
  setBooks: Dispatch<SetStateAction<Book[]>>;
  setModels: Dispatch<SetStateAction<ModelProfile[]>>;
  setPageError: Dispatch<SetStateAction<string>>;
  runAction: <T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) => Promise<T>;
  syncBookWorkspaceAfterWrite: (bookId: string, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }, fallback?: () => void) => Promise<void>;
}) {
  async function setBookModel(modelId: string) {
    const requestBookId = activeBook.id;
    if (!modelId) {
      const result = await runAction(
        "model-unbind",
        () => workbenchClient.setBookModel({ bookId: requestBookId, modelId: "" }),
        { shouldReportError: () => activeBookIdRef.current === requestBookId }
      );
      await syncBookWorkspaceAfterWrite(result.bookId, {}, () => {
        setBooks((current) =>
          current.map((book) => (book.id === result.bookId ? { ...book, currentModelId: "" } : book))
        );
      });
      if (activeBookIdRef.current === result.bookId) {
        message.success(authorText(`${activeBook.title} 已取消写作模型绑定。`));
      }
      return;
    }
    const model = models.find((item) => item.id === modelId);
    if (!model) {
      setPageError("当前没有可切换的模型。");
      return;
    }
    const result = await runAction(
      `model-apply-${modelId}`,
      () => workbenchClient.setBookModel({ bookId: requestBookId, modelId: model.id }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {}, () => {
      setBooks((current) =>
        current.map((book) => (book.id === result.bookId ? { ...book, currentModelId: result.modelId } : book))
      );
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    message.success(authorText(`${activeBook.title} 已切换到模型：${model.name}`));
  }

  async function validateModel(modelId: string) {
    const model = models.find((item) => item.id === modelId);
    if (!model) {
      setPageError("当前没有可验证的模型。");
      return;
    }
    const result = await runAction(`model-validate-${modelId}`, () => workbenchClient.validateModel({ modelId: model.id }));
    setModels((current) => validateModelProfiles(current, result));
    message.success(authorText(`模型验证完成：${model.name}。`));
  }

  return {
    setBookModel,
    validateModel
  };
}
