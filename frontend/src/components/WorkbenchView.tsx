import { lazy, Suspense } from "react";
import { Alert, Button, Layout, Space, Typography } from "antd";
import { FireOutlined } from "@ant-design/icons";
import { AppSidebar } from "./AppSidebar";
import {
  parseAcceptAction,
  parseMaterialDeleteAction,
  parseMaterialLinkAction,
  parseModelAction
} from "../domain/workbenchShell";
import { memoryUpdateCacheKey } from "../hooks/useWorkbenchReviews";
import type {
  AcceptChapterBlockedDetail,
  AcceptChapterResponse,
  ChapterGateResponse,
  ChapterPrepareResponse,
  ExportCheckResponse,
  ExportGenerateResponse
} from "../api/contracts";
import type {
  Book,
  BookCreationSetup,
  BookCreationOptions,
  BookWorkspace,
  ExportReadiness,
  GenerationState,
  Material,
  MaterialType,
  MemoryUpdateItem,
  ModelProfile,
  ModuleKey,
  NewBookDraft,
  GenerationMode,
  ReviewItem
} from "../types";
import { authorText } from "../utils/authorText";

const { Header, Content } = Layout;
const { Text, Title } = Typography;

const ShelfPage = lazy(() => import("../pages/ShelfPage").then((module) => ({ default: module.ShelfPage })));
const TodayPage = lazy(() => import("../pages/TodayPage").then((module) => ({ default: module.TodayPage })));
const WritingPage = lazy(() => import("../pages/WritingPage").then((module) => ({ default: module.WritingPage })));
const LibraryPage = lazy(() => import("../pages/LibraryPage").then((module) => ({ default: module.LibraryPage })));
const ReviewPage = lazy(() => import("../pages/ReviewPage").then((module) => ({ default: module.ReviewPage })));
const ExportPage = lazy(() => import("../pages/ExportPage").then((module) => ({ default: module.ExportPage })));
const MorePage = lazy(() => import("../pages/MorePage").then((module) => ({ default: module.MorePage })));
const ModelPage = lazy(() => import("../pages/ModelPage").then((module) => ({ default: module.ModelPage })));
const AIAccountsPage = lazy(() => import("../pages/AIAccountsPage").then((module) => ({ default: module.AIAccountsPage })));

const moduleTitle: Record<ModuleKey, string> = {
  shelf: "书架",
  accounts: "AI 模型",
  today: "生成主控台",
  writing: "章节",
  library: "资料",
  review: "审稿中心",
  export: "导出",
  more: "更多",
  model: "我的模型"
};

