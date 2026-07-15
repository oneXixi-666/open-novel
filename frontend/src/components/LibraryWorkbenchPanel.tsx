import { Button, Card, Divider, Flex, Input, Space, Tag, Typography } from "antd";
import {
  BookOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  FileAddOutlined,
  HighlightOutlined,
  PlusOutlined
} from "@ant-design/icons";
import { MaterialEditorForm } from "./MaterialEditorForm";
import { PanelEmptyState } from "./shared";
import { materialDetailLabels } from "../domain/bookWorkspace";
import type { Material, MaterialAiSuggestion, MaterialDeleteAction, MaterialLinkAction, MaterialSaveAction, MaterialType } from "../types";
import { authorText } from "../utils/authorText";

const { Text, Title, Paragraph } = Typography;

type SideMode = "detail" | "edit" | "ai";
type AiMode = "new" | "improve" | "advice";

export function LibraryWorkbenchPanel({
  materialType,
  activeChapterTitle,
  visibleMaterial,
  editorMode,
  sideMode,
  editingMaterial,
  draftTitle,
  draftSummary,
  draftInfluence,
  draftRelated,
  draftDetailA,
  draftDetailB,
  draftDetailC,
  draftConfidence,
  formError,
  aiSeed,
  aiSuggestion,
  lastAiMode,
  agentAction,
  linked,
  editorSaveLoading,
  aiApplyLoading,
  materialLinkAction,
  materialDeleteAction,
  materialSaveAction,
  onCreate,
  onBackToDetail,
  onEdit,
  onShowAi,
  onDraftTitleChange,
  onDraftSummaryChange,
  onDraftInfluenceChange,
  onDraftRelatedChange,
  onDraftDetailAChange,
  onDraftDetailBChange,
  onDraftDetailCChange,
  onDraftConfidenceChange,
  onSaveMaterial,
  onAiSeedChange,
  onGenerateAi,
  isAiActionDisabled,
  onDiscardAi,
  onRegenerateAi,
  onApplyAi,
  onDelete,
  onLink
}: {
  materialType: MaterialType;
  activeChapterTitle: string;
  visibleMaterial?: Material;
  editorMode: "create" | "edit" | null;
  sideMode: SideMode;
  editingMaterial: Material | null;
  draftTitle: string;
  draftSummary: string;
  draftInfluence: string;
  draftRelated: string;
  draftDetailA: string;
  draftDetailB: string;
  draftDetailC: string;
  draftConfidence: number;
  formError: string;
  aiSeed: string;
  aiSuggestion: MaterialAiSuggestion | null;
  lastAiMode: AiMode;
  agentAction: string | null;
  linked: boolean;
  editorSaveLoading: boolean;
  aiApplyLoading: boolean;
  materialLinkAction: MaterialLinkAction;
  materialDeleteAction: MaterialDeleteAction;
  materialSaveAction: MaterialSaveAction;
  onCreate: () => void;
  onBackToDetail: () => void;
  onEdit: (material: Material) => void;
  onShowAi: () => void;
  onDraftTitleChange: (value: string) => void;
  onDraftSummaryChange: (value: string) => void;
  onDraftInfluenceChange: (value: string) => void;
  onDraftRelatedChange: (value: string) => void;
  onDraftDetailAChange: (value: string) => void;
  onDraftDetailBChange: (value: string) => void;
  onDraftDetailCChange: (value: string) => void;
  onDraftConfidenceChange: (value: number) => void;
  onSaveMaterial: () => void | Promise<void>;
  onAiSeedChange: (value: string) => void;
  onGenerateAi: (mode: AiMode) => Promise<void>;
  isAiActionDisabled: (mode: AiMode) => boolean;
  onDiscardAi: () => void;
  onRegenerateAi: () => Promise<void>;
  onApplyAi: () => void | Promise<void>;
  onDelete: (material: Material) => void;
  onLink: () => void | Promise<void>;
}) {
  return (
    <Card className="side-card library-workbench-card" variant="borderless">
      <Flex justify="space-between" align="start" gap={12} className="library-workbench-head">
        <div>
          <Text type="secondary">资料工作台</Text>
          <Title level={4}>{editorMode ? (editingMaterial ? "编辑资料" : `新增${materialType}`) : authorText(visibleMaterial?.title ?? "请选择资料")}</Title>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          新增{materialType}
        </Button>
      </Flex>
      <div className="library-workbench-actions">
        {sideMode !== "detail" || editorMode ? <Button onClick={onBackToDetail}>返回详情</Button> : null}
        <Button icon={<EditOutlined />} disabled={!visibleMaterial} onClick={() => visibleMaterial && onEdit(visibleMaterial)}>
          编辑
        </Button>
        <Button icon={<ExperimentOutlined />} onClick={onShowAi}>
          AI 助手
        </Button>
      </div>
      <Divider />
      {sideMode === "edit" || editorMode ? (
        <MaterialEditor
          editingMaterial={editingMaterial}
          materialType={materialType}
          draftTitle={draftTitle}
          draftSummary={draftSummary}
          draftInfluence={draftInfluence}
          draftRelated={draftRelated}
          draftDetailA={draftDetailA}
          draftDetailB={draftDetailB}
          draftDetailC={draftDetailC}
          draftConfidence={draftConfidence}
          formError={formError}
          saveLoading={editorSaveLoading}
          onDraftTitleChange={onDraftTitleChange}
          onDraftSummaryChange={onDraftSummaryChange}
          onDraftInfluenceChange={onDraftInfluenceChange}
          onDraftRelatedChange={onDraftRelatedChange}
          onDraftDetailAChange={onDraftDetailAChange}
          onDraftDetailBChange={onDraftDetailBChange}
          onDraftDetailCChange={onDraftDetailCChange}
          onDraftConfidenceChange={onDraftConfidenceChange}
          onSave={onSaveMaterial}
          onCancel={onBackToDetail}
        />
      ) : sideMode === "ai" ? (
        <MaterialAiWorkbench
          materialType={materialType}
          activeChapterTitle={activeChapterTitle}
          visibleMaterial={visibleMaterial}
          aiSeed={aiSeed}
          aiSuggestion={aiSuggestion}
          lastAiMode={lastAiMode}
          agentAction={agentAction}
          onAiSeedChange={onAiSeedChange}
          onGenerate={onGenerateAi}
          isActionDisabled={isAiActionDisabled}
          onDiscard={onDiscardAi}
          onRegenerate={onRegenerateAi}
          onApply={onApplyAi}
          saveLoading={aiApplyLoading}
        />
      ) : visibleMaterial ? (
        <MaterialDetail
          material={visibleMaterial}
          linked={linked}
          linkLoading={isMaterialLinking(materialLinkAction, visibleMaterial.id)}
          deleteLoading={materialDeleteAction?.materialId === visibleMaterial.id}
          saveLoading={Boolean(materialSaveAction)}
          onEdit={() => onEdit(visibleMaterial)}
          onDelete={() => onDelete(visibleMaterial)}
          onLink={onLink}
        />
      ) : (
        <PanelEmptyState
          compact
          title={`还没有选中${materialType}`}
          description="从左侧选择已有资料，或直接新建后在这里继续编辑和调用 AI。"
        />
      )}
    </Card>
  );
}

