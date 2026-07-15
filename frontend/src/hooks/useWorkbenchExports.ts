import type { Dispatch, RefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { exportSelectionKey, replaceExportReadiness } from "../domain/workbenchShell";
import type { Book, ExportReadiness } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchExports({
  activeBook,
  activeBookIdRef,
  setExportsByBookId,
  runAction
}: {
  activeBook: Book;
  activeBookIdRef: RefObject<string>;
  setExportsByBookId: Dispatch<SetStateAction<Record<string, ExportReadiness[]>>>;
  runAction: <T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) => Promise<T>;
}) {
  async function checkExport(kind: ExportReadiness["kind"], range: string, rangeStart?: string, rangeEnd?: string) {
    const requestBookId = activeBook.id;
    const exportKey = exportSelectionKey(kind, range, rangeStart, rangeEnd);
    const result = await runAction(`export-check-${exportKey}`, () =>
      workbenchClient.checkExport({
        bookId: requestBookId,
        kind,
        range,
        rangeStart,
        rangeEnd
      }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return result;
    }
    setExportsByBookId((current) => ({
      ...current,
      [requestBookId]: replaceExportReadiness(current[requestBookId] ?? [], {
        ...result.readiness,
        bookId: requestBookId
      })
    }));
    message.success(`${kind}检查完成，已更新风险摘要。`);
    return result;
  }

  async function generateExport(
    kind: ExportReadiness["kind"],
    range: string,
    rangeStart?: string,
    rangeEnd?: string,
    trainingChapterIds?: string[]
  ) {
    const requestBookId = activeBook.id;
    const exportKey = exportSelectionKey(kind, range, rangeStart, rangeEnd);
    const result = await runAction(`export-generate-${exportKey}`, () =>
      workbenchClient.generateExport({
        bookId: requestBookId,
        kind,
        range,
        rangeStart,
        rangeEnd,
        trainingChapterIds
      }),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return result;
    }
    setExportsByBookId((current) => ({
      ...current,
      [requestBookId]: replaceExportReadiness(current[requestBookId] ?? [], {
        ...result.readiness,
        bookId: requestBookId
      })
    }));
    message.success(authorText(result.summary));
    return result;
  }

  return {
    checkExport,
    generateExport
  };
}
