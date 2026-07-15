import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Divider, Empty, Flex, Input, List, message, Modal, Pagination, Progress, Select, Space, Switch, Tabs, Tag, Typography } from "antd";
import { BookOutlined, DeleteOutlined, EditOutlined, ExperimentOutlined, SearchOutlined } from "@ant-design/icons";
import { workbenchClient } from "../api/workbenchClient";
import type { ChapterLanding, LongFormPlanResponse, LongFormReplanResponse, WritingAssetsResponse } from "../api/contracts";
import { LibraryRelationshipsPanel, LibraryTimelinePanel } from "../components/AdvancedPanels";
import { LibraryWorkbenchPanel } from "../components/LibraryWorkbenchPanel";
import { PanelEmptyState } from "../components/shared";
import { MaterialSummaryCard } from "../components/MaterialSummaryBlock";
import { ScrollTabs } from "../components/ScrollTabs";
import { materialTypes } from "../domain/bookWorkspace";
import { useLibraryMaterialWorkflow } from "../hooks/useLibraryMaterialWorkflow";
import type {
  Chapter,
  Material,
  MaterialDeleteAction,
  MaterialLinkAction,
  MaterialLibrary,
  MaterialSaveAction,
  MaterialType,
  MemoryInspection
} from "../types";
import { authorText } from "../utils/authorText";

