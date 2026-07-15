import { useEffect, useRef, useState } from "react";
import type { Key, ReactNode } from "react";
import { Alert, Button, Card, Divider, Empty, Flex, Input, InputNumber, message, Modal, Pagination, Progress, Radio, Select, Space, Steps, Tag, Tooltip, Typography } from "antd";
import { EditOutlined, ExperimentOutlined, FolderOpenOutlined, SearchOutlined } from "@ant-design/icons";
import { workbenchClient } from "../api/workbenchClient";
import { WorkbenchField, WorkbenchForm } from "../components/shared";
import type { Book, BookCreationOptions, BookCreationSetup, GenerationMode, GenerationState, NewBookDraft, PlatformStyleOption, TensionPoint } from "../types";
import { authorText } from "../utils/authorText";
import { statusLabel } from "../utils/statusLabel";

const { Text, Title, Paragraph } = Typography;
const CREATION_DRAFT_KEY = "open_novel_creation_draft_v1";
const creationModeOptions = [
  { label: "自动推进", value: "full_auto" },
  { label: "阶段确认", value: "stage_confirm" },
  { label: "逐章确认", value: "chapter_confirm" },
  { label: "深度参与", value: "deep_control" }
];

export function ShelfPage({
  books,
  activeBook,
  search,
  onSearchChange,
  onCreateBook,
  creationOptions,
  generationStates,
  createLoading,
  onSelectBook,
  onOpenBook,
  onBookUpdated
}: {
  books: Book[];
  activeBook: Book;
  search: string;
  onSearchChange: (value: string) => void;
  onCreateBook: (draft: NewBookDraft, setup: BookCreationSetup) => void | Promise<void>;
  creationOptions: BookCreationOptions;
  generationStates: GenerationState[];
  createLoading: boolean;
  onSelectBook: (bookId: string) => void;
  onOpenBook: (bookId: string) => void;
  onBookUpdated: (book: Book) => void;
}) {
  const [createOpen, setCreateOpen] = useState(false);
  const [sortBy, setSortBy] = useState("最近更新");
  const defaultStyle = creationOptions.platformStyles[0];
  const defaultGenre = defaultStyle ? defaultGenreForStyle(defaultStyle, creationOptions) : "";
  const savedDraft = useRef(readSavedCreationDraft()).current;
  const [draftTitle, setDraftTitle] = useState(savedDraft.title);
  const [draftStyleProfileId, setDraftStyleProfileId] = useState(savedDraft.styleProfileId || defaultStyle?.id || "");
  const [draftGenre, setDraftGenre] = useState(savedDraft.genre || defaultGenre);
  const [draftTagline, setDraftTagline] = useState(savedDraft.tagline);
  const [draftChapterTitle, setDraftChapterTitle] = useState(savedDraft.firstChapterTitle);
  const [draftSeed, setDraftSeed] = useState(savedDraft.seed);
  const [createStep, setCreateStep] = useState(0);
  const [interventionMode, setInterventionMode] = useState<GenerationMode>(savedDraft.interventionMode);
  const [batchTarget, setBatchTarget] = useState(savedDraft.batchTarget);
  const [targetChapterCount, setTargetChapterCount] = useState(savedDraft.targetChapterCount);
  const [targetWordsPerChapter, setTargetWordsPerChapter] = useState(savedDraft.targetWordsPerChapter);
  const [targetChaptersPerPlot, setTargetChaptersPerPlot] = useState(savedDraft.targetChaptersPerPlot);
  const [bookPage, setBookPage] = useState(1);
  const [formError, setFormError] = useState("");
  const [aiFilling, setAiFilling] = useState(false);
  const [selectedChapterIds, setSelectedChapterIds] = useState<Key[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsTitle, setSettingsTitle] = useState(activeBook.title);
  const [settingsGenre, setSettingsGenre] = useState(activeBook.genre);
  const [settingsTagline, setSettingsTagline] = useState(activeBook.tagline);
  const [settingsStyleId, setSettingsStyleId] = useState(activeBook.styleProfileId);
  const createOpenRef = useRef(createOpen);
  const aiFillRequestRef = useRef(0);
  const creationReady = creationOptions.platformStyles.length > 0 && creationOptions.genres.length > 0;

  useEffect(() => {
    createOpenRef.current = createOpen;
  }, [createOpen]);

  useEffect(() => {
    if (!creationReady) {
      return;
    }
    const styleStillAvailable = creationOptions.platformStyles.some((style) => style.id === draftStyleProfileId);
    if (!draftStyleProfileId || !styleStillAvailable) {
      setDraftStyleProfileId(defaultStyle?.id ?? "");
      setDraftGenre(defaultGenre);
      return;
    }
    const genreStillAvailable = creationOptions.genres.some((genre) => genre.value === draftGenre);
    if (!draftGenre || !genreStillAvailable) {
      const selectedStyle = getSelectedStyle(draftStyleProfileId, creationOptions);
      setDraftGenre(defaultGenreForStyle(selectedStyle, creationOptions));
    }
  }, [creationOptions, creationReady, defaultGenre, defaultStyle?.id, draftGenre, draftStyleProfileId]);

  useEffect(() => {
    saveCreationDraft({
      title: draftTitle,
      styleProfileId: draftStyleProfileId,
      genre: draftGenre,
      tagline: draftTagline,
      firstChapterTitle: draftChapterTitle,
      seed: draftSeed,
      modelId: "",
      interventionMode,
      batchTarget,
      targetChapterCount,
      targetWordsPerChapter,
      targetChaptersPerPlot
    });
  }, [batchTarget, draftChapterTitle, draftGenre, draftSeed, draftStyleProfileId, draftTagline, draftTitle, interventionMode, targetChapterCount, targetChaptersPerPlot, targetWordsPerChapter]);

  const visibleBooks = books
    .filter((book) => {
      const keyword = search.trim().toLowerCase();
      if (!keyword) {
        return true;
      }
      return [book.title, book.genre, book.styleProfileLabel, book.platform, book.tagline, book.nextAction].some((value) =>
        value.toLowerCase().includes(keyword)
      );
    })
    .sort((left, right) => {
      if (sortBy === "进度") {
        return right.progress - left.progress;
      }
      if (sortBy === "待处理优先") {
        return riskScore(right) - riskScore(left);
      }
      return books.indexOf(left) - books.indexOf(right);
    });
  const selectedGenerationState = generationStates.find((state) => state.bookId === activeBook.id);
  const hasActiveBook = activeBook.id !== "empty-book" && books.some((book) => book.id === activeBook.id);
  const bookPageSize = 6;
  const pagedBooks = visibleBooks.slice((bookPage - 1) * bookPageSize, bookPage * bookPageSize);

  useEffect(() => {
    setBookPage(1);
  }, [books.length, search, sortBy]);

  function resetCreateDraft() {
    aiFillRequestRef.current += 1;
    setAiFilling(false);
    setDraftTitle("");
    setDraftStyleProfileId(defaultStyle?.id ?? "");
    setDraftGenre(defaultGenre);
    setDraftTagline("");
    setDraftChapterTitle("");
    setDraftSeed("");
    setCreateStep(0);
    setInterventionMode("stage_confirm");
    setBatchTarget(1);
    setTargetChapterCount(200);
    setTargetWordsPerChapter(2500);
    setTargetChaptersPerPlot(10);
    setFormError("");
    sessionStorage.removeItem(CREATION_DRAFT_KEY);
  }

  async function aiFillBookDraft() {
    if (!creationReady) {
      setFormError("作品创建配置还在加载，稍后再生成初始设定。");
      return;
    }
    const selectedStyle = getSelectedStyle(draftStyleProfileId, creationOptions);
    const assistBookId = activeBook?.id && activeBook.id !== "empty-book" ? activeBook.id : books[0]?.id ?? "workspace-seed";
    const baseSeed =
      draftSeed.trim() ||
      `平台风格：${selectedStyle.label}\n题材：${draftGenre || defaultGenreForStyle(selectedStyle, creationOptions)}\n请生成作品标题、简介、首章标题和开场灵感。`;
    const requestId = aiFillRequestRef.current + 1;
    aiFillRequestRef.current = requestId;
    setAiFilling(true);
    setFormError("");
    try {
      const response = await workbenchClient.runAgentAssist({
        bookId: assistBookId,
        scope: "book",
        action: "生成新书初始设定",
        input: baseSeed
      });
      if (aiFillRequestRef.current !== requestId || !createOpenRef.current) {
        return;
      }
      const nextIndex = books.length + 1;
      const candidateText = response.candidateText?.trim() || response.content.trim();
      setDraftTitle((value) => value || deriveBookTitle(candidateText, nextIndex));
      setDraftGenre((value) => value || defaultGenreForStyle(selectedStyle, creationOptions));
      setDraftTagline((value) => value || deriveBookTagline(candidateText, buildDefaultTagline(selectedStyle, draftGenre)));
      setDraftChapterTitle((value) => value || deriveFirstChapterTitle(candidateText));
      setDraftSeed(candidateText || baseSeed);
      message.success("AI 已生成新书初始设定，可继续编辑后创建。");
    } catch (error) {
      if (aiFillRequestRef.current !== requestId || !createOpenRef.current) {
        return;
      }
      setFormError(authorText(error instanceof Error ? error.message : "AI 初始设定生成失败，请稍后重试。"));
    } finally {
      if (aiFillRequestRef.current === requestId) {
        setAiFilling(false);
      }
    }
  }

  async function submitCreateBook() {
    if (!creationReady) {
      setFormError("作品创建配置还在加载，请稍后再试。");
      return;
    }
    if (!draftTitle.trim()) {
      setFormError("先填写作品名称。");
      return;
    }
    setFormError("");
    const selectedStyle = getSelectedStyle(draftStyleProfileId, creationOptions);
    try {
      await onCreateBook({
        title: draftTitle,
        platform: selectedStyle.platform,
        styleProfileId: selectedStyle.id,
        styleProfileLabel: selectedStyle.label,
        genre: draftGenre,
        tagline: draftTagline,
        firstChapterTitle: draftChapterTitle,
        seed: draftSeed
      }, {
        modelId: "",
        interventionMode,
        batchTarget,
        targetChapterCount,
        targetWordsPerChapter,
        targetChaptersPerPlot
      });
      setCreateOpen(false);
      resetCreateDraft();
    } catch (error) {
      setFormError(authorText(error instanceof Error ? error.message : "作品创建失败，请稍后重试。"));
    }
  }

  function openBookSettings() {
    setSettingsTitle(activeBook.title);
    setSettingsGenre(activeBook.genre);
    setSettingsTagline(activeBook.tagline);
    setSettingsStyleId(activeBook.styleProfileId);
    setFormError("");
    setSettingsOpen(true);
  }

  async function saveBookSettings() {
    if (!settingsTitle.trim() || !settingsGenre.trim() || !settingsStyleId) {
      setFormError("作品名称、题材和风格不能为空。");
      return;
    }
    const style = getSelectedStyle(settingsStyleId, creationOptions);
    setSettingsSaving(true);
    setFormError("");
    try {
      const result = await workbenchClient.updateBookSettings({
        bookId: activeBook.id,
        title: settingsTitle,
        genre: settingsGenre,
        tagline: settingsTagline,
        styleProfileId: style.id,
        styleProfileLabel: style.label
      });
      onBookUpdated(result.book);
      setSettingsOpen(false);
      message.success(result.authorMessage);
    } catch (settingsError) {
      setFormError(authorText(settingsError instanceof Error ? settingsError.message : "作品设置保存失败。"));
    } finally {
      setSettingsSaving(false);
    }
  }

  return (
    <div className="single-page">
      <Flex justify="space-between" align="center" gap={16} className="section-toolbar">
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索书名、题材或下一步"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
        <Space wrap>
          <Text type="secondary">排序</Text>
          <Select
            value={sortBy}
            onChange={setSortBy}
            options={["最近更新", "进度", "待处理优先"].map((item) => ({ label: item, value: item }))}
          />
          {books.length ? (
            <Button icon={<FolderOpenOutlined />} onClick={() => setCreateOpen(true)}>
              新建作品
            </Button>
          ) : null}
        </Space>
      </Flex>
      <div className={`page-grid shelf-grid ${!hasActiveBook ? "shelf-grid-empty" : ""}`}>
        <section className="main-column">
          {visibleBooks.length ? (
            <>
            <div className="book-grid">
              {pagedBooks.map((book) => {
                const generationState = generationStates.find((state) => state.bookId === book.id);
                const quality = book.qualitySummary;
                return (
                  <Card
                    key={book.id}
                    className={`book-card ${book.id === activeBook.id ? "active" : ""}`}
                    variant="borderless"
                    onClick={() => onSelectBook(book.id)}
                  >
                    <Flex justify="space-between" align="start" gap={14}>
                      <div>
                        <Space wrap>
                          <Tag>{authorText(book.genre)}</Tag>
                          <Tag color="blue">{authorText(book.styleProfileLabel)}</Tag>
                          {generationState ? (
                            <Tag color={generationStatusColor(generationState.status)}>
                              {authorText(generationState.statusLabel)}
                            </Tag>
                          ) : null}
                        </Space>
                        <Title level={3}>{authorText(book.title)}</Title>
                        <Paragraph className="muted-text">{authorText(book.tagline)}</Paragraph>
                      </div>
                      <Progress type="circle" percent={book.progress} size={66} />
                    </Flex>
                    <Divider />
                    {quality ? <ShelfQualityBlock book={book} /> : null}
                    <Text type="secondary">下一步</Text>
                    <Paragraph strong>{authorText(generationState?.nextAction || book.nextAction)}</Paragraph>
                    {generationState ? (
                      <Space wrap className="shelf-generation-tags">
                        <Tag>{authorText(generationState.stageLabel)}</Tag>
                        <Tag>{authorText(generationState.interventionModeLabel)}</Tag>
                        <Tag>{generationState.batchDone} / {generationState.batchTarget} 章</Tag>
                        {generationState.blockers.length ? <Tag color="error">有阻断</Tag> : null}
                      </Space>
                    ) : null}
                    <Flex justify="space-between" align="center">
                      <Text type="secondary">{authorText(book.updatedAt)}</Text>
                      <Button
                        type={book.id === activeBook.id ? "primary" : "default"}
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpenBook(book.id);
                        }}
                      >
                        打开
                      </Button>
                    </Flex>
                  </Card>
                );
              })}
            </div>
            <Pagination
              className="book-grid-pagination"
              current={bookPage}
              pageSize={bookPageSize}
              total={visibleBooks.length}
              hideOnSinglePage
              showSizeChanger={false}
              onChange={setBookPage}
            />
            </>
          ) : (
            <Card className="content-card shelf-empty-card" variant="borderless">
              <Empty description={books.length ? "没有匹配的作品" : "还没有作品"}>
                {books.length ? (
                  <Button onClick={() => onSearchChange("")}>清除搜索</Button>
                ) : (
                  <Button type="primary" onClick={() => setCreateOpen(true)}>新建第一部作品</Button>
                )}
              </Empty>
            </Card>
          )}
        </section>
        {hasActiveBook ? <aside className="side-column shelf-detail-column">
          <Card className="side-card" variant="borderless">
            <Flex justify="space-between" align="center" gap={12}>
              <div>
                <Text type="secondary">选中作品</Text>
                <Title level={4}>{authorText(activeBook.title)}</Title>
              </div>
              <Button icon={<EditOutlined />} onClick={openBookSettings}>
                编辑设置
              </Button>
            </Flex>
            <Paragraph className="muted-text">{authorText(activeBook.tagline)}</Paragraph>
            <Divider />
            <Space direction="vertical" className="wide">
              <Flex justify="space-between"><Text>题材</Text><Text strong>{authorText(activeBook.genre)}</Text></Flex>
              <Flex justify="space-between"><Text>平台风格</Text><Text strong>{authorText(activeBook.styleProfileLabel)}</Text></Flex>
              <Flex justify="space-between"><Text>章节数</Text><Text strong>{activeBook.chapters.length}</Text></Flex>
              {activeBook.qualitySummary ? (
                <>
                  <Flex justify="space-between"><Text>完成章节</Text><Text strong>{activeBook.qualitySummary.completedChapterCount} / {activeBook.qualitySummary.targetChapterCount}</Text></Flex>
                  <Flex justify="space-between"><Text>平均质量</Text><Text strong>{activeBook.qualitySummary.averageQualityScore || "-"}</Text></Flex>
                  <Flex justify="space-between"><Text>近 5 章质量</Text><Text strong>{activeBook.qualitySummary.recentAverageQualityScore || "-"}</Text></Flex>
                  <Flex justify="space-between"><Text>连贯性健康度</Text><Text strong>{activeBook.qualitySummary.coherenceScore}</Text></Flex>
                  <Flex justify="space-between"><Text>训练准入</Text><Text strong>{activeBook.qualitySummary.trainingEligibleCount} 章</Text></Flex>
                  {activeBook.qualitySummary.lastTrainingRunAt ? (
                    <Flex justify="space-between"><Text>最近训练</Text><Text strong>{authorText(activeBook.qualitySummary.lastTrainingRunAt)}</Text></Flex>
                  ) : null}
                </>
              ) : null}
              <Flex justify="space-between"><Text>最近更新</Text><Text strong>{authorText(activeBook.updatedAt)}</Text></Flex>
              {selectedGenerationState ? (
                <>
                  <Flex justify="space-between"><Text>生成阶段</Text><Text strong>{authorText(selectedGenerationState.stageLabel)}</Text></Flex>
                  <Flex justify="space-between"><Text>干预档位</Text><Text strong>{authorText(selectedGenerationState.interventionModeLabel)}</Text></Flex>
                  <Flex justify="space-between"><Text>本次目标</Text><Text strong>{selectedGenerationState.batchDone} / {selectedGenerationState.batchTarget} 章</Text></Flex>
                </>
              ) : null}
            </Space>
            <Divider />
            <div className="shelf-summary-metrics">
              <div className="summary-metric">
                <Text type="secondary">进度</Text>
                <Text strong>{activeBook.progress}%</Text>
              </div>
              <div className="summary-metric">
                <Text type="secondary">待处理</Text>
                <Text strong>{riskScore(activeBook)}</Text>
              </div>
            </div>
            <Text type="secondary">下一步</Text>
            <Paragraph strong>{authorText(selectedGenerationState?.nextAction || activeBook.nextAction)}</Paragraph>
            <MemoryInspectionBlock book={activeBook} />
            <Divider />
            <ChapterStatusHeatmap book={activeBook} onOpenChapter={onOpenBook} />
            <BookAnalysisPanel book={activeBook} />
            {activeBook.chapters.length ? (
              <>
                <Divider />
                <Text type="secondary">章节列表</Text>
                <div className="shelf-chapter-list">
                  {activeBook.chapters.map((chapter) => {
                    const checked = selectedChapterIds.includes(chapter.id);
                    return (
                      <label key={chapter.id} className={`shelf-chapter-row ${checked ? "selected" : ""}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(event) => {
                            setSelectedChapterIds((current) => event.target.checked
                              ? [...current, chapter.id]
                              : current.filter((id) => id !== chapter.id));
                          }}
                        />
                        <span className="shelf-chapter-copy">
                          <Text strong ellipsis={{ tooltip: authorText(chapter.title) }}>{authorText(chapter.title)}</Text>
                          <Text type="secondary">{authorText(chapter.status)} · {chapter.wordCount.toLocaleString()} 字</Text>
                        </span>
                      </label>
                    );
                  })}
                </div>
                <Space wrap className="batch-chapter-actions">
                  <Tag>已选 {selectedChapterIds.length} 章</Tag>
                  <Button
                    disabled={!selectedChapterIds.length}
                    onClick={() => {
                      const titles = activeBook.chapters
                        .filter((item) => selectedChapterIds.includes(item.id))
                        .map((item) => item.title)
                        .join("、");
                      void navigator.clipboard?.writeText(titles);
                      message.success("已复制选中章节标题。");
                    }}
                  >
                    复制选中章节
                  </Button>
                </Space>
              </>
            ) : null}
            {selectedGenerationState?.blockers.length ? (
              <Paragraph className="form-error">{authorText(selectedGenerationState.blockers.join("；"))}</Paragraph>
            ) : null}
            <Button block type="primary" icon={<FolderOpenOutlined />} onClick={() => onOpenBook(activeBook.id)}>
              打开生成主控台
            </Button>
          </Card>
        </aside> : null}
      </div>
      <Modal
        title="新建作品"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          resetCreateDraft();
        }}
        footer={[
          <Button key="cancel" onClick={() => { setCreateOpen(false); resetCreateDraft(); }}>取消</Button>,
          createStep > 0 ? <Button key="previous" onClick={() => { setFormError(""); setCreateStep((step) => step - 1); }}>上一步</Button> : null,
          createStep < 2 ? (
            <Button
              key="next"
              type="primary"
              disabled={aiFilling || !creationReady}
              onClick={() => {
                if (createStep === 0 && !draftTitle.trim()) {
                  setFormError("先填写作品名称。");
                  return;
                }
                setFormError("");
                setCreateStep((step) => step + 1);
              }}
            >下一步</Button>
          ) : (
            <Button key="create" type="primary" loading={createLoading} onClick={() => void submitCreateBook()}>创建并生成方向</Button>
          )
        ]}
      >
        <WorkbenchForm>
          <Steps
            size="small"
            current={createStep}
            items={[{ title: "作品想法" }, { title: "生成方式" }, { title: "确认创建" }]}
          />
          {!creationReady ? (
            <Paragraph className="muted-text">正在读取作品创建配置...</Paragraph>
          ) : null}
          {formError ? <Paragraph className="form-error">{formError}</Paragraph> : null}
          {createStep === 0 ? <>
          <NewBookField label="作品名称">
            <Input
              status={formError ? "error" : undefined}
              placeholder="作品名称"
              value={draftTitle}
              onChange={(event) => {
                setDraftTitle(event.target.value);
                if (formError) {
                  setFormError("");
                }
              }}
            />
          </NewBookField>
          <NewBookField label="平台风格">
            <Select
              className="new-book-control"
              value={draftStyleProfileId}
              optionLabelProp="label"
              popupClassName="new-book-style-popup"
              popupMatchSelectWidth
              disabled={!creationReady}
              onChange={(value) => {
                const selectedStyle = getSelectedStyle(value, creationOptions);
                setDraftStyleProfileId(value);
                setDraftGenre(defaultGenreForStyle(selectedStyle, creationOptions));
              }}
              optionRender={(option) => {
                const style = option.data.style as PlatformStyleOption | undefined;
                if (!style) {
                  return option.label;
                }
                return (
                  <div className="style-option">
                    <Flex justify="space-between" align="start" gap={12}>
                      <Text strong className="style-option-title">{authorText(style.label)}</Text>
                      <Tag color={style.status === "active" ? "green" : style.status === "candidate" ? "blue" : "default"}>
                        {style.status === "candidate" ? "专项" : "通用"}
                      </Tag>
                    </Flex>
                    <Text type="secondary" className="style-option-platform">{authorText(creationOptions.platformLabels[style.platform] ?? style.platform)}</Text>
                    <Paragraph className="muted-text style-option-summary">{authorText(style.summary)}</Paragraph>
                  </div>
                );
              }}
              options={creationOptions.platformStyles.map((style) => ({
                label: authorText(style.label),
                value: style.id,
                style
              }))}
            />
          </NewBookField>
          <NewBookField label="题材">
            <Select
              className="new-book-control"
              value={draftGenre}
              showSearch
              placeholder="选择题材"
              disabled={!creationReady}
              onChange={setDraftGenre}
              options={creationOptions.genres.map((genre) => ({ label: authorText(genre.label), value: genre.value }))}
            />
          </NewBookField>
          <Paragraph className="inline-note">
            这里只显示可直接用于创建的中文风格模板；选择结果会和作品一起保存。
          </Paragraph>
          <NewBookField label="一句话简介">
            <Input.TextArea
              rows={3}
              placeholder="一句话简介"
              value={draftTagline}
              onChange={(event) => setDraftTagline(event.target.value)}
            />
          </NewBookField>
          <NewBookField label="首章标题">
            <Input
              placeholder="首章标题"
              value={draftChapterTitle}
              onChange={(event) => setDraftChapterTitle(event.target.value)}
            />
          </NewBookField>
          <NewBookField label="开场种子">
            <Input.TextArea
              rows={4}
              placeholder="给 AI 的新书想法，可以是一句话、题材方向或开场灵感"
              value={draftSeed}
              onChange={(event) => setDraftSeed(event.target.value)}
            />
          </NewBookField>
          <Button block icon={<ExperimentOutlined />} disabled={!creationReady || createLoading} loading={aiFilling} onClick={() => void aiFillBookDraft()}>
            AI 生成初始设定
          </Button>
          </> : null}
          {createStep === 1 ? <>
            <Alert
              type="info"
              showIcon
              message="生成将使用“AI 模型”中的写作角色"
              description="无需为每本书重复选择账号；创建前请在菜单栏第一项“AI 模型”中新增、拨测账号并分配写作角色。"
            />
            <NewBookField label="作者介入方式">
              <Radio.Group
                value={interventionMode}
                onChange={(event) => setInterventionMode(event.target.value)}
                options={creationModeOptions}
              />
            </NewBookField>
            <Alert type="info" showIcon message={creationModeDescription(interventionMode)} />
            <Flex gap={12} wrap="wrap">
              <NewBookField label="本次生成">
                <InputNumber aria-label="本次生成章节数" min={1} max={20} value={batchTarget} onChange={(value) => setBatchTarget(value ?? 1)} addonAfter="章" />
              </NewBookField>
              <NewBookField label="全书目标">
                <InputNumber aria-label="全书目标章节数" min={1} max={2000} value={targetChapterCount} onChange={(value) => setTargetChapterCount(value ?? 200)} addonAfter="章" />
              </NewBookField>
              <NewBookField label="单章目标">
                <InputNumber aria-label="每章目标字数" min={500} max={20000} step={100} value={targetWordsPerChapter} onChange={(value) => setTargetWordsPerChapter(value ?? 2500)} addonAfter="字" />
              </NewBookField>
              <NewBookField label="剧情段目标">
                <InputNumber aria-label="每个剧情段目标章节数" min={1} max={100} value={targetChaptersPerPlot} onChange={(value) => setTargetChaptersPerPlot(value ?? 10)} addonAfter="章" />
              </NewBookField>
            </Flex>
          </> : null}
          {createStep === 2 ? <>
            <Title level={5}>{draftTitle || "未命名作品"}</Title>
            <Paragraph>{draftTagline || draftSeed || "尚未填写一句话简介。"}</Paragraph>
            <Divider />
            <Paragraph>将使用“AI 模型”中分配的<Text strong>写作角色</Text>，以“{creationModeLabel(interventionMode)}”方式启动。</Paragraph>
            <Paragraph>创建后立即进入生成主控台，并生成作品方向候选；正式作品架构会等候当前档位确认后再写入。</Paragraph>
            <Space wrap>
              <Tag>本次 {batchTarget} 章</Tag>
              <Tag>全书 {targetChapterCount} 章</Tag>
              <Tag>单章 {targetWordsPerChapter} 字</Tag>
              <Tag>每个剧情段约 {targetChaptersPerPlot} 章</Tag>
            </Space>
          </> : null}
        </WorkbenchForm>
      </Modal>
      <Modal
        title="编辑作品设置"
        open={settingsOpen}
        okText="保存设置"
        cancelText="取消"
        confirmLoading={settingsSaving}
        onOk={() => void saveBookSettings()}
        onCancel={() => setSettingsOpen(false)}
      >
        <WorkbenchForm>
          {formError ? <Paragraph className="form-error">{formError}</Paragraph> : null}
          <NewBookField label="作品名称">
            <Input value={settingsTitle} onChange={(event) => setSettingsTitle(event.target.value)} />
          </NewBookField>
          <NewBookField label="题材">
            <Select
              showSearch
              value={settingsGenre}
              options={creationOptions.genres.map((genre) => ({ value: genre.value, label: genre.label }))}
              onChange={setSettingsGenre}
            />
          </NewBookField>
          <NewBookField label="平台风格">
            <Select
              value={settingsStyleId}
              options={creationOptions.platformStyles.map((style) => ({ value: style.id, label: style.label }))}
              onChange={setSettingsStyleId}
            />
          </NewBookField>
          <NewBookField label="一句话简介">
            <Input.TextArea rows={4} value={settingsTagline} onChange={(event) => setSettingsTagline(event.target.value)} />
          </NewBookField>
        </WorkbenchForm>
      </Modal>
    </div>
  );
}

function ShelfQualityBlock({ book }: { book: Book }) {
  const quality = book.qualitySummary;
  if (!quality) {
    return null;
  }
  const trend = qualityTrend(quality.averageQualityScore, quality.recentAverageQualityScore);
  const tensionWarnings = quality.tensionPoints.filter((point) => point.warning).length;
  return (
    <div className="shelf-quality-block">
      <Space wrap className="shelf-quality-tags">
        <Tag>{quality.completedChapterCount} / {quality.targetChapterCount} 章</Tag>
        <Tag>
          <span className={`quality-dot ${qualityColorClass(quality.averageQualityScore)}`} />
          平均质量 {quality.averageQualityScore || "-"}
        </Tag>
        {trend ? <Tag color={trend.color}>近 5 章 {trend.label}</Tag> : null}
        <Tag color={quality.coherenceScore < 80 ? "warning" : "success"}>连贯性 {quality.coherenceScore}</Tag>
        <Tag>训练准入 {quality.trainingEligibleCount} 章</Tag>
        {tensionWarnings ? <Tag color="warning">节奏预警 {tensionWarnings}</Tag> : null}
        {quality.lastTrainingRunAt ? <Tag>训练 {authorText(quality.lastTrainingRunAt)}</Tag> : null}
      </Space>
      {quality.tensionPoints.length ? <TensionSparkline points={quality.tensionPoints} /> : null}
      {book.arcs.length ? (
        <div className="arc-progress-list">
          {book.arcs.slice(0, 2).map((arc) => (
            <div key={arc.arcId} className="arc-progress-row">
              <Text strong>{authorText(arc.title)}</Text>
              <Progress percent={arc.progress} size="small" />
              <Text type="secondary">{authorText(arc.arcGoal || arc.emotionalArc)}</Text>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ChapterStatusHeatmap({ book, onOpenChapter }: { book: Book; onOpenChapter: (bookId: string) => void }) {
  return (
    <div className="chapter-status-heatmap">
      <Text type="secondary">章节状态</Text>
      <div className="chapter-status-grid">
        {book.chapters.map((chapter) => (
          <Tooltip key={chapter.id} title={`${chapter.title} · ${chapter.status} · ${chapter.progress}%`}>
            <button
              type="button"
              className={`chapter-status-cell status-${chapter.status}`}
              aria-label={`${chapter.title} ${chapter.status}`}
              onClick={() => onOpenChapter(book.id)}
            />
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

function BookAnalysisPanel({ book }: { book: Book }) {
  const [loading, setLoading] = useState("");
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [sequence, setSequence] = useState<Record<string, unknown> | null>(null);
  const [revisionPlan, setRevisionPlan] = useState<Awaited<ReturnType<typeof workbenchClient.buildRevisionPlan>> | null>(null);
  const firstChapter = book.chapters[0]?.id ?? "001";
  const lastChapter = book.chapters.at(-1)?.id ?? firstChapter;
  const analysisPath = typeof analysis?.path === "string" ? analysis.path : "";

  async function runAnalysis() {
    setLoading("analysis");
    try {
      const response = await workbenchClient.analyzeBook({
        bookId: book.id,
        startChapterId: firstChapter,
        endChapterId: lastChapter
      });
      setAnalysis(response.report);
      message.success("书稿分析已完成。");
    } finally {
      setLoading("");
    }
  }

  async function promoteFormulas() {
    if (!analysisPath) {
      return;
    }
    setLoading("formula");
    try {
      await workbenchClient.promoteWritingFormulas({ bookId: book.id, reportPath: analysisPath });
      message.success("写作公式已沉淀到本书记忆。");
    } finally {
      setLoading("");
    }
  }

  async function evaluateSequence() {
    setLoading("sequence");
    try {
      const response = await workbenchClient.evaluateSequence({
        bookId: book.id,
        startChapterId: firstChapter,
        endChapterId: lastChapter,
        preferDrafts: true
      });
      setSequence(response.report);
      message.success("序列评估已完成。");
    } finally {
      setLoading("");
    }
  }

  async function buildRevisionPlan() {
    setLoading("revision");
    try {
      const response = await workbenchClient.buildRevisionPlan({
        bookId: book.id,
        startChapterId: firstChapter,
        endChapterId: lastChapter,
        maxChapters: 3
      });
      setRevisionPlan(response);
      message.success("修订计划已生成。");
    } finally {
      setLoading("");
    }
  }

  return (
    <div className="book-analysis-panel">
      <Space wrap>
        <Button loading={loading === "analysis"} onClick={() => void runAnalysis()}>
          分析我的书稿
        </Button>
        <Button disabled={!analysisPath} loading={loading === "formula"} onClick={() => void promoteFormulas()}>
          提炼写作公式
        </Button>
        <Button loading={loading === "sequence"} onClick={() => void evaluateSequence()}>
          序列评估
        </Button>
        <Button loading={loading === "revision"} onClick={() => void buildRevisionPlan()}>
          修订计划
        </Button>
      </Space>
      {analysis ? (
        <Paragraph className="muted-text">
          分析范围 {String(analysis.startChapterId ?? firstChapter)} - {String(analysis.endChapterId ?? lastChapter)}，
          候选公式 {Array.isArray(analysis.formulaCandidates) ? analysis.formulaCandidates.length : 0} 条。
        </Paragraph>
      ) : null}
      {sequence ? (
        <Paragraph className="muted-text">
          序列状态 {statusLabel(sequence.status)}，
          最低质量 {String(sequence.minQualityScore ?? "-")}。
        </Paragraph>
      ) : null}
      {revisionPlan ? (
        <Paragraph className="muted-text">
          修订状态 {statusLabel(revisionPlan.plan.status)}，
          摘要 {revisionPlan.briefs.length} 章，
          主因 {authorText(String(revisionPlan.diagnosis.primaryCause ?? ""))}。
        </Paragraph>
      ) : null}
    </div>
  );
}

function TensionSparkline({ points }: { points: TensionPoint[] }) {
  const visible = points.slice(-20);
  return (
    <div className="tension-sparkline" aria-label="最近章节张力曲线">
      {visible.map((point) => (
        <span
          key={point.chapterId}
          className={point.warning ? "warn" : ""}
          style={{ height: `${Math.max(8, Math.min(44, point.conflictMarkers * 8 + point.qualityScore / 6))}px` }}
          title={`第 ${point.chapterId} 章：质量 ${point.qualityScore}，冲突标记 ${point.conflictMarkers}`}
        />
      ))}
    </div>
  );
}

function MemoryInspectionBlock({ book }: { book: Book }) {
  const inspection = book.memoryInspection;
  if (!inspection) {
    return null;
  }
  return (
    <div className="memory-inspection-block">
      <Text type="secondary">记忆检视</Text>
      <Space wrap>
        <Tag>人物 {inspection.characters.length}</Tag>
        <Tag>关系 {inspection.relationships.edgeCount ?? 0}</Tag>
        <Tag>伏笔 {inspection.promises.length}</Tag>
        <Tag>弧线 {inspection.arcs.length}</Tag>
      </Space>
    </div>
  );
}

function NewBookField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <WorkbenchField>
      <div className="new-book-field">
        <Text type="secondary" className="new-book-field-label">{label}</Text>
        {children}
      </div>
    </WorkbenchField>
  );
}

type SavedCreationDraft = NewBookDraft & BookCreationSetup;

function readSavedCreationDraft(): SavedCreationDraft {
  const fallback: SavedCreationDraft = {
    title: "",
    platform: "",
    styleProfileId: "",
    styleProfileLabel: "",
    genre: "",
    tagline: "",
    firstChapterTitle: "",
    seed: "",
    modelId: "",
    interventionMode: "stage_confirm",
    batchTarget: 1,
    targetChapterCount: 200,
    targetWordsPerChapter: 2500,
    targetChaptersPerPlot: 10
  };
  try {
    const parsed = JSON.parse(sessionStorage.getItem(CREATION_DRAFT_KEY) ?? "{}") as Partial<SavedCreationDraft>;
    return {
      ...fallback,
      ...parsed,
      interventionMode: ["full_auto", "stage_confirm", "chapter_confirm", "deep_control"].includes(String(parsed.interventionMode))
        ? parsed.interventionMode as GenerationMode
        : fallback.interventionMode
    };
  } catch {
    return fallback;
  }
}

function saveCreationDraft(draft: Omit<SavedCreationDraft, "platform" | "styleProfileLabel">) {
  sessionStorage.setItem(CREATION_DRAFT_KEY, JSON.stringify(draft));
}

function creationModeLabel(mode: GenerationMode) {
  return creationModeOptions.find((option) => option.value === mode)?.label ?? "阶段确认";
}

function creationModeDescription(mode: GenerationMode) {
  return {
    full_auto: "系统持续推进；模型失败、内容不合格、检查阻断或本次目标完成时暂停。",
    stage_confirm: "作品方向、长篇规划和章节蓝图会等待确认，章节规划与正文按规则继续。",
    chapter_confirm: "每章正文完成后等待确认，再进入检查和定稿。",
    deep_control: "作品方向、规划、蓝图、章节规划和正文都等待逐项确认。"
  }[mode];
}

function riskScore(book: Book) {
  return book.chapters.filter((chapter) => chapter.status !== "完成").length;
}

function qualityColorClass(score: number) {
  if (score >= 80) {
    return "good";
  }
  if (score >= 60) {
    return "warn";
  }
  return "bad";
}

function qualityTrend(average: number, recent: number) {
  if (!average || !recent) {
    return { label: "--", color: "default" };
  }
  if (recent > average + 5) {
    return { label: "↑", color: "success" };
  }
  if (recent < average - 5) {
    return { label: "↓", color: "error" };
  }
  return { label: "—", color: "default" };
}

function generationStatusColor(status: GenerationState["status"]) {
  if (status === "blocked") {
    return "error";
  }
  if (status === "paused" || status === "waiting_confirm") {
    return "warning";
  }
  if (status === "completed") {
    return "success";
  }
  if (status === "running") {
    return "processing";
  }
  return "default";
}

function getSelectedStyle(styleProfileId: string, options: BookCreationOptions) {
  return options.platformStyles.find((style) => style.id === styleProfileId) ?? options.platformStyles[0];
}

function defaultGenreForStyle(style: PlatformStyleOption, options: BookCreationOptions) {
  const matched = options.genres.find((genre) => genre.platformHints.includes(style.platform));
  return matched?.value ?? options.genres[0]?.value ?? "";
}

function buildDefaultTagline(style: { platform: string; label: string }, genre: string) {
  if (style.platform === "fanqie") {
    return `一部${genre || "升级流"}作品，围绕压迫、反击、代价和章尾追读持续推进。`;
  }
  if (style.platform === "qidian") {
    return `一部${genre || "长篇类型"}作品，围绕体系、势力、长期目标和阶段性突破展开。`;
  }
  if (style.platform === "douyin") {
    return `一部${genre || "短剧"}作品，用高频钩子和反转推动主角完成复仇或翻盘。`;
  }
  if (style.platform === "jjwxc") {
    return `一部${genre || "情感成长"}作品，围绕关系拉扯、人物边界和细腻转折推进。`;
  }
  return `一部${genre || style.label}作品，围绕清晰目标、冲突转折和章尾钩子持续推进。`;
}

function deriveBookTitle(candidateText: string, nextIndex: number) {
  const firstLine = candidateText.split("\n").map((line) => line.trim()).find(Boolean) ?? "";
  return firstLine.replace(/^标题[:：]*/, "").trim() || `新书 ${nextIndex}`;
}

function deriveBookTagline(candidateText: string, fallback: string) {
  const lines = candidateText.split("\n").map((line) => line.trim()).filter(Boolean);
  const matched = lines.find((line) => /简介|一句话|tagline|故事/.test(line));
  return matched?.replace(/^(简介|一句话简介|Tagline|故事简介)[:：]*/, "").trim() || fallback;
}

function deriveFirstChapterTitle(candidateText: string) {
  const lines = candidateText.split("\n").map((line) => line.trim()).filter(Boolean);
  const matched = lines.find((line) => /首章|第一章/.test(line));
  return matched?.replace(/^(首章标题|第一章|首章)[:：]*/, "").trim() || "第一章 异常来临";
}
