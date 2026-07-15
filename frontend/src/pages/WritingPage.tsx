import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Badge, Button, Card, Divider, Empty, Flex, Grid, Input, message, Modal, Progress, Segmented, Space, Tag, Timeline, Typography } from "antd";
import {
  CheckCircleOutlined,
  BookOutlined,
  BranchesOutlined,
  BulbOutlined,
  CopyOutlined,
  DashboardOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  FullscreenOutlined,
  HighlightOutlined,
  ReadOutlined,
  TeamOutlined
} from "@ant-design/icons";
import type { AcceptChapterBlockedDetail, AcceptChapterResponse, ChapterGateRecoveryResponse, ChapterGateResponse, ChapterPrepareResponse } from "../api/contracts";
import { workbenchClient } from "../api/workbenchClient";
import { ChapterMaterialPanel } from "../components/ChapterMaterialPanel";
import { DiffView } from "../components/DiffView";
import { ScrollTabs } from "../components/ScrollTabs";
import { SimpleList, TaskPanel, statusColor } from "../components/shared";
import { type DraftSnapshot, type PostAcceptSummary, useWritingChapterWorkflow } from "../hooks/useWritingChapterWorkflow";
import type { Book, Chapter, Material, MaterialDeleteAction, MaterialLinkAction, MaterialSaveAction } from "../types";
import { authorText } from "../utils/authorText";
import { statusLabel } from "../utils/statusLabel";

const { Text, Title, Paragraph } = Typography;

const chapterSidePanels = ["任务", "资料", "人物", "线索", "审阅", "经验", "创意", "上下文", "场景"];