function MaterialDetail({
  material,
  linked,
  linkLoading,
  deleteLoading,
  saveLoading,
  onEdit,
  onDelete,
  onLink
}: {
  material: Material;
  linked: boolean;
  linkLoading: boolean;
  deleteLoading: boolean;
  saveLoading: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onLink: () => void | Promise<void>;
}) {
  return (
    <div className="library-workbench-section">
      <Paragraph className="library-detail-paragraph">{authorText(material.summary)}</Paragraph>
      <Divider />
      <Text type="secondary">对下一章的影响</Text>
      <Paragraph strong className="library-detail-paragraph">{authorText(material.influence)}</Paragraph>
      {material.details ? (
        <>
          <Divider />
          <Text type="secondary">{authorText(material.type)}细节</Text>
          <div className="detail-grid">
            {Object.entries(material.details).map(([label, value], index) => (
              <div key={label}>
                <Text type="secondary">{materialDetailLabel(material.type, label, index)}</Text>
                <Paragraph className="library-detail-paragraph">{authorText(value || "待补全")}</Paragraph>
              </div>
            ))}
          </div>
        </>
      ) : null}
      <Divider />
      <div className="library-detail-tags-section">
        <Text type="secondary">关联标签</Text>
        <Space wrap className="tag-block">
          {material.related.map((item) => (
            <Tag key={item}>{authorText(item)}</Tag>
          ))}
        </Space>
      </div>
      <Divider />
      <div className="library-detail-actions">
        <Button block icon={<EditOutlined />} onClick={onEdit}>
          编辑资料
        </Button>
        <Button block danger icon={<DeleteOutlined />} loading={deleteLoading} onClick={onDelete}>
          删除资料
        </Button>
        <Button
          block
          type={linked ? "default" : "primary"}
          icon={<BookOutlined />}
          loading={linkLoading}
          disabled={linked || saveLoading}
          onClick={() => void onLink()}
        >
          {linked ? "已纳入当前章节" : "纳入当前章节"}
        </Button>
      </div>
    </div>
  );
}

