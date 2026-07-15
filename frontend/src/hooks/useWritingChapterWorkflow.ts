import { useEffect, useRef, useState } from "react";
import { message, Modal } from "antd";
import type { AcceptChapterBlockedDetail, AcceptChapterResponse, ChapterGateRecoveryResponse, ChapterGateResponse, ChapterPrepareResponse } from "../api/contracts";
import { ApiRequestError, isAcceptChapterBlockedDetail, workbenchClient } from "../api/workbenchClient";
import type { Book, Chapter } from "../types";
import { authorText } from "../utils/authorText";

type CandidateKind = "续写" | "润色" | "冲突" | "整章";
export type DraftSnapshot = {
  id: string;
  savedAt: string;
  content: string;
  wordCount: number;
};

export type PostAcceptSummary = {
  chapterTitle: string;
  gateStatus: string;
  gateScore: number;
  issueCount: number;
  patchPath: string;
  reviewTitle: string;
  nextAction: string;
};

export function useWritingChapterWorkflow({
  book,
  chapter,
  onChapterChange,
  onApplyCandidate,
  onSaveDraft,
  onPrepareChapter,
  onCheckGate,
  onAcceptChapter,
  onCreateNextChapter,
  onOpenReview
}: {
  book: Book;
  chapter: Chapter;
  onChapterChange: (chapterId: string) => void;
  onApplyCandidate: (nextContent: string) => void | Promise<void>;
  onSaveDraft: (nextContent: string) => void | Promise<void>;
  onPrepareChapter: () => Promise<ChapterPrepareResponse>;
  onCheckGate: () => Promise<ChapterGateResponse>;
  onAcceptChapter: (force?: boolean) => Promise<AcceptChapterBlockedDetail | AcceptChapterResponse | null>;
  onCreateNextChapter: () => void | Promise<void>;
  onOpenReview?: () => void;
}) {
  const contextRef = useRef({ bookId: book.id, chapterId: chapter.id });
  const serverContentRef = useRef(chapter.content);
  const candidateRequestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const [candidateText, setCandidateText] = useState("");
  const [candidateSource, setCandidateSource] = useState("");
  const [agentAction, setAgentAction] = useState<string | null>(null);
  const [draftText, setDraftText] = useState(
    () => readPersistedDraft(book.id, chapter.id) ?? chapter.content
  );
  const [gateOpen, setGateOpen] = useState(false);
  const [prepared, setPrepared] = useState(chapter.status !== "待写");
  const [prepareResult, setPrepareResult] = useState<ChapterPrepareResponse | null>(null);
  const [gateResult, setGateResult] = useState<ChapterGateResponse | null>(null);
  const [gateRecovery, setGateRecovery] = useState<ChapterGateRecoveryResponse | null>(null);
  const [actionError, setActionError] = useState("");
  const [pendingDraftAction, setPendingDraftAction] = useState<"save" | "apply" | null>(null);
  const [lastCandidateKind, setLastCandidateKind] = useState<CandidateKind>("续写");
  const [draftHistory, setDraftHistory] = useState<DraftSnapshot[]>(() => readDraftHistory(book.id, chapter.id));
  const [postAcceptSummary, setPostAcceptSummary] = useState<PostAcceptSummary | null>(null);

  useEffect(() => {
    contextRef.current = { bookId: book.id, chapterId: chapter.id };
  }, [book.id, chapter.id]);

  useEffect(() => {
    serverContentRef.current = chapter.content;
    candidateRequestRef.current += 1;
    setDraftText(readPersistedDraft(book.id, chapter.id) ?? chapter.content);
    setCandidateText("");
    setCandidateSource("");
    setGateOpen(false);
    setPrepared(chapter.status !== "待写");
    setPrepareResult(null);
    setGateResult(null);
    setGateRecovery(null);
    setActionError("");
    setPendingDraftAction(null);
    setDraftHistory(readDraftHistory(book.id, chapter.id));
    abortRef.current?.abort();
    abortRef.current = null;
  }, [book.id, chapter.id]);

  useEffect(() => {
    const previousContent = serverContentRef.current;
    serverContentRef.current = chapter.content;
    setDraftText((current) => current === previousContent ? chapter.content : current);
  }, [chapter.content]);

  useEffect(() => {
    setPrepared(chapter.status !== "待写");
  }, [chapter.status]);

  useEffect(() => {
    persistDraft(book.id, chapter.id, draftText, chapter.content);
  }, [book.id, chapter.id, chapter.content, draftText]);

  const isDirty = draftText !== chapter.content;

  async function createCandidate(
    kind: CandidateKind,
    revisionInstruction = "",
    bypassCache = false
  ) {
    const requestKey = `${book.id}:${chapter.id}`;
    const requestId = candidateRequestRef.current + 1;
    candidateRequestRef.current = requestId;
    setLastCandidateKind(kind);
    setAgentAction(kind);
    setCandidateText("");
    setCandidateSource(kind);
    setActionError("");
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await workbenchClient.streamAgentAssist({
        bookId: book.id,
        chapterId: chapter.id,
        scope: "chapter",
        action: kind,
        input: [
          buildChapterAssistContext(chapter, draftText),
          revisionInstruction.trim() ? `\n---\n修改意见：\n${revisionInstruction.trim()}` : ""
        ].filter(Boolean).join("\n"),
        bypassCache
      }, (text) => {
        if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey && candidateRequestRef.current === requestId) {
          setCandidateText((current) => `${current}${text}`);
        }
      }, controller.signal);
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey || candidateRequestRef.current !== requestId) {
        return;
      }
      setCandidateText((current) => current || response.candidateText || response.content);
      setCandidateSource(kind);
      message.success(`AI 已生成${kind}候选，可在正文下方审阅。`);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey && candidateRequestRef.current === requestId) {
        setActionError(authorText(error instanceof Error ? error.message : "AI 候选生成失败，请稍后重试。"));
      }
    } finally {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey && candidateRequestRef.current === requestId) {
        setAgentAction(null);
        abortRef.current = null;
      }
    }
  }

  function cancelCandidate() {
    candidateRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setAgentAction(null);
    message.info("已取消本次 AI 生成。");
  }

  function isCandidateActionDisabled(kind: CandidateKind) {
    return Boolean(agentAction && agentAction !== kind);
  }

  async function polishWholeChapter() {
    const requestKey = `${book.id}:${chapter.id}`;
    setLastCandidateKind("润色");
    setAgentAction("润色");
    setCandidateText("");
    setCandidateSource("AI润色全章");
    setActionError("");
    try {
      if (isDirty) {
        await onSaveDraft(draftText);
      }
      const response = await workbenchClient.polishChapter({
        bookId: book.id,
        chapterId: chapter.id,
        instruction: "在保留剧情事实和章节结构的前提下润色全章，强化节奏、情绪和可读性。"
      });
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setCandidateText(response.candidateText);
      setCandidateSource("AI润色全章");
      message.success("全章润色已生成，可用对照视图审阅。");
    } catch (error) {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setActionError(authorText(error instanceof Error ? error.message : "全章润色失败，请稍后重试。"));
      }
    } finally {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setAgentAction(null);
      }
    }
  }

  async function prepareChapter() {
    const requestKey = `${book.id}:${chapter.id}`;
    setActionError("");
    try {
      const result = await onPrepareChapter();
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setPrepareResult(result);
      setPrepared(result.readiness.status !== "block");
    } catch (error) {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setActionError(authorText(error instanceof Error ? error.message : "章节准备失败，请稍后重试。"));
      }
    }
  }

  function changeChapter(nextChapterId: string) {
    onChapterChange(nextChapterId);
  }

  async function applyCandidate() {
    const requestKey = `${book.id}:${chapter.id}`;
    const normalizedCandidate = candidateText.replace(/^【AI [^】]+】\n?/, "").trim();
    const nextContent = `${draftText}\n\n${normalizedCandidate}`;
    setActionError("");
    setPendingDraftAction("apply");
    try {
      await onApplyCandidate(nextContent);
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setDraftText(nextContent);
      setCandidateText("");
      setCandidateSource("");
      setGateOpen(false);
      setGateResult(null);
      setGateRecovery(null);
    } catch (error) {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setActionError(authorText(error instanceof Error ? error.message : "候选应用失败，请稍后重试。"));
      }
    } finally {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setPendingDraftAction((current) => (current === "apply" ? null : current));
      }
    }
  }

  async function saveDraft() {
    const requestKey = `${book.id}:${chapter.id}`;
    setActionError("");
    setPendingDraftAction("save");
    try {
      const nextHistory = pushDraftHistory(book.id, chapter.id, chapter.content);
      setDraftHistory(nextHistory);
      await onSaveDraft(draftText);
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setGateOpen(false);
      setGateResult(null);
      setGateRecovery(null);
    } catch (error) {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setActionError(authorText(error instanceof Error ? error.message : "草稿保存失败，请稍后重试。"));
      }
    } finally {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
        setPendingDraftAction((current) => (current === "save" ? null : current));
      }
    }
  }

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey)) {
        if (event.key === "Escape" && agentAction) {
          cancelCandidate();
        }
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        if (isDirty && !pendingDraftAction) {
          void saveDraft();
        }
      }
      if (key === "enter") {
        event.preventDefault();
        if (!agentAction) {
          void createCandidate("续写");
        }
      }
      if (key === "g") {
        event.preventDefault();
        void openGatePanel();
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [agentAction, draftText, isDirty, pendingDraftAction]);

  function restoreDraftSnapshot(snapshot: DraftSnapshot) {
    setDraftText(snapshot.content);
    message.success("已恢复到本地历史版本，保存前不会影响服务端。");
  }

  function discardDraftChanges() {
    if (!isDirty) {
      return;
    }
    Modal.confirm({
      title: "确认还原草稿？",
      content: "还原会丢弃当前未保存的本地修改，并恢复为最近一次同步的正文。",
      okText: "确认还原",
      cancelText: "继续编辑",
      onOk: () => setDraftText(chapter.content)
    });
  }

  async function acceptAfterGate(force = false) {
    const requestKey = `${book.id}:${chapter.id}`;
    setActionError("");
    try {
      const result = await onAcceptChapter(force);
      if (isBlockedAcceptDetail(result)) {
        if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
          return;
        }
        applyBlockedDetail(result);
        return;
      }
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setGateOpen(false);
      if (isAcceptChapterResponse(result)) {
        setPostAcceptSummary({
          chapterTitle: result.chapter.title,
          gateStatus: result.gate?.status ?? gateResult?.gate.status ?? "",
          gateScore: result.gate?.score ?? gateResult?.gate.score ?? 0,
          issueCount: result.gate?.issues?.length ?? gateResult?.gate.issues.length ?? 0,
          patchPath: result.patchPath ?? "",
          reviewTitle: result.review?.title ?? "",
          nextAction: result.gate?.recommendedNextAction ?? gateResult?.gate.recommendedNextAction ?? "建议查看接收后复盘。"
        });
      } else if (gateResult?.gate.recommendedNextAction?.includes("review")) {
        setPostAcceptSummary({
          chapterTitle: chapter.title,
          gateStatus: gateResult.gate.status,
          gateScore: gateResult.gate.score,
          issueCount: gateResult.gate.issues.length,
          patchPath: "",
          reviewTitle: "",
          nextAction: gateResult.gate.recommendedNextAction
        });
      }
    } catch (error) {
      if (error instanceof ApiRequestError && isAcceptChapterBlockedDetail(error.detail)) {
        if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
          return;
        }
        applyBlockedDetail(error.detail);
        return;
      }
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setActionError(authorText(error instanceof Error ? error.message : "章节接收失败，请稍后重试。"));
    }
  }

  async function openGatePanel() {
    const requestKey = `${book.id}:${chapter.id}`;
    setActionError("");
    try {
      const result = await onCheckGate();
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setGateResult(result);
      if (result.gate.status === "block" || result.gate.status === "warn") {
        try {
          const recovery = await workbenchClient.fetchChapterGateRecovery(book.id, chapter.id);
          if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
            return;
          }
          setGateRecovery(recovery);
        } catch (error) {
          if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
            return;
          }
          setGateRecovery(null);
          setActionError(authorText(error instanceof Error ? error.message : "修复建议加载失败，请稍后重试。"));
        }
      } else {
        setGateRecovery(null);
      }
      setGateOpen(true);
    } catch (error) {
      if (`${contextRef.current.bookId}:${contextRef.current.chapterId}` !== requestKey) {
        return;
      }
      setActionError(authorText(error instanceof Error ? error.message : "接收前检查失败，请稍后重试。"));
    }
  }

  function forceAcceptAfterGate() {
    Modal.confirm({
      title: "确认强制接收？",
      content: "当前接收前检查仍有提示项。强制接收会保留风险记录，并把章节标记为可继续推进。",
      okText: "强制接收",
      cancelText: "返回修复",
      onOk: () => acceptAfterGate(true)
    });
  }

  async function createNextChapter() {
    setActionError("");
    try {
      await onCreateNextChapter();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "开始下一章失败，请稍后重试。"));
    }
  }

  async function copyCandidate() {
    try {
      await navigator.clipboard?.writeText(candidateText);
      message.success("候选已复制。");
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "候选复制失败，请稍后重试。"));
    }
  }

  function applyBlockedDetail(blockedDetail: AcceptChapterBlockedDetail) {
    setGateResult({
      bookId: book.id,
      chapterId: chapter.id,
      gate: {
        status: blockedDetail.gate.status,
        score: blockedDetail.gate.score,
        issues: blockedDetail.gate.issues,
        recommendedNextAction: blockedDetail.gate.recommendedNextAction ?? blockedDetail.recovery?.recommendedNextAction ?? ""
      },
      display: blockedDetail.message
    });
    setGateRecovery(blockedDetail.recovery ?? null);
    setGateOpen(true);
  }

  return {
    candidateText,
    setCandidateText,
    candidateSource,
    agentAction,
    draftText,
    setDraftText,
    gateOpen,
    setGateOpen,
    prepared,
    prepareResult,
    gateResult,
    gateRecovery,
    actionError,
    pendingDraftAction,
    lastCandidateKind,
    isDirty,
    createCandidate,
    isCandidateActionDisabled,
    polishWholeChapter,
    prepareChapter,
    changeChapter,
    applyCandidate,
    saveDraft,
    acceptAfterGate,
    openGatePanel,
    forceAcceptAfterGate,
    createNextChapter,
    copyCandidate,
    discardDraftChanges,
    cancelCandidate,
    draftHistory,
    restoreDraftSnapshot,
    postAcceptSummary,
    setPostAcceptSummary,
    onOpenReview
  };
}

