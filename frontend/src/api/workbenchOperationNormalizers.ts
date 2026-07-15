import type { ExportKind, ExportReadiness, JobStatus, JobSummary, RunSummary, TrainingExportPreview } from "../types";
import type {
  ExportCheckResponse,
  ExportGenerateResponse,
  ExportRequest,
  JobDetailResponse,
  JobEventsResponse,
  JobMutationResponse,
  JobsResponse,
  RunsResponse
} from "./contracts";
import {
  asArray,
  normalizeNonNegativeNumber,
  normalizePercent,
  normalizeStringList,
  safeDisplayText
} from "./workbenchNormalizerUtils";

const firstVersionExportKinds = new Set<ExportKind>(["正文", "训练数据", "审稿报告", "资料包"]);
const jobStatusValues: JobStatus[] = ["运行中", "已完成", "失败", "等待中"];
const operationInternalDetailPattern =
  /(?:\b(?:prompt|output|traceback|stack|command|cmd|stderr|stdout|raw|log|job\s*id|run\s*id|event\s*id|path|outputPath|draftPath|reportPath)\b|原始日志|原始\s*(?:prompt|output)|命令|调用栈|堆栈|回溯|本地路径|运行编号|任务编号|路径已隐藏|已隐藏本地路径|已隐藏运行编号|任务编号已隐藏)/i;

export function isFirstVersionExportKind(kind: unknown): kind is ExportKind {
  return firstVersionExportKinds.has(kind as ExportKind);
}

export function normalizeExportReadiness(item: Partial<ExportReadiness>): ExportReadiness {
  return {
    bookId: item.bookId ?? "",
    kind: normalizeExportKind(item.kind),
    chapterIds: normalizeStringList(item.chapterIds),
    ready: Boolean(item.ready),
    summary: safeOperationText(item.summary, "导出检查已完成。"),
    checks: normalizeOperationTextList(item.checks, "检查项已整理，已隐藏不适合展示的细节。"),
    risks: normalizeOperationTextList(item.risks, "导出存在需要处理的风险。"),
    resultName: item.resultName ? safeOperationText(item.resultName, "导出结果已生成。") : undefined,
    trainingPreview: normalizeTrainingPreview(item.trainingPreview)
  };
}

export function normalizeJob(job: Partial<JobSummary>): JobSummary {
  return {
    id: String(job.id ?? ""),
    bookId: String(job.bookId ?? ""),
    title: safeOperationText(job.title, "处理任务"),
    status: normalizeJobStatus(job.status),
    progress: normalizePercent(job.progress),
    startedAt: safeOperationText(job.startedAt, ""),
    result: safeOperationText(job.result, "任务结果已整理。"),
    events: normalizeJobEventList(job.events)
  };
}

export function normalizeRun(run: Partial<RunSummary>): RunSummary {
  const kind = run.kind === "审稿" || run.kind === "导出" || run.kind === "模型" ? run.kind : "生成";
  return {
    id: String(run.id ?? ""),
    bookId: String(run.bookId ?? ""),
    title: authorRunTitle(run.title, kind),
    kind,
    status: run.status === "警告" || run.status === "失败" ? run.status : "成功",
    createdAt: safeOperationText(run.createdAt, ""),
    summary: authorRunSummary(run.summary, kind)
  };
}

export function normalizeExportCheckResponse(
  response: Partial<ExportCheckResponse>,
  requestBody: ExportRequest
): ExportCheckResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    readiness: normalizeExportReadiness({
      bookId: requestBody.bookId,
      kind: requestBody.kind,
      ...response.readiness
    })
  };
}

export function normalizeExportGenerateResponse(
  response: Partial<ExportGenerateResponse>,
  requestBody: ExportRequest
): ExportGenerateResponse {
  return {
    bookId: String(response.bookId ?? requestBody.bookId),
    kind: normalizeExportKind(response.kind ?? requestBody.kind),
    resultName: safeOperationText(response.resultName, "导出结果已生成。"),
    summary: safeOperationText(response.summary, "导出已完成。"),
    readiness: normalizeExportReadiness({
      bookId: requestBody.bookId,
      kind: response.kind ?? requestBody.kind,
      ...response.readiness
    })
  };
}

export function normalizeJobsResponse(response: Partial<JobsResponse>, bookId: string): JobsResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    jobs: asArray(response.jobs).map((job) => normalizeJob({ ...job, bookId: job.bookId ?? bookId }))
  };
}

export function normalizeJobDetailResponse(
  response: Partial<JobDetailResponse>,
  bookId: string,
  jobId: string
): JobDetailResponse {
  const job = normalizeJob({ id: jobId, bookId, ...response.job });
  return {
    bookId: String(response.bookId ?? bookId),
    job,
    detail: {
      title: safeOperationText(response.detail?.title, job.title) || job.title,
      status: normalizeJobStatus(response.detail?.status ?? job.status),
      summary: safeOperationText(response.detail?.summary || job.result, "任务详情已整理。"),
      events: normalizeJobEventList(response.detail?.events),
      startedAt: safeOperationText(response.detail?.startedAt || job.startedAt, ""),
      finishedAt: response.detail?.finishedAt ? safeOperationText(response.detail.finishedAt, "") : undefined
    }
  };
}