function materialDetailLabel(materialType: MaterialType, label: string, index: number) {
  if (!/^[\x00-\x7F]+$/.test(label)) {
    return authorText(label);
  }
  return materialDetailLabels[materialType][index] ?? "资料细节";
}

function MaterialEditor(props: {
  editingMaterial: Material | null;
  materialType: MaterialType;
  draftTitle: string;
  draftSummary: string;
  draftInfluence: string;
  draftRelated: string;
  draftDetailA: string;
  draftDetailB: string;
  draftDetailC: string;
  draftConfidence: number;
  formError: string;
  saveLoading: boolean;
  onDraftTitleChange: (value: string) => void;
  onDraftSummaryChange: (value: string) => void;
  onDraftInfluenceChange: (value: string) => void;
  onDraftRelatedChange: (value: string) => void;
  onDraftDetailAChange: (value: string) => void;
  onDraftDetailBChange: (value: string) => void;
  onDraftDetailCChange: (value: string) => void;
  onDraftConfidenceChange: (value: number) => void;
  onSave: () => void | Promise<void>;
  onCancel: () => void;
}) {
  return (
    <div className="library-workbench-section material-editor-card">
      <MaterialEditorForm
        editingMaterial={props.editingMaterial}
        materialType={props.materialType}
        draftTitle={props.draftTitle}
        draftSummary={props.draftSummary}
        draftInfluence={props.draftInfluence}
        draftRelated={props.draftRelated}
        draftDetailA={props.draftDetailA}
        draftDetailB={props.draftDetailB}
        draftDetailC={props.draftDetailC}
        draftConfidence={props.draftConfidence}
        formError={props.formError}
        saveLoading={props.saveLoading}
        introText="保存前只在右侧编辑，确认后才写入资料库。"
        saveLabel="保存到资料库"
        onDraftTitleChange={props.onDraftTitleChange}
        onDraftSummaryChange={props.onDraftSummaryChange}
        onDraftInfluenceChange={props.onDraftInfluenceChange}
        onDraftRelatedChange={props.onDraftRelatedChange}
        onDraftDetailAChange={props.onDraftDetailAChange}
        onDraftDetailBChange={props.onDraftDetailBChange}
        onDraftDetailCChange={props.onDraftDetailCChange}
        onDraftConfidenceChange={props.onDraftConfidenceChange}
        onSave={props.onSave}
        onCancel={props.onCancel}
      />
    </div>
  );
}

