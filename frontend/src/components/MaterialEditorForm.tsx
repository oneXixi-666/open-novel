import { Button, Input, InputNumber, Typography } from "antd";
import { CheckCircleOutlined } from "@ant-design/icons";
import { materialDetailLabels } from "../domain/bookWorkspace";
import type { Material, MaterialType } from "../types";

const { Text, Paragraph } = Typography;

export function MaterialEditorForm(props: {
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
  saveLoading?: boolean;
  introText?: string;
  saveLabel?: string;
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
  const labels = materialDetailLabels[props.editingMaterial?.type ?? props.materialType];

  return (
    <div className="material-editor-form">
      {props.introText ? (
        <div className="material-editor-intro">
          <Text type="secondary">资料编辑</Text>
          <Paragraph className="muted-text">{props.introText}</Paragraph>
        </div>
      ) : null}
      {props.formError ? <Paragraph className="form-error">{props.formError}</Paragraph> : null}
      <section className="material-editor-group">
        <Text strong>基础信息</Text>
        <Input placeholder={`${props.materialType}名称`} value={props.draftTitle} onChange={(event) => props.onDraftTitleChange(event.target.value)} />
        <Input.TextArea
          rows={4}
          placeholder={`概括${props.materialType}的核心信息`}
          value={props.draftSummary}
          onChange={(event) => props.onDraftSummaryChange(event.target.value)}
        />
      </section>
      <section className="material-editor-group">
        <Text strong>{props.materialType}细节</Text>
        <div className="material-editor-detail-grid">
          {labels.map((label, index) => (
            <label className="material-editor-field" key={label}>
              <Text type="secondary">{label}</Text>
              <Input
                placeholder={`填写${label}`}
                value={[props.draftDetailA, props.draftDetailB, props.draftDetailC][index]}
                onChange={(event) => {
                  if (index === 0) props.onDraftDetailAChange(event.target.value);
                  if (index === 1) props.onDraftDetailBChange(event.target.value);
                  if (index === 2) props.onDraftDetailCChange(event.target.value);
                }}
              />
            </label>
          ))}
        </div>
      </section>
      <section className="material-editor-group">
        <Text strong>创作关联</Text>
        <Input.TextArea
          rows={3}
          placeholder="这条资料会怎样影响后续章节"
          value={props.draftInfluence}
          onChange={(event) => props.onDraftInfluenceChange(event.target.value)}
        />
        <Input placeholder="关联标签，用逗号分隔" value={props.draftRelated} onChange={(event) => props.onDraftRelatedChange(event.target.value)} />
        <div className="material-confidence-field">
          <Text type="secondary">可信度</Text>
          <InputNumber
            min={0}
            max={100}
            addonAfter="%"
            value={props.draftConfidence}
            onChange={(value) => props.onDraftConfidenceChange(Number(value ?? 0))}
          />
        </div>
      </section>
      <div className="material-editor-actions">
        <Button block type="primary" icon={<CheckCircleOutlined />} loading={props.saveLoading} onClick={props.onSave}>
          {props.saveLabel ?? "保存资料"}
        </Button>
        <Button block onClick={props.onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}