function buildChapterAssistContext(chapter: Chapter, draftText: string) {
  const draftSnippet = (draftText || chapter.content).slice(-800).trim();
  return [
    `章节：${chapter.title}`,
    `状态：${chapter.status}`,
    `摘要：${chapter.summary}`,
    `任务：${chapter.tasks.join("、") || "无"}`,
    `剧情点：${chapter.plotPoints.join("、") || "无"}`,
    `人物：${chapter.people.join("、") || "无"}`,
    `线索：${chapter.clues.join("、") || "无"}`,
    `审阅提醒：${chapter.review.join("、") || "无"}`,
    draftSnippet ? `\n---\n当前正文末尾（续写时从这里接）：\n${draftSnippet}` : ""
  ].filter(Boolean).join("\n");
}

function isBlockedAcceptDetail(result: AcceptChapterBlockedDetail | AcceptChapterResponse | null): result is AcceptChapterBlockedDetail {
  return Boolean(result && "message" in result && "gate" in result && !("chapter" in result));
}

function isAcceptChapterResponse(result: AcceptChapterBlockedDetail | AcceptChapterResponse | null): result is AcceptChapterResponse {
  return Boolean(result && "chapter" in result);
}

function draftHistoryKey(bookId: string, chapterId: string) {
  return `draft_history_${bookId}_${chapterId}`;
}