function MaterialAiWorkbench(props: {
  materialType: MaterialType;
  activeChapterTitle: string;
  visibleMaterial?: Material;
  aiSeed: string;
  aiSuggestion: MaterialAiSuggestion | null;
  lastAiMode: AiMode;
  agentAction: string | null;
  onAiSeedChange: (value: string) => void;
  onGenerate: (mode: AiMode) => Promise<void>;
  isActionDisabled: (mode: AiMode) => boolean;
  onDiscard: () => void;
  onRegenerate: () => Promise<void>;
  onApply: () => void | Promise<void>;
  saveLoading: boolean;
}) {
  return (
    <div className="library-workbench-section material-ai-workbench">
      <div className="material-ai-heading">
        <div className="material-ai-heading-icon">
          <ExperimentOutlined />
        </div>
        <div>
          <Text strong>AI 资料助手</Text>
          <Paragraph className="muted-text">描述你希望补充的内容，AI 会先整理成候选资料。</Paragraph>
        </div>
      </div>
      <div className="material-ai-context">
        <div>
          <Text type="secondary">资料类型</Text>
          <Text strong>{authorText(props.materialType)}</Text>
        </div>
        <div>
          <Text type="secondary">参考章节</Text>
          <Text strong ellipsis={{ tooltip: authorText(props.activeChapterTitle) }}>{authorText(props.activeChapterTitle)}</Text>
        </div>
      </div>
      <div className="material-ai-prompt">
        <Text strong>你的想法</Text>
        <Input.TextArea
          rows={6}
          placeholder={materialAiPlaceholder(props.materialType)}
          value={props.aiSeed}
          onChange={(event) => props.onAiSeedChange(event.target.value)}
        />
        <div className="material-ai-actions">
          <Button type="primary" icon={<FileAddOutlined />} loading={props.agentAction === "new"} disabled={props.isActionDisabled("new")} onClick={() => void props.onGenerate("new")}>
            生成{props.materialType}
          </Button>
          <Button
            icon={<HighlightOutlined />}
            loading={props.agentAction === "improve"}
            onClick={() => void props.onGenerate("improve")}
            disabled={!props.visibleMaterial || props.isActionDisabled("improve")}
          >
            优化当前
          </Button>
        </div>
      </div>
      {props.aiSuggestion ? (
        <div className="material-ai-candidate">
          <Flex justify="space-between" align="start" gap={12}>
            <div>
              <Text type="secondary">AI 资料候选</Text>
              <Title level={5}>{authorText(props.aiSuggestion.title)}</Title>
            </div>
            <Tag>{authorText(props.aiSuggestion.type)}</Tag>
          </Flex>
          <InlineNote title="来源上下文" content={`基于当前分类「${authorText(props.materialType)}」和章节「${authorText(props.activeChapterTitle)}」生成。`} />
          <Paragraph className="candidate-text">{authorText(props.aiSuggestion.summary)}</Paragraph>
          <Text type="secondary">影响</Text>
          <Paragraph strong>{authorText(props.aiSuggestion.influence)}</Paragraph>
          <div className="detail-grid">
            {Object.entries(props.aiSuggestion.details).map(([label, value]) => (
              <div key={label}>
                <Text type="secondary">{authorText(label)}</Text>
                <Paragraph>{authorText(value)}</Paragraph>
              </div>
            ))}
          </div>
          <Space direction="vertical" className="wide">
            <Button block onClick={() => void props.onRegenerate()} loading={props.agentAction === props.lastAiMode} disabled={props.isActionDisabled(props.lastAiMode)}>
              重新生成
            </Button>
            <Button block onClick={props.onDiscard} disabled={Boolean(props.agentAction) || props.saveLoading}>
              丢弃候选
            </Button>
            <Button block type="primary" icon={<CheckCircleOutlined />} loading={props.saveLoading} disabled={Boolean(props.agentAction)} onClick={() => void props.onApply()}>
              应用 AI 建议
            </Button>
          </Space>
        </div>
      ) : (
        <div className="material-ai-placeholder">
          <FileAddOutlined />
          <div>
            <Text strong>候选资料将在这里展开</Text>
            <Paragraph className="muted-text">会包含名称、摘要、章节影响和{authorText(props.materialType)}专属字段，确认后才写入资料库。</Paragraph>
          </div>
        </div>
      )}
    </div>
  );
}

function materialAiPlaceholder(materialType: MaterialType) {
  const examples: Record<MaterialType, string> = {
    人物: "例如：新增一位表面冷静、实际害怕被抛弃的调查员。补充身份、目标、秘密，以及他会怎样影响当前章节。",
    地点: "例如：设计一处雨夜仍在营业的旧车站，说明空间特点、危险和可触发的剧情。",
    势力: "例如：补充一个控制地下消息渠道的组织，写清目标、资源和与主角的冲突。",
    关系: "例如：描述两个人目前的关系、未说出口的矛盾，以及下一次变化的触发点。",
    设定: "例如：补充一条会限制人物选择的世界规则，并说明违反规则的代价。",
    时间线: "例如：整理关键事件发生顺序、前因后果，以及当前章节需要承接的节点。",
    伏笔: "例如：设计一个本章可露出、后续三章内回收的伏笔，注明表层线索和真实指向。",
    写法: "例如：记录本书在冲突场景中的叙述要求、节奏重点和需要避免的表达。"
  };
  return examples[materialType];
}

function InlineNote({ title, content }: { title: string; content: string }) {
  return (
    <div className="inline-note">
      <Text type="secondary">{title}</Text>
      <Paragraph className="muted-text">{authorText(content)}</Paragraph>
    </div>
  );
}

function isMaterialLinking(action: MaterialLinkAction, materialId: string) {
  return action?.mode === "append" && action.materialIds.includes(materialId);
}
