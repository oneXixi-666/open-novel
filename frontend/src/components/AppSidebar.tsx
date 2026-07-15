import {
  ApiOutlined,
  AuditOutlined,
  BookOutlined,
  CheckCircleOutlined,
  DashboardOutlined,
  EditOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  FolderOpenOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoreOutlined,
  RightOutlined
} from "@ant-design/icons";
import { Badge, Button, Dropdown, Progress, Space, Tag, Tooltip, Typography } from "antd";
import type { MenuProps } from "antd";
import { useState, type ReactNode } from "react";
import type { Book, Chapter, GenerationState, JobSummary, ModuleKey, ReviewItem } from "../types";
import { authorText } from "../utils/authorText";
import { SystemUpdateControl } from "./SystemUpdateControl";

const { Text } = Typography;

type NavItem = {
  key: ModuleKey;
  label: string;
  icon: ReactNode;
  meta?: string;
  badge?: number;
  tone?: "default" | "warning" | "processing";
};

function NavButton({
  item,
  active,
  onClick,
  collapsed = false
}: {
  item: NavItem;
  active: boolean;
  onClick: (key: ModuleKey) => void;
  collapsed?: boolean;
}) {
  const button = (
    <button
      className={`sidebar-link ${active ? "active" : ""}`}
      aria-label={item.label}
      onClick={() => onClick(item.key)}
    >
      <span className="sidebar-link-icon">{item.icon}</span>
      <span className="sidebar-link-main">
        <span className="sidebar-link-label">{item.label}</span>
        {item.meta ? <span className="sidebar-link-meta">{item.meta}</span> : null}
      </span>
      {item.badge ? <Badge count={item.badge} size="small" /> : null}
      {item.tone === "warning" ? <span className="sidebar-dot warning" /> : null}
      {item.tone === "processing" ? <span className="sidebar-dot processing" /> : null}
    </button>
  );
  return collapsed ? <Tooltip title={item.meta ? `${item.label} · ${item.meta}` : item.label} placement="right">{button}</Tooltip> : button;
}

function MobileTabButton({
  item,
  active,
  onClick
}: {
  item: NavItem;
  active: boolean;
  onClick: (key: ModuleKey) => void;
}) {
  return (
    <button className={`mobile-tab ${active ? "active" : ""}`} onClick={() => onClick(item.key)}>
      <span className="mobile-tab-icon">
        <Badge dot={Boolean(item.badge || item.tone === "warning" || item.tone === "processing")}>{item.icon}</Badge>
      </span>
      <span className="mobile-tab-label">{item.label}</span>
    </button>
  );
}

