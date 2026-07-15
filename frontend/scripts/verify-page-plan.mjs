import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { approvedAdvancedPaths, blockedAdvancedActionCopy, blockedAdvancedPaths, blockedAdvancedPlaceholderCopy } from "./advanced-paths.mjs";

const root = new URL("..", import.meta.url).pathname;
const srcRoot = join(root, "src");
const workbenchE2e = readFileSync(join(root, "tests/e2e/workbench.spec.ts"), "utf8");

function walk(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry);
    return statSync(fullPath).isDirectory() ? walk(fullPath) : [fullPath];
  });
}

const files = Object.fromEntries(
  [
    ...walk(srcRoot).filter((file) => /\.(ts|tsx|css)$/.test(file)),
    join(root, "vite.config.ts")
  ].map((file) => [relative(root, file), readFileSync(file, "utf8")])
);

const blockedClientMethods = [
  "fetchModelTrainingReadiness",
  "compareModels",
  "promoteComparedModel",
  "fetchWritingModels",
  "createWritingModel",
  "setDefaultWritingModel",
  "fetchEditorialModels",
  "createEditorialModel",
  "setDefaultEditorialModel",
  "fetchStyleProfiles",
  "applyStyleProfile",
  "fetchDiff",
  "fetchDiagnostics",
  "runMaintenanceAction",
  "fetchLibraryRelationships",
  "fetchLibraryRelationshipDetail",
  "updateLibraryRelationshipEvent",
  "fetchLibraryTopicDetail",
  "fetchLibraryTimeline",
  "syncLibraryTimeline"
];

const blockedClientPaths = [
  "/api/models/training/readiness",
  "/api/models/quality-distribution",
  "/api/models/compare",
  "/api/models/writing",
  "/api/models/editorial",
  "/api/models/style-profiles",
  "/library/relationships",
  "/library/topics",
  "/library/timeline",
  "/diff",
  "/diagnostics",
  "/maintenance"
];

const requiredClientMethods = [
  "fetchWorkspace",
  "fetchBookWorkspace",
  "createBook",
  "updateBookSettings",
  "createMaterial",
  "updateMaterial",
  "deleteMaterial",
  "setBookModel",
  "updateProjectPlan",
  "validateModel",
  "applyChapterDraft",
  "updateChapterPlanning",
  "linkChapterMaterials",
  "fetchChapterMaterials",
  "prepareChapter",
  "checkChapterGate",
  "fetchChapterGateRecovery",
  "acceptChapter",
  "createNextChapter",
  "applyReviewRepair",
  "fetchBookReviews",
  "runReviews",
  "updateReviewStatus",
  "fetchChapterMemoryUpdates",
  "applyMemoryUpdate",
  "checkExport",
  "generateExport",
  "fetchJobs",
  "fetchJobDetail",
  "fetchJobEvents",
  "cancelJob",
  "retryJob",
  "fetchRuns",
  "fetchGeneration",
  "setGenerationMode",
  "continueGeneration",
  "confirmGeneration",
  "pauseGeneration",
  "resumeGeneration",
  "takeoverGeneration",
  "runAgentAssist"
  ,"streamAgentAssist"
  ,"fetchAISettings"
  ,"createAIAccount"
  ,"updateAIAccount"
  ,"deleteAIAccount"
  ,"bindAIRoles"
  ,"probeAIAccount"
  ,"runModelTraining"
  ,"fetchModelLibrary"
  ,"fetchModelTrainingBackends"
  ,"fetchModelLibraryDetail"
  ,"createModelLibraryItem"
  ,"createModelCategory"
  ,"uploadModelSources"
  ,"addModelBookSources"
  ,"deleteModelSource"
  ,"fetchModelLibraryReadiness"
  ,"startModelLibraryTraining"
];

const requiredClientPaths = [
  "/api/workspace",
  "/workspace",
  "/api/books",
  "/settings",
  "/materials",
  "/materials/link",
  "/model",
  "/plan",
  "/api/models/",
  "/validate",
  "/draft",
  "/planning",
  "/prepare",
  "/gate",
  "/gate/recovery",
  "/accept",
  "/chapters/next",
  "/reviews/",
  "/repair",
  "/reviews/run",
  "/memory-updates",
  "/apply",
  "/exports/check",
  "/exports",
  "/jobs",
  "/events",
  "/cancel",
  "/retry",
  "/runs",
  "/generation",
  "/generation/mode",
  "/generation/continue",
  "/generation/confirm",
  "/generation/pause",
  "/generation/resume",
  "/generation/takeover",
  "/api/agent/assist",
  "/api/ai/settings",
  "/api/ai/accounts",
  "/api/ai/roles",
  "/probe",
  "/api/models/training/run",
  "/api/model-library",
  "/api/model-library-training-backends"
];

function has(path, pattern) {
  const content = files[path];
  if (!content) {
    return false;
  }
  return pattern instanceof RegExp ? pattern.test(content) : content.includes(pattern);
}

function any(pattern) {
  return Object.values(files).some((content) => (pattern instanceof RegExp ? pattern.test(content) : content.includes(pattern)));
}

function countOccurrences(content, pattern) {
  return (content.match(new RegExp(pattern, "g")) ?? []).length;
}

function appearsAfter(path, earlier, later) {
  const content = files[path] ?? "";
  const earlierIndex = content.indexOf(earlier);
  const laterIndex = content.indexOf(later);
  return earlierIndex >= 0 && laterIndex > earlierIndex;
}

