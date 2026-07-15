import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, Collapse, Divider, Empty, Flex, List, message, Space, Tag, Typography } from "antd";
import { CheckCircleOutlined, ExperimentOutlined, HighlightOutlined } from "@ant-design/icons";
import { workbenchClient } from "../api/workbenchClient";
import { MetricGrid } from "../components/shared";
import type { Chapter, MemoryUpdateItem, ReviewItem } from "../types";
import { authorText } from "../utils/authorText";

const { Text, Title, Paragraph } = Typography;

export function ReviewPage({
  chapters,
  reviews,
  activeReview,
  memoryUpdates,
  onReviewChange,
  onApplyRepair,
  onRunReview,
  onConfirmReview,
  onLoadMemoryUpdates,
  onApplyMemoryUpdate,
  onGoWriting,
  repairingReviewId,
  runLoading,
  confirmLoading,
  memoryLoading,
  memoryApplyLoadingId
}: {
  chapters: Chapter[];
  reviews: ReviewItem[];
  activeReview?: ReviewItem;
  memoryUpdates: MemoryUpdateItem[];
  onReviewChange: (id: string) => void;
  onApplyRepair: (
    review: ReviewItem,
    repairText: string,
    options?: { stayOnReview?: boolean; silent?: boolean }
  ) => void | Promise<void>;
  onRunReview: () => void | Promise<void>;
  onConfirmReview: (review: ReviewItem, options?: { silent?: boolean }) => void | Promise<void>;
  onLoadMemoryUpdates: (chapterId: string) => unknown;
  onApplyMemoryUpdate: (update: MemoryUpdateItem) => void | Promise<void>;
  onGoWriting: () => void;
  repairingReviewId: string | null;
  runLoading: boolean;
  confirmLoading: boolean;
  memoryLoading: boolean;
  memoryApplyLoadingId: string | null;
}) {
  const [repairCandidate, setRepairCandidate] = useState("");
  const [repairCandidateReviewId, setRepairCandidateReviewId] = useState("");
  const [repairCandidatesByReviewId, setRepairCandidatesByReviewId] = useState<Record<string, string>>({});
  const [issueExplanation, setIssueExplanation] = useState("");
  const [issueExplanationReviewId, setIssueExplanationReviewId] = useState("");
  const [selectedReviewIds, setSelectedReviewIds] = useState<string[]>([]);
  const [batchAction, setBatchAction] = useState<"confirm-low-risk" | "confirm-selected" | "repair-selected" | null>(null);
  const [actionError, setActionError] = useState("");
  const [memoryError, setMemoryError] = useState("");
  const [agentAction, setAgentAction] = useState<string | null>(null);
  const activeReviewIdRef = useRef(activeReview?.id ?? "");
  const reviewAiRequestRef = useRef(0);
  const loadMemoryUpdatesRef = useRef(onLoadMemoryUpdates);
  const reviewSummary = useMemo(() => ({
    pendingCount: reviews.filter((review) => review.status !== "已确认").length,
    highPriorityCount: reviews.filter((review) => review.priority === "高").length,
    confirmedCount: reviews.filter((review) => review.status === "已确认").length
  }), [reviews]);
  const chapterTitleById = useMemo(() => new Map(chapters.map((chapter) => [chapter.id, chapter.title])), [chapters]);
  const selectedReviewSet = useMemo(() => new Set(selectedReviewIds), [selectedReviewIds]);
  const pendingReviews = useMemo(() => reviews.filter((review) => review.status !== "已确认"), [reviews]);
  const lowRiskReviews = useMemo(() => pendingReviews.filter((review) => review.priority === "低"), [pendingReviews]);
  const selectedReviews = useMemo(
    () => reviews.filter((review) => selectedReviewSet.has(review.id)),
    [reviews, selectedReviewSet]
  );
  const selectedPendingReviews = useMemo(
    () => selectedReviews.filter((review) => review.status !== "已确认"),
    [selectedReviews]
  );
  const selectedRepairableReviews = useMemo(
    () => selectedPendingReviews.filter((review) => Boolean(repairCandidatesByReviewId[review.id]?.trim())),
    [repairCandidatesByReviewId, selectedPendingReviews]
  );
  const visibleRepairCandidate =
    activeReview ? repairCandidatesByReviewId[activeReview.id] ?? (repairCandidateReviewId === activeReview.id ? repairCandidate : "") : "";
  const visibleIssueExplanation =
    activeReview && issueExplanationReviewId === activeReview.id ? issueExplanation : "";
  const canApplyRepair = Boolean(activeReview && visibleRepairCandidate.trim());
  const activeChapter = activeReview ? chapters.find((chapter) => chapter.id === activeReview.chapterId) : undefined;
  const activeRepairPreview =
    activeReview && visibleRepairCandidate
      ? buildRepairPreview(activeChapter?.content ?? "", visibleRepairCandidate)
      : null;
  const visibleMemoryUpdates = activeReview
    ? memoryUpdates.filter((item) => item.chapterId === activeReview.chapterId)
    : [];

  useEffect(() => {
    loadMemoryUpdatesRef.current = onLoadMemoryUpdates;
  }, [onLoadMemoryUpdates]);

  useEffect(() => {
    if (!activeReview) {
      return;
    }
    const requestReviewId = activeReview.id;
    activeReviewIdRef.current = requestReviewId;
    setMemoryError("");
    void Promise.resolve(loadMemoryUpdatesRef.current(activeReview.chapterId)).catch((error) => {
      if (activeReviewIdRef.current === requestReviewId) {
        setMemoryError(authorText(error instanceof Error ? error.message : "记忆更新候选加载失败，请稍后重试。"));
      }
    });
  }, [activeReview?.chapterId, activeReview?.id]);

  useEffect(() => {
    activeReviewIdRef.current = activeReview?.id ?? "";
    reviewAiRequestRef.current += 1;
    clearReviewAiDrafts();
    setActionError("");
    setMemoryError("");
    setAgentAction(null);
  }, [activeReview?.id]);

  useEffect(() => {
    const liveReviewIds = new Set(reviews.map((review) => review.id));
    setSelectedReviewIds((current) => current.filter((id) => liveReviewIds.has(id)));
  }, [reviews]);

  function clearReviewAiDrafts() {
    setRepairCandidate("");
    setRepairCandidateReviewId("");
    setIssueExplanation("");
    setIssueExplanationReviewId("");
  }

  async function explainReviewIssue() {
    if (!activeReview) {
      return;
    }
    const requestReviewId = activeReview.id;
    const requestId = reviewAiRequestRef.current + 1;
    reviewAiRequestRef.current = requestId;
    const isCurrentRequest = () => activeReviewIdRef.current === requestReviewId && reviewAiRequestRef.current === requestId;
    setAgentAction("explain");
    setActionError("");
    try {
      const response = await workbenchClient.runAgentAssist({
        bookId: activeReview.bookId,
        reviewId: activeReview.id,
        scope: "review",
        action: "解释问题",
        input: buildReviewAssistContext(activeReview, chapterTitleById)
      });
      if (!isCurrentRequest()) {
        return;
      }
      setIssueExplanation(response.content || response.candidateText || "");
      setIssueExplanationReviewId(requestReviewId);
      message.success("AI 已生成作者语言解释。");
    } catch (error) {
      if (isCurrentRequest()) {
        setActionError(authorText(error instanceof Error ? error.message : "AI 解释失败，请稍后重试。"));
      }
    } finally {
      if (isCurrentRequest()) {
        setAgentAction(null);
      }
    }
  }

  async function createRepairCandidate() {
    if (!activeReview) {
      return;
    }
    const requestReviewId = activeReview.id;
    const requestId = reviewAiRequestRef.current + 1;
    reviewAiRequestRef.current = requestId;
    const isCurrentRequest = () => activeReviewIdRef.current === requestReviewId && reviewAiRequestRef.current === requestId;
    setAgentAction("repair");
    setActionError("");
    try {
      const response = await workbenchClient.runAgentAssist({
        bookId: activeReview.bookId,
        reviewId: activeReview.id,
        scope: "review",
        action: "生成修复方案",
        input: buildReviewAssistContext(activeReview, chapterTitleById)
      });
      if (!isCurrentRequest()) {
        return;
      }
      const candidate = response.candidateText ?? response.content;
      setRepairCandidate(candidate);
      setRepairCandidateReviewId(requestReviewId);
      setRepairCandidatesByReviewId((current) => ({
        ...current,
        [requestReviewId]: candidate
      }));
      setActionError("");
      message.success("AI 已生成审稿修复候选，可确认应用。");
    } catch (error) {
      if (isCurrentRequest()) {
        setActionError(authorText(error instanceof Error ? error.message : "AI 修复候选生成失败，请稍后重试。"));
      }
    } finally {
      if (isCurrentRequest()) {
        setAgentAction(null);
      }
    }
  }

  function isReviewAiActionDisabled(action: "explain" | "repair") {
    return Boolean((agentAction && agentAction !== action) || runLoading || confirmLoading || repairingReviewId === activeReview?.id);
  }

  async function applyRepairCandidate() {
    if (!activeReview) {
      setActionError("当前没有可应用的审稿项。");
      return;
    }
    const requestReviewId = activeReview.id;
    const normalizedCandidate = normalizeRepairCandidate(visibleRepairCandidate);
    if (!normalizedCandidate) {
      setActionError("请先生成修复候选，再应用到章节草稿。");
      return;
    }
    setActionError("");
    try {
      await onApplyRepair(activeReview, normalizedCandidate);
      if (activeReviewIdRef.current === requestReviewId) {
        setRepairCandidate("");
        setRepairCandidateReviewId("");
        setRepairCandidatesByReviewId((current) => {
          const next = { ...current };
          delete next[requestReviewId];
          return next;
        });
      }
    } catch (error) {
      if (activeReviewIdRef.current === requestReviewId) {
        setActionError(authorText(error instanceof Error ? error.message : "修复候选应用失败，请稍后重试。"));
      }
    }
  }

  async function confirmActiveReview() {
    if (!activeReview) {
      setActionError("当前没有可确认的审稿项。");
      return;
    }
    const requestReviewId = activeReview.id;
    setActionError("");
    try {
      await onConfirmReview(activeReview);
      if (activeReviewIdRef.current === requestReviewId) {
        clearReviewAiDrafts();
        setRepairCandidatesByReviewId((current) => {
          const next = { ...current };
          delete next[requestReviewId];
          return next;
        });
      }
    } catch (error) {
      if (activeReviewIdRef.current === requestReviewId) {
        setActionError(authorText(error instanceof Error ? error.message : "审稿项确认失败，请稍后重试。"));
      }
    }
  }

  async function rerunReview() {
    clearReviewAiDrafts();
    setRepairCandidatesByReviewId({});
    setSelectedReviewIds([]);
    setAgentAction(null);
    setActionError("");
    try {
      await onRunReview();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "重新审稿失败，请稍后重试。"));
    }
  }

  async function applyMemoryUpdateCandidate(update: MemoryUpdateItem) {
    const requestReviewId = activeReview?.id ?? "";
    setMemoryError("");
    try {
      await onApplyMemoryUpdate(update);
    } catch (error) {
      if (activeReviewIdRef.current === requestReviewId) {
        setMemoryError(authorText(error instanceof Error ? error.message : "记忆更新应用失败，请稍后重试。"));
      }
    }
  }

  function toggleReviewSelection(reviewId: string, checked: boolean) {
    setSelectedReviewIds((current) =>
      checked
        ? Array.from(new Set([...current, reviewId]))
        : current.filter((id) => id !== reviewId)
    );
  }

  function toggleAllPendingReviews(checked: boolean) {
    setSelectedReviewIds(checked ? pendingReviews.map((review) => review.id) : []);
  }

  async function confirmLowRiskReviews() {
    await confirmReviewBatch(lowRiskReviews, "confirm-low-risk", "低风险审稿项已批量确认。");
  }

  async function confirmSelectedReviews() {
    await confirmReviewBatch(selectedPendingReviews, "confirm-selected", "选中审稿项已批量确认。");
  }

  async function confirmReviewBatch(
    targetReviews: ReviewItem[],
    action: "confirm-low-risk" | "confirm-selected",
    successText: string
  ) {
    if (!targetReviews.length) {
      setActionError("当前没有可批量确认的审稿项。");
      return;
    }
    setBatchAction(action);
    setActionError("");
    try {
      for (const review of targetReviews) {
        await onConfirmReview(review, { silent: true });
      }
      setSelectedReviewIds((current) => current.filter((id) => !targetReviews.some((review) => review.id === id)));
      message.success(successText);
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "批量确认失败，请稍后重试。"));
    } finally {
      setBatchAction(null);
    }
  }

  async function applySelectedRepairCandidates() {
    if (!selectedRepairableReviews.length) {
      setActionError("选中审稿项里还没有可应用的修复候选。");
      return;
    }
    setBatchAction("repair-selected");
    setActionError("");
    try {
      for (const review of selectedRepairableReviews) {
        const candidate = normalizeRepairCandidate(repairCandidatesByReviewId[review.id] ?? "");
        if (candidate) {
          await onApplyRepair(review, candidate, { stayOnReview: true, silent: true });
        }
      }
      setRepairCandidatesByReviewId((current) => {
        const next = { ...current };
        for (const review of selectedRepairableReviews) {
          delete next[review.id];
        }
        return next;
      });
      setSelectedReviewIds((current) => current.filter((id) => !selectedRepairableReviews.some((review) => review.id === id)));
      message.success("选中审稿项的修复候选已批量应用。");
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "批量修复失败，请稍后重试。"));
    } finally {
      setBatchAction(null);
    }
  }

  return (
    <div className="page-grid responsive-detail-page review-page-grid">
      <section className="main-column">
        <MetricGrid compact items={[
          { label: "待处理", value: reviewSummary.pendingCount },
          { label: "高优先级", value: reviewSummary.highPriorityCount },
          { label: "已确认", value: reviewSummary.confirmedCount }
        ]} />
        {reviews.length ? (
          <div className="review-batch-toolbar">
            <Checkbox
              checked={pendingReviews.length > 0 && selectedPendingReviews.length === pendingReviews.length}
              indeterminate={selectedPendingReviews.length > 0 && selectedPendingReviews.length < pendingReviews.length}
              onChange={(event) => toggleAllPendingReviews(event.target.checked)}
            >
              已选 {selectedPendingReviews.length} 条
            </Checkbox>
            <Space wrap>
              <Button
                icon={<CheckCircleOutlined />}
                loading={batchAction === "confirm-low-risk"}
                disabled={!lowRiskReviews.length || Boolean(agentAction) || Boolean(batchAction)}
                onClick={() => void confirmLowRiskReviews()}
              >
                批量接受低风险建议
              </Button>
              <Button
                icon={<CheckCircleOutlined />}
                loading={batchAction === "confirm-selected"}
                disabled={!selectedPendingReviews.length || Boolean(agentAction) || Boolean(batchAction)}
                onClick={() => void confirmSelectedReviews()}
              >
                批量确认选中
              </Button>
              <Button
                icon={<HighlightOutlined />}
                loading={batchAction === "repair-selected"}
                disabled={!selectedRepairableReviews.length || Boolean(agentAction) || Boolean(batchAction)}
                onClick={() => void applySelectedRepairCandidates()}
              >
                批量应用修复
              </Button>
            </Space>
          </div>
        ) : null}
        {reviews.length ? (
          <div className="review-list">
            {reviews.map((review) => (
              <div
                className={`review-list-row ${review.id === activeReview?.id ? "active" : ""}`}
                key={review.id}
              >
                <Checkbox
                  checked={selectedReviewSet.has(review.id)}
                  disabled={review.status === "已确认"}
                  onChange={(event) => toggleReviewSelection(review.id, event.target.checked)}
                />
                <button className="timeline-button" onClick={() => onReviewChange(review.id)}>
                  <Flex justify="space-between" gap={12} align="start">
                    <div className="min-w-0">
                      <Text strong className="review-list-title">{authorText(review.title)}</Text>
                      <Space wrap size={[4, 4]} className="review-list-meta">
                        <Tag color={review.status === "已确认" ? "success" : "warning"}>{authorText(review.status)}</Tag>
                        <Tag color={review.priority === "高" ? "red" : "blue"}>优先级 {authorText(review.priority)}</Tag>
                      </Space>
                    </div>
                    <Tag className="review-chapter-tag">{authorText(chapterTitleById.get(review.chapterId) ?? "对应章节")}</Tag>
                  </Flex>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <Card className="content-card" variant="borderless">
            <Empty description="当前没有审稿项">
              <Button type="primary" icon={<ExperimentOutlined />} loading={runLoading} onClick={rerunReview}>
                运行一次审稿
              </Button>
            </Empty>
          </Card>
        )}
      </section>
      <aside className="side-column">
        <Card className="side-card" variant="borderless">
          {activeReview ? (
            <>
              <Badge status={activeReview.status === "已确认" ? "success" : "warning"} text={authorText(activeReview.status)} />
              <Title level={4}>{authorText(activeReview.title)}</Title>
              <Space wrap className="review-detail-tags">
                <Tag>{authorText(chapterTitleById.get(activeReview.chapterId) ?? "对应章节")}</Tag>
                <Tag color={activeReview.priority === "高" ? "red" : "blue"}>优先级 {authorText(activeReview.priority)}</Tag>
              </Space>
              <Collapse
                ghost
                className="review-chapter-collapse"
                items={[{
                  key: "content",
                  label: "章节内容（前 500 字）",
                  children: (
                    <>
                      <Paragraph className="chapter-preview-text">
                        {authorText((activeChapter?.content ?? "").slice(0, 500))}
                      </Paragraph>
                      {(activeChapter?.content.length ?? 0) > 500 ? (
                        <Button type="link" size="small" onClick={onGoWriting}>
                          查看全文
                        </Button>
                      ) : null}
                    </>
                  )
                }]}
              />
              <Paragraph>{authorText(activeReview.suggestion)}</Paragraph>
              {actionError ? (
                <Alert
                  type="error"
                  showIcon
                  message="审稿操作未完成"
                  description={authorText(actionError)}
                />
              ) : null}
              {visibleIssueExplanation ? (
                <>
                  <Divider />
                  <Text type="secondary">AI 解释</Text>
                  <Paragraph className="candidate-text">{authorText(visibleIssueExplanation)}</Paragraph>
                </>
              ) : null}
              <Divider />
              <div className="review-focus-section">
                <Text type="secondary">审阅重点</Text>
                <Space wrap className="tag-block">
                  {activeReview.focus.map((item) => (
                    <Tag key={item}>{authorText(item)}</Tag>
                  ))}
                </Space>
              </div>
              <Divider />
              <Space direction="vertical" className="wide">
                <Button block icon={<ExperimentOutlined />} loading={agentAction === "explain"} disabled={isReviewAiActionDisabled("explain") || Boolean(batchAction)} onClick={explainReviewIssue}>
                  AI 解释问题
                </Button>
                <Button block icon={<HighlightOutlined />} loading={agentAction === "repair"} disabled={isReviewAiActionDisabled("repair") || Boolean(batchAction)} onClick={createRepairCandidate}>
                  AI 生成修复方案
                </Button>
                <Button block type="primary" icon={<CheckCircleOutlined />} disabled={!canApplyRepair || Boolean(agentAction) || Boolean(batchAction)} loading={repairingReviewId === activeReview.id} onClick={applyRepairCandidate}>
                  应用修复候选
                </Button>
                <Button
                  block
                  icon={<CheckCircleOutlined />}
                  disabled={activeReview.status === "已确认" || Boolean(agentAction) || Boolean(batchAction) || repairingReviewId === activeReview.id}
                  loading={confirmLoading}
                  onClick={confirmActiveReview}
                >
                  {activeReview.status === "已确认" ? "审稿项已确认" : "确认审稿项"}
                </Button>
                <Button block icon={<ExperimentOutlined />} loading={runLoading} disabled={Boolean(agentAction) || Boolean(batchAction) || repairingReviewId === activeReview.id || confirmLoading} onClick={rerunReview}>
                  重新审稿
                </Button>
              </Space>
            </>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前书还没有可处理的审稿项">
              <Button type="primary" icon={<ExperimentOutlined />} loading={runLoading} onClick={rerunReview}>
                运行一次审稿
              </Button>
            </Empty>
          )}
        </Card>
      </aside>
      <section className="review-candidate-column">
        <Card className="side-card candidate-card" variant="borderless">
          <Text type="secondary">AI 修复候选</Text>
          {visibleRepairCandidate && activeReview ? (
            <Paragraph className="muted-text review-candidate-source">
              来源：{authorText(activeReview.title)}
            </Paragraph>
          ) : null}
          {visibleRepairCandidate ? (
            <div className="review-repair-preview">
              {activeRepairPreview?.currentExcerpt ? (
                <div className="review-preview-block">
                  <Text type="secondary">当前草稿末段</Text>
                  <Paragraph>{authorText(activeRepairPreview.currentExcerpt)}</Paragraph>
                </div>
              ) : null}
              <div className="review-preview-block review-preview-candidate">
                <Text type="secondary">建议修改为</Text>
                <Paragraph className="candidate-text">{authorText(activeRepairPreview?.candidateExcerpt ?? visibleRepairCandidate)}</Paragraph>
              </div>
            </div>
          ) : (
            <Paragraph className="muted-text">
              先生成修复方案，这里会保留一份可审阅的修改候选。
            </Paragraph>
          )}
          <Divider />
          <Text type="secondary">长期记忆建议（可选）</Text>
          <Paragraph className="muted-text">
            这些建议用于把本章确认过的事实、人物变化和伏笔写入后续章节会读取的长期记忆。
          </Paragraph>
          {memoryError ? (
            <Alert
              type="error"
              showIcon
              message="记忆更新候选加载失败"
              description={authorText(memoryError)}
            />
          ) : null}
          {visibleMemoryUpdates.length ? (
            <List
              className="dense-list"
              loading={memoryLoading}
              dataSource={visibleMemoryUpdates}
              renderItem={(item) => (
                <List.Item className="model-action-item">
                  <div className="wide">
                    <Flex vertical gap={8}>
                      <Flex justify="space-between" align="start" gap={12}>
                        <div className="min-w-0">
                          <Text strong>{authorText(item.title)}</Text>
                          <Paragraph className="muted-text">{authorText(item.summary)}</Paragraph>
                        </div>
                        <Tag color={item.status === "applied" ? "success" : item.canApply ? "blue" : "default"}>
                          {authorText(item.statusLabel)}
                        </Tag>
                      </Flex>
                      <Space wrap className="tag-block">
                        <Tag>{authorText(item.targetLabel)}</Tag>
                        <Tag>{authorText(item.actionLabel)}</Tag>
                        {item.evidence.map((evidence, index) => (
                          <Tag key={`${item.id}-${index}`}>证据 {index + 1}</Tag>
                        ))}
                      </Space>
                      {item.blockedReason ? <Text type="secondary">{authorText(item.blockedReason)}</Text> : null}
                      <Button
                        block
                        icon={<CheckCircleOutlined />}
                        disabled={!item.canApply || item.status === "applied"}
                        loading={memoryApplyLoadingId === item.id}
                        onClick={() => void applyMemoryUpdateCandidate(item)}
                      >
                        {item.status === "applied"
                          ? "已写入长期记忆"
                          : item.canApply
                            ? "写入长期记忆"
                            : "当前不可写入"}
                      </Button>
                    </Flex>
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Paragraph className="muted-text">
              当前章节还没有可直接写入长期记忆的候选，先完成修复或重新审稿。
            </Paragraph>
          )}
        </Card>
      </section>
    </div>
  );
}

function buildReviewAssistContext(review: ReviewItem, chapterTitleById: Map<string, string>) {
  return [
    `审稿项：${review.title}`,
    `章节：${chapterTitleById.get(review.chapterId) ?? "对应章节"}`,
    `状态：${review.status}`,
    `优先级：${review.priority}`,
    `重点：${review.focus.join("、") || "无"}`,
    `建议：${review.suggestion}`
  ].join("\n");
}

function normalizeRepairCandidate(value: string) {
  return value.replace(/^【[^】]+】\n?/, "").trim();
}

function buildRepairPreview(currentText: string, repairText: string) {
  const beforeLines = currentText.trim().split(/\r?\n/).filter(Boolean).slice(-6);
  const repairLines = normalizeRepairCandidate(repairText).split(/\r?\n/).filter(Boolean);
  if (!repairLines.length) {
    return null;
  }
  return {
    currentExcerpt: beforeLines.join("\n"),
    candidateExcerpt: repairLines.join("\n")
  };
}
