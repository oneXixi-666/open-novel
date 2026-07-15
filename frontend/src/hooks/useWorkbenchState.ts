import { useCallback, useEffect, useRef, useState } from "react";
import { buildBookWorkspace } from "../domain/bookWorkspace";
import {
  attachBookIdToExports,
  emptyCreationOptions,
  fallbackBook,
  fallbackChapter,
  fallbackGenerationState,
  groupExportsByBookId,
  replaceBookWorkspaceItems,
  selectBookWorkspaceState,
  selectWorkspaceState
} from "../domain/workbenchShell";
import type {
  Book,
  BookCreationOptions,
  ExportReadiness,
  GenerationState,
  JobSummary,
  Material,
  ModelProfile,
  ReviewItem,
  RunSummary,
  WorkspaceData
} from "../types";

const ACTIVE_BOOK_STORAGE_KEY = "open-novel-active-book";

export function useWorkbenchState() {
  const [books, setBooks] = useState<Book[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [exportsByBookId, setExportsByBookId] = useState<Record<string, ExportReadiness[]>>({});
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [generationStates, setGenerationStates] = useState<GenerationState[]>([]);
  const [creationOptions, setCreationOptions] = useState<BookCreationOptions>(emptyCreationOptions);
  const [activeBookId, setActiveBookId] = useState(() => localStorage.getItem(ACTIVE_BOOK_STORAGE_KEY) || fallbackBook.id);
  const [activeChapterId, setActiveChapterId] = useState(fallbackChapter.id);
  const [activeMaterialId, setActiveMaterialId] = useState("");
  const [activeReviewId, setActiveReviewId] = useState("");

  const activeBook = books.find((book) => book.id === activeBookId) ?? books[0] ?? fallbackBook;
  const activeBookIdRef = useRef(activeBook.id);
  const hasBooks = books.length > 0;
  const activeChapter = activeBook.chapters.find((chapter) => chapter.id === activeChapterId) ?? activeBook.chapters[0] ?? fallbackChapter;
  const activeGenerationState = generationStates.find((state) => state.bookId === activeBook.id) ?? {
    ...fallbackGenerationState,
    bookId: activeBook.id,
    activeChapterId: activeChapter.id,
    nextAction: activeBook.nextAction || fallbackGenerationState.nextAction
  };
  const activeWorkspace = buildBookWorkspace({
    book: activeBook,
    activeChapterId,
    materials,
    reviews,
    models,
    jobs,
    runs,
    exports: exportsByBookId[activeBook.id] ?? [],
    generationState: activeGenerationState
  });
  const activeMaterial = activeWorkspace.materials.find((item) => item.id === activeMaterialId) ?? activeWorkspace.materials[0];
  const activeReview = activeWorkspace.reviews.find((item) => item.id === activeReviewId) ?? activeWorkspace.reviews[0];
  const activeModel = activeWorkspace.model;

  useEffect(() => {
    activeBookIdRef.current = activeBook.id;
    if (activeBook.id !== fallbackBook.id) {
      localStorage.setItem(ACTIVE_BOOK_STORAGE_KEY, activeBook.id);
    }
  }, [activeBook.id, activeBookIdRef]);

  const applyWorkspaceState = useCallback((workspace: WorkspaceData, options?: {
    preferredBookId?: string;
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }) => {
    setBooks(workspace.books);
    setMaterials(workspace.materials);
    setReviews(workspace.reviews);
    setModels(workspace.models);
    setExportsByBookId(groupExportsByBookId(workspace.exports, workspace.books));
    setJobs(workspace.jobs);
    setRuns(workspace.runs);
    setGenerationStates(workspace.generationStates);
    setCreationOptions(workspace.creationOptions);
    const selection = selectWorkspaceState(workspace, {
      activeBookId,
      activeChapterId,
      activeMaterialId,
      activeReviewId
    }, options);
    setActiveBookId(selection.activeBookId);
    setActiveChapterId(selection.activeChapterId);
    setActiveMaterialId(selection.activeMaterialId);
    setActiveReviewId(selection.activeReviewId);
  }, [activeBookId, activeChapterId, activeMaterialId, activeReviewId]);

  const applyBookWorkspaceState = useCallback((bookId: string, workspace: WorkspaceData, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }) => {
    const nextBook = workspace.books[0];
    const selection = selectBookWorkspaceState(workspace, {
      activeChapterId,
      activeMaterialId,
      activeReviewId
    }, options);
    if (!nextBook || !selection) {
      return;
    }
    setBooks((current) => current.map((book) => (book.id === bookId ? nextBook : book)));
    setMaterials((current) => replaceBookWorkspaceItems(current, workspace.materials, bookId));
    setReviews((current) => replaceBookWorkspaceItems(current, workspace.reviews, bookId));
    setExportsByBookId((current) => ({
      ...current,
      [bookId]: attachBookIdToExports(bookId, workspace.exports)
    }));
    setJobs((current) => replaceBookWorkspaceItems(current, workspace.jobs, bookId));
    setRuns((current) => replaceBookWorkspaceItems(current, workspace.runs, bookId));
    setGenerationStates((current) => replaceBookWorkspaceItems(current, workspace.generationStates, bookId));
    setCreationOptions(workspace.creationOptions);
    setActiveBookId(bookId);
    setActiveChapterId(selection.activeChapterId);
    setActiveMaterialId(selection.activeMaterialId);
    setActiveReviewId(selection.activeReviewId);
  }, [activeChapterId, activeMaterialId, activeReviewId]);

  return {
    books,
    setBooks,
    materials,
    setMaterials,
    reviews,
    setReviews,
    models,
    setModels,
    exportsByBookId,
    setExportsByBookId,
    jobs,
    setJobs,
    runs,
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
    activeChapterId,
    setActiveBookId,
    setActiveChapterId,
    setActiveMaterialId,
    setActiveReviewId,
    applyWorkspaceState,
    applyBookWorkspaceState
  };
}
