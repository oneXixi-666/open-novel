import type { AcceptChapterBlockedDetail, WorkbenchClient } from "./contracts";
import { ApiRequestError, apiWorkbenchClient } from "./workbenchApiClient";

export { ApiRequestError };

export function isAcceptChapterBlockedDetail(detail: unknown): detail is AcceptChapterBlockedDetail {
  if (!detail || typeof detail !== "object") {
    return false;
  }
  const candidate = detail as Record<string, unknown>;
  const gate = candidate.gate;
  return typeof candidate.message === "string" && !!gate && typeof gate === "object" && (gate as Record<string, unknown>).status === "block";
}

export const workbenchClientMode = "api";
export const workbenchClient: WorkbenchClient = apiWorkbenchClient;