type WorkbenchViewProps = {
  books: Book[];
  activeBook: Book;
  activeChapter: Book["chapters"][number];
  activeWorkspace: BookWorkspace;
  generationStates: GenerationState[];
  activeMaterial?: Material;
  activeReview?: ReviewItem;
  activeModel: BookWorkspace["model"];
  models: ModelProfile[];
  hasBooks: boolean;
  moduleKey: ModuleKey;
  bookSearch: string;
  materialSearch: string;
  materialType: MaterialType;
  chapterPanel: string;
  checkedTasks: string[];
  chapterMemoryUpdates: Record<string, MemoryUpdateItem[]>;
  creationOptions: BookCreationOptions;
  loadingAction: string | null;
  pageError: string;
  operationsError: string;
  moreActionError: string;
  onModuleChange: (moduleKey: ModuleKey) => void;
  onPageErrorClear: () => void;
  onBookSearchChange: (value: string) => void;
  onMaterialSearchChange: (value: string) => void;
  onMaterialTypeChange: (value: MaterialType) => void;
  onChapterChange: (chapterId: string) => void;
  onChapterPanelChange: (panel: string) => void;
  onTasksChange: (tasks: string[]) => void;
  onCreateBook: (draft: NewBookDraft, setup: BookCreationSetup) => void | Promise<void>;
  onBookUpdated: (book: Book) => void;
  onSelectBook: (bookId: string) => void;
  onOpenBook: (bookId: string) => void;
  onCreateFirstChapter: () => void | Promise<void>;
  onGenerationModeChange: (mode: GenerationMode, batchTarget: number, autoStepLimit: number) => void | Promise<void>;
  onProjectPlanChange: (
    targetChapterCount: number,
    targetWordsPerChapter: number,
    targetChaptersPerPlot: number
  ) => void | Promise<void>;
  onGenerationContinue: () => void | Promise<void>;
  onGenerationConfirm: (optionId?: string) => void | Promise<void>;
  onGenerationRegenerate: () => void | Promise<void>;
  onGenerationCandidateSelect: (candidateId: string) => void | Promise<void>;
  onGenerationRollback: () => void | Promise<void>;
  onGenerationPause: () => void | Promise<void>;
  onGenerationResume: () => void | Promise<void>;
  onGenerationTakeover: (target: "writing" | "library" | "review") => void | Promise<void>;
  onRefreshTasks: () => void | Promise<void>;
  onPlanningChange: (tasks: string[], plotPoints: string[]) => void | Promise<void>;
  onCreateMaterial: (material: Omit<Material, "bookId"> & { bookId?: string }) => void | Promise<void>;
  onUpdateMaterial: (material: Material) => void | Promise<void>;
  onDeleteMaterial: (materialId: string) => void | Promise<void>;
  onLinkMaterials: (materialIds: string[], mode?: "append" | "replace") => void | Promise<unknown>;
  onApplyCandidate: (nextContent: string) => void | Promise<void>;
  onSaveDraft: (nextContent: string) => void | Promise<void>;
  onPrepareChapter: () => Promise<ChapterPrepareResponse>;
  onCheckGate: () => Promise<ChapterGateResponse>;
  onAcceptChapter: (force?: boolean) => Promise<AcceptChapterBlockedDetail | AcceptChapterResponse | null>;
  onCreateNextChapter: () => void | Promise<void>;
  onMaterialChange: (id: string) => void;
  onReviewChange: (id: string) => void;
  onApplyRepair: (review: ReviewItem, repairText: string) => void | Promise<void>;
  onRunReview: () => void | Promise<void>;
  onConfirmReview: (review: ReviewItem) => void | Promise<void>;
  onLoadMemoryUpdates: (chapterId: string) => Promise<MemoryUpdateItem[]>;
  onApplyMemoryUpdate: (update: MemoryUpdateItem) => void | Promise<void>;
  onCheckExport: (kind: ExportReadiness["kind"], range: string, rangeStart?: string, rangeEnd?: string) => Promise<ExportCheckResponse>;
  onGenerateExport: (
    kind: ExportReadiness["kind"],
    range: string,
    rangeStart?: string,
    rangeEnd?: string,
    trainingChapterIds?: string[]
  ) => Promise<ExportGenerateResponse>;
  onLoadJobDetail: (jobId: string) => Promise<unknown>;
  onCancelJob: (jobId: string) => void | Promise<void>;
  onRetryJob: (jobId: string) => void | Promise<void>;
  onModelChange: (modelId: string) => void | Promise<void>;
  onValidateModel: (modelId: string) => void | Promise<void>;
};

