import { useEffect, useState } from "react";
import { Alert, Button, Card, Divider, Drawer, Empty, Flex, InputNumber, List, Modal, Progress, Radio, Segmented, Select, Space, Tag, Timeline, Tooltip, Typography } from "antd";
import { AuditOutlined, BookOutlined, CheckOutlined, ClockCircleOutlined, EditOutlined, PauseOutlined, PlayCircleOutlined, ReloadOutlined, ToolOutlined } from "@ant-design/icons";
import { MetricGrid, SupportRow } from "../components/shared";
import type { Book, Chapter, GenerationArtifact, GenerationCandidateVersion, GenerationMode, GenerationState, JobSummary, TodayState } from "../types";
import { authorText } from "../utils/authorText";
import { statusLabel } from "../utils/statusLabel";

const { Text, Title, Paragraph } = Typography;

export function TodayPage({
  book,
  chapter,
  today,
  generationState,
  jobs,
  onGoWriting,
  onGoLibrary,
  onGoReview,
  onGoMore,
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
  onPrepareChapter,
  onOpenTasks,
  onRefreshTasks,
  onRetryJob,
  createFirstChapterLoading,
  prepareChapterLoading,
  tasksLoading,
  generationAction,
  projectPlanLoading,
  tasksError
}: {
  book: Book;
  chapter: Chapter;
  today: TodayState;
  generationState: GenerationState;
  jobs: JobSummary[];
  onGoWriting: () => void;
  onGoLibrary: () => void;
  onGoReview: () => void;
  onGoMore: () => void;
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
  onPrepareChapter: () => void | Promise<unknown>;
  onOpenTasks: () => void;
  onRefreshTasks: () => void | Promise<void>;
  onRetryJob: (jobId: string) => void | Promise<void>;
  createFirstChapterLoading: boolean;
  prepareChapterLoading: boolean;
  tasksLoading: boolean;
  generationAction: string | null;
  projectPlanLoading: boolean;
  tasksError?: string;
}) {
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
  const [actionError, setActionError] = useState("");
  const [draftMode, setDraftMode] = useState<GenerationMode>(generationState.interventionMode);
  const [draftBatchTarget, setDraftBatchTarget] = useState(generationState.batchTarget);
  const [draftAutoStepLimit, setDraftAutoStepLimit] = useState(generationState.autoStepLimit);
  const [draftTargetChapterCount, setDraftTargetChapterCount] = useState(book.writingPlan.targetChapterCount);
  const [draftTargetWordsPerChapter, setDraftTargetWordsPerChapter] = useState(book.writingPlan.targetWordsPerChapter);
  const [draftTargetChaptersPerPlot, setDraftTargetChaptersPerPlot] = useState(book.writingPlan.targetChaptersPerPlot);
  const [selectedDirectionId, setSelectedDirectionId] = useState(generationState.selectedOptionId);
  const nextStep = getNextStep(today);
  const latestChapter = book.chapters[book.chapters.length - 1];
  const canCreateFromPipeline =
    generationState.status === "completed" || generationState.stage === "next_chapter";
  const shouldCreateChapter =
    !book.chapters.length ||
    (
      canCreateFromPipeline
      && latestChapter?.id === chapter.id
      && latestChapter.status === "完成"
    );
  const shouldPrepareChapter = !shouldCreateChapter && /准备本章/.test(`${nextStep.title} ${nextStep.action}`);
  const taskSummary = buildTaskSummary(jobs);
  const primaryAction = getPrimaryGenerationAction(generationState, shouldCreateChapter);
  const primaryIcon = getPrimaryActionIcon(primaryAction.kind);
  const interventionMode = getInterventionMode(generationState);
  const pipelineStages = buildGenerationPipeline(generationState);
  const estimate = estimateGenerationMinutes(jobs, draftBatchTarget);
  const secondaryAction = getSecondaryAction(nextStep.kind, {
    onGoWriting,
    onGoLibrary,
    onGoReview,
    onGoMore
  });

  useEffect(() => {
    setDraftMode(generationState.interventionMode);
    setDraftBatchTarget(generationState.batchTarget);
    setDraftAutoStepLimit(generationState.autoStepLimit);
    setSelectedDirectionId(generationState.selectedOptionId);
  }, [generationState.autoStepLimit, generationState.batchTarget, generationState.interventionMode, generationState.selectedOptionId]);

  useEffect(() => {
    setDraftTargetChapterCount(book.writingPlan.targetChapterCount);
    setDraftTargetWordsPerChapter(book.writingPlan.targetWordsPerChapter);
    setDraftTargetChaptersPerPlot(book.writingPlan.targetChaptersPerPlot);
  }, [book.id, book.writingPlan.targetChapterCount, book.writingPlan.targetChaptersPerPlot, book.writingPlan.targetWordsPerChapter]);

  function openTaskDrawer() {
    setTaskDrawerOpen(true);
    void Promise.resolve(onRefreshTasks()).catch(() => undefined);
  }

  async function createChapterFromToday() {
    setActionError("");
    try {
      await onCreateFirstChapter();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "章节创建失败，请稍后重试。"));
    }
  }

  async function prepareChapterFromToday() {
    setActionError("");
    try {
      await onPrepareChapter();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "章节准备失败，请稍后重试。"));
    }
  }

  async function saveGenerationMode() {
    setActionError("");
    try {
      await onGenerationModeChange(draftMode, draftBatchTarget, draftAutoStepLimit);
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "生成设置保存失败，请稍后重试。"));
    }
  }

  async function saveProjectPlan() {
    setActionError("");
    try {
      await onProjectPlanChange(
        draftTargetChapterCount,
        draftTargetWordsPerChapter,
        draftTargetChaptersPerPlot
      );
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "作品写作参数保存失败，请稍后重试。"));
    }
  }

  async function runGenerationPrimaryAction() {
    setActionError("");
    try {
      if (primaryAction.kind === "confirm") {
        await onGenerationConfirm(
          generationState.stage === "architecture" ? selectedDirectionId : undefined
        );
        return;
      }
      if (primaryAction.kind === "resume") {
        await onGenerationResume();
        return;
      }
      await onGenerationContinue();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "生成推进失败，请稍后重试。"));
    }
  }

  async function pauseGeneration() {
    setActionError("");
    try {
      await onGenerationPause();
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "生成暂停失败，请稍后重试。"));
    }
  }

  async function takeoverGeneration(target: "writing" | "library" | "review") {
    setActionError("");
    try {
      await onGenerationTakeover(target);
    } catch (error) {
      setActionError(authorText(error instanceof Error ? error.message : "作者接管失败，请稍后重试。"));
    }
  }

  function handlePrimaryAction() {
    if (shouldCreateChapter) {
      void createChapterFromToday();
      return;
    }
    void runGenerationPrimaryAction();
  }

  return (
    <div className="single-page generation-page">
      {!book.chapters.length ? (
        <Card className="content-card" variant="borderless">
          <Empty description="这本书还没有章节">
            <Button type="primary" icon={<EditOutlined />} loading={createFirstChapterLoading} onClick={() => void createChapterFromToday()}>
              创建第一章
            </Button>
          </Empty>
        </Card>
      ) : null}
      {actionError ? (
        <Alert
          type="error"
          showIcon
          className="inline-page-alert"
          message="生成操作未完成"
          description={authorText(actionError)}
        />
      ) : null}
      <section className="hero-panel">
        <div>
          <Tag color="blue">生成主控台</Tag>
          <Title level={1}>{authorText(generationState.nextAction || nextStep.title)}</Title>
          <Paragraph>当前章：{authorText(chapter.summary)}</Paragraph>
          <Space wrap>
            <Tag color={interventionMode.color}>干预档位：{interventionMode.label}</Tag>
            <Tag icon={<ClockCircleOutlined />} color={statusTagColor(generationState.status)}>{authorText(generationState.statusLabel)}</Tag>
            <Tag>{authorText(book.genre)}</Tag>
          </Space>
        </div>
        <div className="hero-actions">
          <Button type="primary" size="large" icon={primaryIcon} loading={(shouldCreateChapter && createFirstChapterLoading) || generationAction === primaryAction.loadingKey} onClick={handlePrimaryAction}>
            {authorText(primaryAction.label)}
          </Button>
          <Button size="large" icon={<PauseOutlined />} disabled={generationState.status === "paused"} loading={generationAction === "generation-pause"} onClick={() => void pauseGeneration()}>
            暂停
          </Button>
        </div>
      </section>
      <Card className="content-card generation-control-card" variant="borderless">
        <Flex justify="space-between" gap={16} wrap="wrap" align="center">
          <Space wrap>
            <Tooltip title={generationModeHint(draftMode)}>
              <Segmented
                value={draftMode}
                options={[
                  { label: "全自动", value: "full_auto" },
                  { label: "阶段确认", value: "stage_confirm" },
                  { label: "逐章确认", value: "chapter_confirm" },
                  { label: "深度干预", value: "deep_control" }
                ]}
                onChange={(value) => {
                  const mode = value as GenerationMode;
                  setDraftMode(mode);
                  setDraftAutoStepLimit(mode === "full_auto" ? draftBatchTarget * 7 + 8 : 1);
                }}
              />
            </Tooltip>
            <InputNumber
              aria-label="本次目标章节数"
              min={1}
              max={20}
              value={draftBatchTarget}
              addonBefore="本次目标"
              addonAfter="章"
              onChange={(value) => {
                const target = Number(value) || 1;
                const previousDefault = draftBatchTarget * 7 + 8;
                const nextDefault = target * 7 + 8;
                setDraftBatchTarget(target);
                setDraftAutoStepLimit((current) => draftMode === "full_auto"
                  ? current === previousDefault ? nextDefault : Math.min(current, nextDefault)
                  : 1);
              }}
            />
            <InputNumber
              aria-label="单次自动推进步数上限"
              min={1}
              max={draftMode === "full_auto" ? draftBatchTarget * 7 + 8 : 1}
              value={draftAutoStepLimit}
              addonBefore="自动推进上限"
              addonAfter="步"
              disabled={draftMode !== "full_auto"}
              onChange={(value) => setDraftAutoStepLimit(Number(value) || 1)}
            />
            <Tooltip title={estimate.tooltip}>
              <Tag icon={<ClockCircleOutlined />} color="blue">预计 {estimate.minutes} 分钟</Tag>
            </Tooltip>
            <Button icon={<CheckOutlined />} loading={generationAction?.startsWith("generation-mode")} onClick={() => void saveGenerationMode()}>
              保存设置
            </Button>
          </Space>
          <Space wrap>
            <Button onClick={() => void takeoverGeneration("writing")}>接管章节</Button>
            <Button onClick={() => void takeoverGeneration("library")}>接管资料</Button>
            <Button onClick={() => void takeoverGeneration("review")}>接管审稿</Button>
          </Space>
        </Flex>
      </Card>
      <Card className="content-card book-plan-control-card" variant="borderless">
        <Flex justify="space-between" gap={16} wrap="wrap" align="center">
          <div className="book-plan-copy">
            <Text type="secondary">作品写作参数</Text>
            <Title level={5}>控制全书规模、单章长度和剧情段节奏</Title>
            <Text type="secondary">保存后用于后续规划与章节生成；已有长篇规划不会被静默改写，可在资料页主动生成重规划候选。</Text>
          </div>
          <Space wrap>
            <InputNumber
              aria-label="全书目标章节数"
              min={1}
              max={2000}
              value={draftTargetChapterCount}
              addonBefore="全书"
              addonAfter="章"
              onChange={(value) => setDraftTargetChapterCount(Number(value) || 1)}
            />
            <InputNumber
              aria-label="每章目标字数"
              min={500}
              max={20000}
              step={100}
              value={draftTargetWordsPerChapter}
              addonBefore="每章"
              addonAfter="字"
              onChange={(value) => setDraftTargetWordsPerChapter(Number(value) || 500)}
            />
            <InputNumber
              aria-label="每个剧情段目标章节数"
              min={1}
              max={100}
              value={draftTargetChaptersPerPlot}
              addonBefore="每个剧情段"
              addonAfter="章"
              onChange={(value) => setDraftTargetChaptersPerPlot(Number(value) || 1)}
            />
            <Button icon={<CheckOutlined />} loading={projectPlanLoading} onClick={() => void saveProjectPlan()}>
              保存作品参数
            </Button>
          </Space>
        </Flex>
      </Card>
      {generationState.stage === "architecture" && generationState.candidateOptions.length ? (
        <section className="generation-direction-band">
          <Title level={4}>作品方向候选</Title>
          <Radio.Group
            className="generation-direction-options"
            value={selectedDirectionId}
            onChange={(event) => setSelectedDirectionId(event.target.value)}
          >
            <Space direction="vertical" size={10} className="wide">
              {generationState.candidateOptions.map((option) => (
                <Radio key={option.id} value={option.id} className="generation-direction-option">
                  <Space direction="vertical" size={2}>
                    <Text strong>{authorText(option.title)}</Text>
                    <Text>{authorText(option.summary)}</Text>
                    <Text type="secondary">{authorText(option.readerExperience)}</Text>
                    <Text type="secondary">{statusLabel(option.recommendation)}</Text>
                  </Space>
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </section>
      ) : null}
      {generationState.status === "waiting_confirm" && generationState.artifact ? (
        <CandidateDecisionPanel
          artifact={generationState.artifact}
          loadingAction={generationAction}
          onRegenerate={onGenerationRegenerate}
          onSelect={onGenerationCandidateSelect}
          onRollback={onGenerationRollback}
        />
      ) : null}
      <MetricGrid items={[
        { label: "作品进度", value: book.progress, suffix: "%" },
        { label: "当前章节", value: chapter.progress, suffix: "%" },
        { label: "本次目标", value: generationState.batchDone, suffix: `/ ${generationState.batchTarget} 章` },
        { label: "本次自动推进", value: generationState.autoStepsUsed, suffix: `/ ${generationState.autoStepLimit} 步` },
        { label: "待确认", value: generationState.confirmations.length || today.openReviewCount, suffix: "项" }
      ]} />
      <div className="today-grid generation-workspace-grid">
        <Card className="content-card generation-scroll-card" variant="borderless">
          <Title level={4}>生成流水线</Title>
          <Alert
            className="pipeline-guide"
            type="info"
            showIcon
            message={`当前只需处理：${authorText(generationState.stageLabel)}`}
            description={pipelineStageHelp(generationState)}
          />
          <Timeline items={pipelineStages.map((stage) => ({
            color: stage.color,
            dot: stage.approval ? <span className={`approval-diamond ${stage.active ? "active" : ""}`} /> : undefined,
            children: (
              <Space direction="vertical" size={2} className={`wide pipeline-stage ${stage.active ? "active" : ""}`}>
                <Flex justify="space-between" gap={12} align="center">
                  <Text strong>{stage.title}</Text>
                  <Tag color={stage.tagColor}>{stage.status}</Tag>
                </Flex>
                <Text type="secondary">{stage.detail}</Text>
              </Space>
            )
          }))} />
        </Card>
        <Card className="content-card generation-scroll-card" variant="borderless">
          <Flex justify="space-between" align="center">
            <Title level={4}>生成支撑</Title>
            <Button size="small" icon={<ToolOutlined />} loading={tasksLoading} onClick={openTaskDrawer}>
              任务状态
            </Button>
          </Flex>
          <Space direction="vertical" size={12} className="wide">
            <SupportRow label="AI 执行账号" value={generationState.sourceModelLabel || "使用“AI 模型”中分配的写作角色"} />
            <SupportRow label="当前章节" value={`${chapter.title} · ${chapter.status}`} />
            <SupportRow label="生成阶段" value={`${generationState.stageLabel} · ${generationState.statusLabel}`} />
            {generationState.longFormPosition.volumeTitle ? (
              <SupportRow
                label="当前卷"
                value={`${generationState.longFormPosition.volumeTitle} · ${generationState.longFormPosition.volumeGoal}`}
              />
            ) : null}
            {generationState.longFormPosition.segmentTitle ? (
              <SupportRow
                label="节奏段"
                value={`${generationState.longFormPosition.segmentTitle} · ${generationState.longFormPosition.chapterRange}`}
              />
            ) : null}
            {generationState.sourceModelLabel ? <SupportRow label="本次模型" value={generationState.sourceModelLabel} /> : null}
            <SupportRow label="作者干预" value={`${interventionMode.label} · ${interventionMode.summary}`} />
            <SupportRow label="最近结果" value={generationState.lastResult || nextStep.reason} />
            {generationState.blockers.length ? <SupportRow label="阻断项" value={generationState.blockers.join("；")} /> : null}
            {generationState.recoverySummary ? <SupportRow label="恢复状态" value={generationState.recoverySummary} /> : null}
            {today.overduePromiseCount ? (
              <Alert
                type="error"
                showIcon
                message={`${today.overduePromiseCount} 个承诺已过期未兑现`}
              />
            ) : null}
            <SupportRow label="待处理审稿" value={today.openReviewCount ? `${today.openReviewCount} 项待处理` : "当前没有待处理审稿"} />
            <SupportRow label="可用资料" value={today.readyMaterialCount ? `${today.readyMaterialCount} 条可直接引用` : "当前还没有高置信资料"} />
            <SupportRow label="处理任务" value={taskSummary.label} />
          </Space>
          <Divider />
          <Space direction="vertical" className="wide">
            <Button block icon={<AuditOutlined />} onClick={onGoReview}>
              查看审稿建议
            </Button>
            <Button block icon={secondaryAction.icon} onClick={secondaryAction.onClick}>
              {secondaryAction.label}
            </Button>
            {shouldPrepareChapter ? (
              <Button block loading={prepareChapterLoading} onClick={() => void prepareChapterFromToday()}>
                准备本章
              </Button>
            ) : null}
          </Space>
        </Card>
      </div>
      <Drawer
        title="任务状态"
        open={taskDrawerOpen}
        onClose={() => setTaskDrawerOpen(false)}
        width={420}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} loading={tasksLoading} onClick={() => void Promise.resolve(onRefreshTasks()).catch(() => undefined)}>
              刷新
            </Button>
            <Button onClick={onGoMore}>打开更多</Button>
          </Space>
        }
      >
        <Paragraph className="muted-text">这里只展示当前书的任务摘要，更多事件和运行记录在更多页查看。</Paragraph>
        {tasksError ? (
          <>
            <Alert
              type="error"
              showIcon
              message="任务状态刷新失败"
              description={authorText(tasksError)}
            />
            <Divider />
          </>
        ) : null}
        {jobs.length ? (
          <>
            <List
              dataSource={jobs.slice(0, 5)}
              renderItem={(job) => (
                <List.Item>
                  <Space direction="vertical" className="wide">
                    <Flex justify="space-between" gap={12} align="start">
                      <Text strong className="today-task-title">{authorText(job.title)}</Text>
                      <Space size={6}>
                        <Tag color={jobTagColor(job.status)}>{authorText(job.status)}</Tag>
                        {job.status === "失败" ? (
                          <Button size="small" onClick={() => void onRetryJob(job.id)}>
                            重试
                          </Button>
                        ) : null}
                      </Space>
                    </Flex>
                    <Text type="secondary" className="today-task-result">{authorText(job.result)}</Text>
                    <Progress percent={job.progress} size="small" showInfo={false} />
                    <Text type="secondary">开始于 {authorText(job.startedAt)}</Text>
                  </Space>
                </List.Item>
              )}
            />
            {jobs.length > 5 ? (
              <Paragraph className="muted-text">还有 {jobs.length - 5} 条任务记录，可在更多页查看。</Paragraph>
            ) : null}
          </>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前书暂时没有处理任务" />
        )}
      </Drawer>
    </div>
  );
}

