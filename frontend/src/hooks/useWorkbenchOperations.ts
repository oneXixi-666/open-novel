import { useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { actionErrorText, replaceBookWorkspaceItems } from "../domain/workbenchShell";
import type { Book, JobSummary, RunSummary } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchOperations({
  activeBook,
  activeBookIdRef,
  setJobs,
  setRuns,
  setLoadingAction
}: {
  activeBook: Book;
  activeBookIdRef: MutableRefObject<string>;
  setJobs: Dispatch<SetStateAction<JobSummary[]>>;
  setRuns: Dispatch<SetStateAction<RunSummary[]>>;
  setLoadingAction: Dispatch<SetStateAction<string | null>>;
}) {
  const [operationsError, setOperationsError] = useState("");
  const [moreActionError, setMoreActionError] = useState("");

  async function syncBookOperationsState(bookId: string, options?: {
    suppressErrorToast?: boolean;
  }) {
    try {
      const [jobsResult, runsResult] = await Promise.all([
        workbenchClient.fetchJobs(bookId),
        workbenchClient.fetchRuns(bookId)
      ]);
      setJobs((current) => replaceBookWorkspaceItems(current, jobsResult.jobs, bookId));
      setRuns((current) => replaceBookWorkspaceItems(current, runsResult.runs, bookId));
      if (activeBookIdRef.current === bookId) {
        setOperationsError("");
      }
      return {
        bookId,
        jobs: jobsResult.jobs,
        runs: runsResult.runs
      };
    } catch (error) {
      const errorMessage = authorText(error instanceof Error ? error.message : "当前书任务和运行记录加载失败。");
      const isActiveBook = activeBookIdRef.current === bookId;
      if (isActiveBook) {
        setOperationsError(errorMessage);
      }
      if (isActiveBook && !options?.suppressErrorToast) {
        message.error(errorMessage);
      }
      throw error;
    }
  }

  async function syncBookOperationsAfterWrite(bookId: string, fallback?: () => void) {
    await syncBookOperationsState(bookId, {
      suppressErrorToast: true
    }).catch(() => {
      if (activeBookIdRef.current === bookId) {
        fallback?.();
      }
    });
  }

  async function runMoreAction<T>(key: string, action: () => Promise<T>, fallback: string, options?: { shouldReportError?: () => boolean }) {
    setLoadingAction(key);
    setMoreActionError("");
    try {
      return await action();
    } catch (error) {
      const errorMessage = actionErrorText(error, fallback);
      if (options?.shouldReportError?.() ?? true) {
        setMoreActionError(errorMessage);
      }
      throw error;
    } finally {
      clearLoadingAction(key);
    }
  }

  async function refreshOperations() {
    const actionKey = "ops-refresh";
    setLoadingAction(actionKey);
    setMoreActionError("");
    try {
      await syncBookOperationsState(activeBook.id, {
        suppressErrorToast: true
      });
    } finally {
      clearLoadingAction(actionKey);
    }
  }

  async function cancelJob(jobId: string) {
    const requestBookId = activeBook.id;
    const result = await runMoreAction(
      `job-cancel-${jobId}`,
      () => workbenchClient.cancelJob(requestBookId, jobId),
      "任务取消失败，请稍后重试。",
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookOperationsAfterWrite(result.bookId, () => {
      setJobs((current) => current.map((job) => (job.id === result.job.id ? result.job : job)));
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    message.warning(authorText(`已取消：${result.job.title}`));
  }

  async function retryJob(jobId: string) {
    const requestBookId = activeBook.id;
    const result = await runMoreAction(
      `job-retry-${jobId}`,
      () => workbenchClient.retryJob(requestBookId, jobId),
      "任务重试失败，请稍后重试。",
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookOperationsAfterWrite(result.bookId, () => {
      setJobs((current) => [result.job, ...current]);
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    message.success(authorText(`已创建重试任务：${result.job.title}`));
  }

  async function loadJobDetail(jobId: string) {
    const requestBookId = activeBook.id;
    const [detailResult, eventsResult] = await runMoreAction(
      `job-detail-${jobId}`,
      () =>
        Promise.all([
          workbenchClient.fetchJobDetail(requestBookId, jobId),
          workbenchClient.fetchJobEvents(requestBookId, jobId)
        ]),
      "任务详情加载失败，请稍后重试。",
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    if (activeBookIdRef.current !== requestBookId || detailResult.job.bookId !== requestBookId) {
      return detailResult;
    }
    const events = eventsResult.events.length ? eventsResult.events : detailResult.detail.events;
    setJobs((current) => current.map((job) => (job.id === detailResult.job.id ? { ...detailResult.job, events } : job)));
    return detailResult;
  }

  function clearLoadingAction(key: string) {
    setLoadingAction((current) => (current === key ? null : current));
  }

  return {
    operationsError,
    moreActionError,
    refreshOperations,
    cancelJob,
    retryJob,
    loadJobDetail
  };
}
