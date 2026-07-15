import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Button, Card, Divider, Flex, Input, List, message, Space, Tag, Typography } from "antd";
import { ClockCircleOutlined, ExperimentOutlined, FileSearchOutlined, NodeIndexOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { advancedWorkbenchClient } from "../api/advancedWorkbenchClient";
import type {
  BookDiffSummaryResponse,
  BookDiagnosticsResponse,
  LibraryRelationshipDetailResponse,
  LibraryRelationshipEdge,
  LibraryRelationshipsResponse,
  LibraryTimelineResponse,
  ModelQualityDistributionResponse,
  ModelTrainingReadiness
} from "../api/advancedContracts";
import { authorText } from "../utils/authorText";
import { statusLabel } from "../utils/statusLabel";

const { Text, Title, Paragraph } = Typography;

type AdvancedReadOnlyPanelProps<T> = {
  title: string;
  description: string;
  loadText: string;
  successText?: string;
  modeLabel?: string;
  icon: ReactNode;
  resetKey: string;
  onLoad: () => Promise<T>;
  render: (data: T) => ReactNode;
};

function AdvancedReadOnlyPanel<T>({
  title,
  description,
  loadText,
  successText,
  modeLabel = "高级 · 只读",
  icon,
  resetKey,
  onLoad,
  render
}: AdvancedReadOnlyPanelProps<T>) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<T | null>(null);
  const [requested, setRequested] = useState(false);
  const requestRef = useRef(0);
  const onLoadRef = useRef(onLoad);

  useEffect(() => {
    onLoadRef.current = onLoad;
  }, [onLoad]);

  useEffect(() => {
    requestRef.current += 1;
    setLoading(false);
    setError("");
    setData(null);
    setRequested(false);
  }, [resetKey]);

  useEffect(() => {
    if (!open || data || loading || requested) {
      return;
    }
    async function load() {
      const requestId = requestRef.current + 1;
      requestRef.current = requestId;
      setRequested(true);
      setLoading(true);
      setError("");
      try {
        const result = await onLoadRef.current();
        if (requestRef.current === requestId) {
          setData(result);
          if (successText) {
            message.success(successText);
          }
        }
      } catch (loadError) {
        if (requestRef.current === requestId) {
          setError(loadError instanceof Error ? loadError.message : "高级能力加载失败。");
        }
      } finally {
        if (requestRef.current === requestId) {
          setLoading(false);
        }
      }
    }
    void load();
  }, [data, loading, open, requested, successText]);

  function toggleOpen() {
    setOpen((value) => {
      const nextOpen = !value;
      if (!nextOpen) {
        setError("");
        setRequested(false);
      }
      return nextOpen;
    });
  }

  function retryLoad() {
    setError("");
    setData(null);
    setRequested(false);
  }

  return (
    <Card className="side-card advanced-panel" variant="borderless">
      <Flex justify="space-between" align="start" gap={16} className="advanced-panel-head">
        <div className="min-w-0">
          <Text type="secondary">{modeLabel}</Text>
          <Title level={5}>{title}</Title>
          <Paragraph className="muted-text">{description}</Paragraph>
        </div>
        <Button icon={icon} onClick={toggleOpen}>
          {open ? "收起" : "查看"}
        </Button>
      </Flex>
      {open ? (
        <>
          <Divider />
          {error ? (
            <Alert
              type="warning"
              showIcon
              message={loadText}
              description={authorText(error)}
              action={<Button size="small" onClick={retryLoad}>重试</Button>}
            />
          ) : null}
          {loading ? <Text type="secondary">正在加载...</Text> : null}
          {!loading && data && successText ? (
            <Alert
              type="success"
              showIcon
              message={successText}
            />
          ) : null}
          {!loading && data ? render(data) : null}
        </>
      ) : null}
    </Card>
  );
}

export function ModelTrainingReadinessPanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<ModelTrainingReadiness>
      title="训练就绪检查"
      description="查看当前书是否具备离线增强的样本基础。"
      loadText="训练就绪检查失败"
      successText="训练就绪检查已加载。"
      icon={<ExperimentOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchModelTrainingReadiness(bookId)}
      render={(data) => (
        <Space direction="vertical" size={10} className="wide">
          <Space wrap>
            <Tag color={data.status === "ready" ? "success" : data.status === "block" ? "error" : "warning"}>{statusLabel(data.status)}</Tag>
            <Tag>可用 {data.eligibleCount} 章</Tag>
            <Tag>跳过 {data.skippedCount} 章</Tag>
            <Tag>建议 {data.minRecommendedExamples} 章</Tag>
          </Space>
          <Alert
            type={data.status === "ready" ? "success" : "warning"}
            showIcon
            message={authorText(data.maturity || "训练只适合作为高质量样本后的离线增强。")}
          />
          <Paragraph className="muted-text">{authorText(data.recommendedNextAction || "暂无建议。")}</Paragraph>
          <List
            size="small"
            dataSource={[...data.checks, ...data.warnings].slice(0, 5)}
            locale={{ emptyText: "暂无训练就绪提示。" }}
            renderItem={(item) => <List.Item>{authorText(item)}</List.Item>}
          />
          <List
            size="small"
            dataSource={data.items.slice(0, 5)}
            locale={{ emptyText: "暂无可评估章节样本。" }}
            renderItem={(item) => (
              <List.Item>
                <div className="advanced-list-item">
                  <Text strong>{authorText(item.chapterId)}</Text>
                  <Space wrap>
                    <Tag color={item.eligible ? "success" : "warning"}>{item.eligible ? "可训练" : "跳过"}</Tag>
                    <Tag>质量 {item.qualityScore}</Tag>
                    <Tag>检查 {statusLabel(item.gateStatus)}</Tag>
                    <Tag>重复 {Math.round(item.previousSimilarity * 100)}%</Tag>
                  </Space>
                  <Text type="secondary">
                    {item.eligible ? "已通过训练样本准入" : authorText(item.reasonLabel || "未通过训练样本准入")}
                    {item.issueCount ? ` · 问题 ${item.issueCount} 个` : ""}
                  </Text>
                  <Text type="secondary">{authorText(item.actionSuggestion || "继续积累稳定样本。")}</Text>
                </div>
              </List.Item>
            )}
          />
        </Space>
      )}
    />
  );
}

export function ModelQualityDistributionPanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<ModelQualityDistributionResponse>
      title="质量分布"
      description="查看章节质量分、训练准入和相似度分布。"
      loadText="质量分布加载失败"
      successText="质量分布已加载。"
      icon={<FileSearchOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchModelQualityDistribution(bookId)}
      render={(data) => <QualityDistributionContent data={data} />}
    />
  );
}

function QualityDistributionContent({ data }: { data: ModelQualityDistributionResponse }) {
  const defaultThreshold = Math.max(0, Math.min(100, Number(data.currentThresholds.min_recommended_score) || 70));
  const [threshold, setThreshold] = useState(defaultThreshold);
  const items = data.items;
  const previewEligible = items.filter((item) => item.score >= threshold && item.gateStatus === "pass").length;
  const buckets = qualityBuckets(items);
  const maxBucketCount = Math.max(1, ...buckets.map((bucket) => bucket.total));

  useEffect(() => {
    setThreshold(defaultThreshold);
  }, [defaultThreshold, data.bookId]);

  return (
    <Space direction="vertical" size={12} className="wide">
      <Space wrap>
        <Tag>章节 {items.length}</Tag>
        <Tag color="success">预览准入 {previewEligible} 章</Tag>
        <Tag>阈值 {threshold}</Tag>
      </Space>
      <div className="quality-threshold-control">
        <Flex justify="space-between" align="center" gap={10}>
          <Text type="secondary">质量阈值</Text>
          <Text strong>{threshold}</Text>
        </Flex>
        <input
          aria-label="质量阈值"
          className="quality-threshold-range"
          type="range"
          min={0}
          max={100}
          step={5}
          value={threshold}
          onChange={(event) => setThreshold(Number(event.target.value))}
        />
      </div>
      <div className="quality-bar-chart">
        {buckets.map((bucket) => (
          <div key={bucket.score} className="quality-bar-column">
            <div className="quality-bar-track">
              <div
                className="quality-bar-fill eligible"
                style={{ height: `${(bucket.eligible / maxBucketCount) * 100}%` }}
              />
              <div
                className="quality-bar-fill skipped"
                style={{ height: `${(bucket.skipped / maxBucketCount) * 100}%` }}
              />
              <div
                className="quality-bar-fill blocked"
                style={{ height: `${(bucket.blocked / maxBucketCount) * 100}%` }}
              />
            </div>
            <Text type="secondary">{bucket.score}</Text>
          </div>
        ))}
      </div>
      <div className="quality-scatter">
        {items.map((item) => (
          <span
            key={item.chapterId}
            className={`quality-scatter-point ${item.eligible ? "eligible" : item.gateStatus === "block" ? "blocked" : "skipped"}`}
            style={{
              left: `${Math.max(0, Math.min(100, item.score))}%`,
              bottom: `${Math.max(0, Math.min(100, item.similarity * 100))}%`
            }}
            title={`${item.chapterId} · score ${item.score} · similarity ${Math.round(item.similarity * 100)}%`}
          />
        ))}
      </div>
      <List
        size="small"
        dataSource={items.slice(0, 5)}
        locale={{ emptyText: "暂无质量分布数据。" }}
        renderItem={(item) => (
          <List.Item>
            <div className="advanced-list-item">
              <Text strong>{authorText(item.chapterId)}</Text>
              <Space wrap>
                <Tag color={item.eligible ? "success" : "warning"}>{item.eligible ? "可训练" : "跳过"}</Tag>
                <Tag>质量 {item.score}</Tag>
                <Tag>重复 {Math.round(item.similarity * 100)}%</Tag>
                {item.label ? <Tag color="blue">{authorText(item.label)}</Tag> : null}
              </Space>
            </div>
          </List.Item>
        )}
      />
    </Space>
  );
}