export function WritingPage({
  book,
  chapter,
  materials,
  panel,
  checkedTasks,
  onChapterChange,
  onPanelChange,
  onTasksChange,
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
  onOpenReview,
  materialLinkAction,
  materialDeleteAction,
  materialSaveAction,
  applyLoading,
  prepareLoading,
  gateLoading,
  acceptAction,
  nextChapterLoading
}: {
  book: Book;
  chapter: Chapter;
  materials: Material[];
  panel: string;
  checkedTasks: string[];
  onChapterChange: (chapterId: string) => void;
  onPanelChange: (panel: string) => void;
  onTasksChange: (tasks: string[]) => void;
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
  onOpenReview?: () => void;
  materialLinkAction: MaterialLinkAction;
  materialDeleteAction: MaterialDeleteAction;
  materialSaveAction: MaterialSaveAction;
  applyLoading: boolean;
  prepareLoading: boolean;
  gateLoading: boolean;
  acceptAction: "normal" | "force" | null;
  nextChapterLoading: boolean;
}) {
  const screens = Grid.useBreakpoint();
  const {
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
    setPostAcceptSummary
  } = useWritingChapterWorkflow({
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
  });
  const [activeGateSnippet, setActiveGateSnippet] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [candidateView, setCandidateView] = useState<"全文" | "对照">("全文");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [zenMode, setZenMode] = useState(false);
  const latestChapter = book.chapters[book.chapters.length - 1];
  const canStartNextChapter = latestChapter?.id === chapter.id && chapter.status === "完成";
  const gatePreviewRef = useRef<HTMLDivElement | null>(null);
  const gateSnippets = useMemo(
    () => Array.from(new Set((gateResult?.gate.issues ?? []).map((issue) => issue.textSnippet).filter(Boolean))),
    [gateResult?.gate.issues]
  );

  function focusGateSnippet(snippet: string) {
    if (!snippet) {
      return;
    }
    setActiveGateSnippet(snippet);
    window.requestAnimationFrame(() => gatePreviewRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }));
  }

  useEffect(() => {
    document.body.classList.toggle("zen-mode", zenMode);
    return () => document.body.classList.remove("zen-mode");
  }, [zenMode]);

  useEffect(() => {
    setRevisionInstruction("");
  }, [book.id, chapter.id]);

  const sideContent = {
    任务: (
      <TaskPanel
        chapter={chapter}
        checkedTasks={checkedTasks}
        onChange={onTasksChange}
        onPlanningChange={onPlanningChange}
      />
    ),
    资料: (
      <ChapterMaterialPanel
        bookId={book.id}
        chapter={chapter}
        materials={materials}
        onCreateMaterial={onCreateMaterial}
        onUpdateMaterial={onUpdateMaterial}
        onDeleteMaterial={onDeleteMaterial}
        onLinkMaterials={onLinkMaterials}
        materialLinkAction={materialLinkAction}
        materialDeleteAction={materialDeleteAction}
        materialSaveAction={materialSaveAction}
      />
    ),
    人物: <CharacterStatePanel bookId={book.id} chapterId={chapter.id} />,
    线索: <SimpleList icon={<ExperimentOutlined />} items={chapter.clues} />,
    审阅: <ReviewReminder items={chapter.review} onOpenReview={onOpenReview} />,
    经验: <WritingLessonsPanel bookId={book.id} />,
    创意: (
      <Space direction="vertical" size={16} className="wide">
        <PlotDirectionPanel bookId={book.id} chapter={chapter} />
        <Divider />
        <IdeationPanel bookId={book.id} chapter={chapter} />
      </Space>
    ),
    上下文: (
      <ContextHintPanel
        ending={previousChapterEnding(book.chapters, chapter.id)}
        promises={materials.filter((material) => material.type === "伏笔" && material.dueStatus !== "resolved")}
        contextPack={prepareResult?.contextPack}
      />
    ),
    场景: <SceneContractPanel bookId={book.id} chapterId={chapter.id} fallbackItems={derivePlaceAndForces(chapter)} />
  }[panel];
  const charCount = draftText.trim().length;
  const targetWordCount = Math.max(1, book.writingPlan.targetWordsPerChapter);
  const wordProgress = Math.min(100, Math.round((charCount / targetWordCount) * 100));
  const chapterWordProgress = (item: Chapter) => {
    if (item.id === chapter.id) {
      return wordProgress;
    }
    return Math.min(100, Math.round((item.wordCount / targetWordCount) * 100));
  };

  return (
    <div className="page-grid writing-page-grid">
      <section className="main-column">
        <Flex justify="space-between" align="center" gap={16} className="section-toolbar writing-toolbar">
          <div className="chapter-rail" aria-label="章节切换">
            {book.chapters.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`chapter-rail-item ${item.id === chapter.id ? "active" : ""}`}
                onClick={() => changeChapter(item.id)}
              >
                <span className="chapter-rail-title">{authorText(item.title)}</span>
                <span className="chapter-rail-meta">
                  {authorText(item.status)} · 字数 {chapterWordProgress(item)}%
                </span>
              </button>
            ))}
          </div>
          <Space className="chapter-sync-status">
            <Badge status={statusColor(chapter.status)} text={authorText(chapter.status)} />
            {isDirty ? <Tag color="warning">未保存</Tag> : <Tag color="success">已同步</Tag>}
            <Text type="secondary" className="chapter-word-count">{chapter.wordCount.toLocaleString()} 字</Text>
          </Space>
        </Flex>
        <div className="writing-workspace">
          <Card className="content-card chapter-card writing-editor-pane" variant="borderless">
            <div className="writing-pane-layout">
              <div className="writing-pane-scroll writing-editor-scroll">
                <Flex justify="space-between" align="start" gap={20}>
                  <div>
                    <Text type="secondary">作者正文</Text>
                    <Title level={2}>{authorText(chapter.title)}</Title>
                    <Paragraph className="muted-text">{authorText(chapter.summary)}</Paragraph>
                  </div>
                  <Progress type="circle" percent={wordProgress} size={74} />
                </Flex>
                <Divider />
                <Input.TextArea
                  className="chapter-editor"
                  value={draftText}
                  autoSize={{ minRows: screens.md ? 5 : 3, maxRows: 24 }}
                  onChange={(event) => setDraftText(event.target.value)}
                />
                <div className="char-count-hint">
                  <Flex justify="space-between" align="center" gap={12} className="char-count-summary">
                    <Text type={charCount < Math.min(1200, targetWordCount * 0.5) ? "warning" : "secondary"}>
                      {charCount.toLocaleString()} / {targetWordCount.toLocaleString()} 字
                    </Text>
                    <Text type="secondary">{wordProgress}%</Text>
                  </Flex>
                  <Progress percent={wordProgress} size="small" status={wordProgress >= 100 ? "success" : "active"} showInfo={false} />
                </div>
                {gateResult ? (
                  <div ref={gatePreviewRef} className="chapter-gate-highlight-preview">
                    {gateSnippets.length ? (
                      draftText.split("\n").filter((paragraph) => paragraph.trim()).map((paragraph, index) => (
                        <Paragraph key={`${index}-${paragraph.slice(0, 12)}`}>
                          {renderHighlightedParagraph(paragraph, gateSnippets, activeGateSnippet)}
                        </Paragraph>
                      ))
                    ) : (
                      <Paragraph className="muted-text">接收前检查已完成，当前正文没有可定位的片段级问题。</Paragraph>
                    )}
                  </div>
                ) : null}
              </div>
              <Flex justify="space-between" align="center" gap={12} className="editor-actions writing-pane-footer">
                <Text type="secondary">
                  {isDirty ? "正文有本地修改，保存后会进入草稿状态。" : "当前显示已保存版本，可继续编辑。"}
                </Text>
                <Space wrap className="editor-action-buttons">
                  <Button icon={<FullscreenOutlined />} onClick={() => setZenMode((value) => !value)}>
                    {zenMode ? "退出沉浸" : "沉浸"}
                  </Button>
                  <Button disabled={!isDirty} onClick={discardDraftChanges}>
                    还原
                  </Button>
                  <Button disabled={!draftHistory.length} onClick={() => setHistoryOpen(true)}>
                    历史版本
                  </Button>
                  <Button type="primary" icon={<CheckCircleOutlined />} disabled={!isDirty} onClick={() => void saveDraft()} loading={applyLoading && pendingDraftAction === "save"}>
                    保存草稿
                  </Button>
                </Space>
              </Flex>
            </div>
          </Card>
          <div className="writing-candidate-pane">
            <Card className="content-card candidate-card chapter-prepare-card" variant="borderless">
              <Flex justify="space-between" align="flex-start" gap={12} className="chapter-prepare-head">
                <div className="chapter-prepare-copy">
                  <div className="chapter-prepare-status">
                    <Text type="secondary">章节准备</Text>
                    {prepareResult ? (
                      <Badge
                        status={prepareResult.readiness.status === "pass" ? "success" : prepareResult.readiness.status === "warn" ? "warning" : "error"}
                        text={authorText(prepareResult.display)}
                      />
                    ) : (
                      <Text strong>{prepared ? "本章已准备" : "准备本章后再生成候选"}</Text>
                    )}
                  </div>
                  <Paragraph className="muted-text">
                    {prepareResult
                      ? authorText(prepareResult.contextPack.summary)
                      : prepared
                        ? "已汇总任务、剧情点、人物、线索和审阅重点，候选生成会围绕这些上下文。"
                        : "准备本章会把章节目标、剧情点、资料提醒和风险项整理成作者可读的写作提要。"}
                  </Paragraph>
                </div>
                <Button icon={<DashboardOutlined />} disabled={prepared} loading={prepareLoading} onClick={prepareChapter}>
                  准备本章
                </Button>
              </Flex>
              {prepareResult?.readiness.issues.length ? (
                <div className="chapter-prepare-details">
                  <ListLike items={prepareResult.readiness.issues.slice(0, 4).map((issue) => issue.message)} />
                </div>
              ) : null}
            </Card>
            {actionError ? (
              <Alert
                type="error"
                showIcon
                message="章节操作未完成"
                description={authorText(actionError)}
              />
            ) : null}
            <Card className="content-card candidate-card writing-ai-workbench" variant="borderless">
              <div className="writing-pane-layout">
                <div className="writing-ai-head">
                  <div className="min-w-0">
                    <Text type="secondary">AI 工作区</Text>
                    <Title level={4}>{candidateText || agentAction ? "候选稿审阅" : "生成并对照候选稿"}</Title>
                    {candidateText || agentAction ? (
                      <Tag color="blue" className="candidate-source-tag">来源：{authorText(candidateSource)}</Tag>
                    ) : (
                      <Text type="secondary">AI 版本与作者正文分离，确认后才会应用。</Text>
                    )}
                  </div>
                  {candidateText || agentAction ? (
                    <Segmented
                      value={candidateView}
                      onChange={(value) => setCandidateView(value as "全文" | "对照")}
                      options={["全文", "对照"]}
                    />
                  ) : null}
                </div>
                <div className="writing-pane-scroll writing-ai-scroll">
                  {candidateText || agentAction ? (
                    <>
                      <Alert
                        showIcon
                        type="info"
                        message="候选来源上下文"
                        description={authorText(`来源动作：${candidateSource}。应用后会追加到草稿末尾，不会覆盖已有正文。`)}
                      />
                      {candidateView === "对照" ? (
                        <DiffView baseText={draftText} candidateText={candidateText} />
                      ) : (
                        <div className="reader-text candidate-text">
                          {candidateText ? candidateText.split("\n").map((paragraph) => (
                            <Paragraph key={paragraph}>{authorText(paragraph)}</Paragraph>
                          )) : <Paragraph className="muted-text">AI 正在生成候选内容...</Paragraph>}
                        </div>
                      )}
                      {candidateText && !agentAction ? (
                        <div className="candidate-revision">
                          <Text type="secondary">修改意见</Text>
                          <Input.TextArea
                            value={revisionInstruction}
                            autoSize={{ minRows: 2, maxRows: 5 }}
                            placeholder="例如：冲突提前，减少解释，保留结尾钩子"
                            onChange={(event) => setRevisionInstruction(event.target.value)}
                          />
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <div className="ai-workbench-empty">
                      <Text type="secondary">AI 候选稿</Text>
                      <Title level={5}>从下方选择一种生成方式</Title>
                      <Paragraph className="muted-text">候选稿会在这里与作者正文并排展示，不会直接覆盖已保存内容。</Paragraph>
                    </div>
                  )}
                  {gateOpen ? (
                    <div className="writing-gate-panel">
                      <Alert
                        type={gateResult?.gate.status === "pass" ? "success" : gateResult?.gate.status === "warn" ? "warning" : "error"}
                        showIcon
                        message="接收前检查"
                        description={authorText(gateResult?.display ?? "正在读取接收前检查结果。")}
                      />
                      {gateResult?.gate.issues.length ? (
                        <GateIssueList issues={gateResult.gate.issues} onFocusSnippet={focusGateSnippet} />
                      ) : (
                        <ListLike items={["接收前检查未发现阻断项。"]} />
                      )}
                      {gateRecovery?.steps.length ? (
                        <>
                          <Divider />
                          <Text type="secondary">修复建议</Text>
                          <ListLike
                            items={gateRecovery.steps.map((step) => {
                              const targets = step.targets.slice(0, 2).map((target) => target.label || "相关位置").filter(Boolean);
                              return `${step.action}${targets.length ? ` 关注：${targets.join("、")}` : ""}`;
                            })}
                          />
                          <Paragraph className="muted-text">
                            推荐下一步：{authorText(gateRecovery.recommendedNextAction)}
                          </Paragraph>
                        </>
                      ) : null}
                      {gateResult?.gate.recommendedNextAction ? (
                        <Paragraph className="muted-text">
                          接收后建议：{authorText(gateResult.gate.recommendedNextAction)}
                        </Paragraph>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="writing-ai-footer writing-pane-footer">
                  <div className="writing-ai-actions">
                    <Button icon={<ReadOutlined />} loading={agentAction === "续写"} disabled={isCandidateActionDisabled("续写")} onClick={() => createCandidate("续写")}>
                      AI 续写
                    </Button>
                    <Button icon={<HighlightOutlined />} loading={agentAction === "润色"} disabled={isCandidateActionDisabled("润色")} onClick={() => createCandidate("润色")}>
                      AI 润色
                    </Button>
                    <Button icon={<HighlightOutlined />} loading={agentAction === "润色"} disabled={isCandidateActionDisabled("润色")} onClick={() => void polishWholeChapter()}>
                      润色全章
                    </Button>
                    <Button icon={<ExperimentOutlined />} loading={agentAction === "冲突"} disabled={isCandidateActionDisabled("冲突")} onClick={() => createCandidate("冲突")}>
                      提炼冲突
                    </Button>
                    <Button className="writing-ai-action-wide" type="primary" icon={<EditOutlined />} loading={agentAction === "整章"} disabled={isCandidateActionDisabled("整章")} onClick={() => createCandidate("整章")}>
                      生成下一版候选稿
                    </Button>
                  </div>
                  {candidateText || agentAction ? (
                    <div className="candidate-action-row">
                      <Button icon={<CopyOutlined />} disabled={!candidateText} onClick={copyCandidate}>
                        复制
                      </Button>
                      <Button icon={<DeleteOutlined />} disabled={!candidateText} onClick={() => setCandidateText("")}>
                        丢弃
                      </Button>
                      <Button loading={agentAction === lastCandidateKind} disabled={isCandidateActionDisabled(lastCandidateKind)} onClick={() => createCandidate(lastCandidateKind, "", true)}>
                        重新生成
                      </Button>
                      {agentAction ? <Button onClick={cancelCandidate}>取消生成</Button> : null}
                      <Button type="primary" icon={<CheckCircleOutlined />} disabled={!candidateText} onClick={() => void applyCandidate()} loading={applyLoading && pendingDraftAction === "apply"}>
                        应用到草稿
                      </Button>
                    </div>
                  ) : null}
                  {candidateText && !agentAction ? (
                    <Button
                      block
                      icon={<EditOutlined />}
                      disabled={!revisionInstruction.trim()}
                      onClick={() => createCandidate(lastCandidateKind, revisionInstruction, true)}
                    >
                      按修改意见重新生成
                    </Button>
                  ) : null}
                  {gateOpen ? (
                    <div className="candidate-action-row">
                      <Button icon={<HighlightOutlined />} loading={agentAction === "润色"} disabled={isCandidateActionDisabled("润色")} onClick={() => createCandidate("润色")}>
                        生成修复候选
                      </Button>
                      <Button onClick={() => setGateOpen(false)}>返回候选稿</Button>
                      <Button danger loading={acceptAction === "force"} onClick={forceAcceptAfterGate}>强制接收</Button>
                      <Button type="primary" icon={<CheckCircleOutlined />} loading={acceptAction === "normal"} onClick={() => acceptAfterGate(false)}>
                        确认接收
                      </Button>
                    </div>
                  ) : (
                    <div className="candidate-action-row">
                      <Button icon={<CheckCircleOutlined />} loading={gateLoading} onClick={openGatePanel}>
                        接收前检查
                      </Button>
                      <Button
                        icon={<DashboardOutlined />}
                        loading={nextChapterLoading}
                        disabled={!canStartNextChapter}
                        onClick={() => void createNextChapter()}
                      >
                        开始下一章
                      </Button>
                    </div>
                  )}
                  {!canStartNextChapter ? (
                    <Text type="secondary">
                      {latestChapter?.id !== chapter.id
                        ? `请先回到最新章节“${authorText(latestChapter?.title ?? "")}”继续推进。`
                        : "当前章正式完稿并接收后，才能开始下一章。"}
                    </Text>
                  ) : null}
                </div>
              </div>
            </Card>
          </div>
        </div>
      </section>
      <aside className="side-column writing-side-column">
        <ScrollTabs
          className="writing-panel-tabs"
          value={panel}
          options={chapterSidePanels}
          ariaLabel="章节辅助面板"
          onChange={onPanelChange}
        />
        <div className="writing-side-scroll" aria-label="章节辅助内容">
          <div className="writing-side-stack">
            <Card className="side-card" variant="borderless">
              {sideContent}
            </Card>
          </div>
        </div>
      </aside>
      <DraftHistoryModal
        open={historyOpen}
        snapshots={draftHistory}
        onClose={() => setHistoryOpen(false)}
        onRestore={(snapshot) => {
          restoreDraftSnapshot(snapshot);
          setHistoryOpen(false);
        }}
      />
      <PostAcceptSummaryModal
        summary={postAcceptSummary}
        onClose={() => setPostAcceptSummary(null)}
        onOpenReview={onOpenReview}
      />
    </div>
  );
}

function ListLike({ items }: { items: string[] }) {
  return (
    <Space direction="vertical" className="wide gate-list">
      {items.map((item) => (
        <Flex key={item} gap={10} align="center">
          <CheckCircleOutlined />
          <Text>{authorText(item)}</Text>
        </Flex>
      ))}
    </Space>
  );
}

function ContextHintPanel({
  ending,
  promises,
  contextPack
}: {
  ending: string;
  promises: Material[];
  contextPack?: ChapterPrepareResponse["contextPack"];
}) {
  const sortedPromises = [...promises].sort((left, right) => dueWeight(left.dueStatus) - dueWeight(right.dueStatus));
  const promiseItems = sortedPromises
    .map((material) => `${material.dueStatus === "overdue" ? "已过期：" : material.dueStatus === "at_risk" ? "即将到期：" : ""}${material.title}`);
  const tokenPercent = contextPack ? Math.min(100, Math.round((contextPack.estimatedTokens / Math.max(1, contextPack.tokenBudget)) * 100)) : 0;
  return (
    <Space direction="vertical" className="wide">
      <div>
        <Text type="secondary">上一章结尾</Text>
        <Paragraph className="context-hint-text">
          {authorText(ending || "当前没有可承接的上一章结尾。")}
        </Paragraph>
      </div>
      <div>
        <Text type="secondary">承诺与伏笔</Text>
        <SimpleList icon={<ExperimentOutlined />} items={promiseItems.length ? promiseItems : ["当前没有待兑现伏笔。"]} />
      </div>
      {contextPack ? (
        <div>
          <Text type="secondary">上下文包</Text>
          <Progress percent={tokenPercent} size="small" showInfo={false} />
          <Paragraph className="muted-text">
            已用 {contextPack.estimatedTokens.toLocaleString()} / {contextPack.tokenBudget.toLocaleString()} tokens，注入 {contextPack.includedCount} 项。
          </Paragraph>
          <Space direction="vertical" className="wide context-pack-items">
            {contextPack.items.length ? contextPack.items.map((item) => (
              <div key={`${item.source}-${item.type}-${item.reason}`} className="context-pack-item">
                <Tag>{authorText(item.type)}</Tag>
                <Text>{authorText(item.source)}</Text>
                <Text type="secondary">{item.tokenEstimate.toLocaleString()} tokens</Text>
                {item.reason ? <Text type="secondary">{authorText(item.reason)}</Text> : null}
              </div>
            )) : <Text type="secondary">本次准备没有返回上下文明细。</Text>}
          </Space>
        </div>
      ) : null}
    </Space>
  );
}

function PlotDirectionPanel({ bookId, chapter }: { bookId: string; chapter: Chapter }) {
  const [intent, setIntent] = useState("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState("");
  const [error, setError] = useState("");
  const [report, setReport] = useState<Awaited<ReturnType<typeof workbenchClient.fetchPlotDirections>>["report"] | null>(null);

  async function loadDirections() {
    setLoading(true);
    setError("");
    try {
      const response = await workbenchClient.fetchPlotDirections(bookId, chapter.id, intent);
      setReport(response.report);
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "剧情方向生成失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }

  async function applyDirection(optionId: string) {
    setApplying(optionId);
    setError("");
    try {
      await workbenchClient.applyPlotDirection({ bookId, chapterId: chapter.id, optionId });
      message.success("剧情方向已应用到章节规划。");
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "剧情方向应用失败，请稍后重试。"));
    } finally {
      setApplying("");
    }
  }

  return (
    <section className="plot-direction-panel">
      <Text type="secondary">剧情方向</Text>
      <Title level={5}>为当前章节选择推进方案</Title>
      <Space direction="vertical" className="wide">
        <Input.TextArea
          value={intent}
          autoSize={{ minRows: 2, maxRows: 4 }}
          placeholder="输入本章想加强的方向"
          onChange={(event) => setIntent(event.target.value)}
        />
        <Button block icon={<BranchesOutlined />} loading={loading} onClick={() => void loadDirections()}>
          获取建议
        </Button>
        {error ? <Alert showIcon type="warning" message={error} /> : null}
        {report?.options.map((option) => (
          <div key={option.id} className="plot-direction-card">
            <Flex justify="space-between" align="center" gap={8}>
              <Text strong>{authorText(option.label)}</Text>
              <Tag color={option.recommendation === "recommended" ? "green" : option.recommendation === "risky" ? "red" : "blue"}>
                {statusLabel(option.recommendation)}
              </Tag>
            </Flex>
            <Paragraph className="muted-text">{authorText(option.focus)}</Paragraph>
            <Paragraph className="muted-text">{authorText(option.likelyOutcome)}</Paragraph>
            {option.risks.length ? <SimpleList icon={<ExperimentOutlined />} items={option.risks.slice(0, 2)} /> : null}
            <Button
              size="small"
              disabled={option.recommendation === "risky"}
              loading={applying === option.id}
              onClick={() => void applyDirection(option.id)}
            >
              应用到章节规划
            </Button>
          </div>
        ))}
      </Space>
    </section>
  );
}

function IdeationPanel({ bookId, chapter }: { bookId: string; chapter: Chapter }) {
  const { data, refetch, isLoading } = useQuery({
    queryKey: ["ideation-sessions", bookId],
    queryFn: () => workbenchClient.fetchIdeationSessions(bookId)
  });
  const [seed, setSeed] = useState(`下一章怎么承接：${chapter.title}`);
  const [turn, setTurn] = useState("");
  const [activeSessionId, setActiveSessionId] = useState("");
  const [saving, setSaving] = useState(false);
  const sessions = data?.sessions ?? [];
  const activeSession = sessions.find((session) => session.sessionId === activeSessionId) ?? sessions[0];

  async function createSession() {
    setSaving(true);
    try {
      const response = await workbenchClient.createIdeationSession({
        bookId,
        title: `${chapter.title} 创意探索`,
        focus: chapter.summary,
        seed
      });
      setActiveSessionId(response.session.sessionId);
      await refetch();
    } finally {
      setSaving(false);
    }
  }

  async function appendTurn() {
    if (!activeSession || !turn.trim()) {
      return;
    }
    setSaving(true);
    try {
      await workbenchClient.appendIdeationTurn(bookId, activeSession.sessionId, {
        role: "user",
        content: turn
      });
      setTurn("");
      await refetch();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Space direction="vertical" className="wide">
      <Text type="secondary">创意会话</Text>
      <Input.TextArea value={seed} autoSize={{ minRows: 3, maxRows: 5 }} onChange={(event) => setSeed(event.target.value)} />
      <Button block icon={<BulbOutlined />} loading={saving} onClick={() => void createSession()}>
        开始创意会话
      </Button>
      {isLoading ? <Text type="secondary">正在读取会话...</Text> : null}
      {activeSession ? (
        <div className="ideation-session-card">
          <Text strong>{authorText(activeSession.title)}</Text>
          <Space direction="vertical" className="wide ideation-turns">
            {activeSession.turns.slice(-4).map((item, index) => (
              <Paragraph key={`${item.createdAt}-${index}`} className="muted-text">
                {authorText(`${item.role}：${item.content}`)}
              </Paragraph>
            ))}
          </Space>
          <Input.TextArea value={turn} autoSize={{ minRows: 2, maxRows: 4 }} onChange={(event) => setTurn(event.target.value)} />
          <Button block loading={saving} onClick={() => void appendTurn()}>
            追加回合
          </Button>
        </div>
      ) : null}
    </Space>
  );
}

function WritingLessonsPanel({ bookId }: { bookId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["writing-lessons", bookId],
    queryFn: () => workbenchClient.fetchWritingLessons(bookId)
  });
  if (isLoading) {
    return <Text type="secondary">正在读取写作经验...</Text>;
  }
  if (error) {
    return <Alert showIcon type="warning" message="写作经验读取失败" description={authorText(error instanceof Error ? error.message : "请稍后重试。")} />;
  }
  if (!data?.lessons.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前书还没有沉淀写作经验" />;
  }
  return (
    <Space direction="vertical" className="wide">
      {data.groups.map((group) => (
        <div key={group.category}>
          <Text type="secondary">{statusLabel(group.category, "写作经验")}</Text>
          <Space direction="vertical" className="wide">
            {group.lessons.map((lesson) => (
              <div key={lesson.id || lesson.lesson} className="lesson-item">
                <Tag color={lesson.severity === "high" ? "red" : lesson.severity === "medium" ? "orange" : "blue"}>
                  {statusLabel(lesson.severity || "lesson", "写作经验")}
                </Tag>
                <Paragraph>{authorText(lesson.lesson)}</Paragraph>
                {lesson.sourceChapters.length ? <Text type="secondary">来源：{lesson.sourceChapters.join("、")}</Text> : null}
              </div>
            ))}
          </Space>
        </div>
      ))}
    </Space>
  );
}

function CharacterStatePanel({ bookId, chapterId }: { bookId: string; chapterId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["character-snapshot", bookId, chapterId],
    queryFn: () => workbenchClient.fetchCharacterSnapshot(bookId, chapterId)
  });
  if (isLoading) {
    return <Text type="secondary">正在读取人物状态...</Text>;
  }
  if (error) {
    return <Alert showIcon type="warning" message="人物状态读取失败" description={authorText(error instanceof Error ? error.message : "请稍后重试。")} />;
  }
  if (!data?.characters.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前章节还没有人物状态快照" />;
  }
  return (
    <Space direction="vertical" className="wide">
      {data.characters.map((character) => (
        <div key={character.id || character.name} className="character-state-item">
          <Flex justify="space-between" align="center" gap={8}>
            <Text strong>{authorText(character.name)}</Text>
            {typeof character.relationshipScore === "number" ? <Tag>{character.relationshipScore}</Tag> : null}
          </Flex>
          <Text type="secondary">{authorText(character.emotion || "情绪未记录")}</Text>
          <Paragraph className="muted-text">{authorText(character.goal || "当前目标未记录")}</Paragraph>
          {character.relationshipStatus ? <Tag color="blue">{authorText(character.relationshipStatus)}</Tag> : null}
        </div>
      ))}
    </Space>
  );
}

function SceneContractPanel({ bookId, chapterId, fallbackItems }: { bookId: string; chapterId: string; fallbackItems: string[] }) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["chapter-contract", bookId, chapterId],
    queryFn: () => workbenchClient.fetchChapterContract(bookId, chapterId)
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const contract = data?.contract ?? {};

  useEffect(() => {
    if (!data?.contract) {
      return;
    }
    setFields(Object.fromEntries(contractFieldKeys.map((key) => [key, String(data.contract[key] ?? "")])));
  }, [data]);

  async function saveContract() {
    setSaving(true);
    try {
      await workbenchClient.updateChapterContract({ bookId, chapterId, fields });
      await refetch();
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return <Text type="secondary">正在读取章节规划...</Text>;
  }
  if (error) {
    return <Alert showIcon type="warning" message="章节规划读取失败" description={authorText(error instanceof Error ? error.message : "请稍后重试。")} />;
  }
  return (
    <Space direction="vertical" className="wide">
      <SimpleList icon={<BookOutlined />} items={fallbackItems} />
      {contractFieldKeys.map((key) => (
        <div key={key}>
          <Text type="secondary">{contractFieldLabels[key]}</Text>
          <Input.TextArea
            aria-label={contractFieldLabels[key]}
            value={fields[key] ?? String(contract[key] ?? "")}
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(event) => setFields((current) => ({ ...current, [key]: event.target.value }))}
          />
        </div>
      ))}
      <Button type="primary" loading={saving} onClick={() => void saveContract()}>
        保存章节规划
      </Button>
    </Space>
  );
}

function previousChapterEnding(chapters: Chapter[], chapterId: string) {
  const index = chapters.findIndex((item) => item.id === chapterId);
  if (index <= 0) {
    return "";
  }
  const paragraphs = chapters[index - 1].content.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  return paragraphs.slice(-2).join("\n\n");
}

function GateIssueList({
  issues,
  onFocusSnippet
}: {
  issues: ChapterGateResponse["gate"]["issues"];
  onFocusSnippet: (snippet: string) => void;
}) {
  const groups = [
    { key: "block", title: "硬阻断", issues: issues.filter((issue) => gateIssueLayer(issue) === "block") },
    { key: "repair", title: "建议修复", issues: issues.filter((issue) => gateIssueLayer(issue) === "repair") },
    { key: "reference", title: "风险参考", issues: issues.filter((issue) => gateIssueLayer(issue) === "reference") }
  ];
  return (
    <Space direction="vertical" className="wide gate-list">
      {groups.filter((group) => group.issues.length).map((group) => (
        <div key={group.key} className="gate-issue-layer">
          <Text strong>{group.title}</Text>
          {group.key === "reference" ? <Text type="secondary">仅供判断风险，不单独阻止接收。</Text> : null}
          {group.issues.slice(0, 6).map((issue) => (
            <button
              key={`${issue.stage}-${issue.type}-${issue.message}`}
              type="button"
              className="gate-issue-button"
              onClick={() => onFocusSnippet(issue.textSnippet)}
            >
              <CheckCircleOutlined />
              <span>
                {authorText(issue.message)}
                {issue.suggestionHint ? <small>{authorText(issue.suggestionHint)}</small> : null}
              </span>
            </button>
          ))}
        </div>
      ))}
    </Space>
  );
}

function gateIssueLayer(issue: ChapterGateResponse["gate"]["issues"][number]): "block" | "repair" | "reference" {
  if (issue.severity === "blocker") return "block";
  if (["dialogue_ratio_out_of_range", "scene_switch_too_frequent", "anti_ai_trace"].includes(issue.type)) return "reference";
  return "repair";
}

function renderHighlightedParagraph(paragraph: string, snippets: string[], activeSnippet: string) {
  const snippet = snippets.find((item) => item && paragraph.includes(item));
  if (!snippet) {
    return authorText(paragraph);
  }
  const start = paragraph.indexOf(snippet);
  const before = paragraph.slice(0, start);
  const after = paragraph.slice(start + snippet.length);
  return (
    <>
      {authorText(before)}
      <mark className={snippet === activeSnippet ? "active" : ""}>{authorText(snippet)}</mark>
      {authorText(after)}
    </>
  );
}

function ReviewReminder({ items, onOpenReview }: { items: string[]; onOpenReview?: () => void }) {
  return (
    <Space direction="vertical" size={12} className="wide">
      <div>
        <Text type="secondary">审稿提醒</Text>
        <Title level={5}>处理后再接收正文更稳</Title>
      </div>
      {items.length ? (
        <SimpleList icon={<HighlightOutlined />} items={items} />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前章节暂无审稿提醒" />
      )}
      <Button block icon={<HighlightOutlined />} onClick={onOpenReview}>
        进入审稿中心
      </Button>
    </Space>
  );
}

function DraftHistoryModal({
  open,
  snapshots,
  onClose,
  onRestore
}: {
  open: boolean;
  snapshots: DraftSnapshot[];
  onClose: () => void;
  onRestore: (snapshot: DraftSnapshot) => void;
}) {
  return (
    <Modal
      centered
      className="draft-history-modal"
      width={640}
      open={open}
      title="本地历史版本"
      footer={null}
      onCancel={onClose}
    >
      {snapshots.length ? (
        <Timeline
          className="draft-history-timeline"
          items={snapshots.map((snapshot) => ({
            children: (
              <div className="draft-history-item">
                <Text strong>{new Date(snapshot.savedAt).toLocaleString()} · {snapshot.wordCount.toLocaleString()} 字</Text>
                <Paragraph className="draft-history-preview" ellipsis={{ rows: 4 }}>
                  {authorText(snapshot.content)}
                </Paragraph>
                <Button size="small" onClick={() => onRestore(snapshot)}>
                  恢复到编辑区
                </Button>
              </div>
            )
          }))}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前章节还没有本地历史版本" />
      )}
    </Modal>
  );
}

function PostAcceptSummaryModal({
  summary,
  onClose,
  onOpenReview
}: {
  summary: PostAcceptSummary | null;
  onClose: () => void;
  onOpenReview?: () => void;
}) {
  return (
    <Modal
      open={Boolean(summary)}
      title="章节接收后复盘"
      onCancel={onClose}
      footer={[
        <Button key="later" onClick={onClose}>稍后再看</Button>,
        <Button
          key="review"
          type="primary"
          onClick={() => {
            onClose();
            onOpenReview?.();
          }}
        >
          查看复盘
        </Button>
      ]}
    >
      {summary ? (
        <Space direction="vertical" className="wide">
          <Alert
            showIcon
            type={summary.gateStatus === "pass" ? "success" : summary.gateStatus === "warn" ? "warning" : "info"}
            message={authorText(summary.chapterTitle)}
            description={`Gate ${summary.gateScore} 分，记录 ${summary.issueCount} 条接收前问题。`}
          />
          <ListLike
            items={[
              summary.patchPath ? `已生成记忆更新复盘：${summary.patchPath}` : "本章没有返回独立复盘路径。",
              summary.reviewTitle ? `审稿任务：${summary.reviewTitle}` : "暂无新增审稿任务标题。",
              summary.nextAction || "建议查看接收后复盘。"
            ]}
          />
        </Space>
      ) : null}
    </Modal>
  );
}

function derivePlaceAndForces(chapter: Chapter) {
  return chapter.clues.slice(0, 4).length ? chapter.clues.slice(0, 4) : ["本章地点待从资料页补齐", "相关势力待确认"];
}

function dueWeight(status: Material["dueStatus"]) {
  if (status === "overdue") {
    return 0;
  }
  if (status === "at_risk") {
    return 1;
  }
  if (status === "on_track") {
    return 2;
  }
  return 3;
}

const contractFieldKeys = ["openingHook", "internalNeed", "stakes", "cost", "subtext", "aftertaste"];
const contractFieldLabels: Record<string, string> = {
  openingHook: "开场钩子",
  internalNeed: "内在需求",
  stakes: "利害关系",
  cost: "代价",
  subtext: "潜台词",
  aftertaste: "余味"
};