export function normalizeJobEventsResponse(
  response: Partial<JobEventsResponse>,
  bookId: string,
  jobId: string
): JobEventsResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    jobId: String(response.jobId ?? jobId),
    events: normalizeJobEventList(response.events)
  };
}

export function normalizeJobMutationResponse(
  response: Partial<JobMutationResponse>,
  bookId: string
): JobMutationResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    job: normalizeJob({ bookId, ...response.job })
  };
}

export function normalizeRunsResponse(response: Partial<RunsResponse>, bookId: string): RunsResponse {
  return {
    bookId: String(response.bookId ?? bookId),
    runs: asArray(response.runs).map((run) => normalizeRun({ ...run, bookId: run.bookId ?? bookId }))
  };
}

function normalizeJobStatus(status: JobStatus | undefined): JobStatus {
  return jobStatusValues.includes(status as JobStatus) ? status as JobStatus : "等待中";
}

function normalizeExportKind(kind: ExportKind | undefined): ExportKind {
  return isFirstVersionExportKind(kind) ? kind : "正文";
}

function normalizeTrainingPreview(value: unknown): TrainingExportPreview | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const preview = value as Partial<TrainingExportPreview>;
  return {
    eligibleCount: normalizeNonNegativeNumber(preview.eligibleCount),
    skippedCount: normalizeNonNegativeNumber(preview.skippedCount),
    items: asArray(preview.items).map((item) => ({
      chapterId: safeOperationText(item.chapterId, "未命名章节"),
      eligible: Boolean(item.eligible),
      reason: safeOperationText(item.reason, ""),
      reasonLabel: safeOperationText(item.reasonLabel, ""),
      qualityScore: normalizeNonNegativeNumber(item.qualityScore),
      gateStatus: safeOperationText(item.gateStatus, "unknown"),
      gateScore: normalizeNonNegativeNumber(item.gateScore),
      previousSimilarity: Number(item.previousSimilarity) || 0,
      batchSimilarity: Number(item.batchSimilarity) || 0,
      batchDuplicateOf: safeOperationText(item.batchDuplicateOf, ""),
      actionSuggestion: safeOperationText(item.actionSuggestion, "")
    }))
  };
}

function normalizeJobEventList(value: unknown): string[] {
  return normalizeOperationTextList(value, "任务阶段已更新，已隐藏不适合展示的细节。")
    .map(summarizeJobEvent)
    .filter(Boolean);
}

function normalizeOperationTextList(value: unknown, fallback: string): string[] {
  return normalizeStringList(value).map((item) => safeOperationText(item, fallback)).filter(Boolean);
}

function safeOperationText(value: unknown, fallback: string): string {
  const text = safeDisplayText(value);
  if (!text) {
    return fallback;
  }
  if (operationInternalDetailPattern.test(text)) {
    return fallback;
  }
  return text;
}

function authorRunTitle(value: unknown, kind: RunSummary["kind"]): string {
  const text = safeOperationText(value, "");
  if (!text) {
    return `${kind}记录`;
  }
  const labels: Array<[RegExp, string]> = [
    [/book-direction/i, "作品方向生成"],
    [/long-form/i, "长篇规划生成"],
    [/blueprint/i, "作品架构生成"],
    [/chapter.*(?:plan|contract)/i, "章节规划生成"],
    [/chapter.*(?:draft|writer)/i, "章节正文生成"],
    [/review|editorial|continuity/i, "章节审稿"],
    [/export/i, "作品导出"],
    [/model|training/i, "模型处理"]
  ];
  const matched = labels.find(([pattern]) => pattern.test(text));
  if (matched) {
    return matched[1];
  }
  if (/\brun[_-]?\d|[a-z]+(?:-[a-z]+){1,}/i.test(text)) {
    return `${kind}记录`;
  }
  return text;
}

function authorRunSummary(value: unknown, kind: RunSummary["kind"]): string {
  const text = safeOperationText(value, "");
  if (!text || /(?:^|[\\/])[\w.-]+(?:[\\/][\w.-]+)+|\.json\b|\.md\b|\.txt\b/i.test(text)) {
    return `${kind}结果已整理，可在对应页面继续查看。`;
  }
  return text;
}

function summarizeJobEvent(event: string): string {
  if (/已隐藏本地路径|路径已隐藏|已隐藏运行编号|任务编号已隐藏|prompt|output|traceback|stack|command|命令/i.test(event)) {
    return "任务阶段已更新，已隐藏不适合展示的细节。";
  }
  if (/fail|error|exception|失败|异常|错误/i.test(event)) {
    return "任务遇到问题，请查看结果摘要。";
  }
  if (/complete|done|finish|success|完成|成功/i.test(event)) {
    return "任务阶段已完成。";
  }
  if (/start|begin|queue|waiting|开始|等待|排队/i.test(event)) {
    return "任务已进入处理队列。";
  }
  return event;
}