function qualityBuckets(items: ModelQualityDistributionResponse["items"]) {
  return Array.from({ length: 21 }, (_, index) => {
    const score = index * 5;
    const bucketItems = items.filter((item) => Math.floor(Math.max(0, Math.min(100, item.score)) / 5) * 5 === score);
    return {
      score,
      eligible: bucketItems.filter((item) => item.eligible).length,
      blocked: bucketItems.filter((item) => item.gateStatus === "block").length,
      skipped: bucketItems.filter((item) => !item.eligible && item.gateStatus !== "block").length,
      total: bucketItems.length
    };
  });
}

export function LibraryRelationshipsPanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<LibraryRelationshipsResponse>
      title="资料关系洞察"
      description="查看人物或资料关系摘要。"
      loadText="资料关系加载失败"
      modeLabel="高级 · 可编辑关系标签"
      icon={<NodeIndexOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchLibraryRelationships(bookId)}
      render={(data) => <LibraryRelationshipsContent bookId={bookId} data={data} />}
    />
  );
}

function LibraryRelationshipsContent({
  bookId,
  data
}: {
  bookId: string;
  data: LibraryRelationshipsResponse;
}) {
  const [selectedEdge, setSelectedEdge] = useState<LibraryRelationshipEdge | null>(null);
  const [detail, setDetail] = useState<LibraryRelationshipDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const detailRequestRef = useRef(0);

  async function loadDetail(edge: LibraryRelationshipEdge) {
    if (!edge.id) {
      return;
    }
    const requestId = detailRequestRef.current + 1;
    detailRequestRef.current = requestId;
    setSelectedEdge(edge);
    setDetail(null);
    setDetailError("");
    setDetailLoading(true);
    try {
      const nextDetail = await advancedWorkbenchClient.fetchLibraryRelationshipDetail(bookId, edge.id);
      if (detailRequestRef.current === requestId) {
        setDetail(nextDetail);
      }
    } catch (error) {
      if (detailRequestRef.current === requestId) {
        setDetailError(error instanceof Error ? error.message : "关系详情加载失败。");
      }
    } finally {
      if (detailRequestRef.current === requestId) {
        setDetailLoading(false);
      }
    }
  }

  return (
    <Space direction="vertical" size={10} className="wide">
      <Space wrap>
        <Tag>节点 {data.nodeCount}</Tag>
        <Tag>关系 {data.edgeCount}</Tag>
      </Space>
      <List
        size="small"
        dataSource={data.edges.slice(0, 6)}
        locale={{ emptyText: "当前书还没有可展示的关系。" }}
        renderItem={(edge) => (
          <List.Item
            actions={[
              <Button
                key="detail"
                size="small"
                disabled={!edge.id}
                loading={detailLoading && selectedEdge?.id === edge.id}
                onClick={() => loadDetail(edge)}
              >
                详情
              </Button>
            ]}
          >
            <div className="advanced-list-item">
              <Text strong>{authorText(edge.fromLabel || "未命名")} 到 {authorText(edge.toLabel || "未命名")}</Text>
              <Text type="secondary">
                {authorText(edge.type || "关系")} · {authorText(edge.status || "状态待补")} · {authorText(edge.chapterLabel || "-")}
              </Text>
            </div>
          </List.Item>
        )}
      />
      {detailError ? (
        <Alert
          type="warning"
          showIcon
          message="关系详情加载失败"
          description={authorText(detailError)}
          action={
            selectedEdge ? (
              <Button size="small" loading={detailLoading} onClick={() => loadDetail(selectedEdge)}>
                重试
              </Button>
            ) : null
          }
        />
      ) : null}
      {detail ? <LibraryRelationshipDetail detail={detail} /> : null}
    </Space>
  );
}