export function WorkbenchView({
  books,
  activeBook,
  activeChapter,
  activeWorkspace,
  generationStates,
  activeMaterial,
  activeReview,
  activeModel,
  models,
  hasBooks,
  moduleKey,
  bookSearch,
  materialSearch,
  materialType,
  chapterPanel,
  checkedTasks,
  chapterMemoryUpdates,
  creationOptions,
  loadingAction,
  pageError,
  operationsError,
  moreActionError,
  onModuleChange,
  onPageErrorClear,
  onBookSearchChange,
  onMaterialSearchChange,
  onMaterialTypeChange,
  onChapterChange,
  onChapterPanelChange,
  onTasksChange,
  onCreateBook,
  onBookUpdated,
  onSelectBook,
  onOpenBook,
  onCreateFirstChapter,
  onGenerationModeChange,
  onProjectPlanChange,
  onGenerationContinue,
  onGenerationConfirm,
  onGenerationRegenerate,
  onGenerationCandidateSelect,
  onGenerationRollback,
  onGenerationPause,
  onGenerationResume,
  onGenerationTakeover,
  onRefreshTasks,
  onPlanningChange,
  onCreateMaterial,
  onUpdateMaterial,
  onDeleteMaterial,
  onLinkMaterials,
  onApplyCandidate,
  onSaveDraft,
  onPrepareChapter,
  onCheckGate,
  onAcceptChapter,
  onCreateNextChapter,
  onMaterialChange,
  onReviewChange,
  onApplyRepair,
  onRunReview,
  onConfirmReview,
  onLoadMemoryUpdates,
  onApplyMemoryUpdate,
  onCheckExport,
  onGenerateExport,
  onLoadJobDetail,
  onCancelJob,
  onRetryJob,
  onModelChange,
  onValidateModel
}: WorkbenchViewProps) {
  const materialSaveAction =
    loadingAction === "material-create"
      ? { type: "create" as const }
      : loadingAction?.startsWith("material-update-")
        ? { type: "update" as const, materialId: loadingAction.slice("material-update-".length) }
        : null;

  return (
    <Layout className="app-shell">
      <AppSidebar
        books={books}
        activeBook={activeBook}
        activeChapter={activeChapter}
        generationState={activeWorkspace.generationState}
        reviews={activeWorkspace.reviews}
        jobs={activeWorkspace.jobs}
        moduleKey={moduleKey}
        onModuleChange={onModuleChange}
      />
      <Layout>
        <Header className="topbar">
          <div className="topbar-title">
            <Text type="secondary">
              {authorText(activeBook.title)} · {authorText(activeBook.genre)} · {authorText(activeBook.updatedAt)}
            </Text>
            <Title level={3}>{moduleTitle[moduleKey]}</Title>
            {!hasBooks || moduleKey === "shelf" || moduleKey === "accounts" || moduleKey === "model" ? null : (
              <Text type="secondary">当前章节：{authorText(activeChapter.title)}</Text>
            )}
          </div>
          <Space wrap>
            <Button type="primary" icon={<FireOutlined />} disabled={!hasBooks} onClick={() => onModuleChange("today")}>
              继续生成
            </Button>
          </Space>
        </Header>
        <Content className="workspace">
          <Suspense fallback={<CardLoading />}>
            {pageError ? (
              <Alert
                className="api-alert"
                type="error"
                showIcon
                closable
                message="当前操作失败"
                description={authorText(pageError)}
                onClose={onPageErrorClear}
              />
            ) : null}
            {moduleKey === "shelf" && (
              <ShelfPage
                books={books}
                activeBook={activeBook}
                search={bookSearch}
                onSearchChange={onBookSearchChange}
                onCreateBook={onCreateBook}
                creationOptions={creationOptions}
                generationStates={generationStates}
                createLoading={loadingAction === "book-create"}
                onSelectBook={onSelectBook}
                onOpenBook={onOpenBook}
                onBookUpdated={onBookUpdated}
              />
            )}
            {!hasBooks && moduleKey !== "shelf" && moduleKey !== "accounts" && moduleKey !== "model" ? (
              <ShelfPage
                books={books}
                activeBook={activeBook}
                search={bookSearch}
                onSearchChange={onBookSearchChange}
                onCreateBook={onCreateBook}
                creationOptions={creationOptions}
                generationStates={generationStates}
                createLoading={loadingAction === "book-create"}
                onSelectBook={onSelectBook}
                onOpenBook={onOpenBook}
                onBookUpdated={onBookUpdated}
              />
            ) : null}
            {hasBooks && moduleKey === "today" && (
              <TodayPage
                book={activeBook}
                chapter={activeChapter}
                today={activeWorkspace.today}
                generationState={activeWorkspace.generationState}
                jobs={activeWorkspace.jobs}
                onGoWriting={() => onModuleChange("writing")}
                onGoLibrary={() => onModuleChange("library")}
                onGoReview={() => onModuleChange("review")}
                onGoMore={() => onModuleChange("more")}
                onOpenTasks={() => onModuleChange("today")}
                onCreateFirstChapter={onCreateFirstChapter}
                onGenerationModeChange={onGenerationModeChange}
                onProjectPlanChange={onProjectPlanChange}
                onGenerationContinue={onGenerationContinue}
                onGenerationConfirm={onGenerationConfirm}
                onGenerationRegenerate={onGenerationRegenerate}
                onGenerationCandidateSelect={onGenerationCandidateSelect}
                onGenerationRollback={onGenerationRollback}
                onGenerationPause={onGenerationPause}
                onGenerationResume={onGenerationResume}
                onGenerationTakeover={onGenerationTakeover}
                onPrepareChapter={onPrepareChapter}
                onRefreshTasks={onRefreshTasks}
                onRetryJob={onRetryJob}
                createFirstChapterLoading={loadingAction === "chapter-next"}
                prepareChapterLoading={loadingAction === "chapter-prepare"}
                tasksLoading={loadingAction === "ops-refresh"}
                generationAction={loadingAction?.startsWith("generation-") ? loadingAction : null}
                projectPlanLoading={loadingAction === `book-plan-${activeBook.id}`}
                tasksError={operationsError}
              />
            )}
            {hasBooks && moduleKey === "writing" && (
              <WritingPage
                book={activeBook}
                chapter={activeChapter}
                materials={activeWorkspace.materials}
                panel={chapterPanel}
                checkedTasks={checkedTasks}
                onChapterChange={onChapterChange}
                onPanelChange={onChapterPanelChange}
                onTasksChange={onTasksChange}
                onPlanningChange={onPlanningChange}
                onCreateMaterial={onCreateMaterial}
                onUpdateMaterial={onUpdateMaterial}
                onDeleteMaterial={onDeleteMaterial}
                onLinkMaterials={onLinkMaterials}
                materialLinkAction={parseMaterialLinkAction(loadingAction)}
                materialDeleteAction={parseMaterialDeleteAction(loadingAction)}
                onApplyCandidate={onApplyCandidate}
                onSaveDraft={onSaveDraft}
                onPrepareChapter={onPrepareChapter}
                onCheckGate={onCheckGate}
                onAcceptChapter={onAcceptChapter}
                onCreateNextChapter={onCreateNextChapter}
                onOpenReview={() => onModuleChange("review")}
                materialSaveAction={materialSaveAction}
                applyLoading={loadingAction === "chapter-draft-save" || loadingAction === "chapter-draft-apply"}
                prepareLoading={loadingAction === "chapter-prepare"}
                gateLoading={loadingAction === "chapter-gate"}
                acceptAction={parseAcceptAction(loadingAction)}
                nextChapterLoading={loadingAction === "chapter-next"}
              />
            )}
            {hasBooks && moduleKey === "library" && (
              <LibraryPage
                bookId={activeBook.id}
                activeChapter={activeChapter}
                memoryInspection={activeBook.memoryInspection}
                materials={activeWorkspace.materials}
                materialLibrary={activeWorkspace.materialLibrary}
                activeMaterial={activeMaterial}
                search={materialSearch}
                materialType={materialType}
                onSearchChange={onMaterialSearchChange}
                onTypeChange={onMaterialTypeChange}
                onMaterialChange={onMaterialChange}
                onCreateMaterial={onCreateMaterial}
                onUpdateMaterial={onUpdateMaterial}
                onDeleteMaterial={onDeleteMaterial}
                onLinkToChapter={onLinkMaterials}
                materialLinkAction={parseMaterialLinkAction(loadingAction)}
                materialDeleteAction={parseMaterialDeleteAction(loadingAction)}
                materialSaveAction={materialSaveAction}
              />
            )}
            {hasBooks && moduleKey === "review" && (
              <ReviewPage
                chapters={activeWorkspace.chapters}
                reviews={activeWorkspace.reviews}
                activeReview={activeReview}
                memoryUpdates={activeReview ? chapterMemoryUpdates[memoryUpdateCacheKey(activeReview.bookId, activeReview.chapterId)] ?? [] : []}
                onReviewChange={onReviewChange}
                onApplyRepair={onApplyRepair}
                onRunReview={onRunReview}
                onConfirmReview={onConfirmReview}
                onLoadMemoryUpdates={onLoadMemoryUpdates}
                onApplyMemoryUpdate={onApplyMemoryUpdate}
                onGoWriting={() => onModuleChange("writing")}
                repairingReviewId={
                  loadingAction?.startsWith("review-repair-") ? loadingAction.slice("review-repair-".length) : null
                }
                runLoading={loadingAction === "review-run"}
                confirmLoading={loadingAction === `review-confirm-${activeReview?.id}`}
                memoryLoading={activeReview ? loadingAction === `memory-updates-${memoryUpdateCacheKey(activeReview.bookId, activeReview.chapterId)}` : false}
                memoryApplyLoadingId={
                  loadingAction?.startsWith("memory-apply-") ? loadingAction.slice("memory-apply-".length) : null
                }
              />
            )}
            {hasBooks && moduleKey === "export" && (
              <ExportPage
                book={activeBook}
                activeChapter={activeChapter}
                exports={activeWorkspace.exports}
                generationState={activeWorkspace.generationState}
                materials={activeWorkspace.materials}
                reviews={activeWorkspace.reviews}
                onCheckExport={onCheckExport}
                onGenerateExport={onGenerateExport}
                checking={loadingAction?.startsWith("export-check-") ?? false}
                generating={loadingAction?.startsWith("export-generate-") ?? false}
              />
            )}
            {hasBooks && moduleKey === "more" && (
              <MorePage
                book={activeBook}
                jobs={activeWorkspace.jobs}
                runs={activeWorkspace.runs}
                refreshError={operationsError}
                actionError={moreActionError}
                onRefresh={onRefreshTasks}
                onLoadJobDetail={onLoadJobDetail}
                onCancelJob={onCancelJob}
                onRetryJob={onRetryJob}
                loadingAction={loadingAction}
              />
            )}
            {moduleKey === "model" && (
              <ModelPage
                activeBook={activeBook}
                books={books}
                onModelChange={onModelChange}
              />
            )}
            {moduleKey === "accounts" && (
              <AIAccountsPage />
            )}
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
}

function CardLoading() {
  return (
    <div className="content-card page-loading">
      <Text type="secondary">正在打开页面...</Text>
    </div>
  );
}
