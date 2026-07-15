import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Input, Modal, Segmented, Select, Space, Table, Typography } from "antd";
import { BookOutlined, DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { workbenchClient } from "../api/workbenchClient";
import { materialDetailLabels, materialTypes } from "../domain/bookWorkspace";
import type { Chapter, Material, MaterialDeleteAction, MaterialLinkAction, MaterialSaveAction, MaterialType } from "../types";
import { authorText } from "../utils/authorText";
import { MaterialEditorForm } from "./MaterialEditorForm";
import { MaterialSummaryCard } from "./MaterialSummaryBlock";

const { Text, Title } = Typography;

export function ChapterMaterialPanel({
  bookId,
  chapter,
  materials,
  onCreateMaterial,
  onUpdateMaterial,
  onDeleteMaterial,
  onLinkMaterials,
  materialLinkAction,
  materialDeleteAction,
  materialSaveAction
}: {
  bookId: string;
  chapter: Chapter;
  materials: Material[];
  onCreateMaterial: (material: Omit<Material, "bookId"> & { bookId?: string }) => void | Promise<void>;
  onUpdateMaterial: (material: Material) => void | Promise<void>;
  onDeleteMaterial: (materialId: string) => void | Promise<void>;
  onLinkMaterials: (materialIds: string[], mode?: "append" | "replace") => void | Promise<unknown>;
  materialLinkAction: MaterialLinkAction;
  materialDeleteAction: MaterialDeleteAction;
  materialSaveAction: MaterialSaveAction;
}) {
  const [type, setType] = useState<MaterialType>("人物");
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [scope, setScope] = useState<"related" | "all">("related");
  const [editing, setEditing] = useState<Material | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [influence, setInfluence] = useState("");
  const [related, setRelated] = useState("");
  const [detailA, setDetailA] = useState("");
  const [detailB, setDetailB] = useState("");
  const [detailC, setDetailC] = useState("");
  const [confidence, setConfidence] = useState(62);
  const [error, setError] = useState("");
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeResults, setKnowledgeResults] = useState<Awaited<ReturnType<typeof workbenchClient.searchKnowledge>>["results"]>([]);
  const typeMaterials = materials.filter((item) => item.type === type);
  const materialVersion = materials
    .map((item) => `${item.id}:${item.type}:${item.title}:${item.summary}:${item.influence}:${item.related.join("|")}:${item.confidence}`)
    .join(";");
  const relatedQuery = useQuery({
    queryKey: ["chapter-materials", bookId, chapter.id, type, scope, materialVersion],
    queryFn: () => workbenchClient.fetchChapterMaterials(bookId, chapter.id, {
      type,
      scope: "related"
    }),
    enabled: scope === "related"
  });
  const relatedMaterials = relatedQuery.data?.materials ?? [];
  const relatedLoading = relatedQuery.isLoading;
  const relatedError = relatedQuery.error instanceof Error ? authorText(relatedQuery.error.message) : relatedQuery.error ? "相关资料加载失败。" : "";
  const relatedFallbackActive = scope === "related" && Boolean(relatedError) && !relatedMaterials.length && typeMaterials.length > 0;
  const displayMaterials = scope === "related" ? (relatedFallbackActive ? typeMaterials : relatedMaterials) : typeMaterials;
  const labels = materialDetailLabels[editing?.type ?? type];
  const activeCount = displayMaterials.length;
  const typeCount = typeMaterials.length;
  const relatedCount = relatedMaterials.length;
  const linkedSet = new Set(chapter.linkedMaterialIds ?? []);
  const editorSaveLoading = creating
    ? materialSaveAction?.type === "create"
    : Boolean(editing && materialSaveAction?.type === "update" && materialSaveAction.materialId === editing.id);

  useEffect(() => {
    setExpandedIds([]);
  }, [bookId, chapter.id, scope, type]);

  useEffect(() => {
    setCreating(false);
    setEditing(null);
    setError("");
  }, [bookId, chapter.id]);

  function startCreate() {
    setCreating(true);
    setEditing(null);
    setTitle("");
    setSummary("");
    setInfluence("");
    setRelated(`当前章节, ${chapter.title}`);
    setDetailA("");
    setDetailB("");
    setDetailC("");
    setConfidence(62);
    setError("");
  }

  function startEdit(material: Material) {
    setCreating(false);
    setEditing(material);
    setTitle(material.title);
    setSummary(material.summary);
    setInfluence(material.influence);
    setRelated(material.related.join(", "));
    const editLabels = materialDetailLabels[material.type];
    setDetailA(material.details?.[editLabels[0]] ?? "");
    setDetailB(material.details?.[editLabels[1]] ?? "");
    setDetailC(material.details?.[editLabels[2]] ?? "");
    setConfidence(material.confidence);
    setError("");
  }

  async function saveMaterial() {
    if (!title.trim()) {
      setError("先填写资料名称。");
      return;
    }
    const details = {
      [labels[0]]: detailA.trim(),
      [labels[1]]: detailB.trim(),
      [labels[2]]: detailC.trim()
    };
    setError("");
    try {
      if (editing) {
        await onUpdateMaterial({
          ...editing,
          title: title.trim(),
          summary: summary.trim() || editing.summary,
          influence: influence.trim() || editing.influence,
          related: parseRelated(related, editing.related),
          confidence: normalizeConfidence(confidence),
          details: { ...editing.details, ...details }
        });
      } else {
        await onCreateMaterial({
          id: "",
          bookId,
          type,
          title: title.trim(),
          summary: summary.trim() || "从章节草稿页补充的资料。",
          influence: influence.trim() || "会影响当前章节的候选生成和接收检查。",
          related: parseRelated(related, ["当前章节", chapter.title]),
          confidence: normalizeConfidence(confidence),
          details
        });
      }
      setCreating(false);
      setEditing(null);
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "章节资料保存失败，请稍后重试。"));
    }
  }

  async function linkMaterial(materialId: string) {
    setError("");
    try {
      await onLinkMaterials([materialId], "append");
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "章节资料关联失败，请稍后重试。"));
    }
  }

  async function searchKnowledge() {
    const query = knowledgeQuery.trim();
    if (!query) {
      setKnowledgeResults([]);
      return;
    }
    setKnowledgeLoading(true);
    setError("");
    try {
      const result = await workbenchClient.searchKnowledge(bookId, query, 6);
      setKnowledgeResults(result.results);
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "知识库搜索失败，请稍后重试。"));
    } finally {
      setKnowledgeLoading(false);
    }
  }

  async function citeKnowledgeResult(result: (typeof knowledgeResults)[number]) {
    setError("");
    try {
      const material = {
        id: "",
        bookId,
        type: "设定" as MaterialType,
        title: result.title || result.source,
        summary: result.excerpt,
        influence: `来自知识库 ${result.source}，用于当前章节上下文。`,
        related: ["知识库", chapter.title],
        confidence: Math.max(60, Math.min(95, result.score)),
        details: {
          来源: result.source,
          匹配词: result.matchedTerms.join("、"),
          知识片段: result.excerpt
        }
      };
      await onCreateMaterial(material);
    } catch (error) {
      setError(authorText(error instanceof Error ? error.message : "知识片段引用失败，请稍后重试。"));
    }
  }

  function confirmDeleteMaterial(material: Material) {
    Modal.confirm({
      title: authorText(`删除资料：${material.title}`),
      content: "删除后会同步清理章节资料引用，当前章节相关筛选结果也会立即更新。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setError("");
        try {
          await onDeleteMaterial(material.id);
        } catch (error) {
          setError(authorText(error instanceof Error ? error.message : "章节资料删除失败，请稍后重试。"));
        }
      }
    });
  }

  if (creating || editing) {
    return (
      <Space direction="vertical" className="wide chapter-material-panel">
        <div className="chapter-material-editor-head">
          <div className="min-w-0">
            <Text type="secondary">{editing ? "编辑章节资料" : "新增章节资料"}</Text>
            <Title level={5} className="chapter-material-title-ellipsis">
              {editing ? authorText(editing.title) : `新增${type}`}
            </Title>
          </div>
          <Button size="small" onClick={() => {
            setCreating(false);
            setEditing(null);
          }}>
            返回
          </Button>
        </div>
        <MaterialEditorForm
          editingMaterial={editing}
          materialType={type}
          draftTitle={title}
          draftSummary={summary}
          draftInfluence={influence}
          draftRelated={related}
          draftDetailA={detailA}
          draftDetailB={detailB}
          draftDetailC={detailC}
          draftConfidence={confidence}
          formError={error}
          saveLoading={editorSaveLoading}
          introText="这里新增或编辑的资料会立刻回到当前章节助手，不需要跳去资料库页。"
          saveLabel="保存到当前书资料库"
          onDraftTitleChange={setTitle}
          onDraftSummaryChange={setSummary}
          onDraftInfluenceChange={setInfluence}
          onDraftRelatedChange={setRelated}
          onDraftDetailAChange={setDetailA}
          onDraftDetailBChange={setDetailB}
          onDraftDetailCChange={setDetailC}
          onDraftConfidenceChange={setConfidence}
          onSave={saveMaterial}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      </Space>
    );
  }

  return (
    <Space direction="vertical" className="wide chapter-material-panel">
      <div className="chapter-material-head">
        <div className="min-w-0">
          <Text type="secondary">章节资料</Text>
          <Title level={5} className="chapter-material-title-ellipsis">
            {type} · {scope === "related" ? relatedCount : typeCount} 条
          </Title>
          <div className="chapter-material-stats">
            <span>已纳入 {linkedSet.size}</span>
            <span>当前 {activeCount}</span>
          </div>
        </div>
        <div className="chapter-material-head-actions">
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={startCreate}>
            新增
          </Button>
        </div>
      </div>
      <div className="chapter-material-filters">
        <Select
          className="chapter-material-type-select"
          value={type}
          options={materialTypes.map((item) => ({ label: item, value: item }))}
          onChange={(value) => {
            setType(value);
            setExpandedIds([]);
          }}
        />
        <Segmented
          className="chapter-material-scope"
          size="small"
          value={scope}
          onChange={(value) => {
            setScope(value as "related" | "all");
            setExpandedIds([]);
          }}
          options={[
            { label: "相关", value: "related" },
            { label: "全部", value: "all" }
          ]}
        />
      </div>
      <Space.Compact className="wide">
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索知识库片段"
          value={knowledgeQuery}
          onChange={(event) => setKnowledgeQuery(event.target.value)}
          onPressEnter={() => void searchKnowledge()}
        />
        <Button loading={knowledgeLoading} onClick={() => void searchKnowledge()}>
          搜索
        </Button>
      </Space.Compact>
      {knowledgeResults.length ? (
        <Space direction="vertical" className="wide knowledge-search-results">
          {knowledgeResults.map((result) => (
            <div key={result.id} className="knowledge-search-result">
              <Text strong>{authorText(result.title || result.source)}</Text>
              <Text type="secondary">{authorText(result.source)} · {result.score}</Text>
              {result.matchReasons.length ? (
                <Text type="secondary">{authorText(result.matchReasons.join("；"))}</Text>
              ) : null}
              <Typography.Paragraph ellipsis={{ rows: 3 }}>{authorText(result.excerpt)}</Typography.Paragraph>
              <Button size="small" icon={<BookOutlined />} onClick={() => void citeKnowledgeResult(result)}>
                引用到当前章节
              </Button>
            </div>
          ))}
        </Space>
      ) : null}
      {scope === "related" && relatedLoading ? (
        <Text type="secondary" className="chapter-material-inline-status">正在整理相关资料...</Text>
      ) : null}
      {scope === "related" && relatedError ? (
        <Alert
          showIcon
          type="warning"
          className="chapter-material-hint"
          message="当前章节相关资料加载失败"
          description={authorText(relatedFallbackActive ? `${relatedError} 已先显示本地同类资料，可继续选择或新增。` : relatedError)}
        />
      ) : null}
      {error ? (
        <Alert
          showIcon
          type="error"
          className="chapter-material-hint"
          message="章节资料操作未完成"
          description={authorText(error)}
        />
      ) : null}
      {scope === "related" && !relatedLoading && !relatedCount && typeCount ? (
        <Alert
          showIcon
          type="info"
          className="chapter-material-hint"
          message="当前章节暂无强关联资料"
          description="可以切到“全部”查看同类资料，或新增一条只服务当前章节的资料。"
        />
      ) : null}
      {activeCount > 50 ? (
        <Table
          virtual
          size="small"
          rowKey="id"
          pagination={false}
          scroll={{ y: 400, x: 520 }}
          dataSource={displayMaterials}
          columns={[
            {
              title: "资料",
              dataIndex: "title",
              render: (value: string, material: Material) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{authorText(value)}</Text>
                  <Text type="secondary">{authorText(material.summary)}</Text>
                </Space>
              )
            },
            {
              title: "置信",
              dataIndex: "confidence",
              width: 72
            },
            {
              title: "操作",
              key: "actions",
              width: 96,
              render: (_value, material: Material) => (
                <Button
                  size="small"
                  disabled={linkedSet.has(material.id)}
                  onClick={() => void linkMaterial(material.id)}
                >
                  {linkedSet.has(material.id) ? "已纳入" : "纳入"}
                </Button>
              )
            }
          ]}
        />
      ) : activeCount ? (
        <div className="chapter-material-list">
          {displayMaterials.map((material) => {
            const expanded = expandedIds.includes(material.id);
            return (
              <MaterialSummaryCard
                key={material.id}
                material={material}
                expanded={expanded}
                linked={linkedSet.has(material.id)}
                onToggle={() =>
                  setExpandedIds((current) =>
                    current.includes(material.id)
                      ? current.filter((item) => item !== material.id)
                      : [...current, material.id]
                  )
                }
                actions={(
                  <Space direction="vertical" className="wide chapter-material-actions">
                    <Button
                      size="small"
                      type={linkedSet.has(material.id) ? "default" : "primary"}
                      icon={<BookOutlined />}
                      loading={materialLinkAction?.mode === "append" && materialLinkAction.materialIds.includes(material.id)}
                      disabled={linkedSet.has(material.id)}
                      onClick={() => void linkMaterial(material.id)}
                    >
                      {linkedSet.has(material.id) ? "已纳入当前章节" : "纳入当前章节"}
                    </Button>
                    <Button size="small" icon={<EditOutlined />} onClick={() => startEdit(material)}>
                      编辑资料
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      loading={materialDeleteAction?.materialId === material.id}
                      onClick={() => confirmDeleteMaterial(material)}
                    >
                      删除资料
                    </Button>
                  </Space>
                )}
              />
            );
          })}
        </div>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={scope === "related" ? "当前章节还没有相关资料" : `还没有${type}资料`}
        >
          <Button type="primary" icon={<PlusOutlined />} onClick={startCreate}>
            新增{type}
          </Button>
        </Empty>
      )}
    </Space>
  );
}

function parseRelated(value: string, fallback: string[]) {
  const items = value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(items.length ? items : fallback));
}

function normalizeConfidence(value: number) {
  return Math.max(0, Math.min(100, Math.round(Number.isFinite(value) ? value : 0)));
}