function CandidateDecisionPanel({
  artifact,
  loadingAction,
  onRegenerate,
  onSelect,
  onRollback
}: {
  artifact: GenerationArtifact;
  loadingAction: string | null;
  onRegenerate: () => void | Promise<void>;
  onSelect: (candidateId: string) => void | Promise<void>;
  onRollback: () => void | Promise<void>;
}) {
  const selected = artifact.versions.find((version) => version.selected) ?? artifact.versions[0];
  const [compareId, setCompareId] = useState("");
  const [compareOpen, setCompareOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const compare = artifact.versions.find((version) => version.id === compareId);
  const compareOptions = artifact.versions
    .filter((version) => version.id !== selected?.id)
    .map((version) => ({ label: `${version.title} · ${version.summary}`, value: version.id }));

  useEffect(() => {
    if (!compareOptions.some((option) => option.value === compareId)) {
      setCompareId(compareOptions[0]?.value ?? "");
    }
  }, [artifact.candidateId, artifact.versions.length, compareId]);

  useEffect(() => {
    setGuideOpen(localStorage.getItem(candidateGuideKey(artifact.artifactType)) !== "seen");
  }, [artifact.artifactType]);

  return (
    <section className="candidate-decision-band">
      <Flex justify="space-between" align="start" gap={16} wrap="wrap">
        <div>
          <Text type="secondary">当前阶段候选</Text>
          <Title level={4}>{artifactTitle(artifact.artifactType)} · 版本 {artifact.version}</Title>
          <Paragraph className="muted-text">{artifact.summary || "审阅候选内容，确认后才会影响正式作品。"}</Paragraph>
        </div>
        <Space wrap className="candidate-decision-actions">
          <select
            aria-label="候选版本"
            value={selected?.id}
            className="candidate-version-select"
            disabled={loadingAction === "generation-select-candidate"}
            onChange={(event) => void onSelect(event.target.value)}
          >
            {artifact.versions.map((version) => (
              <option key={version.id} value={version.id}>
                {version.title} · {version.summary}{version.selected ? " · 当前" : ""}
              </option>
            ))}
          </select>
          <Button
            disabled={!compareId}
            onClick={() => setCompareOpen(true)}
          >
            比较版本
          </Button>
          <Button onClick={() => setGuideOpen((open) => !open)}>本阶段说明</Button>
          <Button loading={loadingAction === "generation-regenerate"} onClick={() => setRegenerateOpen(true)}>
            重新生成
          </Button>
          <Button loading={loadingAction === "generation-rollback"} onClick={() => setRollbackOpen(true)}>
            返回上一确认点
          </Button>
        </Space>
      </Flex>
      {guideOpen ? (
        <Alert
          closable
          showIcon
          type="info"
          message={candidateGuide(artifact.artifactType).decision}
          description={candidateGuide(artifact.artifactType).impact}
          onClose={() => {
            localStorage.setItem(candidateGuideKey(artifact.artifactType), "seen");
            setGuideOpen(false);
          }}
        />
      ) : null}
      <Divider />
      {selected ? <CandidateDetail version={selected} artifactType={artifact.artifactType} /> : <Empty description="候选内容暂不可用" />}
      <Modal
        open={compareOpen}
        width={1080}
        title="候选版本比较"
        footer={null}
        onCancel={() => setCompareOpen(false)}
      >
        <Flex gap={16} align="start" className="candidate-compare-layout">
          <div className="candidate-compare-column">
            <Text strong>{selected?.title} · 当前选择</Text>
            {selected ? <CandidateDetail version={selected} artifactType={artifact.artifactType} compact /> : null}
          </div>
          <div className="candidate-compare-column">
            <Select
              aria-label="对比候选版本"
              value={compareId || undefined}
              options={compareOptions}
              className="wide"
              onChange={setCompareId}
            />
            {compare ? <CandidateDetail version={compare} artifactType={artifact.artifactType} compact /> : null}
          </div>
        </Flex>
      </Modal>
      <Modal
        open={regenerateOpen}
        title="重新生成当前阶段候选？"
        okText="重新生成"
        cancelText="取消"
        confirmLoading={loadingAction === "generation-regenerate"}
        onCancel={() => setRegenerateOpen(false)}
        onOk={async () => {
          await onRegenerate();
          setRegenerateOpen(false);
        }}
      >
        <Paragraph>这份候选会保留，生成完成后可以继续比较和切换。</Paragraph>
      </Modal>
      <Modal
        open={rollbackOpen}
        title="返回上一个确认点？"
        okText="确认返回"
        cancelText="取消"
        confirmLoading={loadingAction === "generation-rollback"}
        onCancel={() => setRollbackOpen(false)}
        onOk={async () => {
          await onRollback();
          setRollbackOpen(false);
        }}
      >
        <Paragraph>系统会让当前阶段的下游正式内容失效，但会保留所有候选版本。已有定稿章节时不会执行危险回退。</Paragraph>
      </Modal>
    </section>
  );
}

function CandidateDetail({
  version,
  artifactType,
  compact = false
}: {
  version: GenerationCandidateVersion;
  artifactType: string;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const rows = candidateDetailRows(version.detail, artifactType);
  const visibleRows = compact || expanded ? rows : rows.slice(0, 6);
  if (artifactType === "chapter_draft" && !compact) {
    return (
      <div className="candidate-draft-block">
        <Text strong>正文候选</Text>
        <div className={`candidate-draft-preview ${expanded ? "expanded" : ""}`}>
          {rows[0]?.content || "候选详情暂不可用"}
        </div>
        {rows[0]?.content ? (
          <Button block onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起正文" : "展开完整正文"}
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <>
      <List
        size="small"
        className={compact ? "candidate-detail-list compact" : "candidate-detail-list"}
        dataSource={visibleRows}
        locale={{ emptyText: "候选详情暂不可用" }}
        renderItem={(row) => (
          <List.Item>
            <Space direction="vertical" size={2} className="wide">
              <Text strong>{row.title}</Text>
              <Text>{row.content}</Text>
            </Space>
          </List.Item>
        )}
      />
      {!compact && rows.length > 6 ? (
        <Button block className="candidate-detail-toggle" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "收起详情" : `查看全部 ${rows.length} 项`}
        </Button>
      ) : null}
    </>
  );
}

function candidateDetailRows(detail: Record<string, unknown>, artifactType: string) {
  if (artifactType === "chapter_draft") {
    return [{ title: "正文候选", content: String(detail.text ?? "") }];
  }
  if (artifactType === "book_direction") {
    return asRecordList(detail.options).map((item, index) => ({
      title: String(item.title ?? `方向 ${index + 1}`),
      content: [item.genrePositioning, item.centralConflict, item.serialHook, item.recommendation].filter(Boolean).join("；")
    }));
  }
  if (artifactType === "chapter_blueprint") {
    return asRecordList(detail.chapters).map((item, index) => ({
      title: String(item.title ?? `第 ${index + 1} 章`),
      content: [item.goal, item.conflict, item.turn, item.outcome, item.hook].filter(Boolean).join("；")
    }));
  }
  if (artifactType === "scene_contract") {
    const contract = asRecord(detail.contract);
    return Object.entries(contract)
      .filter(([key]) => !["schemaVersion", "chapterId", "version"].includes(key))
      .map(([key, value]) => ({ title: contractFieldLabel(key), content: displayCandidateValue(value) }))
      .filter((row) => row.content);
  }
  const plan = asRecord(detail.plan);
  const volumes = asRecordList(plan.volumes);
  return [
    { title: "整书主线", content: displayCandidateValue(plan.mainline) },
    { title: "结局方向", content: displayCandidateValue(plan.endingDirection) },
    ...volumes.map((volume, index) => ({
      title: String(volume.title ?? `第 ${index + 1} 卷`),
      content: [volume.chapterRange, volume.goal, volume.mainConflict, volume.endingChange].filter(Boolean).join("；")
    }))
  ].filter((row) => row.content);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item) => Object.keys(item).length) : [];
}

function displayCandidateValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(displayCandidateValue).filter(Boolean).join("、");
  }
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function artifactTitle(type: string) {
  return {
    book_direction: "作品方向",
    long_form_plan: "长篇规划",
    long_form_replan: "长篇重规划",
    chapter_blueprint: "章节蓝图",
    scene_contract: "章节规划",
    chapter_draft: "章节正文"
  }[type] ?? "生成候选";
}

function candidateGuideKey(type: string) {
  return `generation_candidate_guide_${type}`;
}

function candidateGuide(type: string) {
  return {
    book_direction: { decision: "本次决定作品走向", impact: "确认后会据此展开正式作品架构和长篇规划。" },
    long_form_plan: { decision: "本次决定全书与分卷路线", impact: "确认后会据此生成当前范围的章节蓝图。" },
    long_form_replan: { decision: "本次决定未来章节如何调整", impact: "确认只改变未定稿规划，不会改写已定稿章节。" },
    chapter_blueprint: { decision: "本次决定各章的推进落点", impact: "确认后会据此生成章节规划，不会直接写入正文。" },
    scene_contract: { decision: "本次决定当前章必须完成什么", impact: "确认后会构建上下文并生成正文候选。" },
    chapter_draft: { decision: "本次决定采用哪一版正文", impact: "确认后才进入接收前检查，尚不会直接定稿。" }
  }[type] ?? { decision: "本次决定当前候选是否继续", impact: "确认后系统会进入下一生成阶段。" };
}

function contractFieldLabel(key: string) {
  return {
    title: "本章标题",
    pov: "叙事视角",
    time: "时间",
    location: "场景地点",
    characters: "参与人物",
    focus: "本章重点",
    goal: "本章目标",
    conflict: "核心冲突",
    turn: "关键转折",
    outcome: "章节结果",
    hook: "结尾钩子",
    emotionalBeat: "情绪变化",
    relationshipBeat: "关系变化",
    stakes: "风险",
    cost: "代价",
    mustAvoid: "禁止发生",
    readerPromises: "读者承诺",
    mustReveal: "本章必须揭示",
    mustNotReveal: "本章必须保留",
    openingHook: "开场钩子",
    endingHook: "结尾钩子",
    foreshadowing: "伏笔安排",
    logicDependencies: "逻辑依赖",
    mustInclude: "必须包含",
    wordOrder: "信息顺序",
    risk: "风险提示",
    aftertaste: "余味"
  }[key] ?? "补充约束";
}

function buildTaskSummary(jobs: JobSummary[]) {
  const runningCount = jobs.filter((job) => job.status === "运行中").length;
  const waitingCount = jobs.filter((job) => job.status === "等待中").length;
  const failedCount = jobs.filter((job) => job.status === "失败").length;
  if (runningCount || waitingCount) {
    return { label: `${runningCount + waitingCount} 条处理中` };
  }
  if (failedCount) {
    return { label: `${failedCount} 条需要处理` };
  }
  return { label: jobs.length ? `${jobs.length} 条历史记录` : "当前没有处理任务" };
}

function estimateGenerationMinutes(jobs: JobSummary[], batchTarget: number) {
  const completed = jobs.filter((job) => job.status === "已完成").length;
  const average = completed >= 3 ? 4 : completed > 0 ? 5 : 6;
  const minutes = Math.max(1, average * Math.max(1, batchTarget));
  return {
    minutes,
    tooltip: completed >= 3 ? `基于最近 ${completed} 条任务历史，平均约 ${average} 分钟/章` : "历史数据不足，为参考估算"
  };
}

function getNextStep(today: TodayState) {
  return today.nextStep;
}

function getInterventionMode(generationState: GenerationState) {
  if (generationState.interventionMode === "full_auto") {
    return {
      label: generationState.interventionModeLabel,
      color: "green",
      summary: "连续推进到目标章节数"
    };
  }
  if (generationState.interventionMode === "chapter_confirm") {
    return {
      label: generationState.interventionModeLabel,
      color: "blue",
      summary: "每章定稿前暂停确认"
    };
  }
  if (generationState.interventionMode === "deep_control") {
    return {
      label: generationState.interventionModeLabel,
      color: "purple",
      summary: "草稿、检查、接收都由作者确认"
    };
  }
  return {
    label: generationState.interventionModeLabel,
    color: "cyan",
    summary: "关键阶段暂停确认"
  };
}

function buildGenerationPipeline(generationState: GenerationState) {
  const stageOrder: GenerationState["stage"][] = ["architecture", "blueprint", "contract", "context", "draft", "gate", "review", "accept", "memory", "next_chapter"];
  const currentIndex = stageOrder.indexOf(generationState.stage);
  const definitions = [
    ["作品架构", "作品方向和长篇路线已确认。", "先生成并确认作品方向与长篇路线。"],
    ["章节蓝图", "本次目标章节的推进落点已确认。", "作品架构完成后生成章节蓝图。"],
    ["章节规划", "当前章目标、冲突、转折和钩子已确认。", "章节蓝图完成后生成章节规划。"],
    ["上下文包", "当前章所需资料和连续性约束已整理。", "章节规划确认后整理上下文。"],
    ["草稿候选", "当前章正文候选已生成。", "上下文准备完成后生成正文候选。"],
    ["接收前检查", "正文候选已完成质量与连续性检查。", "草稿候选生成后执行接收前检查。"],
    ["审稿修复", "阻断问题已处理或确认无需修复。", "检查发现问题时先审稿和修复。"],
    ["定稿接收", "当前章已由作者确认接收。", "修复完成后由作者确认定稿。"],
    ["记忆资料", "本章事实、人物和伏笔已写入记忆。", "定稿后更新记忆和资料。"],
    ["下一章", "本轮章节闭环已完成。", "完成记忆更新后进入下一章。"]
  ] as const;
  return definitions.map(([title, completedDetail, pendingDetail], index) => {
    const active = index === currentIndex && generationState.status !== "completed";
    const approval = isApprovalStage(title, generationState.interventionMode);
    if (index < currentIndex || (index === currentIndex && generationState.status === "completed")) {
      return {
        title,
        status: "已完成",
        detail: completedDetail,
        color: "green",
        tagColor: "success",
        active: false,
        approval
      };
    }
    if (index === currentIndex) {
      return {
        title,
        active,
        approval,
        status: generationState.statusLabel,
        detail: generationState.nextAction,
        color: statusTimelineColor(generationState.status),
        tagColor: statusTagColor(generationState.status)
      };
    }
    return {
      title,
      status: "未开始",
      detail: pendingDetail,
      color: "gray",
      tagColor: "default",
      active: false,
      approval
    };
  });
}

function pipelineStageHelp(generationState: GenerationState) {
  const action = {
    architecture: "先点击主按钮生成作品方向；出现候选后选择方向并确认，系统才会进入章节蓝图。",
    blueprint: "确认本次要写的章节落点，蓝图未确认前不会生成章节规划。",
    contract: "检查当前章必须完成的目标、冲突、转折和钩子，确认后再整理上下文。",
    context: "补齐当前章需要的人物、设定、伏笔和连续性资料，再进入正文生成。",
    draft: "审阅正文候选；候选不会直接覆盖正文，确认后才进入检查。",
    gate: "处理质量与连续性检查结果，阻断项未解决前不能定稿。",
    review: "根据审稿建议修复候选，确认问题已处理后继续。",
    accept: "确认采用当前正文并定稿；定稿后才会更新记忆。",
    memory: "检查本章新增事实、人物状态和伏笔更新，再进入下一章。",
    next_chapter: "当前章闭环完成，可以创建或继续下一章。"
  }[generationState.stage];
  if (generationState.status === "paused") {
    return `${action} 当前流水线已暂停，点击“恢复生成”后从这一阶段继续。后续灰色步骤不会提前就绪。`;
  }
  if (generationState.status === "waiting_confirm") {
    return `${action} 当前候选正在等待作者确认，未确认前后续步骤不会开始。`;
  }
  if (generationState.status === "blocked") {
    return `${action} 先处理当前阻断项，后续步骤不会跳过。`;
  }
  return `${action} 流水线严格按顺序推进，后续步骤不会提前标记为完成。`;
}

function isApprovalStage(title: string, mode: GenerationMode) {
  if (mode === "full_auto") {
    return false;
  }
  if (mode === "deep_control") {
    return true;
  }
  return ["章节规划", "接收前检查", "定稿接收"].includes(title);
}

function generationModeHint(mode: GenerationMode) {
  const hints: Record<GenerationMode, string> = {
    full_auto: "系统连续推进，作者只处理阻断。",
    stage_confirm: "关键阶段等待作者确认后继续。",
    chapter_confirm: "每章完成后等待作者确认。",
    deep_control: "每个生成节点都保留作者接管和确认。"
  };
  return hints[mode];
}

function getPrimaryActionIcon(kind: PrimaryGenerationAction["kind"]) {
  if (kind === "continue") {
    return <PlayCircleOutlined />;
  }
  if (kind === "confirm") {
    return <CheckOutlined />;
  }
  if (kind === "resume") {
    return <PlayCircleOutlined />;
  }
  if (kind === "create") {
    return <EditOutlined />;
  }
  if (kind === "task") {
    return <ToolOutlined />;
  }
  if (kind === "library") {
    return <BookOutlined />;
  }
  if (kind === "review") {
    return <AuditOutlined />;
  }
  return <EditOutlined />;
}

type PrimaryGenerationAction = {
  kind: "continue" | "confirm" | "resume" | "create" | "task" | "library" | "review" | "writing";
  label: string;
  loadingKey: string;
};

function getPrimaryGenerationAction(generationState: GenerationState, shouldCreateChapter: boolean): PrimaryGenerationAction {
  if (shouldCreateChapter) {
    return { kind: "create", label: "开始下一章", loadingKey: "chapter-next" };
  }
  if (generationState.status === "waiting_confirm") {
    return { kind: "confirm", label: "确认并继续", loadingKey: "generation-confirm" };
  }
  if (generationState.status === "paused") {
    return { kind: "resume", label: "恢复生成", loadingKey: "generation-resume" };
  }
  if (generationState.stage === "architecture") {
    return { kind: "continue", label: "生成作品架构", loadingKey: "generation-continue" };
  }
  if (generationState.stage === "blueprint") {
    return { kind: "continue", label: "生成章节蓝图", loadingKey: "generation-continue" };
  }
  return { kind: "continue", label: "继续生成", loadingKey: "generation-continue" };
}

function statusTagColor(status: GenerationState["status"]) {
  if (status === "blocked") {
    return "error";
  }
  if (status === "paused" || status === "waiting_confirm") {
    return "warning";
  }
  if (status === "running") {
    return "processing";
  }
  if (status === "completed") {
    return "success";
  }
  return "default";
}

function statusTimelineColor(status: GenerationState["status"]) {
  if (status === "blocked") {
    return "red";
  }
  if (status === "paused" || status === "waiting_confirm") {
    return "orange";
  }
  if (status === "running") {
    return "blue";
  }
  if (status === "completed") {
    return "green";
  }
  return "gray";
}

function getSecondaryAction(
  nextStepKind: TodayState["nextStep"]["kind"],
  actions: {
    onGoWriting: () => void;
    onGoLibrary: () => void;
    onGoReview: () => void;
    onGoMore: () => void;
  }
) {
  if (nextStepKind === "library") {
    return { label: "回到章节", icon: <EditOutlined />, onClick: actions.onGoWriting };
  }
  if (nextStepKind === "review") {
    return { label: "查看资料", icon: <BookOutlined />, onClick: actions.onGoLibrary };
  }
  if (nextStepKind === "task") {
    return { label: "打开更多", icon: <ToolOutlined />, onClick: actions.onGoMore };
  }
  return { label: "检查资料", icon: <BookOutlined />, onClick: actions.onGoLibrary };
}

function jobTagColor(status: JobSummary["status"]) {
  if (status === "已完成") {
    return "success";
  }
  if (status === "失败") {
    return "error";
  }
  if (status === "运行中") {
    return "processing";
  }
  return "default";
}