const { Text, Paragraph } = Typography;
export function LibraryPage({
  bookId,
  activeChapter,
  memoryInspection,
  materials,
  materialLibrary,
  activeMaterial,
  search,
  materialType,
  onSearchChange,
  onTypeChange,
  onMaterialChange,
  onCreateMaterial,
  onUpdateMaterial,
  onDeleteMaterial,
  onLinkToChapter,
  materialLinkAction,
  materialDeleteAction,
  materialSaveAction
}: {
  bookId: string;
  activeChapter: Chapter;
  memoryInspection: MemoryInspection;
  materials: Material[];
  materialLibrary: MaterialLibrary;
  activeMaterial?: Material;
  search: string;
  materialType: MaterialType;
  onSearchChange: (value: string) => void;
  onTypeChange: (value: MaterialType) => void;
  onMaterialChange: (id: string) => void;
  onCreateMaterial: (material: Omit<Material, "bookId"> & { bookId?: string }) => void | Promise<void>;
  onUpdateMaterial: (material: Material) => void | Promise<void>;
  onDeleteMaterial: (materialId: string) => void | Promise<void>;
  onLinkToChapter: (materialIds: string[], mode?: "append" | "replace") => void | Promise<unknown>;
  materialLinkAction: MaterialLinkAction;
  materialDeleteAction: MaterialDeleteAction;
  materialSaveAction: MaterialSaveAction;
}) {
  const contextRef = useRef({ bookId, chapterId: activeChapter.id, materialType, materialId: activeMaterial?.id ?? "" });
  const [currentChapterOnly, setCurrentChapterOnly] = useState(false);
  const [expandedMaterialIds, setExpandedMaterialIds] = useState<string[]>([]);

  const [chapterMaterialResults, setChapterMaterialResults] = useState<Record<string, Material[]>>({});
  const [chapterMaterialError, setChapterMaterialError] = useState("");
  const [chapterMaterialLoading, setChapterMaterialLoading] = useState(false);
  const [longFormPlan, setLongFormPlan] = useState<LongFormPlanResponse | null>(null);
  const [planningView, setPlanningView] = useState("book");
  const [selectedVolumeId, setSelectedVolumeId] = useState("");
  const [volumeGoal, setVolumeGoal] = useState("");
  const [volumeRange, setVolumeRange] = useState("");
  const [replanResult, setReplanResult] = useState<LongFormReplanResponse | null>(null);
  const [landingDraft, setLandingDraft] = useState<ChapterLanding | null>(null);
  const [planningAction, setPlanningAction] = useState<"save" | "replan" | "confirm" | null>(null);
  const [planningMessage, setPlanningMessage] = useState("");
  const [writingAssets, setWritingAssets] = useState<WritingAssetsResponse | null>(null);
  const [writingAssetAction, setWritingAssetAction] = useState("");
  const [materialPage, setMaterialPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    void workbenchClient.fetchLongFormPlan(bookId).then((response) => {
      if (cancelled) return;
      setLongFormPlan(response);
      const current = response.plan.volumes.find((volume) => volume.volumeId === response.plan.currentVolumeId) ?? response.plan.volumes[0];
      setSelectedVolumeId(current?.volumeId ?? "");
      setVolumeGoal(current?.goal ?? "");
      setVolumeRange(current?.chapterRange ?? "");
      setReplanResult(response.replanCandidate ? { bookId, deviation: {}, candidate: response.replanCandidate, authorMessage: "已有重规划候选等待确认。" } : null);
    }).catch(() => {
      if (!cancelled) setLongFormPlan(null);
    });
    return () => { cancelled = true; };
  }, [bookId]);

  useEffect(() => {
    let cancelled = false;
    void workbenchClient.fetchWritingAssets(bookId).then((response) => {
      if (!cancelled) setWritingAssets(response);
    }).catch(() => {
      if (!cancelled) setWritingAssets(null);
    });
    return () => { cancelled = true; };
  }, [bookId]);

  async function toggleWritingFormula(formulaId: string, enabled: boolean) {
    setWritingAssetAction(formulaId);
    try {
      setWritingAssets(await workbenchClient.setWritingFormulaStatus(
        bookId,
        formulaId,
        enabled ? "active" : "retired"
      ));
    } catch (error) {
      message.error(authorText(error instanceof Error ? error.message : "写法资产更新失败。"));
    } finally {
      setWritingAssetAction("");
    }
  }

  const currentVolume = longFormPlan?.plan.volumes.find((volume) => volume.volumeId === selectedVolumeId)
    ?? longFormPlan?.plan.volumes[0];

  async function saveVolumeGoal() {
    if (!currentVolume || !volumeGoal.trim()) return;
    setPlanningAction("save");
    setPlanningMessage("");
    try {
      await workbenchClient.updateVolumeGoal(bookId, currentVolume.volumeId, volumeGoal.trim(), volumeRange.trim());
      const refreshed = await workbenchClient.fetchLongFormPlan(bookId);
      setLongFormPlan(refreshed);
      setPlanningMessage("卷目标已保存，后续重规划只影响未定稿章节。");
    } catch (error) {
      setPlanningMessage(authorText(error instanceof Error ? error.message : "卷目标保存失败。"));
    } finally {
      setPlanningAction(null);
    }
  }

  async function generateReplan() {
    setPlanningAction("replan");
    setPlanningMessage("");
    try {
      const response = await workbenchClient.generateLongFormReplan(bookId, activeChapter.id);
      setReplanResult(response.candidate ? response : null);
      setPlanningMessage(response.authorMessage);
    } catch (error) {
      setPlanningMessage(authorText(error instanceof Error ? error.message : "重规划候选生成失败。"));
    } finally {
      setPlanningAction(null);
    }
  }

  async function confirmReplan() {
    setPlanningAction("confirm");
    setPlanningMessage("");
    try {
      await workbenchClient.confirmLongFormReplan(bookId);
      const refreshed = await workbenchClient.fetchLongFormPlan(bookId);
      setLongFormPlan(refreshed);
      setVolumeGoal((refreshed.plan.volumes.find((volume) => volume.volumeId === refreshed.plan.currentVolumeId) ?? refreshed.plan.volumes[0])?.goal ?? "");
      setPlanningMessage("重规划候选已确认。");
      setReplanResult(null);
    } catch (error) {
      setPlanningMessage(authorText(error instanceof Error ? error.message : "重规划候选确认失败。"));
    } finally {
      setPlanningAction(null);
    }
  }

  async function saveChapterLanding() {
    if (!landingDraft) return;
    setPlanningAction("save");
    setPlanningMessage("");
    try {
      await workbenchClient.updateChapterLanding(bookId, landingDraft);
      const refreshed = await workbenchClient.fetchLongFormPlan(bookId);
      setLongFormPlan(refreshed);
      setLandingDraft(null);
      setPlanningMessage("章节落点已更新，尚未改变正文。");
    } catch (error) {
      setPlanningMessage(authorText(error instanceof Error ? error.message : "章节落点保存失败。"));
    } finally {
      setPlanningAction(null);
    }
  }

  const fallbackMaterials = materialLibrary[materialType].filter((item) => {
    const keyword = search.trim().toLowerCase();
    return keyword
      ? [item.title, item.summary, item.influence, ...item.related].some((value) => value.toLowerCase().includes(keyword))
      : true;
  });
  const relatedKey = `${bookId}:${activeChapter.id}:${materialType}:${search.trim()}:${currentChapterOnly ? "related" : "all"}`;
  const chapterRelatedFallbackActive = currentChapterOnly && Boolean(chapterMaterialError) && !chapterMaterialResults[relatedKey]?.length && fallbackMaterials.length > 0;
  const filteredMaterials = currentChapterOnly
    ? chapterRelatedFallbackActive ? fallbackMaterials : chapterMaterialResults[relatedKey] ?? []
    : fallbackMaterials;
  const materialPageSize = 8;
  const pagedMaterials = filteredMaterials.slice(
    (materialPage - 1) * materialPageSize,
    materialPage * materialPageSize
  );

  useEffect(() => {
    setMaterialPage(1);
  }, [activeChapter.id, bookId, currentChapterOnly, materialType, search]);

  const visibleMaterial = activeMaterial
    ? pagedMaterials.find((item) => item.id === activeMaterial.id) ?? pagedMaterials[0]
    : pagedMaterials[0];
  const linkedCount = (activeChapter.linkedMaterialIds ?? []).length;
  const linkedSet = new Set(activeChapter.linkedMaterialIds ?? []);
  const replaceLinkLoading = materialLinkAction?.mode === "replace";
  const materialVersion = materials
    .map((item) => `${item.id}:${item.type}:${item.title}:${item.summary}:${item.influence}:${item.related.join("|")}:${item.confidence}`)
    .join(";");
  const {
    editorMode,
    sideMode,
    setSideMode,
    editingMaterial,
    aiSeed,
    setAiSeed,
    aiSuggestion,
    setAiSuggestion,
    lastAiMode,
    draftTitle,
    setDraftTitle,
    draftSummary,
    setDraftSummary,
    draftInfluence,
    setDraftInfluence,
    draftRelated,
    setDraftRelated,
    draftDetailA,
    setDraftDetailA,
    draftDetailB,
    setDraftDetailB,
    draftDetailC,
    setDraftDetailC,
    draftConfidence,
    setDraftConfidence,
    formError,
    materialActionError,
    setMaterialActionError,
    agentAction,
    editorSaveLoading,
    aiApplyLoading,
    createAiSuggestion,
    isMaterialAiActionDisabled,
    applyAiSuggestion,
    openCreateEditor,
    openUpdateEditor,
    saveMaterial,
    removeMaterial,
    backToDetail
  } = useLibraryMaterialWorkflow({
    bookId,
    activeChapter,
    materialType,
    materials,
    activeMaterial,
    visibleMaterial,
    onMaterialChange,
    onCreateMaterial,
    onUpdateMaterial,
    onDeleteMaterial,
    materialSaveAction,
    resetKey: `${bookId}:${activeChapter.id}:${currentChapterOnly}:${materialType}:${materialVersion}:${search}`
  });

  useEffect(() => {
    contextRef.current = { bookId, chapterId: activeChapter.id, materialType, materialId: activeMaterial?.id ?? "" };
  }, [activeMaterial?.id, activeChapter.id, bookId, materialType]);

  useEffect(() => {
    if (visibleMaterial && activeMaterial?.id !== visibleMaterial.id) {
      onMaterialChange(visibleMaterial.id);
      return;
    }
    if (!visibleMaterial && activeMaterial?.id) {
      onMaterialChange("");
    }
  }, [activeMaterial?.id, onMaterialChange, visibleMaterial]);

  useEffect(() => {
    setExpandedMaterialIds([]);
    setChapterMaterialError("");
    setChapterMaterialLoading(false);
  }, [activeChapter.id, bookId, currentChapterOnly, materialType, materialVersion, search]);

  useEffect(() => {
    if (!currentChapterOnly) {
      setChapterMaterialLoading(false);
      setChapterMaterialError("");
      return;
    }
    let cancelled = false;
    async function loadRelatedMaterials() {
      const requestKey = `${bookId}:${activeChapter.id}`;
      setChapterMaterialLoading(true);
      try {
        const result = await workbenchClient.fetchChapterMaterials(bookId, activeChapter.id, {
          type: materialType,
          q: search,
          scope: "related"
        });
        if (!cancelled && `${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
          setChapterMaterialResults((current) => ({ ...current, [relatedKey]: result.materials }));
          setChapterMaterialError("");
        }
      } catch (error) {
        if (!cancelled && `${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
          setChapterMaterialError(authorText(error instanceof Error ? error.message : "相关资料加载失败。"));
        }
      } finally {
        if (!cancelled && `${contextRef.current.bookId}:${contextRef.current.chapterId}` === requestKey) {
          setChapterMaterialLoading(false);
        }
      }
    }
    void loadRelatedMaterials();
    return () => {
      cancelled = true;
    };
  }, [activeChapter.id, bookId, currentChapterOnly, materialType, materialVersion, relatedKey, search]);

  async function linkVisibleMaterial() {
    if (!visibleMaterial) {
      message.warning("请先选择一条资料。");
      return;
    }
    await linkMaterialsToChapter([visibleMaterial.id], "append");
  }

  async function replaceChapterMaterials() {
    const ids = filteredMaterials.map((item) => item.id);
    if (!ids.length) {
      message.warning("当前筛选结果里没有可纳入本章的资料。");
      return;
    }
    await linkMaterialsToChapter(ids, "replace");
  }

  async function linkMaterialsToChapter(materialIds: string[], mode: "append" | "replace") {
    setMaterialActionError("");
    try {
      await onLinkToChapter(materialIds, mode);
    } catch (error) {
      setMaterialActionError(authorText(error instanceof Error ? error.message : "资料关联到章节失败，请稍后重试。"));
    }
  }

  function toggleMaterial(material: Material) {
    onMaterialChange(material.id);
    setExpandedMaterialIds((current) =>
      current.includes(material.id)
        ? current.filter((item) => item !== material.id)
        : [...current, material.id]
    );
  }

  return (
    <div className={`page-grid library-page-grid ${sideMode !== "detail" || editorMode ? "library-workbench-open" : ""}`}>
      <section className="main-column library-main-column">
        {longFormPlan && currentVolume ? (
          <section className="long-form-plan-band">
            <Flex justify="space-between" align="center" gap={12} wrap="wrap">
              <div>
                <Text type="secondary">长篇经营</Text>
                <Paragraph strong>{authorText(longFormPlan.plan.mainline)}</Paragraph>
              </div>
              <Space wrap>
                <Tag>{longFormPlan.plan.estimatedVolumes} 卷</Tag>
                <Tag>{longFormPlan.chapterLandings.length} 个章节落点</Tag>
              </Space>
            </Flex>
            <Tabs
              activeKey={planningView}
              onChange={setPlanningView}
              items={[
                {
                  key: "book",
                  label: "全书",
                  children: (
                    <div className="long-form-view">
                      <Paragraph><Text strong>终局方向：</Text>{authorText(longFormPlan.plan.endingDirection)}</Paragraph>
                      <Paragraph><Text strong>长期对立：</Text>{authorText(longFormPlan.plan.longTermOpposition)}</Paragraph>
                      <Space wrap>{longFormPlan.plan.corePromises.map((item) => <Tag key={item}>{authorText(item)}</Tag>)}</Space>
                      <List
                        size="small"
                        dataSource={longFormPlan.plan.volumes}
                        renderItem={(volume) => (
                          <List.Item actions={[<Button key="open" onClick={() => {
                            setSelectedVolumeId(volume.volumeId);
                            setVolumeGoal(volume.goal);
                            setVolumeRange(volume.chapterRange);
                            setPlanningView("volume");
                          }}>
                            查看当前卷
                          </Button>]}
                          >
                            <List.Item.Meta
                              title={`${authorText(volume.title)} · ${authorText(volume.chapterRange)}`}
                              description={`${authorText(volume.goal)}；卷末变化：${authorText(volume.endingChange)}`}
                            />
                          </List.Item>
                        )}
                      />
                    </div>
                  )
                },
                {
                  key: "volume",
                  label: "当前卷",
                  children: (
                    <div className="long-form-view">
                      <Flex gap={8} wrap="wrap">
                        <Select
                          value={currentVolume.volumeId}
                          options={longFormPlan.plan.volumes.map((volume) => ({ value: volume.volumeId, label: authorText(volume.title) }))}
                          onChange={(value) => {
                            const volume = longFormPlan.plan.volumes.find((item) => item.volumeId === value);
                            setSelectedVolumeId(value);
                            setVolumeGoal(volume?.goal ?? "");
                            setVolumeRange(volume?.chapterRange ?? "");
                          }}
                        />
                        <Input value={volumeRange} aria-label="卷章节范围" onChange={(event) => setVolumeRange(event.target.value)} />
                      </Flex>
                      <Input.TextArea aria-label="卷目标" value={volumeGoal} autoSize={{ minRows: 2, maxRows: 4 }} onChange={(event) => setVolumeGoal(event.target.value)} />
                      <Paragraph><Text strong>主要矛盾：</Text>{authorText(currentVolume.mainConflict)}</Paragraph>
                      <List
                        size="small"
                        dataSource={currentVolume.beatSegments}
                        renderItem={(segment) => (
                          <List.Item>
                            <List.Item.Meta title={`${authorText(segment.title)} · ${authorText(segment.chapterRange)}`} description={`${authorText(segment.purpose)}；压力：${authorText(segment.pressure)}；兑现：${authorText(segment.payoff)}`} />
                          </List.Item>
                        )}
                      />
                      <Flex gap={8} wrap="wrap">
                        <Button loading={planningAction === "save"} onClick={() => void saveVolumeGoal()}>保存卷目标与边界</Button>
                        <Button icon={<ExperimentOutlined />} loading={planningAction === "replan"} onClick={() => void generateReplan()}>生成重规划候选</Button>
                        <Button disabled={!replanResult?.candidate} onClick={() => setPlanningView("compare")}>比较重规划</Button>
                      </Flex>
                    </div>
                  )
                },
                {
                  key: "landings",
                  label: "章节落点",
                  children: (
                    <List
                      size="small"
                      dataSource={longFormPlan.chapterLandings}
                      renderItem={(landing) => (
                        <List.Item actions={landing.status === "完成" ? [] : [<Button key="edit" onClick={() => setLandingDraft(landing)}>编辑落点</Button>]}>
                          <List.Item.Meta
                            title={`${landing.chapterId} · ${authorText(landing.title)} · ${authorText(landing.status)}`}
                            description={`目标：${authorText(landing.goal)}；钩子：${authorText(landing.hook)}；承诺：${authorText(landing.promiseProgression)}；依赖：${landing.logicDependencies.map(authorText).join("、") || "无"}`}
                          />
                        </List.Item>
                      )}
                    />
                  )
                },
                {
                  key: "compare",
                  label: "重规划比较",
                  children: replanResult?.candidate ? (
                    <div className="long-form-compare">
                      <List
                        size="small"
                        dataSource={longFormPlan.plan.volumes}
                        renderItem={(volume, index) => {
                          const candidatePlan = (replanResult.candidate as { plan?: LongFormPlanResponse["plan"] }).plan;
                          const next = candidatePlan?.volumes[index];
                          return <List.Item><List.Item.Meta title={authorText(volume.title)} description={`当前：${authorText(volume.goal)}；候选：${authorText(next?.goal || "未提供")}`} /></List.Item>;
                        }}
                      />
                      <Button type="primary" loading={planningAction === "confirm"} onClick={() => void confirmReplan()}>确认重规划</Button>
                    </div>
                  ) : <Empty description="请先生成重规划候选" />
                }
              ]}
            />
            {planningMessage ? <Text type="secondary">{authorText(planningMessage)}</Text> : null}
            <Divider />
            <Text strong>连载决策</Text>
            <List
              size="small"
              dataSource={longFormPlan.serialRisks}
              renderItem={(risk) => (
                <List.Item>
                  <List.Item.Meta
                    title={<Space><Text strong>{authorText(risk.title)}</Text><Tag color={risk.status === "risk" ? "warning" : risk.status === "clear" ? "success" : "default"}>{risk.status === "risk" ? "需处理" : risk.status === "clear" ? "正常" : "样本不足"}</Tag></Space>}
                    description={`${authorText(risk.reason)} 影响：${authorText(risk.impact)} 建议：${authorText(risk.action)} 证据章节：${risk.evidenceChapters.join("、") || "暂无"}`}
                  />
                </List.Item>
              )}
            />
          </section>
        ) : null}
        <Modal
          title="编辑章节落点"
          open={Boolean(landingDraft)}
          okText="保存落点"
          cancelText="取消"
          confirmLoading={planningAction === "save"}
          onCancel={() => setLandingDraft(null)}
          onOk={() => void saveChapterLanding()}
        >
          {landingDraft ? <Space direction="vertical" className="wide">
            <Input aria-label="章节目标" value={landingDraft.goal} onChange={(event) => setLandingDraft({ ...landingDraft, goal: event.target.value })} />
            <Input aria-label="章节钩子" value={landingDraft.hook} onChange={(event) => setLandingDraft({ ...landingDraft, hook: event.target.value })} />
            <Input aria-label="承诺推进" value={landingDraft.promiseProgression} onChange={(event) => setLandingDraft({ ...landingDraft, promiseProgression: event.target.value })} />
            <Input aria-label="逻辑依赖" value={landingDraft.logicDependencies.join("、")} onChange={(event) => setLandingDraft({ ...landingDraft, logicDependencies: event.target.value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean) })} />
          </Space> : null}
        </Modal>
        {writingAssets?.formulas.length ? (
          <section className="writing-assets-band">
            <Flex justify="space-between" align="center" gap={12} wrap="wrap">
              <div>
                <Text type="secondary">当前书写法资产</Text>
                <Paragraph strong>生成、检查和修复共用</Paragraph>
              </div>
              <Tag>{writingAssets.formulas.filter((item) => item.status === "active").length} 条生效</Tag>
            </Flex>
            <Space direction="vertical" className="wide">
              {writingAssets.formulas.map((formula) => (
                <Flex key={formula.id} justify="space-between" align="flex-start" gap={12} wrap="wrap">
                  <div className="writing-asset-copy">
                    <Text strong>{authorText(formula.title)}</Text>
                    <Paragraph type="secondary">{authorText(formula.guidance)}</Paragraph>
                    <Text type="secondary">
                      {formula.evidenceChapters.length ? `来源章节：${formula.evidenceChapters.join("、")}` : "等待样本证据"}
                    </Text>
                  </div>
                  <Switch
                    checked={formula.status === "active"}
                    loading={writingAssetAction === formula.id}
                    onChange={(checked) => void toggleWritingFormula(formula.id, checked)}
                  />
                </Flex>
              ))}
            </Space>
          </section>
        ) : null}
        <Flex gap={12} wrap="wrap" className="section-toolbar library-material-toolbar">
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索资料"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
          />
          <ScrollTabs
            className="material-type-tabs"
            ariaLabel="资料类型"
            value={materialType}
            onChange={(value) => {
              onTypeChange(value as MaterialType);
              setAiSuggestion(null);
            }}
            options={materialTypes}
          />
          <Space className="chapter-filter-toggle">
            <Switch checked={currentChapterOnly} onChange={setCurrentChapterOnly} />
            <Text type="secondary">仅当前章节相关</Text>
          </Space>
        </Flex>
        {currentChapterOnly && chapterMaterialError ? (
          <Alert
            showIcon
            type="warning"
            className="inline-page-alert"
            message="当前章节相关资料加载失败"
            description={authorText(chapterRelatedFallbackActive ? `${chapterMaterialError} 已先显示本地同类资料，可继续编辑或纳入本章。` : chapterMaterialError)}
          />
        ) : null}
        {currentChapterOnly && chapterMaterialLoading ? (
          <Text type="secondary">正在整理当前章节相关资料...</Text>
        ) : null}
        {materialActionError ? (
          <Alert
            showIcon
            type="error"
            className="inline-page-alert"
            message="资料操作未完成"
            description={authorText(materialActionError)}
          />
        ) : null}
        {filteredMaterials.length ? (
          <>
          <div className="material-summary-list">
            {pagedMaterials.map((item) => (
              <MaterialSummaryCard
                key={item.id}
                material={item}
                expanded={expandedMaterialIds.includes(item.id)}
                linked={linkedSet.has(item.id)}
                active={visibleMaterial?.id === item.id}
                compact={false}
                onToggle={() => toggleMaterial(item)}
                actions={(
                  <Space wrap className="material-summary-card-actions">
                    <Button size="small" icon={<EditOutlined />} onClick={() => openUpdateEditor(item)}>
                      编辑
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      loading={materialDeleteAction?.materialId === item.id}
                      onClick={() => removeMaterial(item)}
                    >
                      删除
                    </Button>
                    <Button
                      size="small"
                      type={linkedSet.has(item.id) ? "default" : "primary"}
                      icon={<BookOutlined />}
                      loading={isMaterialLinking(materialLinkAction, item.id)}
                      disabled={linkedSet.has(item.id)}
                      onClick={() => void linkMaterialsToChapter([item.id], "append")}
                    >
                      {linkedSet.has(item.id) ? "已纳入本章" : "纳入本章"}
                    </Button>
                  </Space>
                )}
              />
            ))}
          </div>
          <Pagination
            className="material-list-pagination"
            current={materialPage}
            pageSize={materialPageSize}
            total={filteredMaterials.length}
            hideOnSinglePage
            showSizeChanger={false}
            onChange={setMaterialPage}
          />
          </>
        ) : (
          <Card className="content-card" variant="borderless">
            <PanelEmptyState
              title={`暂无匹配${materialType}`}
              description={currentChapterOnly ? "当前章节还没有关联这类资料，可以查看全部资料或新建一条。" : "调整搜索条件，或在右侧资料工作台新建一条。"}
            />
          </Card>
        )}
        <Card className="content-card library-context-card" variant="borderless">
          <Flex justify="space-between" align="center" gap={12}>
            <div>
              <Text type="secondary">当前章节相关资料</Text>
              <Paragraph className="muted-text">
                {authorText(activeChapter.title)} 当前筛出 {filteredMaterials.length} 条{materialType}资料，已纳入本章 {linkedCount} 条。
              </Paragraph>
            </div>
            <Space>
              <Button onClick={() => setCurrentChapterOnly((value) => !value)}>
                {currentChapterOnly ? "查看全部资料" : "只看相关资料"}
              </Button>
              <Button
                type="primary"
                loading={replaceLinkLoading}
                disabled={!filteredMaterials.length}
                onClick={() => void replaceChapterMaterials()}
              >
                用当前筛选更新本章
              </Button>
            </Space>
          </Flex>
        </Card>
        <div className="library-advanced-grid">
          <LibraryRelationshipsPanel bookId={bookId} />
          <LibraryTimelinePanel bookId={bookId} />
        </div>
      </section>

      <aside className="side-column library-side-column">
        <div className="library-memory-scroll">
          <MemoryInspectionPanel inspection={memoryInspection} />
        </div>
        <div className="library-workbench-fixed">
          <LibraryWorkbenchPanel
          materialType={materialType}
          activeChapterTitle={activeChapter.title}
          visibleMaterial={visibleMaterial}
          editorMode={editorMode}
          sideMode={sideMode}
          editingMaterial={editingMaterial}
          draftTitle={draftTitle}
          draftSummary={draftSummary}
          draftInfluence={draftInfluence}
          draftRelated={draftRelated}
          draftDetailA={draftDetailA}
          draftDetailB={draftDetailB}
          draftDetailC={draftDetailC}
          draftConfidence={draftConfidence}
          formError={formError}
          aiSeed={aiSeed}
          aiSuggestion={aiSuggestion}
          lastAiMode={lastAiMode}
          agentAction={agentAction}
          linked={Boolean(visibleMaterial && linkedSet.has(visibleMaterial.id))}
          editorSaveLoading={editorSaveLoading}
          aiApplyLoading={aiApplyLoading}
          materialLinkAction={materialLinkAction}
          materialDeleteAction={materialDeleteAction}
          materialSaveAction={materialSaveAction}
          onCreate={openCreateEditor}
          onBackToDetail={backToDetail}
          onEdit={openUpdateEditor}
          onShowAi={() => setSideMode("ai")}
          onDraftTitleChange={setDraftTitle}
          onDraftSummaryChange={setDraftSummary}
          onDraftInfluenceChange={setDraftInfluence}
          onDraftRelatedChange={setDraftRelated}
          onDraftDetailAChange={setDraftDetailA}
          onDraftDetailBChange={setDraftDetailB}
          onDraftDetailCChange={setDraftDetailC}
          onDraftConfidenceChange={setDraftConfidence}
          onSaveMaterial={saveMaterial}
          onAiSeedChange={setAiSeed}
          onGenerateAi={createAiSuggestion}
          isAiActionDisabled={isMaterialAiActionDisabled}
          onDiscardAi={() => setAiSuggestion(null)}
          onRegenerateAi={() => createAiSuggestion(lastAiMode)}
          onApplyAi={applyAiSuggestion}
          onDelete={removeMaterial}
          onLink={linkVisibleMaterial}
          />
        </div>
      </aside>
    </div>
  );
}