function draftStorageKey(bookId: string, chapterId: string) {
  return `chapter_draft_${bookId}_${chapterId}`;
}

function readPersistedDraft(bookId: string, chapterId: string) {
  if (typeof localStorage === "undefined") {
    return null;
  }
  return localStorage.getItem(draftStorageKey(bookId, chapterId));
}

function persistDraft(
  bookId: string,
  chapterId: string,
  draftText: string,
  serverContent: string
) {
  if (typeof localStorage === "undefined") {
    return;
  }
  const key = draftStorageKey(bookId, chapterId);
  if (draftText === serverContent) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, draftText);
}

function readDraftHistory(bookId: string, chapterId: string): DraftSnapshot[] {
  if (typeof localStorage === "undefined") {
    return [];
  }
  try {
    const parsed = JSON.parse(localStorage.getItem(draftHistoryKey(bookId, chapterId)) ?? "[]");
    return Array.isArray(parsed) ? parsed.slice(0, 10) : [];
  } catch {
    return [];
  }
}

function pushDraftHistory(bookId: string, chapterId: string, content: string) {
  const text = content.trim();
  if (!text || typeof localStorage === "undefined") {
    return readDraftHistory(bookId, chapterId);
  }
  const current = readDraftHistory(bookId, chapterId);
  if (current[0]?.content === content) {
    return current;
  }
  const next = [
    {
      id: `${Date.now()}`,
      savedAt: new Date().toISOString(),
      content,
      wordCount: text.length
    },
    ...current
  ].slice(0, 10);
  localStorage.setItem(draftHistoryKey(bookId, chapterId), JSON.stringify(next));
  return next;
}