export function AppSidebar({
  books,
  activeBook,
  activeChapter,
  generationState,
  reviews,
  jobs,
  moduleKey,
  onModuleChange
}: {
  books: Book[];
  activeBook: Book;
  activeChapter: Chapter;
  generationState: GenerationState;
  reviews: ReviewItem[];
  jobs: JobSummary[];
  moduleKey: ModuleKey;
  onModuleChange: (key: ModuleKey) => void;
}) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("open-novel-sidebar-collapsed") === "true");
  const openReviewCount = reviews.filter((review) => review.status !== "已确认").length;
  const activeJobCount = jobs.filter((job) => job.status === "运行中" || job.status === "等待中").length;
  const chapterMeta = `${activeChapter.status} · ${activeChapter.progress}%`;
  const bookProgress = activeBook.progress;
  const hasExportRisk = openReviewCount > 0 || activeBook.chapters.length === 0 || activeBook.progress < 100;
  const isBlocked = generationState.status === "blocked" || generationState.blockers.length > 0;

  const globalItems: NavItem[] = [
    { key: "accounts", label: "AI 模型", icon: <ApiOutlined />, meta: "方案 / 账号" },
    { key: "shelf", label: "书架", icon: <FolderOpenOutlined />, meta: `${books.length} 本书` },
    { key: "model", label: "我的模型", icon: <ExperimentOutlined />, meta: "公共模型库" }
  ];

  const bookItems: NavItem[] = [
    { key: "today", label: "生成", icon: <DashboardOutlined />, meta: "下一步" },
    { key: "writing", label: "章节", icon: <EditOutlined />, meta: chapterMeta, tone: activeChapter.status === "审阅" ? "warning" : "default" },
    { key: "library", label: "资料", icon: <BookOutlined />, meta: "人物 / 伏笔" },
    { key: "review", label: "审稿", icon: <AuditOutlined />, badge: openReviewCount || undefined, tone: openReviewCount ? "warning" : "default" },
    { key: "export", label: "导出", icon: <FileDoneOutlined />, meta: hasExportRisk ? "有风险" : "可导出", tone: hasExportRisk ? "warning" : "default" },
    { key: "more", label: "更多", icon: <MoreOutlined />, badge: activeJobCount || undefined, tone: activeJobCount ? "processing" : "default" }
  ];
  const mobilePrimaryItems = [globalItems[0], globalItems[1], bookItems[0], bookItems[1]];
  const mobileMoreKeys: ModuleKey[] = ["model", "library", "review", "export", "more"];
  const mobileMoreItems = [globalItems[2], bookItems[2], bookItems[3], bookItems[4], bookItems[5]];
  const mobileMoreActive = mobileMoreKeys.includes(moduleKey);
  const mobileMoreMenuItems: MenuProps["items"] = mobileMoreItems.map((item) => ({
    key: item.key,
    icon: item.icon,
    label: (
      <span className="mobile-more-label">
        <span>{item.label}</span>
        {item.badge ? <Badge count={item.badge} size="small" /> : null}
        {item.tone === "warning" ? <span className="sidebar-dot warning" /> : null}
        {item.tone === "processing" ? <span className="sidebar-dot processing" /> : null}
      </span>
    )
  }));
  const updateCollapsed = (value: boolean) => {
    setCollapsed(value);
    localStorage.setItem("open-novel-sidebar-collapsed", String(value));
  };

  return (
    <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""}`}>
      <div className="sidebar-brand">
        <div className="brand-mark">ON</div>
        <div className="brand-copy">
          <Text strong>Open Novel</Text>
          <Text type="secondary">本地小说工作台</Text>
        </div>
        <Tooltip title={collapsed ? "展开左侧导航" : "收起左侧导航"}>
          <Button
            type="text"
            className="sidebar-collapse-button"
            aria-label={collapsed ? "展开左侧导航" : "收起左侧导航"}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => updateCollapsed(!collapsed)}
          />
        </Tooltip>
      </div>
      <SystemUpdateControl collapsed={collapsed} />

      <div className="sidebar-switcher">
        <button className="book-spine" aria-label="打开书架切换作品" onClick={() => onModuleChange("shelf")}>
          {authorText(activeBook.title).slice(0, 1)}
        </button>
        <div className="sidebar-switcher-main">
          <Text type="secondary" className="book-switcher-eyebrow">当前书</Text>
          <button className="book-switcher-title" onClick={() => onModuleChange("shelf")}>
            <Badge dot={isBlocked} color="red" offset={[4, 0]}>
              <span>{authorText(activeBook.title)}</span>
            </Badge>
            <RightOutlined />
          </button>
          <div className="book-switcher-meta">
            <span>{authorText(activeBook.genre)}</span>
            <span>{authorText(activeBook.updatedAt)}</span>
          </div>
          <Progress percent={bookProgress} size="small" showInfo={false} />
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Open Novel navigation">
        <div className="sidebar-section">
          <div className="sidebar-section-title">全局</div>
          {globalItems.map((item) => (
            <NavButton key={item.key} item={item} active={moduleKey === item.key} onClick={onModuleChange} collapsed={collapsed} />
          ))}
        </div>
        <div className="sidebar-section">
          <div className="sidebar-section-title">当前书</div>
          {bookItems.map((item) => (
            <NavButton key={item.key} item={item} active={moduleKey === item.key} onClick={onModuleChange} collapsed={collapsed} />
          ))}
        </div>
      </nav>

      <div className="sidebar-footer-panel">
        <Space direction="vertical" size={8} className="wide">
          <div className="chapter-mini-head">
            <Text type="secondary">当前章节</Text>
            <Tag color={activeChapter.status === "完成" ? "success" : activeChapter.status === "审阅" ? "warning" : "processing"}>
              {activeChapter.status}
            </Tag>
          </div>
          <Text strong className="chapter-mini-title">{authorText(activeChapter.title)}</Text>
          <Progress percent={activeChapter.progress} size="small" />
          <Button type="primary" block icon={<CheckCircleOutlined />} onClick={() => onModuleChange("writing")}>
            继续处理 <RightOutlined />
          </Button>
        </Space>
      </div>
      <div className="sidebar-collapsed-actions">
        <Tooltip title="继续处理当前章节" placement="right">
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            aria-label="继续处理当前章节"
            onClick={() => onModuleChange("writing")}
          />
        </Tooltip>
      </div>

      <nav className="mobile-tabbar" aria-label="Open Novel mobile navigation">
        {mobilePrimaryItems.map((item) => (
          <MobileTabButton key={item.key} item={item} active={moduleKey === item.key} onClick={onModuleChange} />
        ))}
        <Dropdown
          trigger={["click"]}
          placement="topRight"
          menu={{
            selectedKeys: [moduleKey],
            items: mobileMoreMenuItems,
            onClick: ({ key }) => onModuleChange(key as ModuleKey)
          }}
        >
          <button className={`mobile-tab ${mobileMoreActive ? "active" : ""}`}>
            <span className="mobile-tab-icon">
              <Badge dot={Boolean(openReviewCount || hasExportRisk || activeJobCount)}>
                <MoreOutlined />
              </Badge>
            </span>
            <span className="mobile-tab-label">更多</span>
          </button>
        </Dropdown>
      </nav>
    </aside>
  );
}