const workbenchClient = files["src/api/workbenchClient.ts"] ?? "";
const workbenchApiClient = files["src/api/workbenchApiClient.ts"] ?? "";
const workbenchNormalizers = files["src/api/workbenchNormalizers.ts"] ?? "";
const workbenchOperationNormalizers = files["src/api/workbenchOperationNormalizers.ts"] ?? "";
const workbenchNormalizerUtils = files["src/api/workbenchNormalizerUtils.ts"] ?? "";
const workbenchContracts = files["src/api/contracts.ts"] ?? "";
const advancedClient = files["src/api/advancedWorkbenchClient.ts"] ?? "";
const advancedContracts = files["src/api/advancedContracts.ts"] ?? "";
const advancedPanels = files["src/components/AdvancedPanels.tsx"] ?? "";
const chapterMaterialPanel = files["src/components/ChapterMaterialPanel.tsx"] ?? "";
const libraryWorkbenchPanel = files["src/components/LibraryWorkbenchPanel.tsx"] ?? "";
const mainApp = files["src/main.tsx"] ?? "";
const libraryPage = files["src/pages/LibraryPage.tsx"] ?? "";
const libraryWorkflow = files["src/hooks/useLibraryMaterialWorkflow.ts"] ?? "";
const librarySurface = `${libraryPage}\n${libraryWorkbenchPanel}\n${libraryWorkflow}`;
const workbenchView = files["src/components/WorkbenchView.tsx"] ?? "";
const appShellSurface = `${mainApp}\n${workbenchView}`;
const appSidebar = files["src/components/AppSidebar.tsx"] ?? "";
const styles = files["src/styles.css"] ?? "";
const workbenchShell = files["src/domain/workbenchShell.ts"] ?? "";
const workbenchStateHook = files["src/hooks/useWorkbenchState.ts"] ?? "";
const workbenchOperationsHook = files["src/hooks/useWorkbenchOperations.ts"] ?? "";
const workbenchExportsHook = files["src/hooks/useWorkbenchExports.ts"] ?? "";
const workbenchReviewsHook = files["src/hooks/useWorkbenchReviews.ts"] ?? "";
const workbenchModelsHook = files["src/hooks/useWorkbenchModels.ts"] ?? "";
const workbenchMaterialsHook = files["src/hooks/useWorkbenchMaterials.ts"] ?? "";
const workbenchChaptersHook = files["src/hooks/useWorkbenchChapters.ts"] ?? "";
const workbenchActions = files["src/domain/workbenchActions.ts"] ?? "";
const appActionSurface = `${mainApp}\n${workbenchOperationsHook}\n${workbenchExportsHook}\n${workbenchReviewsHook}\n${workbenchModelsHook}\n${workbenchMaterialsHook}\n${workbenchChaptersHook}`;
const writingWorkflow = files["src/hooks/useWritingChapterWorkflow.ts"] ?? "";
const writingPage = files["src/pages/WritingPage.tsx"] ?? "";
const writingSurface = `${writingPage}\n${writingWorkflow}\n${chapterMaterialPanel}`;
const ordinaryClientSurface = `${workbenchClient}\n${workbenchApiClient}\n${workbenchContracts}`;
const networkFiles = new Set(["src/api/workbenchApiClient.ts", "src/api/advancedWorkbenchClient.ts"]);
const uiEntries = Object.entries(files).filter(([path]) => path.startsWith("src/pages/") || path.startsWith("src/components/") || path === "src/main.tsx");
const blockedAdvancedContractFields = /\b(path|source|log|logs|prompt|output|raw|token|password|secret|bearer|jobId|runId|eventId|evidence)\s*:/i;
const blockedAdvancedPanelControls = /\b(Form|Select|Modal|Drawer|Popconfirm|Checkbox|Radio|Switch|Upload|DatePicker|TreeSelect|Cascader|Slider)\b/;
const blockedOrdinaryImplementationCopy = [
  "后端已预留",
  "mock 环境",
  "mock 准备",
  "等待后台执行",
  "本机已安装 codex CLI",
  "新章节占位",
  "开场占位",
  "项目已注册",
  "已注册的写作模型"
];
const checks = [
  ["workbench client is api-only with no mock or auto branch", ["apiWorkbenchClient", "workbenchClientMode", "export const workbenchClient"].every((text) => workbenchClient.includes(text)) && !["mock", "auto", "VITE_WORKBENCH_CLIENT", "workbenchMockClient", "../dev/", "Falling back to mock"].some((text) => workbenchClient.includes(text))],
  ["mock implementation files are removed", ["src/dev/workbenchMockClient.ts", "src/dev/workbenchMockOperations.ts", "src/dev/workspace.ts", "src/dev/mockData.ts", "src/dev/mockAgent.ts", "src/api/workbenchMockClient.ts", "src/api/workbenchMockOperations.ts", "src/api/workspace.ts", "src/mockData.ts"].every((path) => !files[path])],
  ["api workbench implementation lives outside mode selector", workbenchApiClient.includes("export const apiWorkbenchClient") && workbenchClient.includes("import { ApiRequestError, apiWorkbenchClient }") && !workbenchClient.includes("const apiWorkbenchClient") && !/\bfetch\s*\(/.test(workbenchClient)],
  ["api workbench client does not import mock data directly", ["../mockData", "buildNewBookBundle", "buildNextChapter", "buildMockMaterialCandidate"].every((text) => !workbenchApiClient.includes(text))],
  ["api write responses normalize with request-scoped fallbacks", ["normalizeCreateBookResponse", "normalizeMaterialMutationResponse", "normalizeDeleteMaterialResponse", "normalizeSetBookModelResponse", "normalizeChapterDraftResponse", "normalizeChapterPlanningResponse", "normalizeLinkChapterMaterialsResponse", "normalizeAcceptChapterResponse", "normalizeCreateNextChapterResponse"].every((text) => workbenchNormalizers.includes(text) && workbenchApiClient.includes(text)) && ["return { ...response, chapter: normalizeChapter", "return { material: normalizeMaterial(response.material)", "return request<SetBookModelResponse>"].every((text) => !workbenchApiClient.includes(text))],
  ["workbench client contract lives in contracts module", workbenchContracts.includes("export type WorkbenchClient") && workbenchClient.includes("WorkbenchClient") && workbenchApiClient.includes("WorkbenchClient") && !workbenchClient.includes("export type WorkbenchClient")],
  ["workbench client covers first-version API methods", requiredClientMethods.every((method) => ordinaryClientSurface.includes(method))],
  ["workbench api client covers first-version API paths", requiredClientPaths.every((path) => workbenchApiClient.includes(path))],
  ["new book config falls back to local safe options", workbenchNormalizers.includes("bookCreationOptions") && workbenchNormalizers.includes("normalizeCreationOptions") && workbenchNormalizers.includes("!options?.platformStyles?.length") && workbenchNormalizers.includes("!options?.genres?.length")],
  ["agent assist responses are normalized before UI", ["normalizeAgentAssistResponse", "safeAgentText", "agentInternalLinePattern", "normalizeAgentTextList"].every((text) => workbenchNormalizers.includes(text)) && workbenchApiClient.includes("return normalizeAgentAssistResponse(response)") && !workbenchApiClient.includes("return request<AgentAssistResponse>(\"/api/agent/assist\"")],
  ["accept blocked detail is normalized before UI", ["normalizeAcceptChapterBlockedDetail", "normalizeChapterGateRecoveryResponse(candidate.recovery", "message: safeDisplayText(candidate.message)", "status: \"block\""].every((text) => workbenchNormalizers.includes(text)) && ["const blockedDetail = normalizeAcceptChapterBlockedDetail", "throw new ApiRequestError(error.message, error.status, blockedDetail)"].every((text) => workbenchApiClient.includes(text))],
  ["api error messages are sanitized before toast display", ["safeDisplayText(data.detail)", "safeDisplayText(data.detail.message)"].every((text) => workbenchApiClient.includes(text))],
  ["normalizers translate backend action codes", ["authorActionLabels", "safeAuthorActionText", "review-readiness-warnings-before-drafting", "ready-to-accept", "review-post-chapter-summary", "recommendedNextAction: safeAuthorActionText(response.readiness?.recommendedNextAction", "recommendedNextAction: safeAuthorActionText(gate?.recommendedNextAction"].every((text) => workbenchNormalizers.includes(text)) && !workbenchNormalizers.includes("recommendedNextAction: safeDisplayText(gate?.recommendedNextAction")],
  ["model normalizer hides backend model implementation terms", ["function safeModelText", "项目模型", "已找到模型调用配置。", "写作工具可用。", "模型文件暂不可用，验证未通过。", "normalizeModelTextList(result.checks)", "recommendedNextAction: safeModelActionText"].every((text) => workbenchNormalizers.includes(text)) && !["recommendedNextAction: safeDisplayText(model.recommendedNextAction", "(result.checks ?? []).map(safeDisplayText)", "sourceLabel: safeDisplayText(model.sourceLabel"].some((text) => workbenchNormalizers.includes(text))],
  ["operation normalizers own export jobs and runs responses", ["normalizeExportCheckResponse", "normalizeExportGenerateResponse", "normalizeJobsResponse", "normalizeJobDetailResponse", "normalizeJobEventsResponse", "normalizeJobMutationResponse", "normalizeRunsResponse", "firstVersionExportKinds"].every((text) => workbenchOperationNormalizers.includes(text)) && ["normalizeExportCheckResponse", "normalizeJobsResponse", "normalizeRunsResponse", "firstVersionExportKinds"].every((text) => !workbenchNormalizers.includes(text))],
  ["normalizer utilities own shared sanitizers", ["export function safeDisplayText", "export function asArray", "export function normalizeStringList", "export function normalizePercent"].every((text) => workbenchNormalizerUtils.includes(text)) && ["export function safeDisplayText", "export function asArray", "function normalizeStringList", "function normalizePercent"].every((text) => !workbenchNormalizers.includes(text))],
  ["workbench client does not expose advanced first-version methods", blockedClientMethods.every((method) => !ordinaryClientSurface.includes(method))],
  ["workbench client does not call advanced first-version paths", blockedClientPaths.every((path) => !workbenchApiClient.includes(path))],
  ["advanced client only calls approved scoped paths", approvedAdvancedPaths.every((path) => advancedClient.includes(path)) && blockedAdvancedPaths.every((path) => !advancedClient.includes(path))],
  ["advanced path policy is explicit and conflict-free", approvedAdvancedPaths.length > 0 && blockedAdvancedPaths.length > 0 && approvedAdvancedPaths.every((path) => !blockedAdvancedPaths.includes(path))],
  ["advanced client owns all advanced network requests", advancedClient.includes("advancedWorkbenchClient") && ["fetchModelTrainingReadiness", "fetchLibraryRelationships", "fetchLibraryRelationshipDetail", "fetchLibraryTimeline", "fetchDiffSummary", "fetchDiagnostics"].every((method) => advancedClient.includes(method))],
  ["ordinary pages do not import advanced client directly", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("advancedWorkbenchClient"))],
  ["ordinary pages avoid backend implementation wording", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("后端"))],
  ["ordinary pages avoid background implementation wording", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("后台"))],
  ["ordinary pages avoid local path wording", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("本地路径"))],
  ["ordinary pages avoid versioned product wording", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("当前版本"))],
  ["ordinary pages avoid mixed brief wording", !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && /\bbrief\b/i.test(content))],
  ["ordinary source avoids implementation-flavored visible copy", !Object.values(files).some((content) => blockedOrdinaryImplementationCopy.some((text) => content.includes(text)))],
  ["advanced panels are attached only as scoped page panels", !has("src/pages/ModelPage.tsx", "AdvancedPanels") && has("src/pages/LibraryPage.tsx", "LibraryRelationshipsPanel") && has("src/pages/MorePage.tsx", "BookDiagnosticsPanel") && has("src/pages/MorePage.tsx", "BookDiffSummaryPanel")],
  ["advanced panels are collapsed by default", has("src/components/AdvancedPanels.tsx", "useState(false)") && has("src/components/AdvancedPanels.tsx", "高级 · 只读")],
  ["advanced panels load only after opening", advancedPanels.includes("if (!open || data || loading || requested)") && countOccurrences(advancedPanels, "onLoadRef\\.current\\(\\)") === 1],
  ["advanced panels do not auto-retry failed loads", advancedPanels.includes("requested") && advancedPanels.includes("setRequested(true)") && advancedPanels.includes("setRequested(false)")],
  ["advanced panels allow manual retry after failure", advancedPanels.includes("retryLoad") && countOccurrences(advancedPanels, "重试") >= 2 && advancedPanels.includes("loadDetail(selectedEdge)") && advancedPanels.includes("setRequested(false)")],
  ["advanced panels reset cached data when book changes", advancedPanels.includes("resetKey") && advancedPanels.includes("setData(null)") && advancedPanels.includes("[resetKey]") && countOccurrences(advancedPanels, "resetKey=\\{bookId\\}") === 6],
  ["advanced panels keep lists summary-sized", ["slice(0, 5)", "slice(0, 6)", "slice(0, 4)", "Math.min(item.evidenceCount, 2)"].every((text) => advancedPanels.includes(text)) && advancedPanels.includes("data.items.slice(0, 6)")],
  ["advanced panels sanitize visible status text", advancedPanels.includes("statusLabel(data.status)") && advancedPanels.includes("statusLabel(item.gateStatus)")],
  ["advanced panels avoid backend implementation wording", !advancedPanels.includes("后端")],
  ["advanced panels avoid high-risk action copy", !blockedAdvancedActionCopy.some((text) => advancedPanels.includes(text))],
  ["advanced panels limit editing to relationship labels", !blockedAdvancedPanelControls.test(advancedPanels) && ["updateLibraryRelationshipEvent", "编辑标签", "保存关系标签", "关系类型，例如竞争、同盟、亲情"].every((text) => advancedPanels.includes(text))],
  ["ordinary UI avoids fake advanced placeholders", !uiEntries.some(([, content]) => blockedAdvancedPlaceholderCopy.some((text) => content.includes(text)))],
  ["ordinary UI avoids high-risk advanced actions", !uiEntries.some(([, content]) => blockedAdvancedActionCopy.some((text) => content.includes(text)))],
  ["relationship detail stays inside advanced library panel", has("src/components/AdvancedPanels.tsx", "fetchLibraryRelationshipDetail") && has("src/components/AdvancedPanels.tsx", "关系详情") && !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("fetchLibraryRelationshipDetail"))],
  ["relationship detail ignores stale detail requests", ["detailRequestRef", "useRef(0)", "detailRequestRef.current === requestId"].every((text) => has("src/components/AdvancedPanels.tsx", text))],
  ["relationship detail does not keep raw review summary", !advancedClient.includes("reviewSummary") && !has("src/api/advancedContracts.ts", "reviewSummary")],
  ["relationship detail hides raw evidence strings", has("src/components/AdvancedPanels.tsx", "证据 {Math.min(item.evidenceCount, 2)} 条") && !has("src/components/AdvancedPanels.tsx", "authorText(item.evidence")],
  ["advanced contracts avoid raw backend fields", !blockedAdvancedContractFields.test(advancedContracts)],
  ["timeline stays read-only inside advanced library panel", has("src/components/AdvancedPanels.tsx", "fetchLibraryTimeline") && has("src/components/AdvancedPanels.tsx", "资料时间线摘要") && !has("src/components/AdvancedPanels.tsx", "syncLibraryTimeline") && !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("fetchLibraryTimeline"))],
  ["timeline data does not keep source paths", !advancedPanels.includes("event.source") && !advancedClient.includes("event.source") && !has("src/api/advancedContracts.ts", "source: string")],
  ["diff stays summary-only inside advanced more panel", has("src/components/AdvancedPanels.tsx", "fetchDiffSummary") && has("src/components/AdvancedPanels.tsx", "候选差异摘要") && !has("src/components/AdvancedPanels.tsx", "data.diff") && !Object.entries(files).some(([path, content]) => path.startsWith("src/pages/") && content.includes("fetchDiffSummary"))],
  ["advanced panels use author-facing chapter labels", ["chapterLabel: string", "chapterLabel(data.chapterId)", "chapterLabel(event.chapterId)", "authorText(data.chapterLabel || \"-\")", "authorText(edge.chapterLabel || \"-\")"].every((text) => any(text)) && !has("src/components/AdvancedPanels.tsx", "chapterId || \"-\"")],
  ["advanced client redacts secrets and local absolute paths", ["[已隐藏敏感内容]", "[已隐藏本地路径]", "token|password|secret|bearer", "\\/Users\\/", "\\/private\\/", "[A-Za-z]:\\\\"].every((text) => advancedClient.includes(text))],
  ["advanced client truncates long text", ["MAX_SAFE_TEXT_LENGTH", "text.length > MAX_SAFE_TEXT_LENGTH", "text.slice(0, MAX_SAFE_TEXT_LENGTH)"].every((text) => advancedClient.includes(text))],
  ["advanced client redacts error messages", ["return safeText(data.detail)", "return safeText(data.message)", "return safeText(response.statusText)"].every((text) => advancedClient.includes(text))],
  ["app shell sanitizes global error text", appShellSurface.includes("authorText") && !mainApp.includes("const errorMessage = error instanceof Error") && workbenchView.includes("description={authorText(pageError)}")],
  ["app shell sanitizes dynamic toast text", ["message.success(authorText(result.summary", "message.warning(authorText(`已取消：${result.job.title}`", "message.success(authorText(authorMessage ||"].every((text) => appActionSurface.includes(text))],
  ["app shell uses author language for review refresh toast", appActionSurface.includes("已更新审稿列表") && !appActionSurface.includes("审稿 inbox")],
  ["app shell sanitizes topbar book text", ["{authorText(activeBook.title)} · {authorText(activeBook.genre)} · {authorText(activeBook.updatedAt)}", "当前章节：{authorText(activeChapter.title)}"].every((text) => workbenchView.includes(text))],
  ["app shell clears loading only for the active action", ["function clearLoadingAction(key: string)", "setLoadingAction((current) => (current === key ? null : current))", "clearLoadingAction(key)", "const actionKey = `memory-updates-${cacheKey}`", "const actionKey = \"ops-refresh\""].every((text) => appActionSurface.includes(text)) && !appActionSurface.includes("setLoadingAction(null)")],
  ["app shell keeps workspace state in workbench state hook", ["export function useWorkbenchState", "const [books, setBooks]", "buildBookWorkspace", "applyWorkspaceState", "applyBookWorkspaceState", "activeBookIdRef.current = activeBook.id"].every((text) => workbenchStateHook.includes(text)) && ["const [books, setBooks]", "buildBookWorkspace", "function applyWorkspaceState", "function applyBookWorkspaceState"].every((text) => !mainApp.includes(text))],
  ["app shell restores the active book after refresh", ["ACTIVE_BOOK_STORAGE_KEY", "localStorage.getItem(ACTIVE_BOOK_STORAGE_KEY)", "localStorage.setItem(ACTIVE_BOOK_STORAGE_KEY, activeBook.id)"].every((text) => workbenchStateHook.includes(text))],
  ["app shell ignores stale book workspace sync after switching books", ["onlyIfActiveBookId?: string", "activeBookIdRef.current !== options.onlyIfActiveBookId", "onlyIfActiveBookId: requestBookId", "const shouldReportError = !options?.onlyIfActiveBookId || activeBookIdRef.current === options.onlyIfActiveBookId", "if (!shouldReportError)"].every((text) => mainApp.includes(text)) && ["const activeBookIdRef = useRef(activeBook.id)", "activeBookIdRef.current = activeBook.id"].every((text) => workbenchStateHook.includes(text))],
  ["app shell ignores stale book write sync after switching books", ["onlyIfActiveBookId: bookId", "activeBookIdRef.current === bookId", "fallback?.()"].every((text) => mainApp.includes(text))],
  ["app shell ignores stale book action failures after switching books", ["options?: { shouldReportError?: () => boolean }", "if (options?.shouldReportError?.() ?? true)", "shouldReportError: () => isCurrentBook(requestBookId)", "shouldReportError: () => activeBookIdRef.current === requestBookId", "shouldReportError: () => activeBookIdRef.current === update.bookId"].every((text) => any(text))],
  ["book write hooks avoid stale active selection and toasts", ["activeBookIdRef: RefObject<string>", "if (activeBookIdRef.current !== createdMaterial.bookId)", "if (activeBookIdRef.current !== updatedMaterial.bookId)", "function isCurrentBook(bookId: string)", "if (!isCurrentBook(result.bookId))", "if (activeBookIdRef.current !== result.bookId)", "if (activeBookIdRef.current !== result.bookId) {\n      return;\n    }\n    message.success(authorText(`${activeBook.title} 已切换到模型"].every((text) => any(text))],
  ["app shell scopes checked writing tasks by book and chapter", ["function chapterUiStateKey(bookId: string, chapterId: string)", "checkedTasks[chapterUiStateKey(activeBook.id, activeChapter.id)]", "[chapterUiStateKey(activeBook.id, activeChapter.id)]: tasks"].every((text) => mainApp.includes(text)) && !mainApp.includes("checkedTasks[activeChapter.id]") && !mainApp.includes("[activeChapter.id]: tasks")],
  ["app shell applies create response without stale workspace overwrite", ["generationState, authorMessage", "replaceBookWorkspaceItems(current, [generationState], book.id)", "setActiveBookId(book.id)", "activeBookIdRef.current = book.id", "setModuleKey(\"today\")"].every((text) => mainApp.includes(text)) && !mainApp.includes("syncWorkspaceAfterCreate")],
  ["app shell centralizes book write workspace resync", ["function syncBookWorkspaceAfterWrite", "syncBookWorkspaceState(bookId", "suppressErrorToast: true"].every((text) => mainApp.includes(text)) && appActionSurface.includes("syncBookWorkspaceAfterWrite(result.bookId") && countOccurrences(mainApp, "syncBookWorkspaceState\\(") === 3 && !mainApp.includes("syncBookWorkspaceState(result.bookId") && !mainApp.includes("syncBookWorkspaceState(createdMaterial.bookId") && !mainApp.includes("syncBookWorkspaceState(updatedMaterial.bookId")],
  ["app shell delegates pure fallback and action-key helpers", ["fallbackBook", "fallbackChapter", "groupExportsByBookId", "parseMaterialLinkAction", "parseModelAction", "exportSelectionKey", "selectWorkspaceState", "selectBookWorkspaceState", "replaceBookWorkspaceItems"].every((text) => workbenchShell.includes(text)) && ["function parseModelAction", "function parseMaterialLinkAction", "function groupExportsByBookId", "function selectWorkspaceState", "function selectBookWorkspaceState", "function replaceBookWorkspaceItems", "const fallbackBook"].every((text) => !mainApp.includes(text))],
  ["app shell delegates route rendering to workbench view", mainApp.includes("import { WorkbenchView }") && mainApp.includes("<WorkbenchView") && workbenchView.includes("export function WorkbenchView") && !mainApp.includes("lazy(() => import(") && !mainApp.includes("<AppSidebar")],
  ["app sidebar sanitizes book and chapter text", ["authorText(activeBook.title).slice(0, 1)", "authorText(activeBook.title)", "authorText(activeChapter.title)"].every((text) => appSidebar.includes(text))],
  ["chapter progress stages are centralized instead of hardcoded in workbench actions", ["progressForChapterStatus", "INITIAL_BOOK_PROGRESS"].every((text) => has("src/domain/workbenchActions.ts", text)) && ["待写: 0", "草稿: 10", "审阅: 90", "完成: 100"].every((text) => has("src/domain/chapterProgress.ts", text)) && !["progress: 5", "progress: 1"].some((text) => has("src/domain/workbenchActions.ts", text))],
  ["frontend never calls projects API directly", !any("/projects/")],
  ["frontend network requests stay in api clients", /\bfetch\s*\(/.test(workbenchApiClient) && /\bfetch\s*\(/.test(advancedClient) && !Object.entries(files).some(([path, content]) => !networkFiles.has(path) && /\b(fetch|XMLHttpRequest|axios)\s*\(/.test(content))],
  ["vite proxies workbench API in dev", ["127.0.0.1:8765", '"/api"', '"/health"', "VITE_WORKBENCH_API_BASE"].every((text) => has("vite.config.ts", text))],
  ["global IA starts with AI model, then shelf and public model library", has("src/components/AppSidebar.tsx", "globalItems") && ['key: "accounts", label: "AI 模型"', 'key: "shelf", label: "书架"', 'key: "model", label: "我的模型"'].every((text) => has("src/components/AppSidebar.tsx", text)) && appSidebar.indexOf('key: "accounts"') < appSidebar.indexOf('key: "shelf"')],
  ["book IA contains first-version book pages", ["today", "writing", "library", "review", "export", "more"].every((key) => has("src/components/AppSidebar.tsx", `key: "${key}"`))],
  ["page modules are lazy loaded", ["ShelfPage", "AIAccountsPage", "TodayPage", "WritingPage", "LibraryPage", "ReviewPage", "ExportPage", "MorePage", "ModelPage"].every((page) => workbenchView.includes(`lazy(() => import("../pages/${page}")`))],
  ["shared responsive tokens own workspace geometry", [":root", "--ui-sidebar-width: clamp(", "--ui-sidebar-collapsed-width: 72px", "--ui-topbar-height: 108px", "--ui-workspace-padding: 22px", "--ui-workspace-vertical-offset: 152px", "--ui-workspace-height:", "--ui-detail-column-min: 280px", "--ui-detail-column-max: 360px", "--ui-sticky-top: 22px"].every((text) => styles.includes(text))],
  ["desktop sidebar preserves its information hierarchy while adapting to low heights", ["open-novel-sidebar-collapsed", "收起左侧导航", "展开左侧导航", "is-collapsed", "sidebar-collapsed-actions", "book-switcher-eyebrow"].every((text) => appSidebar.includes(text)) && ["@media (min-width: 1081px) and (max-height: 1024px)", "@media (min-width: 1081px) and (max-height: 800px)", "@media (min-width: 1081px) and (max-height: 640px)", ".app-sidebar.is-collapsed", "var(--ui-sidebar-collapsed-width)", ".sidebar-link-meta"].every((text) => styles.includes(text)) && !["MoonOutlined", "SunOutlined", "isDarkMode", "onDarkModeChange"].some((text) => appSidebar.includes(text))],
  ["phase 4 keeps desktop and mobile workspace layouts stable", [".page-grid", "minmax(var(--ui-detail-column-min), var(--ui-detail-column-max))", ".writing-page-grid", "max-width: none", "clamp(340px, 21vw, 400px)", ".writing-workspace", "grid-template-columns: repeat(2, minmax(0, 1fr))", "@media (max-width: 1080px)", "grid-template-columns: 1fr"].every((text) => styles.includes(text))],
  ["phase 4 clamps dense list and material text", [".chapter-rail-title", ".material-summary-title", ".material-summary-text", ".material-summary-impact", ".more-item-title", ".job-event-text", "text-overflow: ellipsis", "-webkit-line-clamp: 2"].every((text) => styles.includes(text))],
  ["phase 4 keeps model and task metrics from deforming", [".model-list-side", "flex: 0 0 138px", ".job-progress-meter", ".more-item-actions", "flex: 0 0 auto"].every((text) => styles.includes(text))],
  ["phase 4 keeps mobile navigation compact", [".mobile-tabbar", "position: fixed", "grid-template-columns: repeat(5, minmax(0, 1fr))", "padding-bottom: calc(76px + env(safe-area-inset-bottom))"].every((text) => styles.includes(text))],
  ["phase 4 protects high-impact actions with confirmation", ["title: \"确认强制接收？\"", "title: \"确认还原草稿？\"", "title: authorText(`删除资料：${material.title}`)", "okButtonProps: { danger: true }"].every((text) => any(text)) && ["readPersistedDraft", "persistDraft(book.id, chapter.id, draftText, chapter.content)"].every((text) => writingWorkflow.includes(text))],
  ["shelf page sanitizes book summary text", ["{authorText(book.title)}", "{authorText(book.tagline)}", "{authorText(generationState?.nextAction || book.nextAction)}", "{authorText(book.updatedAt)}", "{authorText(activeBook.title)}", "{authorText(selectedGenerationState?.nextAction || activeBook.nextAction)}"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page shows per-book generation state", ["generationStates: GenerationState[]", "generationState?.nextAction || book.nextAction", "selectedGenerationState?.nextAction || activeBook.nextAction", "selectedGenerationState.stageLabel", "selectedGenerationState.interventionModeLabel", "generationStatusColor"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page sanitizes creation option text", ["label: authorText(style.label)", "optionRender={(option)", "{authorText(style.label)}", "{authorText(creationOptions.platformLabels[style.platform] ?? style.platform)}", "label: authorText(genre.label)"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page exposes all writing targets during guided creation", ["aria-label=\"全书目标章节数\"", "aria-label=\"每章目标字数\"", "aria-label=\"每个剧情段目标章节数\"", "每个剧情段约 {targetChaptersPerPlot} 章"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page preserves create draft on failure", ["作品创建失败，请稍后重试。", "await onCreateBook", "setCreateOpen(false)", "resetCreateDraft()"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page shows AI create failures in form", ["setFormError(\"作品创建配置还在加载，稍后再生成初始设定。\")", "AI 初始设定生成失败，请稍后重试。"].every((text) => has("src/pages/ShelfPage.tsx", text)) && !has("src/pages/ShelfPage.tsx", "message.error")],
  ["shelf page prevents AI fill while creating book", ["disabled={aiFilling || !creationReady", "disabled={!creationReady || createLoading}"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page uses guided creation with role-based generation", ["作品想法", "生成方式", "确认创建", "生成将使用“AI 模型”中的写作角色", "创建并生成方向"].every((text) => has("src/pages/ShelfPage.tsx", text)) && !["validateCreationModel", "validatedModelIds", "selectedModelId"].some((text) => has("src/pages/ShelfPage.tsx", text))],
  ["shelf page persists creation draft across model setup", ["CREATION_DRAFT_KEY", "readSavedCreationDraft", "saveCreationDraft", "sessionStorage.removeItem(CREATION_DRAFT_KEY)"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["generation page provides first-time candidate guidance", ["candidateGuideKey", "candidateGuide(artifact.artifactType)", "localStorage.getItem", "本阶段说明"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["shelf page cancels stale AI create draft fill", ["aiFillRequestRef.current += 1", "setAiFilling(false)", "if (aiFillRequestRef.current !== requestId || !createOpenRef.current)"].every((text) => has("src/pages/ShelfPage.tsx", text))],
  ["AI model first menu combines model schemes and accounts", ["accounts: \"AI 模型\"", "<AIAccountsPage />"].every((text) => workbenchView.includes(text)) && ["label: \"模型方案\"", "label: \"AI 账号\"", "模型方案与 AI 账号统一管理", "按文风选择"].every((text) => has("src/pages/AIAccountsPage.tsx", text))],
  ["public model library stays in its own global page", ["model: \"我的模型\"", "<ModelPage", "books={books}", "onModelChange={onModelChange}"].every((text) => workbenchView.includes(text)) && ["工作区公共模型", "新增模型", "上传文章", "从作品选择"].every((text) => has("src/pages/ModelPage.tsx", text))],
  ["public model library offers built-in genre and style templates", ["内置模板", "题材与风格起点", "openTemplate", "使用 ${template.name} 模板"].every((text) => has("src/pages/ModelPage.tsx", text)) && has("src/api/contracts.ts", "ModelLibraryTemplate")],
  ["AI model page explains role-based account routing", ["写作角色", "审核角色", "写作和审核角色已保存", "模型方案与 AI 账号统一管理"].every((text) => has("src/pages/AIAccountsPage.tsx", text))],
  ["AI account page supports both API protocols and account probing", ["Responses API", "Chat Completions API", "请求通道", "async function probeAccount", "拨测成功"].every((text) => has("src/pages/AIAccountsPage.tsx", text))],
  ["AI account form discovers models and probes before save", ["async function discoverModels", "discoverAIModels", "自动获取模型", "async function probeFormConfiguration", "拨测当前配置（发送 hi）", "maxContextK", "addonAfter=\"K\""].every((text) => has("src/pages/AIAccountsPage.tsx", text))],
  ["AI account page manages multiple accounts without exposing secrets", ["新增 AI 账号", "编辑 AI 账号", "Key 已保存", "留空表示继续使用已保存的 Key", "deleteAccount"].every((text) => has("src/pages/AIAccountsPage.tsx", text)) && !has("src/pages/AIAccountsPage.tsx", "OPEN_NOVEL_WORKBENCH_AGENT_ID")],
  ["AI account page displays per-call token and cache evidence", ["逐次调用记录", "Token 使用量", "缓存输入", "推理 Token", "originalEstimatedTokens", "usageSourceLabel"].every((text) => has("src/pages/AIAccountsPage.tsx", text))],
  ["model page uses upload-driven training without user commands", ["uploadModelSources", "addModelBookSources", "startModelLibraryTraining", "fetchModelTrainingBackends", "训练方式", "开始训练", "继续添加", "用于当前书"].every((text) => has("src/pages/ModelPage.tsx", text)) && !["训练命令", "推理命令模板", "输出目录", "baseModel"].some((text) => has("src/pages/ModelPage.tsx", text))],
  ["model page separates upload results and exposes model history", ["已添加", "未通过", "训练版本", "使用中的作品", "按分类筛选"].every((text) => has("src/pages/ModelPage.tsx", text))],
  ["model page supports default and custom categories", ["categoryId", "createModelCategory", "新增分类", "categories.map"].every((text) => has("src/pages/ModelPage.tsx", text))],
  ["training inspection actions report successful loads", ["successText=\"训练就绪检查已加载。\"", "successText=\"质量分布已加载。\"", "message.success(successText)"].every((text) => has("src/components/AdvancedPanels.tsx", text))],
  ["app shell delegates model actions to hook", ["import { useWorkbenchModels }", "} = useWorkbenchModels({"].every((text) => mainApp.includes(text)) && workbenchModelsHook.includes("export function useWorkbenchModels") && ["async function setBookModel", "async function validateModel", "validateModelProfiles(current, result)", "message.success(authorText(`模型验证完成"].every((text) => workbenchModelsHook.includes(text)) && ["async function setBookModel", "async function validateModel"].every((text) => !mainApp.includes(text))],
  ["today page contains task refresh failure locally", ["任务状态刷新失败", "description={authorText(tasksError)}", "Promise.resolve(onRefreshTasks()).catch(() => undefined)"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page localizes chapter creation failures", ["async function createChapterFromToday", "章节创建失败，请稍后重试。", "生成操作未完成", "await onCreateFirstChapter()"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page presents generation control surface", ["生成主控台", "生成流水线", "干预档位", "buildGenerationPipeline", "getInterventionMode"].every((text) => has("src/pages/TodayPage.tsx", text)) && ["label: \"生成\"", "today: \"生成主控台\""].every((text) => any(text))],
  ["generation page uses natural page flow without nested workspace scrolling", ["className=\"single-page generation-page\"", "className=\"today-grid generation-workspace-grid\"", "className=\"content-card generation-scroll-card\""].every((text) => has("src/pages/TodayPage.tsx", text)) && [".generation-page", "min-height: var(--ui-workspace-height)", ".generation-scroll-card > .ant-card-body", "overflow: visible"].every((text) => styles.includes(text)) && !styles.includes(".generation-page {\n  height: var(--ui-workspace-height)")],
  ["today page guides the active pipeline stage without pre-marking later work ready", ["当前只需处理：", "pipelineStageHelp", "status: \"未开始\"", "后续灰色步骤不会提前就绪"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page edits persisted project writing targets", ["作品写作参数", "onProjectPlanChange", "aria-label=\"全书目标章节数\"", "aria-label=\"每章目标字数\"", "aria-label=\"每个剧情段目标章节数\"", "保存作品参数"].every((text) => has("src/pages/TodayPage.tsx", text)) && ordinaryClientSurface.includes("updateProjectPlan") && workbenchApiClient.includes("/plan")],
  ["generation state is first-version workbench data", ["GenerationState", "generationStates", "generationState: GenerationState"].every((text) => workbenchContracts.includes(text) || workbenchStateHook.includes(text) || workbenchView.includes(text)) && ["normalizeGenerationState", "normalizeGenerationResponse", "generationStates: asArray(data.generationStates)"].every((text) => workbenchNormalizers.includes(text))],
  ["generation API covers current-version control actions", ["fetchGeneration", "setGenerationMode", "continueGeneration", "confirmGeneration", "pauseGeneration", "resumeGeneration", "takeoverGeneration"].every((method) => ordinaryClientSurface.includes(method)) && ["/generation", "/generation/mode", "/generation/continue", "/generation/confirm", "/generation/pause", "/generation/resume", "/generation/takeover"].every((path) => workbenchApiClient.includes(path))],
  ["generation page is driven by persisted generation state", ["generationState={activeWorkspace.generationState}", "onGenerationModeChange", "onGenerationContinue", "onGenerationConfirm", "onGenerationPause", "onGenerationResume", "onGenerationTakeover"].every((text) => workbenchView.includes(text)) && ["generationState.nextAction", "generationState.status", "generationState.stageLabel", "generationState.batchTarget", "getPrimaryGenerationAction"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page primary action starts architecture and blueprint", ["generationState.stage === \"architecture\"", "label: \"生成作品架构\"", "generationState.stage === \"blueprint\"", "label: \"生成章节蓝图\""].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page lets authors select a generated direction", ["generationState.candidateOptions.length", "<Radio.Group", "setSelectedDirectionId", "generationState.candidateOptions.map"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["generation page reviews every waiting candidate type", ["CandidateDecisionPanel", "CandidateDetail", "artifactTitle", "book_direction", "long_form_plan", "chapter_blueprint", "scene_contract", "chapter_draft"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["generation page keeps and compares candidate versions", ["候选版本", "比较版本", "候选版本比较", "onGenerationCandidateSelect", "versions.map"].every((text) => any(text))],
  ["generation page supports regeneration and guarded rollback", ["重新生成当前阶段候选？", "这份候选会保留", "返回上一个确认点？", "已有定稿章节时不会执行危险回退", "onGenerationRegenerate", "onGenerationRollback"].every((text) => any(text))],
  ["today page shows generation source and recovery state", ["generationState.sourceModelLabel", "label=\"本次模型\"", "generationState.recoverySummary", "label=\"恢复状态\""].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page shows first chapter creation loading", ["createFirstChapterLoading", "loading={createFirstChapterLoading}", "createFirstChapterLoading={loadingAction === \"chapter-next\"}"].every((text) => any(text))],
  ["today page primary action creates only missing or latest completed chapter", ["const latestChapter", "const shouldCreateChapter", "!book.chapters.length", "latestChapter?.id === chapter.id", "latestChapter.status === \"完成\"", "void createChapterFromToday()", "shouldCreateChapter && createFirstChapterLoading"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["today page primary action can prepare current chapter", ["const shouldPrepareChapter", "async function prepareChapterFromToday", "章节准备失败，请稍后重试。", "await onPrepareChapter()", "prepareChapterLoading={loadingAction === \"chapter-prepare\"}"].every((text) => any(text))],
  ["today page sanitizes next action text", ["{authorText(generationState.nextAction || nextStep.title)}", "{authorText(generationState.statusLabel)}", "{authorText(primaryAction.label)}", "{authorText(job.status)}", "开始于 {authorText(job.startedAt)}"].every((text) => has("src/pages/TodayPage.tsx", text))],
  ["writing page keeps chapter loop", ["准备本章", "AI 候选稿", "应用到草稿", "接收前检查", "强制接收", "开始下一章"].every((text) => has("src/pages/WritingPage.tsx", text))],
  ["writing page blocks next chapter until latest chapter is formally accepted", ["const canStartNextChapter", "disabled={!canStartNextChapter}", "当前章正式完稿并接收后，才能开始下一章"].every((text) => has("src/pages/WritingPage.tsx", text))],
  ["dense tab navigation wraps in narrow sidebars instead of hiding options", ["components/ScrollTabs", "className=\"writing-panel-tabs\"", "ariaLabel=\"章节辅助面板\"", "ariaLabel=\"资料类型\""].every((text) => any(text)) && [".writing-panel-tabs", "flex-wrap: wrap", "overflow: visible", ".material-type-tabs"].every((text) => styles.includes(text))],
  ["writing page uses a bounded desktop workbench and natural narrow-screen flow", ["className=\"page-grid writing-page-grid\"", "className=\"section-toolbar writing-toolbar\"", "className=\"side-column writing-side-column\"", "className=\"writing-side-scroll\"", "className=\"writing-pane-scroll writing-editor-scroll\"", "className=\"writing-pane-scroll writing-ai-scroll\""].every((text) => writingPage.includes(text)) && [".writing-page-grid", "height: var(--ui-workspace-height)", ".writing-pane-scroll", "overflow-y: auto", "@media (max-width: 1500px) and (min-width: 1081px)", "height: auto", "overflow: visible"].every((text) => styles.includes(text))],
  ["writing and library dense panels resist narrow-column deformation", ["chapter-sync-status", "char-count-summary", "chapter-prepare-head"].every((text) => writingPage.includes(text)) && ["memory-inspection-head", "memory-inspection-stats"].every((text) => libraryPage.includes(text)) && advancedPanels.includes("advanced-panel-head") && [".chapter-sync-status", "white-space: nowrap", ".char-count-hint", "width: 100%", ".memory-inspection-kanban", "grid-template-columns: 1fr", ".advanced-panel-head"].every((text) => styles.includes(text))],
  ["writing editor avoids oversized empty height for short chapters", writingPage.includes("autoSize={{ minRows: screens.md ? 5 : 3, maxRows: 24 }}") && styles.includes(".editor-actions > .ant-typography") && styles.includes("flex: none")],
  ["plot direction belongs to the creative tab instead of repeating below every panel", appearsAfter("src/pages/WritingPage.tsx", "创意: (", "<PlotDirectionPanel") && appearsAfter("src/pages/WritingPage.tsx", "<PlotDirectionPanel", "<IdeationPanel") && countOccurrences(writingPage, "<PlotDirectionPanel") === 1],
  ["AI writing actions live in the candidate pane while the right column stays reference-only", ["className=\"writing-candidate-pane\"", "className=\"content-card candidate-card writing-ai-workbench\"", "className=\"writing-ai-footer writing-pane-footer\"", "className=\"writing-ai-actions\"", "className=\"writing-ai-action-wide\""].every((text) => writingPage.includes(text)) && !writingPage.includes("writing-ai-assistant") && appearsAfter("src/pages/WritingPage.tsx", "className=\"writing-ai-actions\"", "className=\"side-column writing-side-column\"") && [".writing-ai-workbench", ".writing-ai-footer", ".writing-ai-actions", "grid-template-columns: repeat(2, minmax(0, 1fr))"].every((text) => styles.includes(text))],
  ["library page adapts column width without forcing a nested sidebar scroller", ["page-grid library-page-grid", "library-workbench-open", "className=\"main-column library-main-column\"", "className=\"side-column library-side-column\"", "className=\"library-memory-scroll\"", "className=\"library-workbench-fixed\""].every((text) => libraryPage.includes(text)) && [".library-page-grid", "clamp(300px, 24vw, 360px)", ".library-page-grid.library-workbench-open", "clamp(380px, 31vw, 460px)", ".library-side-column", "position: sticky", "overflow: visible", "minmax(280px, 320px)"].every((text) => styles.includes(text)) && !styles.includes(".library-side-column {\n  min-width: 0;\n  min-height: 0;\n  max-height: var(--ui-workspace-height)")],
  ["review export more and shelf share a natural-flow detail layout", ["src/pages/ReviewPage.tsx", "src/pages/ExportPage.tsx", "src/pages/MorePage.tsx"].every((path) => has(path, "className=\"page-grid responsive-detail-page")) && has("src/pages/ShelfPage.tsx", "page-grid shelf-grid") && [".responsive-detail-page", ".shelf-grid", ".shelf-grid-empty", ".responsive-detail-page > .side-column", ".shelf-detail-column", "position: static", "overflow: visible"].every((text) => styles.includes(text))],
  ["browser regression audits every primary page at responsive desktop and mobile widths", ["all primary pages stay inside the workspace across responsive viewports", "1280", "1100", "1024", "390", "ui-audit", "document.documentElement.scrollWidth", "assertNoLayoutScrollers", ".responsive-detail-page > .side-column", ".library-side-column", ".writing-side-column"].every((text) => workbenchE2e.includes(text))],
  ["writing lessons and legacy material labels stay Chinese", ["statusLabel(group.category, \"写作经验\")", "statusLabel(lesson.severity || \"lesson\", \"写作经验\")"].every((text) => writingPage.includes(text)) && ["high: \"高优先级\"", "continuity: \"连续性\"", "emotion: \"情绪\"", "return statusLabels[text.toLowerCase()] ?? (/"].every((text) => has("src/utils/statusLabel.ts", text)) && libraryWorkbenchPanel.includes("materialDetailLabel(material.type, label, index)") && has("src/components/MaterialSummaryBlock.tsx", "statusLabel(material.title, authorText(material.title))")],
  ["dense book and material collections paginate without stale material detail", ["pagedBooks.map", "className=\"book-grid-pagination\"", "pagedMaterials.map", "className=\"material-list-pagination\"", "pagedMaterials.find"].every((text) => any(text))],
  ["shared metric DSL keeps repeated page summaries responsive", ["export type MetricGridItem", "export function MetricGrid", "metric-grid-compact"].every((text) => has("src/components/shared.tsx", text) || styles.includes(text)) && ["<MetricGrid items={[", "<MetricGrid compact items={["].every((text) => any(text)) && [".metric-grid", "repeat(2, minmax(0, 1fr))"].every((text) => styles.includes(text))],
  ["wide workspaces stay readable and model columns do not stretch to match detail height", [".page-grid", "max-width: 1720px", ".model-library-layout", "align-items: start"].every((text) => styles.includes(text))],
  ["chapter planning stays user-facing while internal contract fields remain stable", ["章节规划", "保存章节规划", "应用到章节规划"].every((text) => any(text)) && !["章节合同", "当前章合同", "应用到合同", "场景契约", "弧线合同"].some((text) => any(text))],
  ["writing page labels deep chapter planning fields", ["aria-label={contractFieldLabels[key]}", "保存章节规划"].every((text) => writingPage.includes(text))],
  ["writing page delegates chapter workflow hook", ["useWritingChapterWorkflow", "} = useWritingChapterWorkflow({"].every((text) => writingPage.includes(text)) && writingWorkflow.includes("export function useWritingChapterWorkflow") && !writingPage.includes("candidateRequestRef") && !writingPage.includes("buildChapterAssistContext")],
  ["writing gate survives chapter review status sync", ["}, [book.id, chapter.id]);", "const serverContentRef = useRef(chapter.content);", "current === previousContent ? chapter.content : current", "}, [chapter.content]);", "setPrepared(chapter.status !== \"待写\");", "}, [chapter.status]);"].every((text) => writingWorkflow.includes(text)) && !writingWorkflow.includes("[chapter.id, chapter.content, chapter.status]")],
  ["writing page localizes prepare failures", ["章节准备失败，请稍后重试。", "onPrepareChapter()", "setPrepared(result.readiness.status !== \"block\")"].every((text) => writingWorkflow.includes(text))],
  ["writing page localizes candidate generation failures", ["AI 候选生成失败，请稍后重试。", "streamAgentAssist", "setActionError(authorText"].every((text) => writingWorkflow.includes(text))],
  ["writing page ignores stale same-chapter candidate requests", ["candidateRequestRef", "candidateRequestRef.current = requestId", "candidateRequestRef.current !== requestId", "candidateRequestRef.current === requestId"].every((text) => writingWorkflow.includes(text))],
  ["writing page prevents parallel candidate generation actions", ["function isCandidateActionDisabled", "disabled={isCandidateActionDisabled(\"续写\")}", "disabled={isCandidateActionDisabled(\"润色\")}", "disabled={isCandidateActionDisabled(\"冲突\")}", "disabled={isCandidateActionDisabled(\"整章\")}", "disabled={isCandidateActionDisabled(lastCandidateKind)}"].every((text) => writingSurface.includes(text))],
  ["writing page localizes draft save failures", ["async function saveDraft", "草稿保存失败，请稍后重试。", "await onSaveDraft(draftText)", "contextRef.current.bookId"].every((text) => writingWorkflow.includes(text))],
  ["writing page confirms draft restore before discarding edits", ["function discardDraftChanges", "确认还原草稿？", "恢复为最近一次同步的正文", "onClick={discardDraftChanges}"].every((text) => writingSurface.includes(text))],
  ["writing page scopes draft loading per operation", ["pendingDraftAction", "loading={applyLoading && pendingDraftAction === \"save\"}", "loading={applyLoading && pendingDraftAction === \"apply\"}", "chapter-draft-save", "chapter-draft-apply"].every((text) => any(text)) && !has("src/pages/WritingPage.tsx", "onClick={() => void saveDraft()} loading={applyLoading}") && !has("src/main.tsx", "runAction(\"chapter-draft\"")],
  ["writing page localizes next chapter failures", ["async function createNextChapter", "await onCreateNextChapter()", "开始下一章失败，请稍后重试。"].every((text) => writingWorkflow.includes(text))],
  ["chapter derived writes keep local state when book sync fails", ["export function upsertChapterInBooks", "export function markChapterReviewingInBooks"].every((text) => workbenchActions.includes(text)) && ["upsertChapterInBooks(current, requestBookId, nextChapter)", "markChapterReviewingInBooks(current, result.bookId, result.chapterId)"].every((text) => workbenchChaptersHook.includes(text)) && workbenchReviewsHook.includes("markChapterReviewingInBooks(current, result.bookId, result.chapterId)")],
  ["writing page preserves candidate on apply failure", ["候选应用失败，请稍后重试。", "章节操作未完成", "await onApplyCandidate(nextContent)"].every((text) => writingSurface.includes(text))],
  ["writing page applies candidate locally only after save succeeds", writingWorkflow.indexOf("await onApplyCandidate(nextContent)") >= 0 && writingWorkflow.indexOf("setDraftText(nextContent)") > writingWorkflow.indexOf("await onApplyCandidate(nextContent)")],
  ["writing page localizes gate and accept failures", ["接收前检查失败，请稍后重试。", "修复建议加载失败，请稍后重试。", "章节接收失败，请稍后重试。"].every((text) => writingWorkflow.includes(text))],
  ["writing page separates hard blocks repairs and risk references", ["硬阻断", "建议修复", "风险参考", "仅供判断风险，不单独阻止接收", "dialogue_ratio_out_of_range", "scene_switch_too_frequent", "anti_ai_trace"].every((text) => writingPage.includes(text))],
  ["writing page separates gate check and accept loading", has("src/pages/WritingPage.tsx", "loading={gateLoading} onClick={openGatePanel}") && !has("src/pages/WritingPage.tsx", "loading={gateLoading || acceptLoading}")],
  ["writing page scopes chapter accept loading per action", ["acceptAction", "loading={acceptAction === \"normal\"}", "loading={acceptAction === \"force\"}", "chapter-accept-normal", "chapter-accept-force", "function parseAcceptAction"].every((text) => any(text)) && !mainApp.includes("runAction(\"chapter-accept\"")],
  ["app shell delegates chapter actions to hook", ["import { useWorkbenchChapters }", "} = useWorkbenchChapters({"].every((text) => mainApp.includes(text)) && workbenchChaptersHook.includes("export function useWorkbenchChapters") && ["async function applyChapterDraft", "async function saveChapterDraft", "async function acceptChapter", "async function createNextChapter", "async function updateChapterPlanning", "async function prepareChapter", "async function checkChapterGate", "async function linkChapterMaterials"].every((text) => workbenchChaptersHook.includes(text)) && ["async function applyChapterDraft", "async function saveChapterDraft", "async function acceptChapter", "async function createNextChapter", "async function updateChapterPlanning", "async function prepareChapter", "async function checkChapterGate", "async function linkChapterMaterials"].every((text) => !mainApp.includes(text))],
  ["writing page uses author language for forced accept prompt", writingWorkflow.includes("当前接收前检查仍有提示项。") && !writingSurface.includes("当前 gate 仍有提示项。")],
  ["writing page review reminders can open review center", ["function ReviewReminder", "审稿提醒", "进入审稿中心", "onOpenReview={onOpenReview}", "onClick={onOpenReview}"].every((text) => writingPage.includes(text))],
  ["writing page localizes candidate copy failures", ["async function copyCandidate", "候选复制失败，请稍后重试。", "setActionError(authorText"].every((text) => writingWorkflow.includes(text))],
  ["writing page avoids raw recovery target fields", has("src/pages/WritingPage.tsx", "target.label || \"相关位置\"") && !has("src/pages/WritingPage.tsx", "target.label || target.field")],
  ["writing page sanitizes chapter and candidate text", ["{authorText(item.title)}", "{authorText(item.status)}", "text={authorText(chapter.status)}", "{authorText(chapter.title)}", "来源：{authorText(candidateSource)}", "description={authorText(`来源动作：${candidateSource}", "{authorText(paragraph)}"].every((text) => has("src/pages/WritingPage.tsx", text)) && ["title: authorText(`删除资料：${material.title}`)", "editing ? authorText(editing.title)"].every((text) => chapterMaterialPanel.includes(text))],
  ["writing page delegates chapter material panel", has("src/pages/WritingPage.tsx", "import { ChapterMaterialPanel }") && !has("src/pages/WritingPage.tsx", "function ChapterMaterialPanel") && has("src/components/ChapterMaterialPanel.tsx", "export function ChapterMaterialPanel")],
  ["writing page localizes chapter material failures", ["章节资料保存失败，请稍后重试。", "章节资料关联失败，请稍后重试。", "章节资料删除失败，请稍后重试。", "章节资料操作未完成"].every((text) => chapterMaterialPanel.includes(text))],
  ["writing page scopes chapter material save loading", ["materialSaveAction", "editorSaveLoading", "saveLoading={editorSaveLoading}", "MaterialSaveAction"].every((text) => chapterMaterialPanel.includes(text) || has("src/types.ts", text))],
  ["writing page scopes chapter material link loading", ["materialLinkAction", "loading={materialLinkAction?.mode === \"append\" && materialLinkAction.materialIds.includes(material.id)}", "MaterialLinkAction"].every((text) => chapterMaterialPanel.includes(text) || has("src/types.ts", text))],
  ["writing page scopes chapter material delete loading", ["materialDeleteAction", "loading={materialDeleteAction?.materialId === material.id}", "MaterialDeleteAction", "parseMaterialDeleteAction"].every((text) => any(text))],
  ["writing page disables already linked material action", ["disabled={linkedSet.has(material.id)}", "已纳入当前章节"].every((text) => chapterMaterialPanel.includes(text))],
  ["writing page resets chapter material state on book or chapter switch", ["queryKey: [\"chapter-materials\", bookId, chapter.id, type, scope, materialVersion]", "enabled: scope === \"related\"", "setExpandedIds([])", "}, [bookId, chapter.id, scope, type]);", "setCreating(false)", "setEditing(null)", "}, [bookId, chapter.id]);"].every((text) => chapterMaterialPanel.includes(text))],
  ["writing page falls back to local materials when related materials fail", ["const relatedFallbackActive", "Boolean(relatedError)", "relatedFallbackActive ? typeMaterials : relatedMaterials", "已先显示本地同类资料"].every((text) => chapterMaterialPanel.includes(text))],
  ["shared task panel sanitizes planning text", ["planning-item-text", "{authorText(text)}"].every((text) => has("src/components/shared.tsx", text))],
  ["shared task rows keep narrow sidebars readable with one overflow action", ["Dropdown", "MoreOutlined", "aria-label={`${authorText(text)}操作`}"].every((text) => has("src/components/shared.tsx", text)) && !["EditOutlined", "DeleteOutlined", "planning-item-actions"].some((text) => has("src/components/shared.tsx", text))],
  ["shared task panel localizes planning failures", ["commitPlanning", "任务和剧情点保存失败，请稍后重试。", "章节规划未保存", "planningError"].every((text) => has("src/components/shared.tsx", text))],
  ["material summary component sanitizes material type", countOccurrences(files["src/components/MaterialSummaryBlock.tsx"] ?? "", "\\{authorText\\(material\\.type\\)\\}") === 2],
  ["library workflows exist in library and chapter pages", ["新增", "生成{props.materialType}", "编辑资料", "应用 AI 建议", "纳入当前章节"].every((text) => any(text))],
  ["library page keeps one clear material creation entry", !has("src/pages/LibraryPage.tsx", "新增{materialType}") && ["type=\"primary\"", "icon={<PlusOutlined />}", "新增{materialType}"].every((text) => has("src/components/LibraryWorkbenchPanel.tsx", text))],
  ["library secondary panels share a compact responsive grid", ["className=\"library-advanced-grid\"", "LibraryRelationshipsPanel", "LibraryTimelinePanel"].every((text) => libraryPage.includes(text)) && [".library-advanced-grid", "grid-template-columns: repeat(2, minmax(0, 1fr))", "@media (max-width: 1080px)", "grid-template-columns: 1fr"].every((text) => styles.includes(text))],
  ["shelf chapter selection avoids narrow-column tables and nested scrollbars", ["className=\"shelf-chapter-list\"", "className={`shelf-chapter-row ${checked ? \"selected\" : \"\"}`}", "type=\"checkbox\""].every((text) => has("src/pages/ShelfPage.tsx", text)) && !["Table", "scroll={{"].some((text) => has("src/pages/ShelfPage.tsx", text)) && [".shelf-chapter-list", ".shelf-chapter-row", "grid-template-columns: 18px minmax(0, 1fr)"].every((text) => styles.includes(text))],
  ["library page delegates right workbench panel", has("src/pages/LibraryPage.tsx", "LibraryWorkbenchPanel") && libraryWorkbenchPanel.includes("MaterialEditorForm") && libraryWorkbenchPanel.includes("AI 资料助手") && !has("src/pages/LibraryPage.tsx", "function MaterialAiWorkbench") && !has("src/pages/LibraryPage.tsx", "function MaterialEditor")],
  ["library page delegates material workflow hook", ["import { useLibraryMaterialWorkflow }", "} = useLibraryMaterialWorkflow({"].every((text) => libraryPage.includes(text)) && libraryWorkflow.includes("export function useLibraryMaterialWorkflow") && !libraryPage.includes("materialAiRequestRef") && !libraryPage.includes("parseRelated")],
  ["library page sanitizes chapter and material context text", ["authorText(`删除资料：${material.title}`)", "{authorText(activeChapter.title)} 当前筛出", "{authorText(material.type)}细节", "{authorText(props.aiSuggestion.type)}", "当前分类「${authorText(props.materialType)}」", "章节「${authorText(props.activeChapterTitle)}」", "{authorText(content)}"].every((text) => librarySurface.includes(text))],
  ["library page avoids raw linked material wording", librarySurface.includes("删除后会同步清理章节里引用它的资料，且不可恢复。") && !librarySurface.includes("linked materials")],
  ["library page localizes material action failures", ["资料保存失败，请稍后重试。", "资料关联到章节失败，请稍后重试。", "资料删除失败，请稍后重试。", "AI 资料生成失败，请稍后重试。", "AI 资料建议应用失败，请稍后重试。", "资料操作未完成"].every((text) => librarySurface.includes(text))],
  ["library page ignores stale AI material suggestions", ["materialAiRequestRef", "materialAiScopeRequestKey(bookId, activeChapter.id, materialType)", "isCurrentMaterialAiRequest(contextRef.current, requestKey, Boolean(target))", "materialAiRequestRef.current === requestId", "setAiSuggestion(null)", "materialId: activeMaterial?.id ?? \"\""].every((text) => libraryWorkflow.includes(text))],
  ["library page clears stale AI suggestion when no material candidate returns", ["if (!response.material)", "setAiSuggestion(null)", "AI 暂时没有返回可应用的资料候选，请调整想法后再试。"].every((text) => libraryWorkflow.includes(text)) && !libraryWorkflow.includes("message.warning(\"AI 暂时没有返回可应用的资料候选。\")")],
  ["library page keeps AI creation in the right workbench", ["setSideMode(\"ai\")", "AI 助手", "isAiActionDisabled={isMaterialAiActionDisabled}", "materialAiPlaceholder"].every((text) => librarySurface.includes(text)) && !libraryPage.includes("AI 新建{materialType}")],
  ["library material types wrap without a trailing scroll rail", ["library-material-toolbar", "material-type-tabs"].every((text) => libraryPage.includes(text)) && [".material-type-tabs", "flex-wrap: wrap", "overflow: visible", "background: transparent", ".library-material-toolbar .chapter-filter-toggle"].every((text) => styles.includes(text))],
  ["library page prevents parallel AI material generation actions", ["function isMaterialAiActionDisabled", "disabled={props.isActionDisabled(\"new\")}", "disabled={!props.visibleMaterial || props.isActionDisabled(\"improve\")}", "disabled={props.isActionDisabled(props.lastAiMode)}"].every((text) => librarySurface.includes(text))],
  ["library page keeps right workbench action-based", librarySurface.includes("library-workbench-actions") && !librarySurface.includes("value={sideMode}") && !librarySurface.includes("查看详情")],
  ["library page ignores stale AI material apply results", ["const isCurrentRequest = ()", "currentMaterialAiScopeRequestKey(contextRef.current) === requestKey", "if (!isCurrentRequest())", "function currentMaterialAiScopeRequestKey"].every((text) => libraryWorkflow.includes(text))],
  ["library page syncs active material to visible filtered item", ["if (visibleMaterial && activeMaterial?.id !== visibleMaterial.id)", "onMaterialChange(visibleMaterial.id)", "if (!visibleMaterial && activeMaterial?.id)", "onMaterialChange(\"\")"].every((text) => has("src/pages/LibraryPage.tsx", text))],
  ["library page scopes chapter material cache by book and chapter", ["const relatedKey = `${bookId}:${activeChapter.id}", "resetKey: `${bookId}:${activeChapter.id}"].every((text) => has("src/pages/LibraryPage.tsx", text)) && !has("src/pages/LibraryPage.tsx", "const relatedKey = `${activeChapter.id}") && !has("src/pages/LibraryPage.tsx", "resetKey: `${activeChapter.id}")],
  ["library page resets chapter material local state when book changes", ["setExpandedMaterialIds([])", "setChapterMaterialError(\"\")", "setChapterMaterialLoading(false)", "}, [activeChapter.id, bookId, currentChapterOnly, materialType, materialVersion, search]);"].every((text) => has("src/pages/LibraryPage.tsx", text))],
  ["library page scopes chapter-related material loading", ["chapterMaterialLoading", "setChapterMaterialLoading(true)", "setChapterMaterialLoading(false)", "正在整理当前章节相关资料", "if (!currentChapterOnly)"].every((text) => has("src/pages/LibraryPage.tsx", text))],
  ["library page falls back to local materials when related materials fail", ["const chapterRelatedFallbackActive", "Boolean(chapterMaterialError)", "chapterRelatedFallbackActive ? fallbackMaterials", "已先显示本地同类资料"].every((text) => has("src/pages/LibraryPage.tsx", text))],
  ["library page scopes material save loading by action", ["materialSaveAction", "editorSaveLoading", "aiApplyLoading", "material-create", "material-update-${material.id}", "startsWith(\"material-update-\")"].every((text) => any(text)) && !has("src/main.tsx", "loadingAction === \"material-save\"") && !has("src/pages/LibraryPage.tsx", "  saveLoading\n")],
  ["library page scopes material link loading by action", ["materialLinkAction", "replaceLinkLoading", "isMaterialLinking", "materialLinkKey", "parseMaterialLinkAction"].every((text) => any(text)) && !has("src/pages/LibraryPage.tsx", "linkLoading") && !has("src/main.tsx", "loadingAction === \"chapter-material-link\"")],
  ["library page disables replace-link when filtered list is empty", ["disabled={!filteredMaterials.length}", "当前筛选结果里没有可纳入本章的资料。"].every((text) => has("src/pages/LibraryPage.tsx", text))],
  ["library page provides three long-form planning views", ["label: \"全书\"", "label: \"当前卷\"", "label: \"章节落点\""].every((text) => libraryPage.includes(text))],
  ["library page edits future chapter landings", ["编辑章节落点", "updateChapterLanding", "landing.status === \"完成\""].every((text) => any(text))],
  ["library page compares replan before confirmation", ["label: \"重规划比较\"", "比较重规划", "确认重规划", "disabled={!replanResult?.candidate}"].every((text) => libraryPage.includes(text))],
  ["library page shows five evidence-based serial risks without scores", ["weak_hooks", "promise_pressure", "rhythm_imbalance", "character_stagnation", "volume_deviation"].every((text) => workbenchContracts.includes(text)) && ["证据章节", "样本不足"].every((text) => libraryPage.includes(text)) && !libraryPage.includes("risk.score")],
  ["library page scopes material delete loading by id", ["materialDeleteAction", "loading={materialDeleteAction?.materialId === item.id}", "deleteLoading={materialDeleteAction?.materialId === visibleMaterial.id}", "material-delete-${materialId}", "parseMaterialDeleteAction"].every((text) => any(text))],
  ["app shell delegates material actions to hook", ["import { useWorkbenchMaterials }", "} = useWorkbenchMaterials({"].every((text) => mainApp.includes(text)) && workbenchMaterialsHook.includes("export function useWorkbenchMaterials") && ["async function createMaterial", "async function updateMaterial", "async function deleteMaterial", "prependMaterial(current, createdMaterial)", "replaceMaterial(current, updatedMaterial)", "removeMaterial(current, materialId)"].every((text) => workbenchMaterialsHook.includes(text)) && ["async function createMaterial", "async function updateMaterial", "async function deleteMaterial"].every((text) => !mainApp.includes(text))],
  ["review page supports repair and memory update", ["AI 生成修复方案", "应用修复候选", "确认审稿项", "记忆更新候选", "重新审稿"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page supports batch operations", ["批量接受低风险建议", "批量确认选中", "批量应用修复", "selectedReviewIds", "confirmLowRiskReviews", "applySelectedRepairCandidates"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page shows author-readable repair comparison", ["buildRepairPreview", "review-repair-preview", "当前草稿末段", "建议修改为"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page localizes AI and repair failures", ["AI 解释失败，请稍后重试。", "AI 修复候选生成失败，请稍后重试。", "修复候选应用失败，请稍后重试。"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page scopes repair loading to active review", ["repairingReviewId", "loading={repairingReviewId === activeReview.id}", "review-repair-${review.id}", "startsWith(\"review-repair-\")"].every((text) => any(text)) && !has("src/pages/ReviewPage.tsx", "repairLoading")],
  ["review page ignores stale same-review AI requests", ["reviewAiRequestRef", "reviewAiRequestRef.current = requestId", "reviewAiRequestRef.current === requestId", "const isCurrentRequest = () => activeReviewIdRef.current === requestReviewId"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page prevents parallel AI review actions", ["function isReviewAiActionDisabled", "disabled={isReviewAiActionDisabled(\"explain\") || Boolean(batchAction)}", "disabled={isReviewAiActionDisabled(\"repair\") || Boolean(batchAction)}", "disabled={!canApplyRepair || Boolean(agentAction) || Boolean(batchAction)}", "disabled={Boolean(agentAction) || Boolean(batchAction) || repairingReviewId === activeReview.id || confirmLoading}"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page clears AI drafts before rerun", ["function clearReviewAiDrafts()", "setRepairCandidate(\"\")", "setIssueExplanation(\"\")", "async function rerunReview()", "clearReviewAiDrafts();"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page clears AI drafts after confirm succeeds", ["async function confirmActiveReview()", "await onConfirmReview(activeReview)", "if (activeReviewIdRef.current === requestReviewId) {\n        clearReviewAiDrafts();"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page localizes confirm and rerun failures", ["confirmActiveReview", "审稿项确认失败，请稍后重试。", "重新审稿失败，请稍后重试。", "activeReviewIdRef.current === requestReviewId"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page sanitizes visible status text", ["{authorText(review.status)}", "优先级 {authorText(review.priority)}", "text={authorText(activeReview.status)}", "优先级 {authorText(activeReview.priority)}", "{authorText(item.statusLabel)}"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page hides raw memory evidence strings", has("src/pages/ReviewPage.tsx", "证据 {index + 1}") && !has("src/pages/ReviewPage.tsx", "authorText(evidence)")],
  ["review page localizes memory update load and apply failures", ["setMemoryError", "记忆更新候选加载失败，请稍后重试。", "记忆更新应用失败，请稍后重试。", "applyMemoryUpdateCandidate", "workbenchClient.fetchChapterMemoryUpdates(requestBookId, chapterId)"].every((text) => any(text)) && !mainApp.includes("runAction(`memory-updates-${chapterId}`")],
  ["review memory updates are scoped by book and chapter", ["function memoryUpdateCacheKey", "memoryUpdateCacheKey(activeReview.bookId, activeReview.chapterId)", "const cacheKey = memoryUpdateCacheKey(requestBookId, chapterId)", "const cacheKey = memoryUpdateCacheKey(result.bookId, result.chapterId)", "bookId: update.bookId"].every((text) => any(text)) && !workbenchView.includes("chapterMemoryUpdates[activeReview.chapterId]")],
  ["review page disables already applied memory updates", ["disabled={!item.canApply || item.status === \"applied\"}", "已写入长期记忆"].every((text) => has("src/pages/ReviewPage.tsx", text))],
  ["review page syncs active review before memory load", has("src/pages/ReviewPage.tsx", "activeReviewIdRef.current = requestReviewId;") && has("src/pages/ReviewPage.tsx", "loadMemoryUpdatesRef.current(activeReview.chapterId)")],
  ["review page avoids repeated memory loads from callback identity", ["const loadMemoryUpdatesRef = useRef(onLoadMemoryUpdates)", "loadMemoryUpdatesRef.current = onLoadMemoryUpdates", "}, [activeReview?.chapterId, activeReview?.id]);"].every((text) => has("src/pages/ReviewPage.tsx", text)) && !has("src/pages/ReviewPage.tsx", "}, [activeReview?.chapterId, onLoadMemoryUpdates]);")],
  ["review page scopes memory updates to active chapter", ["visibleMemoryUpdates", "item.chapterId === activeReview.chapterId", "dataSource={visibleMemoryUpdates}"].every((text) => has("src/pages/ReviewPage.tsx", text)) && !has("src/pages/ReviewPage.tsx", "dataSource={memoryUpdates}")],
  ["review page uses chapter titles instead of visible ids", ["chapters={activeWorkspace.chapters}", "chapterTitleById", "chapterTitleById.get(review.chapterId)", "chapterTitleById.get(activeReview.chapterId)"].every((text) => any(text)) && !has("src/pages/ReviewPage.tsx", ">{review.chapterId}</Tag>") && !has("src/pages/ReviewPage.tsx", ">{activeReview.chapterId}</Tag>")],
  ["review page uses chapter titles in AI context", ["buildReviewAssistContext(activeReview, chapterTitleById)", "function buildReviewAssistContext(review: ReviewItem, chapterTitleById: Map<string, string>)", "`章节：${chapterTitleById.get(review.chapterId) ?? \"对应章节\"}`"].every((text) => has("src/pages/ReviewPage.tsx", text)) && !has("src/pages/ReviewPage.tsx", "`章节：${review.chapterId}`")],
  ["app shell delegates review actions to hook", ["import { useWorkbenchReviews }", "} = useWorkbenchReviews({"].every((text) => mainApp.includes(text)) && workbenchReviewsHook.includes("export function useWorkbenchReviews") && ["async function applyReviewRepair", "async function runReviews", "async function confirmReview", "const loadChapterMemoryUpdates", "const applyMemoryUpdate"].every((text) => workbenchReviewsHook.includes(text)) && ["async function applyReviewRepair", "async function runReviews", "async function confirmReview", "const loadChapterMemoryUpdates", "const applyMemoryUpdate"].every((text) => !mainApp.includes(text))],
  ["export page checks before generate and shows training data", ["等待导出检查", "检查", "生成", "导出摘要", "训练数据", "trainingPreview", "selectedTrainingChapterIds"].every((text) => has("src/pages/ExportPage.tsx", text)) && has("src/api/workbenchOperationNormalizers.ts", "firstVersionExportKinds")],
  ["export page recognizes unfinished generation state", ["generationState: GenerationState", "generationExportRisks", "generationBlocksManuscript", "正文导出前需要完成生成确认", "生成流程已暂停", "|| !currentExport"].every((text) => has("src/pages/ExportPage.tsx", text))],
  ["export page uses author language for gate risks", has("src/pages/ExportPage.tsx", "接收前检查和资料风险") && !has("src/pages/ExportPage.tsx", "gate 和资料风险")],
  ["export page sanitizes book range and risk text", ["{authorText(book.title)}", "label: authorText(chapter.title)", "{authorText(rangeLabel)}", "{authorText(risk)}"].every((text) => has("src/pages/ExportPage.tsx", text))],
  ["export page avoids implementation-flavored check copy", has("src/pages/ExportPage.tsx", "当前还没有这次导出范围的检查结果。") && !has("src/pages/ExportPage.tsx", "真实检查结果")],
  ["export page localizes failed check and generate state", ["导出检查失败，请稍后重试。", "导出生成失败，请稍后重试。", "setCheckedReadiness(null)", "setSummaryOpen(false)"].every((text) => has("src/pages/ExportPage.tsx", text))],
  ["export page invalidates stale async results on selection reset", countOccurrences(files["src/pages/ExportPage.tsx"] ?? "", "exportRequestRef\\.current \\+= 1") === 2],
  ["export page binds checked readiness to the checked chapter set", ["const chapterIdsKey = book.chapters.map((chapter) => chapter.id).join(\"::\")", "const checkedChapterIdsKey = checkedReadiness?.chapterIds.join(\"::\") ?? \"\"", "checkedChapterIdsKey === chapterIdsKey", "chapterIds: normalizeStringList(item.chapterIds)", "}, [book.id]);"].every((text) => any(text)) && !has("src/pages/ExportPage.tsx", "exportCheckInFlightRef")],
  ["export page binds only current chapter range to active chapter", ["activeChapter: Chapter", "range === \"章节范围\" ? rangeStart : undefined", "range === \"章节范围\" ? rangeEnd : undefined", "if (range !== \"当前章节\")", "}, [activeChapter.id, range]);", "activeChapter={activeChapter}"].every((text) => any(text))],
  ["export page blocks reversed chapter ranges", ["const rangeStartIndex", "const rangeEndIndex", "const invalidChapterRange", "结束章节不能早于起始章节。", "disabled={invalidChapterRange || generatingCurrentSelection}", "|| !currentExport"].every((text) => has("src/pages/ExportPage.tsx", text))],
  ["export page scopes loading to current selection", ["pendingExportAction", "pendingExportAction?.key === selectionKey", "pendingExportAction.type === \"check\"", "pendingExportAction.type === \"generate\"", "export-check-${exportKey}", "export-generate-${exportKey}", "function exportSelectionKey"].every((text) => any(text)) && !has("src/pages/ExportPage.tsx", "loading={checking}") && !has("src/pages/ExportPage.tsx", "loading={generating}")],
  ["export actions ignore stale book results after switching books", ["activeBookIdRef: RefObject<string>", "shouldReportError: () => activeBookIdRef.current === requestBookId", "if (activeBookIdRef.current !== requestBookId)", "[requestBookId]: replaceExportReadiness"].every((text) => workbenchExportsHook.includes(text))],
  ["export page prevents check and generate from interrupting each other", ["checkingCurrentSelection", "generatingCurrentSelection", "generatingCurrentSelection}", "|| !currentExport", "|| checkingCurrentSelection"].every((text) => has("src/pages/ExportPage.tsx", text))],
  ["app shell delegates export actions to hook", ["import { useWorkbenchExports }", "} = useWorkbenchExports({"].every((text) => mainApp.includes(text)) && workbenchExportsHook.includes("export function useWorkbenchExports") && ["async function checkExport", "async function generateExport", "replaceExportReadiness(current[requestBookId]", "message.success(authorText(result.summary))"].every((text) => workbenchExportsHook.includes(text)) && ["async function checkExport", "async function generateExport"].every((text) => !mainApp.includes(text))],
  ["more page localizes task action failures", ["moreActionError", "localActionError", "visibleActionError", "任务详情加载失败，请稍后重试。", "任务取消失败，请稍后重试。", "任务重试失败，请稍后重试。", "任务操作未完成"].every((text) => any(text))],
  ["more page ignores stale job detail requests", ["detailRequestRef", "expandedJobIdRef", "detailRequestRef.current === requestId", "switchTab"].every((text) => has("src/pages/MorePage.tsx", text))],
  ["more page clears expanded job when task list changes", ["const jobIdsKey = jobs.map((job) => job.id).join(\"::\")", "if (!expandedJobId || jobs.some((job) => job.id === expandedJobId))", "setExpandedJobId(null)", "}, [expandedJobId, jobIdsKey, jobs]);"].every((text) => has("src/pages/MorePage.tsx", text))],
  ["more page prevents parallel job actions", ["function isJobActionBusy", "loadingAction === \"ops-refresh\"", "disabled={(job.status !== \"运行中\" && job.status !== \"等待中\") || isJobActionBusy(job.id)}", "disabled={job.status === \"运行中\" || isJobActionBusy(job.id)}", "disabled={loadingAction === \"ops-refresh\" || loadingAction === `job-cancel-${job.id}` || loadingAction === `job-retry-${job.id}`}"].every((text) => has("src/pages/MorePage.tsx", text))],
  ["operation normalizer summarizes raw job events", ["normalizeJobEventList", "summarizeJobEvent", "任务阶段已更新，已隐藏不适合展示的细节。", "任务遇到问题，请查看结果摘要。"].every((text) => workbenchOperationNormalizers.includes(text)) && !workbenchOperationNormalizers.includes("events: normalizeStringList(response.events)")],
  ["operation normalizer sanitizes visible operation text", ["operationInternalDetailPattern", "function safeOperationText", "function normalizeOperationTextList", "summary: safeOperationText(item.summary", "resultName: safeOperationText(response.resultName", "title: safeOperationText(job.title", "result: safeOperationText(job.result", "title: authorRunTitle(run.title", "summary: authorRunSummary(run.summary"].every((text) => workbenchOperationNormalizers.includes(text)) && !["summary: safeDisplayText(response.summary)", "resultName: safeDisplayText(response.resultName)", "title: safeDisplayText(job.title)", "result: safeDisplayText(job.result)", "title: safeDisplayText(run.title)", "summary: safeDisplayText(run.summary)"].some((text) => workbenchOperationNormalizers.includes(text))],
  ["operation run records hide internal names and paths", ["authorRunTitle", "authorRunSummary", "作品方向生成", "结果已整理，可在对应页面继续查看。"].every((text) => workbenchOperationNormalizers.includes(text))],
  ["operation detail contract drops retry job ids", !workbenchContracts.includes("retryOfJobId") && !workbenchOperationNormalizers.includes("retryOfJobId")],
  ["app shell delegates operations actions to hook", ["import { useWorkbenchOperations }", "} = useWorkbenchOperations({"].every((text) => mainApp.includes(text)) && workbenchOperationsHook.includes("export function useWorkbenchOperations") && ["async function refreshOperations", "async function cancelJob", "async function retryJob", "async function loadJobDetail"].every((text) => workbenchOperationsHook.includes(text)) && ["async function refreshOperations", "async function cancelJob", "async function retryJob", "async function loadJobDetail"].every((text) => !mainApp.includes(text))],
  ["app shell centralizes operations write resync", ["function syncBookOperationsAfterWrite", "syncBookOperationsState(bookId", "syncBookOperationsAfterWrite(result.bookId", "replaceBookWorkspaceItems(current, jobsResult.jobs, bookId)", "replaceBookWorkspaceItems(current, runsResult.runs, bookId)"].every((text) => workbenchOperationsHook.includes(text)) && countOccurrences(workbenchOperationsHook, "syncBookOperationsState\\(") === 3 && !workbenchOperationsHook.includes("syncBookOperationsState(result.bookId")],
  ["app shell scopes operations errors to active book", ["activeBookIdRef.current === bookId", "const isActiveBook = activeBookIdRef.current === bookId", "if (isActiveBook) {\n        setOperationsError(errorMessage);", "if (isActiveBook && !options?.suppressErrorToast)"].every((text) => workbenchOperationsHook.includes(text))],
  ["more page ignores stale task action failures and toasts", ["options?: { shouldReportError?: () => boolean }", "if (options?.shouldReportError?.() ?? true)", "shouldReportError: () => activeBookIdRef.current === requestBookId", "if (activeBookIdRef.current === bookId) {\n        fallback?.();", "if (activeBookIdRef.current !== result.bookId)"].every((text) => workbenchOperationsHook.includes(text)) && ["const activeBookIdRef = useRef(book.id)", "activeBookIdRef.current = book.id", "if (activeBookIdRef.current === requestBookId) {\n        setLocalActionError"].every((text) => has("src/pages/MorePage.tsx", text))],
  ["app shell ignores stale cross-book job detail writes", ["const requestBookId = activeBook.id", "activeBookIdRef.current !== requestBookId", "detailResult.job.bookId !== requestBookId"].every((text) => workbenchOperationsHook.includes(text)) && ["const activeBookIdRef = useRef(activeBook.id)", "activeBookIdRef.current = activeBook.id"].every((text) => workbenchStateHook.includes(text))],
  ["more page sanitizes operations summary text", ["Promise.resolve(onRefresh()).catch(() => undefined)", "{authorText(book.title)}", "text={authorText(job.status)}", "{authorText(job.startedAt)}", "{authorText(run.kind)}", "{authorText(run.status)}", "{authorText(run.createdAt)}"].every((text) => has("src/pages/MorePage.tsx", text))],
  ["sidebar owns a compact version pill and polls automatic update detection every minute", ["SystemUpdateControl", "collapsed={collapsed}"].every((text) => has("src/components/AppSidebar.tsx", text)) && ["UPDATE_POLL_INTERVAL_MS = 60_000", "autoDetectSystemUpdate", "system-version-panel", "当前版本", "检查更新", "一键更新", "等待服务恢复", "已自动回滚"].every((text) => has("src/components/SystemUpdateControl.tsx", text)) && !["system-update-prompt", "版本更新", "fetchSystemUpdate", "fetchSystemUpdateStatus", "prepareSystemUpdate"].some((text) => has("src/pages/MorePage.tsx", text))],
  ["more page keeps only jobs and run records", ["任务", "运行记录", "事件摘要", "任务摘要"].every((text) => has("src/pages/MorePage.tsx", text)) && !["事件流", "候选差异", "维护", "高级模式", "原始日志"].some((text) => has("src/pages/MorePage.tsx", text))]
];

const failed = checks.filter(([, passed]) => !passed);
for (const [name, passed] of checks) {
  console.log(`${passed ? "PASS" : "FAIL"} ${name}`);
}

if (failed.length) {
  console.error(`\n${failed.length} page-plan check(s) failed.`);
  process.exit(1);
}

console.log(`\n${checks.length} page-plan checks passed.`);
