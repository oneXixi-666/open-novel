import { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { ErrorBoundary } from "react-error-boundary";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import {
  App as AntApp,
  ConfigProvider,
  message
} from "antd";
import "antd/dist/reset.css";
import "./styles.css";
import { workbenchClient } from "./api/workbenchClient";
import { WorkbenchView } from "./components/WorkbenchView";
import { useWorkbenchChapters } from "./hooks/useWorkbenchChapters";
import { useWorkbenchExports } from "./hooks/useWorkbenchExports";
import { useWorkbenchMaterials } from "./hooks/useWorkbenchMaterials";
import { useWorkbenchModels } from "./hooks/useWorkbenchModels";
import { useWorkbenchOperations } from "./hooks/useWorkbenchOperations";
import { useWorkbenchReviews } from "./hooks/useWorkbenchReviews";
import { useWorkbenchState } from "./hooks/useWorkbenchState";
import {
  fallbackBook,
  fallbackChapter,
  replaceBookWorkspaceItems
} from "./domain/workbenchShell";
import type { GenerationResponse } from "./api/contracts";
import type {
  BookCreationSetup,
  GenerationMode,
  MaterialType,
  ModuleKey,
  NewBookDraft
} from "./types";
import { authorText } from "./utils/authorText";

const queryClient = new QueryClient();

function Workbench() {
  const queryClient = useQueryClient();
  const {
    books,
    setBooks,
    materials,
    setMaterials,
    reviews,
    setReviews,
    models,
    setModels,
    setExportsByBookId,
    setJobs,
    setRuns,
    generationStates,
    setGenerationStates,
    creationOptions,
    activeBook,
    activeBookIdRef,
    hasBooks,
    activeChapter,
    activeWorkspace,
    activeMaterial,
    activeReview,
    activeModel,
    setActiveBookId,
    setActiveChapterId,
    setActiveMaterialId,
    setActiveReviewId,
    applyWorkspaceState,
    applyBookWorkspaceState
  } = useWorkbenchState();
  const [moduleKey, setModuleKey] = useState<ModuleKey>("today");
  const [bookSearch, setBookSearch] = useState("");
  const [materialSearch, setMaterialSearch] = useState("");
  const [materialType, setMaterialType] = useState<MaterialType>("人物");
  const [chapterPanel, setChapterPanel] = useState("任务");
  const [checkedTasks, setCheckedTasks] = useState<Record<string, string[]>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [pageError, setPageError] = useState("");
  const {
    operationsError,
    moreActionError,
    refreshOperations,
    cancelJob,
    retryJob,
    loadJobDetail
  } = useWorkbenchOperations({
    activeBook,
    activeBookIdRef,
    setJobs,
    setRuns,
    setLoadingAction
  });
  const {
    checkExport,
    generateExport
  } = useWorkbenchExports({
    activeBook,
    activeBookIdRef,
    setExportsByBookId,
    runAction
  });
  const {
    setBookModel,
    validateModel
  } = useWorkbenchModels({
    activeBook,
    activeBookIdRef,
    models,
    setBooks,
    setModels,
    setPageError,
    runAction,
    syncBookWorkspaceAfterWrite
  });
  const {
    createMaterial,
    updateMaterial,
    deleteMaterial
  } = useWorkbenchMaterials({
    activeBook,
    activeBookIdRef,
    materials,
    setBooks,
    setMaterials,
    setActiveMaterialId,
    setMaterialType,
    runAction,
    syncBookWorkspaceAfterWrite
  });
  const {
    chapterMemoryUpdates,
    applyReviewRepair,
    runReviews,
    confirmReview,
    loadChapterMemoryUpdates,
    applyMemoryUpdate
  } = useWorkbenchReviews({
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
  });
  const {
    applyChapterDraft,
    saveChapterDraft,
    acceptChapter,
    createNextChapter,
    updateChapterPlanning,
    prepareChapter,
    checkChapterGate,
    linkChapterMaterials
  } = useWorkbenchChapters({
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
  });

  async function syncWorkspaceState(options?: {
    preferredBookId?: string;
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
    suppressErrorToast?: boolean;
  }) {
    try {
      const workspace = await queryClient.fetchQuery({
        queryKey: ["workspace"],
        queryFn: () => workbenchClient.fetchWorkspace()
      });
      applyWorkspaceState(workspace, options);
      return workspace;
    } catch (error) {
      const errorMessage = authorText(error instanceof Error ? error.message : "工作区加载失败。");
      setPageError(errorMessage);
      if (!options?.suppressErrorToast) {
        message.error(errorMessage);
      }
      throw error;
    }
  }

  async function syncBookWorkspaceState(bookId: string, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
    onlyIfActiveBookId?: string;
    suppressErrorToast?: boolean;
  }) {
    try {
      const workspace = await queryClient.fetchQuery({
        queryKey: ["book-workspace", bookId],
        queryFn: () => workbenchClient.fetchBookWorkspace(bookId)
      });
      if (options?.onlyIfActiveBookId && activeBookIdRef.current !== options.onlyIfActiveBookId) {
        return workspace;
      }
      applyBookWorkspaceState(bookId, workspace, {
        preferredChapterId: options?.preferredChapterId,
        preferredMaterialId: options?.preferredMaterialId,
        preferredReviewId: options?.preferredReviewId
      });
      return workspace;
    } catch (error) {
      const shouldReportError = !options?.onlyIfActiveBookId || activeBookIdRef.current === options.onlyIfActiveBookId;
      if (!shouldReportError) {
        throw error;
      }
      const errorMessage = authorText(error instanceof Error ? error.message : "当前书工作区加载失败。");
      setPageError(errorMessage);
      if (!options?.suppressErrorToast) {
        message.error(errorMessage);
      }
      throw error;
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadWorkspace() {
      try {
        const workspace = await queryClient.fetchQuery({
          queryKey: ["workspace"],
          queryFn: () => workbenchClient.fetchWorkspace()
        });
        if (cancelled) {
          return;
        }
        applyWorkspaceState(workspace);
      } catch (error) {
        if (!cancelled) {
          const errorMessage = authorText(error instanceof Error ? error.message : "工作区加载失败。");
          setPageError(errorMessage);
          message.error(errorMessage);
        }
      }
    }
    void loadWorkspace();
    return () => {
      cancelled = true;
    };
  }, [applyWorkspaceState, queryClient]);

  useEffect(() => {
    if (!hasBooks) {
      return;
    }
    let cancelled = false;
    async function loadBookReviews() {
      try {
        const result = await workbenchClient.fetchBookReviews(activeBook.id);
        if (cancelled) {
          return;
        }
        setReviews((current) => [
          ...result.reviews,
          ...current.filter((item) => item.bookId !== result.bookId)
        ]);
        setActiveReviewId((current) =>
          result.reviews.some((item) => item.id === current)
            ? current
            : result.reviews[0]?.id ?? ""
        );
      } catch (error) {
        if (!cancelled) {
          const errorMessage = authorText(error instanceof Error ? error.message : "审稿列表加载失败。");
          setPageError(errorMessage);
        }
      }
    }
    void loadBookReviews();
    return () => {
      cancelled = true;
    };
  }, [activeBook.id, hasBooks]);

  async function runAction<T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) {
    setLoadingAction(key);
    setPageError("");
    try {
      return await action();
    } catch (error) {
      const errorMessage = authorText(error instanceof Error ? error.message : "操作失败，请稍后重试。");
      if (options?.shouldReportError?.() ?? true) {
        setPageError(errorMessage);
        message.error(errorMessage);
      }
      throw error;
    } finally {
      clearLoadingAction(key);
    }
  }

  async function syncBookWorkspaceAfterWrite(bookId: string, options: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  } = {}, fallback?: () => void) {
    await syncBookWorkspaceState(bookId, {
      ...options,
      onlyIfActiveBookId: bookId,
      suppressErrorToast: true
    }).catch(() => {
      if (activeBookIdRef.current === bookId) {
        fallback?.();
      }
    });
  }

  function applyGenerationResponse(result: GenerationResponse) {
    setGenerationStates((current) => replaceBookWorkspaceItems(current, [result.generationState], result.generationState.bookId));
    setBooks((current) => current.map((book) => (book.id === result.book.id ? result.book : book)));
    setJobs((current) => replaceBookWorkspaceItems(current, result.jobs, result.generationState.bookId));
    setRuns((current) => replaceBookWorkspaceItems(current, result.runs, result.generationState.bookId));
    if (result.activeChapter.id) {
      setActiveChapterId(result.activeChapter.id);
    }
    if (result.target) {
      setModuleKey(result.target);
    }
  }

  async function setGenerationMode(interventionMode: GenerationMode, batchTarget: number, autoStepLimit: number) {
    const requestBookId = activeBook.id;
    const result = await runAction(`generation-mode-${requestBookId}`, () =>
      workbenchClient.setGenerationMode({
        bookId: requestBookId,
        interventionMode,
        batchTarget,
        autoStepLimit
      }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  async function updateProjectPlan(
    targetChapterCount: number,
    targetWordsPerChapter: number,
    targetChaptersPerPlot: number
  ) {
    const requestBookId = activeBook.id;
    const result = await runAction(`book-plan-${requestBookId}`, () =>
      workbenchClient.updateProjectPlan({
        bookId: requestBookId,
        targetChapterCount,
        targetWordsPerChapter,
        targetChaptersPerPlot
      }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    setBooks((current) => current.map((book) => (book.id === result.bookId ? result.book : book)));
    message.success(authorText(result.authorMessage));
  }

  async function runGenerationAction(
    action: "continue" | "confirm" | "pause" | "resume",
    optionId = ""
  ) {
    const requestBookId = activeBook.id;
    const handlers = {
      continue: workbenchClient.continueGeneration,
      confirm: workbenchClient.confirmGeneration,
      pause: workbenchClient.pauseGeneration,
      resume: workbenchClient.resumeGeneration
    };
    const result = await runAction(`generation-${action}`, () =>
      handlers[action]({
        bookId: requestBookId,
        optionId: optionId || undefined,
        requestId: crypto.randomUUID()
      }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  async function takeoverGeneration(target: "writing" | "library" | "review") {
    const requestBookId = activeBook.id;
    const result = await runAction(`generation-takeover-${target}`, () =>
      workbenchClient.takeoverGeneration({
        bookId: requestBookId,
        target
      }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  async function regenerateGenerationCandidate() {
    const requestBookId = activeBook.id;
    const result = await runAction("generation-regenerate", () =>
      workbenchClient.regenerateGenerationCandidate({ bookId: requestBookId, requestId: crypto.randomUUID() }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  async function selectGenerationCandidate(candidateId: string) {
    const requestBookId = activeBook.id;
    const result = await runAction("generation-select-candidate", () =>
      workbenchClient.selectGenerationCandidate(requestBookId, candidateId, crypto.randomUUID()), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  async function rollbackGenerationCandidate() {
    const requestBookId = activeBook.id;
    const result = await runAction("generation-rollback", () =>
      workbenchClient.rollbackGenerationCandidate({ bookId: requestBookId, requestId: crypto.randomUUID() }), {
        shouldReportError: () => activeBookIdRef.current === requestBookId
      }
    );
    if (activeBookIdRef.current !== requestBookId) {
      return;
    }
    applyGenerationResponse(result);
    message.success(authorText(result.authorMessage));
  }

  function clearLoadingAction(key: string) {
    setLoadingAction((current) => (current === key ? null : current));
  }

  function switchBook(bookId: string) {
    const nextBook = books.find((book) => book.id === bookId) ?? books[0] ?? fallbackBook;
    const nextMaterial = materials.find((item) => item.bookId === nextBook.id);
    const nextReview = reviews.find((item) => item.bookId === nextBook.id);
    const requestBookId = nextBook.id;
    setActiveBookId(nextBook.id);
    setActiveChapterId(nextBook.chapters[0]?.id ?? fallbackChapter.id);
    setActiveMaterialId(nextMaterial?.id ?? "");
    setActiveReviewId(nextReview?.id ?? "");
    void syncBookWorkspaceState(requestBookId, {
      preferredChapterId: nextBook.chapters[0]?.id ?? fallbackChapter.id,
      preferredMaterialId: nextMaterial?.id,
      preferredReviewId: nextReview?.id,
      onlyIfActiveBookId: requestBookId,
      suppressErrorToast: true
    }).catch(() => undefined);
  }

  async function createBook(draft: NewBookDraft, setup: BookCreationSetup) {
    const { book, chapter, review, generationState, authorMessage } = await runAction("book-create", () =>
      workbenchClient.createBook({
        draft,
        existingBookCount: books.length,
        defaultModelId: setup.modelId,
        interventionMode: setup.interventionMode,
        batchTarget: setup.batchTarget,
        targetChapterCount: setup.targetChapterCount,
        targetWordsPerChapter: setup.targetWordsPerChapter,
        targetChaptersPerPlot: setup.targetChaptersPerPlot,
        startGeneration: true
      })
    );
    setBooks((current) => [book, ...current]);
    setReviews((current) => [review, ...current]);
    if (generationState) {
      setGenerationStates((current) => replaceBookWorkspaceItems(current, [generationState], book.id));
    }
    setActiveBookId(book.id);
    activeBookIdRef.current = book.id;
    setActiveChapterId(chapter.id);
    setActiveReviewId(review.id);
    setModuleKey("today");
    message.success(authorText(authorMessage || `已创建《${book.title}》，并切换到这本书的生成主控台。`));
  }

  return (
    <WorkbenchView
      books={books}
      activeBook={activeBook}
      activeChapter={activeChapter}
      activeWorkspace={activeWorkspace}
      generationStates={generationStates}
      activeMaterial={activeMaterial}
      activeReview={activeReview}
      activeModel={activeModel}
      models={models}
      hasBooks={hasBooks}
      moduleKey={moduleKey}
      bookSearch={bookSearch}
      materialSearch={materialSearch}
      materialType={materialType}
      chapterPanel={chapterPanel}
      checkedTasks={checkedTasks[chapterUiStateKey(activeBook.id, activeChapter.id)] ?? [activeChapter.tasks[0]]}
      chapterMemoryUpdates={chapterMemoryUpdates}
      creationOptions={creationOptions}
      loadingAction={loadingAction}
      pageError={pageError}
      operationsError={operationsError}
      moreActionError={moreActionError}
      onModuleChange={setModuleKey}
      onPageErrorClear={() => setPageError("")}
      onBookSearchChange={setBookSearch}
      onMaterialSearchChange={setMaterialSearch}
      onMaterialTypeChange={setMaterialType}
      onChapterChange={setActiveChapterId}
      onChapterPanelChange={setChapterPanel}
      onTasksChange={(tasks) => setCheckedTasks((current) => ({ ...current, [chapterUiStateKey(activeBook.id, activeChapter.id)]: tasks }))}
      onCreateBook={createBook}
      onBookUpdated={(book) => {
        setBooks((current) => current.map((item) => item.id === book.id ? book : item));
      }}
      onSelectBook={switchBook}
      onOpenBook={(bookId) => {
        switchBook(bookId);
        setModuleKey("today");
      }}
      onCreateFirstChapter={createNextChapter}
      onGenerationModeChange={setGenerationMode}
      onProjectPlanChange={updateProjectPlan}
      onGenerationContinue={() => runGenerationAction("continue")}
      onGenerationConfirm={(optionId) => runGenerationAction("confirm", optionId)}
      onGenerationRegenerate={regenerateGenerationCandidate}
      onGenerationCandidateSelect={selectGenerationCandidate}
      onGenerationRollback={rollbackGenerationCandidate}
      onGenerationPause={() => runGenerationAction("pause")}
      onGenerationResume={() => runGenerationAction("resume")}
      onGenerationTakeover={takeoverGeneration}
      onRefreshTasks={refreshOperations}
      onPlanningChange={updateChapterPlanning}
      onCreateMaterial={(material) => createMaterial({ ...material, bookId: activeBook.id })}
      onUpdateMaterial={updateMaterial}
      onDeleteMaterial={deleteMaterial}
      onLinkMaterials={(materialIds, mode) => linkChapterMaterials(activeChapter.id, materialIds, mode)}
      onApplyCandidate={(nextContent) => applyChapterDraft(activeChapter.id, nextContent)}
      onSaveDraft={(nextContent) => saveChapterDraft(activeChapter.id, nextContent)}
      onPrepareChapter={() => prepareChapter(activeChapter.id)}
      onCheckGate={() => checkChapterGate(activeChapter.id)}
      onAcceptChapter={(force) => acceptChapter(activeChapter.id, force)}
      onCreateNextChapter={createNextChapter}
      onMaterialChange={setActiveMaterialId}
      onReviewChange={setActiveReviewId}
      onApplyRepair={applyReviewRepair}
      onRunReview={runReviews}
      onConfirmReview={confirmReview}
      onLoadMemoryUpdates={loadChapterMemoryUpdates}
      onApplyMemoryUpdate={applyMemoryUpdate}
      onCheckExport={checkExport}
      onGenerateExport={generateExport}
      onLoadJobDetail={loadJobDetail}
      onCancelJob={cancelJob}
      onRetryJob={retryJob}
      onModelChange={setBookModel}
      onValidateModel={validateModel}
    />
  );
}

function chapterUiStateKey(bookId: string, chapterId: string) {
  return `${bookId}:${chapterId}`;
}

function App() {
  return (
    <ErrorBoundary fallback={<div style={{ padding: 24 }}>页面发生错误，请刷新重试。</div>}>
      <QueryClientProvider client={queryClient}>
        <ConfigProvider
          theme={{
            token: {
              colorPrimary: "#2563eb",
              borderRadius: 8,
              fontFamily:
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
            }
          }}
        >
          <AntApp>
            <Workbench />
          </AntApp>
        </ConfigProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
