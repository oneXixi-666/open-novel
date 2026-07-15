import { useState } from "react";
import { Alert, Button, Card, Checkbox, Divider, Dropdown, Empty, Flex, Input, List, Space, Statistic, Tag, Typography } from "antd";
import { CheckOutlined, CloseOutlined, FileAddOutlined, MoreOutlined, PlusOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";
import type { StatisticProps } from "antd";
import type { Chapter, ChapterStatus } from "../types";
import { authorText } from "../utils/authorText";

const { Text } = Typography;

export type MetricGridItem = {
  label: string;
  value: StatisticProps["value"];
  suffix?: ReactNode;
};

export function MetricGrid({ items, compact = false }: { items: MetricGridItem[]; compact?: boolean }) {
  return (
    <div className={`metric-grid ${compact ? "metric-grid-compact" : ""}`}>
      {items.map((item) => (
        <Card key={item.label} variant="borderless">
          <Statistic title={item.label} value={item.value} suffix={item.suffix} />
        </Card>
      ))}
    </div>
  );
}

export type PanelEmptyStateAction = {
  label: string;
  onClick: () => void;
};

export function PanelEmptyState({
  title,
  description,
  action,
  compact = false
}: {
  title: string;
  description?: string;
  action?: PanelEmptyStateAction;
  compact?: boolean;
}) {
  return (
    <div className={`panel-empty-state ${compact ? "panel-empty-state-compact" : ""}`}>
      <FileAddOutlined className="panel-empty-state-icon" />
      <div className="panel-empty-state-copy">
        <Text strong>{authorText(title)}</Text>
        {description ? <Text type="secondary">{authorText(description)}</Text> : null}
      </div>
      {action ? (
        <Button size={compact ? "small" : "middle"} type="primary" icon={<PlusOutlined />} onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}

export function TaskPanel({
  chapter,
  checkedTasks,
  onChange,
  onPlanningChange
}: {
  chapter: Chapter;
  checkedTasks: string[];
  onChange: (tasks: string[]) => void;
  onPlanningChange: (tasks: string[], plotPoints: string[]) => void | Promise<void>;
}) {
  const [taskText, setTaskText] = useState("");
  const [plotPointText, setPlotPointText] = useState("");
  const [editing, setEditing] = useState<{ kind: "task" | "plotPoint"; index: number; value: string } | null>(null);
  const [planningError, setPlanningError] = useState("");

  async function commitPlanning(tasks: string[], plotPoints: string[]) {
    setPlanningError("");
    try {
      await onPlanningChange(tasks, plotPoints);
      return true;
    } catch (error) {
      setPlanningError(authorText(error instanceof Error ? error.message : "任务和剧情点保存失败，请稍后重试。"));
      return false;
    }
  }

  async function addItem(kind: "task" | "plotPoint") {
    const value = kind === "task" ? taskText : plotPointText;
    const cleanValue = value.trim();
    if (!cleanValue) {
      return;
    }
    if (kind === "task" && !chapter.tasks.includes(cleanValue)) {
      if (!(await commitPlanning([...chapter.tasks, cleanValue], chapter.plotPoints))) {
        return;
      }
    }
    if (kind === "plotPoint" && !chapter.plotPoints.includes(cleanValue)) {
      if (!(await commitPlanning(chapter.tasks, [...chapter.plotPoints, cleanValue]))) {
        return;
      }
    }
    if (kind === "task") {
      setTaskText("");
    } else {
      setPlotPointText("");
    }
  }

  async function saveEdit() {
    if (!editing) {
      return;
    }
    const cleanValue = editing.value.trim();
    if (!cleanValue) {
      return;
    }
    if (editing.kind === "task") {
      const nextTasks = chapter.tasks.map((task, index) => (index === editing.index ? cleanValue : task));
      const nextChecked = checkedTasks.map((task) => (task === chapter.tasks[editing.index] ? cleanValue : task));
      if (!(await commitPlanning(nextTasks, chapter.plotPoints))) {
        return;
      }
      onChange(nextChecked);
    } else {
      const nextPlotPoints = chapter.plotPoints.map((point, index) => (index === editing.index ? cleanValue : point));
      if (!(await commitPlanning(chapter.tasks, nextPlotPoints))) {
        return;
      }
    }
    setEditing(null);
  }

  async function removeItem(kind: "task" | "plotPoint", index: number) {
    if (kind === "task") {
      const removed = chapter.tasks[index];
      if (!(await commitPlanning(chapter.tasks.filter((_, itemIndex) => itemIndex !== index), chapter.plotPoints))) {
        return;
      }
      onChange(checkedTasks.filter((task) => task !== removed));
    } else {
      if (!(await commitPlanning(chapter.tasks, chapter.plotPoints.filter((_, itemIndex) => itemIndex !== index)))) {
        return;
      }
    }
    setEditing(null);
  }

  function renderEditableRow(kind: "task" | "plotPoint", text: string, index: number) {
    const isEditing = editing?.kind === kind && editing.index === index;
    if (isEditing) {
      return (
        <Flex gap={6} align="center" className="planning-edit-row">
          <Input
            size="small"
            value={editing.value}
            onChange={(event) => setEditing({ ...editing, value: event.target.value })}
            onPressEnter={() => void saveEdit()}
          />
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => void saveEdit()} aria-label="保存" />
          <Button size="small" icon={<CloseOutlined />} onClick={() => setEditing(null)} aria-label="取消" />
        </Flex>
      );
    }
    return (
      <Flex gap={8} align="start" justify="space-between" className="planning-item-row">
        <Text className="planning-item-text">{authorText(text)}</Text>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "edit", label: "编辑" },
              { key: "delete", label: "删除", danger: true }
            ],
            onClick: ({ key }) => {
              if (key === "edit") {
                setEditing({ kind, index, value: text });
              } else {
                void removeItem(kind, index);
              }
            }
          }}
        >
          <Button size="small" type="text" icon={<MoreOutlined />} aria-label={`${authorText(text)}操作`} />
        </Dropdown>
      </Flex>
    );
  }

  return (
    <Space direction="vertical" size={14} className="wide">
      <div>
        <Text type="secondary">章节任务</Text>
      </div>
      {planningError ? (
        <Alert
          type="error"
          showIcon
          message="章节规划未保存"
          description={authorText(planningError)}
        />
      ) : null}
      <Checkbox.Group
        className="planning-task-group"
        value={checkedTasks}
        onChange={(values) => onChange(values.map(String))}
      >
        <Space direction="vertical" size={8} className="wide">
          {chapter.tasks.map((task, index) => (
            <div key={`${task}-${index}`} className="planning-check-row">
              <Checkbox value={task} />
              {renderEditableRow("task", task, index)}
            </div>
          ))}
        </Space>
      </Checkbox.Group>
      <Flex gap={8}>
        <Input
          value={taskText}
          placeholder="新增任务，例如：补一个角色误判"
          onChange={(event) => setTaskText(event.target.value)}
          onPressEnter={() => void addItem("task")}
        />
        <Button icon={<PlusOutlined />} onClick={() => void addItem("task")}>
          新增
        </Button>
      </Flex>
      <Divider />
      <div>
        <Text type="secondary">本章剧情点</Text>
      </div>
      {chapter.plotPoints.length ? (
        <Space direction="vertical" size={8} className="wide">
          {chapter.plotPoints.map((point, index) => (
            <Flex key={`${point}-${index}`} gap={8} align="start" className="planning-point">
              <Tag color="blue">{index + 1}</Tag>
              {renderEditableRow("plotPoint", point, index)}
            </Flex>
          ))}
        </Space>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有剧情点" />
      )}
      <Flex gap={8}>
        <Input
          value={plotPointText}
          placeholder="添加剧情点，例如：门禁记录反咬主角"
          onChange={(event) => setPlotPointText(event.target.value)}
          onPressEnter={() => void addItem("plotPoint")}
        />
        <Button icon={<PlusOutlined />} onClick={() => void addItem("plotPoint")}>
          添加
        </Button>
      </Flex>
    </Space>
  );
}

export function SimpleList({ icon, items }: { icon: ReactNode; items: string[] }) {
  return (
    <List
      dataSource={items}
      locale={{ emptyText: "暂无内容" }}
      renderItem={(item) => (
        <List.Item>
          <Space>
            {icon}
            <Text>{authorText(item)}</Text>
          </Space>
        </List.Item>
      )}
    />
  );
}

export function SupportRow({ label, value }: { label: string; value: string }) {
  return (
    <Flex justify="space-between" gap={16} className="support-row">
      <Text type="secondary">{authorText(label)}</Text>
      <Text strong>{authorText(value)}</Text>
    </Flex>
  );
}

export function WorkbenchForm({ children }: { children: ReactNode }) {
  return (
    <Space direction="vertical" size={10} className="wide workbench-form">
      {children}
    </Space>
  );
}

export function WorkbenchField({ children }: { children: ReactNode }) {
  return <div className="workbench-field">{children}</div>;
}

export function statusColor(status: ChapterStatus): "default" | "processing" | "warning" | "success" {
  const colors = {
    待写: "default",
    草稿: "processing",
    审阅: "warning",
    完成: "success"
  } as const;
  return colors[status];
}