function isMaterialLinking(action: MaterialLinkAction, materialId: string) {
  return action?.mode === "append" && action.materialIds.includes(materialId);
}

function MemoryInspectionPanel({ inspection }: { inspection: MemoryInspection }) {
  const characters = inspection.characters
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .slice(0, 8);
  const relationshipEdges = (inspection.relationships.edges ?? [])
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .slice(0, 8);
  const openPromises = inspection.promises.filter((item) => item.dueStatus !== "resolved");
  const resolvedPromises = inspection.promises.filter((item) => item.dueStatus === "resolved");
  return (
    <Card className="side-card memory-inspection-panel" variant="borderless">
      <div className="memory-inspection-head">
        <div>
          <Text type="secondary">记忆检视</Text>
          <Paragraph className="muted-text">人物、关系、承诺和弧线来自当前作品记忆文件。</Paragraph>
        </div>
        <Space wrap className="memory-inspection-stats">
          <Tag>人物 {characters.length}</Tag>
          <Tag>关系 {inspection.relationships.edgeCount ?? relationshipEdges.length}</Tag>
        </Space>
      </div>
      <Tabs
        size="small"
        items={[
          {
            key: "characters",
            label: "人物",
            children: characters.length ? (
              <div className="memory-inspection-list">
                {characters.map((character, index) => (
                  <div key={`${memoryField(character, "id") || memoryField(character, "name")}-${index}`} className="memory-inspection-row">
                    <Text strong>{authorText(memoryField(character, "name") || memoryField(character, "characterId") || "未命名人物")}</Text>
                    <Text type="secondary">{authorText(memoryField(character, "emotionalState") || memoryField(character, "status") || memoryField(character, "goal") || "状态待沉淀")}</Text>
                  </div>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无人物记忆" />
            )
          },
          {
            key: "relationships",
            label: "关系",
            children: relationshipEdges.length ? (
              <div className="memory-inspection-list">
                {relationshipEdges.map((edge, index) => (
                  <div key={`${memoryField(edge, "id")}-${index}`} className="memory-inspection-row">
                    <Text strong>{authorText(memoryField(edge, "source") || memoryField(edge, "from") || "关系主体")} → {authorText(memoryField(edge, "target") || memoryField(edge, "to") || "关系对象")}</Text>
                    <Text type="secondary">{authorText(memoryField(edge, "status") || memoryField(edge, "type") || memoryField(edge, "summary") || "关系状态待补")}</Text>
                  </div>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关系网络" />
            )
          },
          {
            key: "promises",
            label: "承诺",
            children: (
              <div className="memory-inspection-kanban">
                <MemoryPromiseColumn title="待兑现" promises={openPromises.filter((item) => item.dueStatus !== "overdue")} />
                <MemoryPromiseColumn title="已过期" promises={openPromises.filter((item) => item.dueStatus === "overdue")} />
                <MemoryPromiseColumn title="已兑现" promises={resolvedPromises} />
              </div>
            )
          },
          {
            key: "arcs",
            label: "弧线",
            children: inspection.arcs.length ? (
              <div className="memory-inspection-list">
                {inspection.arcs.map((arc) => (
                  <div key={arc.arcId} className="memory-inspection-row">
                    <Flex justify="space-between" gap={8}>
                      <Text strong>{authorText(arc.title)}</Text>
                      <Tag>{authorText(arc.chapterRange)}</Tag>
                    </Flex>
                    <Progress percent={arc.progress} size="small" />
                    <Text type="secondary">{authorText(arc.arcGoal || arc.emotionalArc || arc.status)}</Text>
                  </div>
                ))}
              </div>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无情节弧线规划" />
            )
          }
        ]}
      />
    </Card>
  );
}

function MemoryPromiseColumn({ title, promises }: { title: string; promises: Material[] }) {
  return (
    <div className="memory-promise-column">
      <Text type="secondary">{title}</Text>
      {promises.slice(0, 5).map((promise) => (
        <div key={promise.id} className="memory-promise-item">
          <Text strong>{authorText(promise.title)}</Text>
          <Text type="secondary">{authorText(promise.summary || promise.influence)}</Text>
        </div>
      ))}
      {!promises.length ? <Text type="secondary">暂无</Text> : null}
    </div>
  );
}

function memoryField(value: Record<string, unknown>, key: string): string {
  const field = value[key];
  if (field === null || field === undefined) {
    return "";
  }
  return String(field);
}
