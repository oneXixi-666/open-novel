import { Progress, Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";
import type { Material } from "../types";
import { authorText } from "../utils/authorText";
import { statusLabel } from "../utils/statusLabel";

const { Text } = Typography;

export function MaterialSummaryBlock({
  material,
  active = false,
  compact = false,
  expanded = false,
  showHeader = true,
  actions
}: {
  material: Material;
  active?: boolean;
  compact?: boolean;
  expanded?: boolean;
  showHeader?: boolean;
  actions?: ReactNode;
}) {
  const inlineOnly = compact && !expanded;
  const Root = inlineOnly ? "span" : "div";
  const Headline = inlineOnly ? "span" : "div";
  const Body = inlineOnly ? "span" : "div";

  return (
    <Root className={`material-summary-block ${active ? "active" : ""} ${compact ? "compact" : ""}`}>
      {showHeader ? (
        <>
          <Headline className="material-summary-headline">
            <Body className="min-w-0">
              <Space size={6} align="center" wrap>
                <Text strong className="material-summary-title">
                  {statusLabel(material.title, authorText(material.title))}
                </Text>
                {!compact ? <Tag>{authorText(material.type)}</Tag> : null}
              </Space>
              <span className="material-summary-text">
                {authorText(material.summary)}
              </span>
            </Body>
            <Text type="secondary" className="material-summary-score">
              {material.confidence}%
            </Text>
          </Headline>
          {!compact ? <Progress percent={material.confidence} size="small" /> : null}
        </>
      ) : null}
      {expanded ? (
        <div className="material-summary-detail">
          <span className="material-summary-impact">
            影响：{authorText(material.influence)}
          </span>
          <Space size={[4, 4]} wrap className="material-summary-tags">
            {material.related.map((item) => (
              <Tag key={item}>{authorText(item)}</Tag>
            ))}
          </Space>
          {actions ? <div className="material-summary-actions">{actions}</div> : null}
        </div>
      ) : null}
    </Root>
  );
}

export function MaterialSummaryCard({
  material,
  expanded,
  linked = false,
  active = false,
  compact = true,
  onToggle,
  actions
}: {
  material: Material;
  expanded: boolean;
  linked?: boolean;
  active?: boolean;
  compact?: boolean;
  onToggle: () => void;
  actions?: ReactNode;
}) {
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onToggle();
    }
  }

  return (
    <div className={`material-summary-card ${expanded ? "active" : ""}`}>
      <div
        role="button"
        tabIndex={0}
        className="material-summary-card-main"
        onClick={onToggle}
        onKeyDown={handleKeyDown}
      >
        <div className="material-summary-card-meta">
          <Tag>{authorText(material.type)}</Tag>
          {linked ? <Tag color="blue">已纳入</Tag> : <Tag color="default">未纳入</Tag>}
          <Text type="secondary">{expanded ? "收起" : "展开"}</Text>
        </div>
        <MaterialSummaryBlock material={material} compact={compact} active={active || expanded} />
      </div>
      {expanded ? (
        <MaterialSummaryBlock
          material={material}
          compact={compact}
          expanded
          showHeader={false}
          actions={actions}
        />
      ) : null}
    </div>
  );
}