function LibraryRelationshipDetail({ detail }: { detail: LibraryRelationshipDetailResponse }) {
  const edge = detail.edge;
  const latestEvent = detail.timeline[detail.timeline.length - 1];
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [type, setType] = useState(edge.type);
  const [status, setStatus] = useState(latestEvent?.status || edge.status);
  const [pressure, setPressure] = useState(latestEvent?.pressure || edge.pressure);
  const [unresolvedEmotion, setUnresolvedEmotion] = useState(
    latestEvent?.unresolvedEmotion || edge.unresolvedEmotion
  );

  useEffect(() => {
    setEditing(false);
    setType(edge.type);
    setStatus(latestEvent?.status || edge.status);
    setPressure(latestEvent?.pressure || edge.pressure);
    setUnresolvedEmotion(latestEvent?.unresolvedEmotion || edge.unresolvedEmotion);
  }, [detail.bookId, edge.id, latestEvent?.id]);

  async function saveRelationshipLabels() {
    if (!latestEvent?.id || !status.trim()) {
      return;
    }
    setSaving(true);
    try {
      const result = await advancedWorkbenchClient.updateLibraryRelationshipEvent(
        detail.bookId,
        latestEvent.id,
        {
          type: type.trim() || "关系",
          status: status.trim(),
          pressure: pressure.trim(),
          unresolvedEmotion: unresolvedEmotion.trim()
        }
      );
      setType(result.edge?.type || type.trim() || "关系");
      setStatus(result.edge?.status || status.trim());
      setPressure(result.edge?.pressure || pressure.trim());
      setUnresolvedEmotion(result.edge?.unresolvedEmotion || unresolvedEmotion.trim());
      setEditing(false);
      message.success("关系标签已更新。");
    } catch (error) {
      message.error(authorText(error instanceof Error ? error.message : "关系标签更新失败。"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="advanced-detail-panel">
      <Flex justify="space-between" align="center" gap={12}>
        <Text type="secondary">关系详情</Text>
        <Button size="small" disabled={!latestEvent?.id} onClick={() => setEditing((value) => !value)}>
          {editing ? "取消编辑" : "编辑标签"}
        </Button>
      </Flex>
      <Title level={5}>{authorText(edge.fromLabel || "未命名")} 到 {authorText(edge.toLabel || "未命名")}</Title>
      {editing ? (
        <Space direction="vertical" className="wide">
          <Input value={type} onChange={(event) => setType(event.target.value)} placeholder="关系类型，例如竞争、同盟、亲情" />
          <Input value={status} onChange={(event) => setStatus(event.target.value)} placeholder="当前关系状态" />
          <Input value={pressure} onChange={(event) => setPressure(event.target.value)} placeholder="当前关系压力，可留空" />
          <Input.TextArea value={unresolvedEmotion} onChange={(event) => setUnresolvedEmotion(event.target.value)} placeholder="尚未解决的情绪，可留空" autoSize={{ minRows: 2, maxRows: 4 }} />
          <Button type="primary" loading={saving} disabled={!status.trim()} onClick={saveRelationshipLabels}>
            保存关系标签
          </Button>
        </Space>
      ) : (
        <>
          <Space wrap>
            <Tag>{authorText(type || "关系")}</Tag>
            <Tag>{authorText(edge.chapterLabel || "-")}</Tag>
            {pressure ? <Tag>{authorText(pressure)}</Tag> : null}
          </Space>
          {status ? <Paragraph className="muted-text">{authorText(status)}</Paragraph> : null}
          {unresolvedEmotion ? <Paragraph className="muted-text">{authorText(unresolvedEmotion)}</Paragraph> : null}
        </>
      )}
      <List
        size="small"
        dataSource={detail.timeline.slice(0, 4)}
        locale={{ emptyText: "暂无关系时间线。" }}
        renderItem={(item) => (
          <List.Item>
            <div className="advanced-list-item">
              <Text strong>{authorText(item.chapterLabel || "-")}</Text>
              <Text type="secondary">{authorText(item.status || statusLabel(item.transition, "关系状态待补"))}</Text>
              {item.evidenceCount ? (
                <Text type="secondary">证据 {Math.min(item.evidenceCount, 2)} 条</Text>
              ) : null}
              {item.needsReview ? <Tag color="warning">{authorText(item.reviewReason || "需要复核")}</Tag> : null}
            </div>
          </List.Item>
        )}
      />
    </div>
  );
}

export function LibraryTimelinePanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<LibraryTimelineResponse>
      title="资料时间线摘要"
      description="查看当前书已整理的时间线事件。"
      loadText="资料时间线加载失败"
      icon={<ClockCircleOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchLibraryTimeline(bookId)}
      render={(data) => (
        <Space direction="vertical" size={10} className="wide">
          <Space wrap>
            <Tag>事件 {data.eventCount}</Tag>
            <Tag>只读</Tag>
          </Space>
          <List
            size="small"
            dataSource={data.events.slice(0, 6)}
            locale={{ emptyText: "当前书还没有可展示的时间线事件。" }}
            renderItem={(event) => (
              <List.Item>
                <div className="advanced-list-item">
                  <Text strong>{authorText(event.label || event.summary || "未命名事件")}</Text>
                  <Text type="secondary">
                    {authorText(event.chapterLabel || "-")} · {authorText(event.time || "时间待补")}
                  </Text>
                  {event.summary ? <Text type="secondary">{authorText(event.summary)}</Text> : null}
                </div>
              </List.Item>
            )}
          />
        </Space>
      )}
    />
  );
}

export function BookDiagnosticsPanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<BookDiagnosticsResponse>
      title="诊断摘要"
      description="查看当前书最近章节的诊断提示。"
      loadText="诊断加载失败"
      icon={<SafetyCertificateOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchDiagnostics(bookId)}
      render={(data) => (
        <Space direction="vertical" size={10} className="wide">
          <Space wrap>
            <Tag>{authorText(data.chapterLabel || "-")}</Tag>
            <Tag>{data.items.length} 条提示</Tag>
          </Space>
          <Paragraph className="muted-text">{authorText(data.summary || "暂无诊断摘要。")}</Paragraph>
          <List
            size="small"
            dataSource={data.items.slice(0, 6)}
            locale={{ emptyText: "暂无诊断提示。" }}
            renderItem={(item) => <List.Item>{authorText(item)}</List.Item>}
          />
        </Space>
      )}
    />
  );
}

export function BookDiffSummaryPanel({ bookId }: { bookId: string }) {
  return (
    <AdvancedReadOnlyPanel<BookDiffSummaryResponse>
      title="候选差异摘要"
      description="查看当前章节候选稿和正文的差异摘要。"
      loadText="候选差异加载失败"
      icon={<FileSearchOutlined />}
      resetKey={bookId}
      onLoad={() => advancedWorkbenchClient.fetchDiffSummary(bookId)}
      render={(data) => (
        <Space direction="vertical" size={10} className="wide">
          <Space wrap>
            <Tag>{authorText(data.chapterLabel || "-")}</Tag>
            <Tag color={data.changed ? "warning" : "success"}>{data.changed ? "有差异" : "无差异"}</Tag>
            <Tag>新增 {data.additions} 行</Tag>
            <Tag>删除 {data.removals} 行</Tag>
          </Space>
          <Paragraph className="muted-text">{authorText(data.summary || "暂无候选差异摘要。")}</Paragraph>
        </Space>
      )}
    />
  );
}
