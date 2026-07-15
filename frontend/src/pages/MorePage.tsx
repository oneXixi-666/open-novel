import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Divider, Empty, Flex, List, Progress, Segmented, Space, Tag, Typography } from "antd";
import { CloseCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { BookDiagnosticsPanel, BookDiffSummaryPanel } from "../components/AdvancedPanels";
import type { Book, JobSummary, RunSummary } from "../types";
import { authorText } from "../utils/authorText";

const { Text, Title, Paragraph } = Typography;

const jobStatus = {
  运行中: "processing",
  已完成: "success",
  失败: "error",
  等待中: "default"
} as const;

const runStatusColor = {
  成功: "success",
  警告: "warning",
  失败: "error"
} as const;

export function MorePage({
  book,
  jobs,
  runs,
  refreshError,
  actionError,
  onRefresh,
  onLoadJobDetail,
  onCancelJob,
  onRetryJob,
  loadingAction
}: {
  book: Book;
  jobs: JobSummary[];
  runs: RunSummary[];
  refreshError?: string;
  actionError?: string;
  onRefresh: () => void | Promise<void>;
  onLoadJobDetail: (jobId: string) => Promise<unknown>;
  onCancelJob: (jobId: string) => void | Promise<void>;
  onRetryJob: (jobId: string) => void | Promise<void>;
  loadingAction: string | null;
}) {
  const [tab, setTab] = useState("任务");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [localActionError, setLocalActionError] = useState("");
  const expandedJobIdRef = useRef<string | null>(null);
  const activeBookIdRef = useRef(book.id);
  const detailRequestRef = useRef(0);
  const tabOptions = ["任务", "运行记录"];
  const visibleActionError = localActionError || actionError;
  const jobIdsKey = jobs.map((job) => job.id).join("::");
  const operationsSummary = {
    runningJobCount: jobs.filter((job) => job.status === "运行中").length,
    waitingJobCount: jobs.filter((job) => job.status === "等待中").length,
    failedJobCount: jobs.filter((job) => job.status === "失败").length,
    warningRunCount: runs.filter((run) => run.status === "警告").length
  };

  useEffect(() => {
    activeBookIdRef.current = book.id;
    detailRequestRef.current += 1;
    expandedJobIdRef.current = null;
    setExpandedJobId(null);
    setLocalActionError("");
    void Promise.resolve(onRefresh()).catch(() => undefined);
  }, [book.id]);

  useEffect(() => {
    if (!expandedJobId || jobs.some((job) => job.id === expandedJobId)) {
      return;
    }
    detailRequestRef.current += 1;
    expandedJobIdRef.current = null;
    setExpandedJobId(null);
    setLocalActionError("");
  }, [expandedJobId, jobIdsKey, jobs]);

  async function toggleJobDetail(job: JobSummary) {
    const nextExpanded = expandedJobId === job.id ? null : job.id;
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    expandedJobIdRef.current = nextExpanded;
    setExpandedJobId(nextExpanded);
    setLocalActionError("");
    if (nextExpanded && !job.events?.length) {
      try {
        await onLoadJobDetail(job.id);
      } catch (error) {
        if (detailRequestRef.current === requestId && expandedJobIdRef.current === job.id) {
          setLocalActionError(authorText(error instanceof Error ? error.message : "任务详情加载失败，请稍后重试。"));
        }
      }
    }
  }

  function switchTab(value: string) {
    setTab(value);
    setLocalActionError("");
    if (value !== "任务") {
      detailRequestRef.current += 1;
      expandedJobIdRef.current = null;
      setExpandedJobId(null);
    }
  }

  async function cancelJob(jobId: string) {
    const requestBookId = book.id;
    setLocalActionError("");
    try {
      await onCancelJob(jobId);
    } catch (error) {
      if (activeBookIdRef.current === requestBookId) {
        setLocalActionError(authorText(error instanceof Error ? error.message : "任务取消失败，请稍后重试。"));
      }
    }
  }

  async function retryJob(jobId: string) {
    const requestBookId = book.id;
    setLocalActionError("");
    try {
      await onRetryJob(jobId);
    } catch (error) {
      if (activeBookIdRef.current === requestBookId) {
        setLocalActionError(authorText(error instanceof Error ? error.message : "任务重试失败，请稍后重试。"));
      }
    }
  }

  function isJobActionBusy(jobId: string) {
    return Boolean(
      loadingAction === "ops-refresh" ||
      loadingAction === `job-cancel-${jobId}` ||
      loadingAction === `job-retry-${jobId}` ||
      loadingAction === `job-detail-${jobId}`
    );
  }

  return (
    <div className="page-grid responsive-detail-page">
      <section className="main-column">
        <Card className="content-card" variant="borderless">
          <Flex justify="space-between" align="center" gap={16}>
            <div>
              <Text type="secondary">当前书处理状态</Text>
              <Title level={3}>{authorText(book.title)}</Title>
              <Paragraph className="muted-text">
                这里只展示任务和运行记录，方便确认当前书是否还有动作在处理。
              </Paragraph>
            </div>
          </Flex>
          <Divider />
          <Flex justify="space-between" align="center" gap={12} wrap="wrap">
            <Segmented value={tab} onChange={(value) => switchTab(String(value))} options={tabOptions} />
            <Button icon={<ReloadOutlined />} loading={loadingAction === "ops-refresh"} onClick={() => void Promise.resolve(onRefresh()).catch(() => undefined)}>
              刷新
            </Button>
          </Flex>
          {refreshError ? (
            <>
              <Divider />
              <Alert
                type="error"
                showIcon
                message="任务与运行记录刷新失败"
                description={authorText(refreshError)}
              />
            </>
          ) : null}
          {visibleActionError ? (
            <>
              <Divider />
              <Alert
                type="error"
                showIcon
                message="任务操作未完成"
                description={authorText(visibleActionError)}
              />
            </>
          ) : null}
        </Card>

        {tab === "任务" && jobs.length ? (
          <List
            className="dense-list more-list"
            dataSource={jobs}
            locale={{ emptyText: "当前书没有处理任务。" }}
            renderItem={(job) => (
              <List.Item>
                <Card className="content-card wide more-item-card" variant="borderless">
                  <Flex justify="space-between" align="start" gap={16} className="more-item-head">
                    <div className="min-w-0">
                      <Space wrap className="more-item-tags">
                        <Badge status={jobStatus[job.status]} text={authorText(job.status)} />
                        <Tag>{authorText(job.startedAt)}</Tag>
                      </Space>
                      <Title level={4} className="more-item-title">{authorText(job.title)}</Title>
                      <Paragraph ellipsis={{ rows: 2 }} className="muted-text">{authorText(job.result)}</Paragraph>
                    </div>
                    <Space wrap className="more-item-actions">
                      <Button
                        icon={<CloseCircleOutlined />}
                        disabled={(job.status !== "运行中" && job.status !== "等待中") || isJobActionBusy(job.id)}
                        loading={loadingAction === `job-cancel-${job.id}`}
                        onClick={() => void cancelJob(job.id)}
                      >
                        取消
                      </Button>
                      <Button
                        icon={<ReloadOutlined />}
                        disabled={job.status === "运行中" || isJobActionBusy(job.id)}
                        loading={loadingAction === `job-retry-${job.id}`}
                        onClick={() => void retryJob(job.id)}
                      >
                        重试
                      </Button>
                      <Button disabled={loadingAction === "ops-refresh" || loadingAction === `job-cancel-${job.id}` || loadingAction === `job-retry-${job.id}`} loading={loadingAction === `job-detail-${job.id}`} onClick={() => toggleJobDetail(job)}>
                        {expandedJobId === job.id ? "收起" : "详情"}
                      </Button>
                    </Space>
                  </Flex>
                  <JobProgressMeter progress={job.progress} />
                  {expandedJobId === job.id ? (
                    <div className="job-event-stream">
                      <Text type="secondary">事件摘要</Text>
                      <List
                        size="small"
                        loading={loadingAction === `job-detail-${job.id}`}
                        locale={{ emptyText: "等待任务事件摘要。" }}
                        dataSource={(job.events ?? []).slice(0, 5)}
                        renderItem={(event) => (
                          <List.Item>
                            <Text className="job-event-text">{authorText(event)}</Text>
                          </List.Item>
                        )}
                      />
                      {(job.events?.length ?? 0) > 5 ? (
                        <Text type="secondary" className="job-event-more">仅显示最近 5 条摘要。</Text>
                      ) : null}
                    </div>
                  ) : null}
                </Card>
              </List.Item>
            )}
          />
        ) : null}
        {tab === "任务" && !jobs.length ? (
          <Card className="content-card more-empty-card" variant="borderless">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前书没有处理任务" />
          </Card>
        ) : null}

        {tab === "运行记录" && runs.length ? (
          <List
            className="dense-list more-list"
            dataSource={runs}
            locale={{ emptyText: "当前书没有运行记录。" }}
            renderItem={(run) => (
              <List.Item>
                <Card className="content-card wide more-item-card" variant="borderless">
                  <Flex justify="space-between" align="start" gap={16} className="more-item-head">
                    <div className="min-w-0">
                      <Space wrap className="more-item-tags">
                        <Tag>{authorText(run.kind)}</Tag>
                        <Tag color={runStatusColor[run.status]}>{authorText(run.status)}</Tag>
                      </Space>
                      <Title level={4} className="more-item-title">{authorText(run.title)}</Title>
                      <Paragraph ellipsis={{ rows: 2 }} className="muted-text">{authorText(run.summary)}</Paragraph>
                    </div>
                    <Text type="secondary" className="more-item-time">{authorText(run.createdAt)}</Text>
                  </Flex>
                </Card>
              </List.Item>
            )}
          />
        ) : null}
        {tab === "运行记录" && !runs.length ? (
          <Card className="content-card more-empty-card" variant="borderless">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前书没有运行记录" />
          </Card>
        ) : null}
      </section>
      <aside className="side-column">
        <Card className="side-card" variant="borderless">
          <Text type="secondary">任务摘要</Text>
          <Title level={5}>作者视角</Title>
          <Paragraph>这里只保留作者需要判断进度的摘要信息。</Paragraph>
          <Divider />
          <Space direction="vertical" className="wide">
            <Flex justify="space-between"><Text>运行中任务</Text><Text strong>{operationsSummary.runningJobCount}</Text></Flex>
            <Flex justify="space-between"><Text>等待中任务</Text><Text strong>{operationsSummary.waitingJobCount}</Text></Flex>
            <Flex justify="space-between"><Text>失败任务</Text><Text strong>{operationsSummary.failedJobCount}</Text></Flex>
            <Flex justify="space-between"><Text>警告记录</Text><Text strong>{operationsSummary.warningRunCount}</Text></Flex>
          </Space>
        </Card>
        <BookDiffSummaryPanel bookId={book.id} />
        <BookDiagnosticsPanel bookId={book.id} />
      </aside>
    </div>
  );
}

function JobProgressMeter({ progress }: { progress: number }) {
  return (
    <div className="job-progress-meter">
      <Flex justify="space-between" align="center" gap={10}>
        <Text type="secondary">处理进度</Text>
        <strong>{progress}%</strong>
      </Flex>
      <Progress percent={progress} showInfo={false} />
    </div>
  );
}
