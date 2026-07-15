import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Checkbox, Divider, Flex, List, Modal, Progress, Segmented, Select, Space, Tag, Typography } from "antd";
import { CheckCircleOutlined, DownloadOutlined, FileTextOutlined, WarningOutlined } from "@ant-design/icons";
import { MetricGrid } from "../components/shared";
import type { Book, Chapter, ExportKind, ExportReadiness, GenerationState, Material, ReviewItem } from "../types";
import { authorText } from "../utils/authorText";

const { Text, Title, Paragraph } = Typography;

export function ExportPage({
  book,
  activeChapter,
  exports,
  materials,
  reviews,
  generationState,
  onCheckExport,
  onGenerateExport,
  checking,
  generating
}: {
  book: Book;
  activeChapter: Chapter;
  exports: ExportReadiness[];
  generationState: GenerationState;
  materials: Material[];
  reviews: ReviewItem[];
  onCheckExport: (kind: ExportKind, range: string, rangeStart?: string, rangeEnd?: string) => Promise<{ readiness: ExportReadiness }>;
  onGenerateExport: (
    kind: ExportKind,
    range: string,
    rangeStart?: string,
    rangeEnd?: string,
    trainingChapterIds?: string[]
  ) => Promise<{ resultName: string; readiness: ExportReadiness }>;
  checking: boolean;
  generating: boolean;
}) {
  const [kind, setKind] = useState<ExportKind>("正文");
  const [range, setRange] = useState("全书");
  const [rangeStart, setRangeStart] = useState(activeChapter.id);
  const [rangeEnd, setRangeEnd] = useState(activeChapter.id);
  const [generated, setGenerated] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const [checkedReadiness, setCheckedReadiness] = useState<ExportReadiness | null>(null);
  const [checkedSelectionKey, setCheckedSelectionKey] = useState("");
  const [selectedTrainingChapterIds, setSelectedTrainingChapterIds] = useState<string[]>([]);
  const [actionError, setActionError] = useState("");
  const [pendingExportAction, setPendingExportAction] = useState<{ key: string; type: "check" | "generate" } | null>(null);
  const exportRequestRef = useRef(0);
  const selectionKeyRef = useRef("");
  const chapterIdsKey = book.chapters.map((chapter) => chapter.id).join("::");

  const chapterOptions = book.chapters.map((chapter) => ({ label: authorText(chapter.title), value: chapter.id }));
  const chapterTitleById = useMemo(() => new Map(book.chapters.map((chapter) => [chapter.id, chapter.title])), [book.chapters]);
  const rangeStartIndex = book.chapters.findIndex((chapter) => chapter.id === rangeStart);
  const rangeEndIndex = book.chapters.findIndex((chapter) => chapter.id === rangeEnd);
  const invalidChapterRange = range === "章节范围" && rangeStartIndex >= 0 && rangeEndIndex >= 0 && rangeEndIndex < rangeStartIndex;
  const requestRangeStart = range === "当前章节" ? activeChapter.id : range === "章节范围" ? rangeStart : undefined;
  const requestRangeEnd = range === "当前章节" ? activeChapter.id : range === "章节范围" ? rangeEnd : undefined;
  const rangeLabel = range === "章节范围"
    ? `${chapterTitleById.get(rangeStart) ?? "起始章节"} 到 ${chapterTitleById.get(rangeEnd) ?? "结束章节"}`
    : range === "当前章节"
      ? chapterTitleById.get(activeChapter.id) ?? "当前章节"
      : range;
  const selectionKey = exportSelectionKey(kind, range, requestRangeStart ?? "", requestRangeEnd ?? "");
  const checkedChapterIdsKey = checkedReadiness?.chapterIds.join("::") ?? "";
  const activeExport =
    checked
      && checkedSelectionKey === selectionKey
      && checkedReadiness?.kind === kind
      && checkedChapterIdsKey === chapterIdsKey
      ? checkedReadiness
      : null;
  const workspaceTrainingReadiness = exports.find((item) => item.kind === "训练数据") ?? null;
  const trainingPreview = (kind === "训练数据" ? activeExport ?? workspaceTrainingReadiness : null)?.trainingPreview;
  const selectedTrainingSet = useMemo(() => new Set(selectedTrainingChapterIds), [selectedTrainingChapterIds]);
  const selectedTrainingItems = trainingPreview?.items.filter((item) => selectedTrainingSet.has(item.chapterId)) ?? [];
  const skippedTrainingItems = trainingPreview?.items.filter((item) => !selectedTrainingSet.has(item.chapterId)) ?? [];
  const currentExport = kind === "训练数据" ? activeExport ?? workspaceTrainingReadiness : activeExport;
  const checkingCurrentSelection = checking && pendingExportAction?.key === selectionKey && pendingExportAction.type === "check";
  const generatingCurrentSelection = generating && pendingExportAction?.key === selectionKey && pendingExportAction.type === "generate";
  const generationRisks = generationExportRisks(generationState, book, activeChapter);
  const generationBlocksManuscript = kind === "正文" && generationRisks.length > 0;
  const exportSupport = useMemo(() => ({
    chapterCount: book.chapters.length,
    reviewCount: reviews.length,
    openReviewCount: reviews.filter((review) => review.status !== "已确认").length,
    lowConfidenceMaterialCount: materials.filter((material) => material.confidence < 75).length,
    materialCount: materials.length
  }), [book.chapters.length, materials, reviews]);

  useEffect(() => {
    selectionKeyRef.current = selectionKey;
  }, [selectionKey]);

  useEffect(() => {
    if (!trainingPreview) {
      setSelectedTrainingChapterIds([]);
      return;
    }
    setSelectedTrainingChapterIds(trainingPreview.items.filter((item) => item.eligible).map((item) => item.chapterId));
  }, [book.id, trainingPreview]);

  useEffect(() => {
    exportRequestRef.current += 1;
    setKind("正文");
    setRange("全书");
    setRangeStart(activeChapter.id);
    setRangeEnd(activeChapter.id);
    setGenerated(null);
    setSummaryOpen(false);
    setChecked(false);
    setCheckedReadiness(null);
    setCheckedSelectionKey("");
    setActionError("");
    setPendingExportAction(null);
  }, [book.id]);

  useEffect(() => {
    if (range !== "当前章节") {
      return;
    }
    setRangeStart(activeChapter.id);
    setRangeEnd(activeChapter.id);
    resetExportSelection();
  }, [activeChapter.id, range]);

  async function generateExport() {
    if (invalidChapterRange) {
      setActionError("结束章节不能早于起始章节。");
      return;
    }
    if (!currentExport) {
      setActionError("请先完成导出检查，再生成导出结果。");
      return;
    }
    if (kind === "训练数据" && selectedTrainingChapterIds.length === 0) {
      setActionError("训练数据至少需要选择一个章节。");
      return;
    }
    setActionError("");
    const requestId = exportRequestRef.current + 1;
    exportRequestRef.current = requestId;
    const requestSelectionKey = selectionKey;
    setPendingExportAction({ key: requestSelectionKey, type: "generate" });
    try {
      const result = await onGenerateExport(
        kind,
        range,
        requestRangeStart,
        requestRangeEnd,
        kind === "训练数据" ? selectedTrainingChapterIds : undefined
      );
      if (exportRequestRef.current !== requestId || selectionKeyRef.current !== requestSelectionKey) {
        return;
      }
      setGenerated(result.resultName);
      setCheckedReadiness(result.readiness);
      setCheckedSelectionKey(requestSelectionKey);
    } catch (error) {
      if (exportRequestRef.current !== requestId || selectionKeyRef.current !== requestSelectionKey) {
        return;
      }
      setGenerated(null);
      setSummaryOpen(false);
      setActionError(authorText(error instanceof Error ? error.message : "导出生成失败，请稍后重试。"));
    } finally {
      if (exportRequestRef.current === requestId) {
        setPendingExportAction((current) => (
          current?.key === requestSelectionKey && current.type === "generate" ? null : current
        ));
      }
    }
  }

  async function runExportCheck() {
    if (invalidChapterRange) {
      setActionError("结束章节不能早于起始章节。");
      return;
    }
    setActionError("");
    const requestId = exportRequestRef.current + 1;
    exportRequestRef.current = requestId;
    const requestSelectionKey = selectionKey;
    setPendingExportAction({ key: requestSelectionKey, type: "check" });
    try {
      const result = await onCheckExport(kind, range, requestRangeStart, requestRangeEnd);
      if (exportRequestRef.current !== requestId || selectionKeyRef.current !== requestSelectionKey) {
        return;
      }
      setGenerated(null);
      setCheckedReadiness(result.readiness);
      setCheckedSelectionKey(requestSelectionKey);
      setChecked(true);
    } catch (error) {
      if (exportRequestRef.current !== requestId || selectionKeyRef.current !== requestSelectionKey) {
        return;
      }
      setGenerated(null);
      setSummaryOpen(false);
      setChecked(false);
      setCheckedReadiness(null);
      setCheckedSelectionKey("");
      setActionError(authorText(error instanceof Error ? error.message : "导出检查失败，请稍后重试。"));
    } finally {
      if (exportRequestRef.current === requestId) {
        setPendingExportAction((current) => (
          current?.key === requestSelectionKey && current.type === "check" ? null : current
        ));
      }
    }
  }

  function resetExportSelection() {
    exportRequestRef.current += 1;
    setGenerated(null);
    setSummaryOpen(false);
    setChecked(false);
    setCheckedReadiness(null);
    setCheckedSelectionKey("");
    if (kind !== "训练数据") {
      setSelectedTrainingChapterIds([]);
    }
    setActionError("");
    setPendingExportAction(null);
  }

  return (
    <div className="page-grid responsive-detail-page">
      <section className="main-column">
        <MetricGrid compact items={[
          { label: "章节数", value: exportSupport.chapterCount },
          { label: "未处理审稿", value: exportSupport.openReviewCount },
          { label: "资料风险", value: exportSupport.lowConfidenceMaterialCount },
          { label: "生成状态", value: generationState.statusLabel }
        ]} />
        <Card className="content-card" variant="borderless">
          <Flex justify="space-between" align="start" gap={16}>
            <div>
              <Text type="secondary">导出对象</Text>
              <Title level={3} className="export-book-title" title={authorText(book.title)}>{authorText(book.title)}</Title>
              <Paragraph className="muted-text">导出前先检查章节、审稿和资料风险，生成结果只显示作者可理解的摘要。</Paragraph>
            </div>
            <Tag color={currentExport?.ready ? "success" : "default"}>{currentExport ? (currentExport.ready ? "可导出" : "建议先处理风险") : "等待导出检查"}</Tag>
          </Flex>
          <Divider />
          <Space direction="vertical" size={18} className="wide">
            <div>
              <Text type="secondary">导出类型</Text>
              <Segmented
                block
                value={kind}
                onChange={(value) => {
                  setKind(value as ExportKind);
                  resetExportSelection();
                }}
                options={["正文", "训练数据", "审稿报告", "资料包"]}
              />
            </div>
            <div>
              <Text type="secondary">导出范围</Text>
              <Segmented
                block
                value={range}
                onChange={(value) => {
                  const nextRange = String(value);
                  setRange(nextRange);
                  if (nextRange === "当前章节") {
                    setRangeStart(activeChapter.id);
                    setRangeEnd(activeChapter.id);
                  }
                  resetExportSelection();
                }}
                options={["全书", "当前章节", "章节范围"]}
              />
            </div>
            {range === "章节范围" ? (
              <Flex gap={12} wrap="wrap">
                <Select
                  className="range-select"
                  value={rangeStart}
                  options={chapterOptions}
                  onChange={(value) => {
                    setRangeStart(value);
                    resetExportSelection();
                  }}
                />
                <Select
                  className="range-select"
                  value={rangeEnd}
                  options={chapterOptions}
                  onChange={(value) => {
                    setRangeEnd(value);
                    resetExportSelection();
                  }}
                />
              </Flex>
            ) : null}
            <Alert
              type={trainingAlertType(kind, selectedTrainingChapterIds.length, currentExport, invalidChapterRange, generationBlocksManuscript, checked)}
              showIcon
              message={
                invalidChapterRange
                  ? "章节范围需要调整"
                  : generationBlocksManuscript
                    ? "正文导出前需要完成生成确认"
                    : kind === "训练数据" && selectedTrainingChapterIds.length === 0
                      ? "训练数据暂不可导出"
                      : currentExport
                      ? authorText(currentExport.summary)
                      : "等待导出检查"
              }
              description={
                invalidChapterRange
                  ? "结束章节不能早于起始章节，请重新选择范围。"
                  : generationBlocksManuscript
                    ? authorText(generationRisks.join("；"))
                  : kind === "训练数据" && trainingPreview
                  ? `当前选择 ${selectedTrainingChapterIds.length} 章；可用 ${trainingPreview.eligibleCount} 章，跳过 ${trainingPreview.skippedCount} 章。`
                  : currentExport
                  ? `当前范围：${rangeLabel}。生成前会保留未处理风险提示。`
                  : "点击检查后会汇总章节、审稿、接收前检查和资料风险。"
              }
            />
            {kind === "训练数据" ? (
              <Alert
                type="info"
                showIcon
                message="训练数据格式"
                description="导出格式：JSONL，每行一条 prompt/completion 训练样本。只包含通过质量门且质量分达标的章节，可用于 mlx-lm、LLaMA Factory 等本地微调框架。"
              />
            ) : null}
            {actionError ? (
              <Alert
                type="error"
                showIcon
                message="导出操作未完成"
                description={authorText(actionError)}
              />
            ) : null}
          </Space>
        </Card>
        {generated ? (
          <Card className="content-card candidate-card" variant="borderless">
            <Flex justify="space-between" align="center" gap={16}>
              <div>
                <Text type="secondary">导出结果</Text>
                <Title level={4}>{authorText(generated)}</Title>
                <Paragraph className="muted-text">包含 {exportSupport.chapterCount} 个章节、{exportSupport.materialCount} 条资料和 {exportSupport.reviewCount} 条审稿记录摘要。</Paragraph>
              </div>
              <Button icon={<FileTextOutlined />} onClick={() => setSummaryOpen(true)}>
                查看摘要
              </Button>
            </Flex>
          </Card>
        ) : null}
      </section>
      <aside className="side-column">
        <Card className="side-card" variant="borderless">
          <Text type="secondary">导出检查</Text>
          <Title level={5}>{kind}</Title>
          <Space direction="vertical" size={6} className="wide">
            <Flex justify="space-between"><Text>生成阶段</Text><Text strong>{authorText(generationState.stageLabel)}</Text></Flex>
            <Flex justify="space-between"><Text>生成状态</Text><Text strong>{authorText(generationState.statusLabel)}</Text></Flex>
            <Flex justify="space-between"><Text>本次目标</Text><Text strong>{generationState.batchDone} / {generationState.batchTarget} 章</Text></Flex>
          </Space>
          <Divider />
          {currentExport ? (
            <>
              <List
                dataSource={currentExport.checks}
                renderItem={(item) => (
                  <List.Item>
                    <Space>
                      <CheckCircleOutlined />
                      <Text>{authorText(item)}</Text>
                    </Space>
                  </List.Item>
                )}
              />
              <Divider />
              <Text type="secondary">风险</Text>
              <List
                dataSource={currentExport.risks}
                renderItem={(item) => (
                  <List.Item>
                    <Space>
                      <WarningOutlined />
                      <Text>{authorText(item)}</Text>
                    </Space>
                  </List.Item>
                )}
              />
              <Divider />
              <Progress percent={currentExport.ready ? 100 : 0} status={currentExport.ready ? "success" : "active"} />
            </>
          ) : (
            <>
              <Paragraph className="muted-text">当前还没有这次导出范围的检查结果。</Paragraph>
              <Divider />
              <Progress percent={0} />
            </>
          )}
          <Button
            block
            icon={<CheckCircleOutlined />}
            loading={checkingCurrentSelection}
            disabled={invalidChapterRange || generatingCurrentSelection}
            onClick={runExportCheck}
          >
            检查{kind}
          </Button>
          <Button
            block
            type="primary"
            icon={<DownloadOutlined />}
            disabled={
              invalidChapterRange
              || generationBlocksManuscript
              || !currentExport
              || checkingCurrentSelection
              || (kind === "训练数据" && selectedTrainingChapterIds.length === 0)
            }
            loading={generatingCurrentSelection}
            onClick={generateExport}
          >
            生成{kind}
          </Button>
        </Card>
        {kind === "训练数据" && trainingPreview ? (
          <Card className="side-card" variant="borderless">
            <Text type="secondary">训练数据预览</Text>
            <Title level={5}>章节选择</Title>
            <Space wrap>
              <Tag color="success">导出 {selectedTrainingItems.length} 章</Tag>
              <Tag>排除 {skippedTrainingItems.length} 章</Tag>
            </Space>
            <Divider />
            <List
              size="small"
              dataSource={trainingPreview.items}
              locale={{ emptyText: "暂无可预览章节。" }}
              renderItem={(item) => (
                <List.Item>
                  <div className="training-preview-row">
                    <Checkbox
                      checked={selectedTrainingSet.has(item.chapterId)}
                      onChange={(event) => {
                        setSelectedTrainingChapterIds((current) => {
                          const next = new Set(current);
                          if (event.target.checked) {
                            next.add(item.chapterId);
                          } else {
                            next.delete(item.chapterId);
                          }
                          return Array.from(next);
                        });
                      }}
                    />
                    <div className="min-w-0">
                      <Flex gap={6} wrap="wrap" align="center">
                        <Text strong>{authorText(item.chapterId)}</Text>
                        <Tag color={item.eligible ? "success" : "warning"}>{item.eligible ? "准入" : "排除"}</Tag>
                        <Tag>质量 {item.qualityScore}</Tag>
                        <Tag>Gate {authorText(item.gateStatus)}</Tag>
                      </Flex>
                      <Text type="secondary">
                        {item.eligible ? "将作为训练样本导出" : authorText(item.reasonLabel || item.actionSuggestion || "未通过训练准入")}
                      </Text>
                    </div>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        ) : null}
      </aside>
      <Modal
        title="导出摘要"
        open={summaryOpen}
        onCancel={() => setSummaryOpen(false)}
        footer={<Button type="primary" onClick={() => setSummaryOpen(false)}>完成</Button>}
      >
        <Space direction="vertical" className="wide">
          <Flex justify="space-between"><Text>文件名</Text><Text strong>{authorText(generated)}</Text></Flex>
          <Flex justify="space-between"><Text>导出类型</Text><Text strong>{kind}</Text></Flex>
          <Flex justify="space-between"><Text>导出范围</Text><Text strong>{authorText(rangeLabel)}</Text></Flex>
          <Flex justify="space-between"><Text>章节</Text><Text strong>{exportSupport.chapterCount} 章</Text></Flex>
          <Flex justify="space-between"><Text>资料</Text><Text strong>{exportSupport.materialCount} 条</Text></Flex>
          <Flex justify="space-between"><Text>未确认审稿</Text><Text strong>{exportSupport.openReviewCount} 条</Text></Flex>
          <Divider />
          <Text type="secondary">保留风险</Text>
          <List
            dataSource={currentExport?.risks ?? ["本次生成前未记录额外风险。"]}
            renderItem={(risk) => (
              <List.Item>
                <Space>
                  <WarningOutlined />
                  <Text>{authorText(risk)}</Text>
                </Space>
              </List.Item>
            )}
          />
        </Space>
      </Modal>
    </div>
  );
}

function exportSelectionKey(kind: ExportKind, range: string, rangeStart: string, rangeEnd: string) {
  return [kind, range, rangeStart, rangeEnd].join("::");
}

function trainingAlertType(
  kind: ExportKind,
  selectedCount: number,
  readiness: ExportReadiness | null,
  invalidChapterRange: boolean,
  generationBlocksManuscript: boolean,
  checked: boolean
): "success" | "info" | "warning" | "error" {
  if (invalidChapterRange || generationBlocksManuscript || (kind === "训练数据" && selectedCount === 0)) {
    return "error";
  }
  if (readiness?.ready) {
    return "success";
  }
  if (readiness || checked) {
    return "warning";
  }
  return "info";
}

function generationExportRisks(generationState: GenerationState, book: Book, activeChapter: Chapter) {
  const risks: string[] = [];
  if (generationState.status === "waiting_confirm") {
    risks.push("仍有生成候选等待确认");
  }
  if (generationState.status === "blocked") {
    risks.push(generationState.blockers[0] || "生成流程存在阻断项");
  }
  if (generationState.status === "paused") {
    risks.push("生成流程已暂停，恢复或接管处理后再导出正文");
  }
  if (generationState.status === "running") {
    risks.push("生成流程仍在推进中");
  }
  if (activeChapter.status !== "完成") {
    risks.push(`${activeChapter.title} 还未定稿`);
  }
  if (book.chapters.some((chapter) => chapter.status === "审阅")) {
    risks.push("仍有章节候选处于审阅状态");
  }
  return Array.from(new Set(risks));
}
