import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Popover,
  Space,
  Tooltip,
  Typography
} from "antd";
import {
  CheckOutlined,
  ClockCircleOutlined,
  CloudDownloadOutlined,
  ExclamationOutlined,
  GithubOutlined,
  ReloadOutlined
} from "@ant-design/icons";
import type {
  SystemUpdateInfo,
  SystemUpdatePreparation,
  SystemUpdateStatus
} from "../api/contracts";
import { workbenchClient } from "../api/workbenchClient";
import { authorText } from "../utils/authorText";

const { Text } = Typography;
const UPDATE_POLL_INTERVAL_MS = 60_000;

const updatePhaseFallback = {
  success: "更新成功",
  rolled_back: "已自动回滚",
  failed: "更新失败",
  reconnecting: "等待服务恢复"
} as const;

function failedUpdateInfo(error: unknown): SystemUpdateInfo {
  return {
    checkSucceeded: false,
    currentVersion: "",
    latestVersion: "",
    updateAvailable: false,
    downloadReady: false,
    status: "检查失败",
    message: authorText(error instanceof Error ? error.message : "版本检查失败，请稍后重试。"),
    releaseName: "",
    releaseNotes: "",
    publishedAt: "",
    releaseUrl: "",
    packageUrl: "",
    checksumUrl: "",
    deploymentMode: "source",
    deploymentLabel: "源码单机",
    automaticUpdateReady: false,
    automaticUpdateMessage: ""
  };
}

export function SystemUpdateControl({ collapsed = false }: { collapsed?: boolean }) {
  const [updateInfo, setUpdateInfo] = useState<SystemUpdateInfo | null>(null);
  const [updatePreparation, setUpdatePreparation] = useState<SystemUpdatePreparation | null>(null);
  const [updateStatus, setUpdateStatus] = useState<SystemUpdateStatus | null>(null);
  const [updateLoading, setUpdateLoading] = useState(false);
  const [updatePreparing, setUpdatePreparing] = useState(false);
  const [updatePollIntervalMs, setUpdatePollIntervalMs] = useState(UPDATE_POLL_INTERVAL_MS);

  async function detectSystemUpdate(manual = false) {
    if (manual) {
      setUpdateLoading(true);
    }
    try {
      if (manual) {
        setUpdateInfo(await workbenchClient.fetchSystemUpdate());
      } else {
        const result = await workbenchClient.autoDetectSystemUpdate();
        setUpdateInfo(result);
        setUpdatePollIntervalMs(result.pollIntervalSeconds * 1000);
      }
    } catch (error) {
      setUpdateInfo(failedUpdateInfo(error));
    } finally {
      if (manual) {
        setUpdateLoading(false);
      }
    }
  }

  async function refreshSystemUpdateStatus(reconnecting = false) {
    try {
      const nextStatus = await workbenchClient.fetchSystemUpdateStatus();
      setUpdateStatus(nextStatus);
      if (nextStatus.succeeded) {
        void detectSystemUpdate();
      }
    } catch {
      if (reconnecting) {
        setUpdateStatus((current) => current ? {
          ...current,
          phase: "reconnecting",
          status: "等待服务恢复",
          message: "服务正在重启，页面会自动重新连接。",
          finished: false
        } : current);
      }
    }
  }

  async function prepareSystemUpdate() {
    setUpdatePreparing(true);
    setUpdatePreparation(null);
    try {
      const result = await workbenchClient.prepareSystemUpdate();
      setUpdatePreparation(result);
      setUpdateStatus({
        phase: result.deploymentMode === "compose" ? "waiting_host" : "waiting_restart",
        status: result.status,
        message: result.message,
        currentVersion: result.currentVersion,
        targetVersion: result.targetVersion,
        deploymentMode: result.deploymentMode,
        finished: false,
        succeeded: false,
        rolledBack: false,
        updatedAt: new Date().toISOString()
      });
    } catch (error) {
      setUpdatePreparation({
        status: "更新启动失败",
        message: authorText(error instanceof Error ? error.message : "更新包准备失败，请稍后重试。"),
        currentVersion: updateInfo?.currentVersion ?? "",
        targetVersion: updateInfo?.latestVersion ?? "",
        planPath: "",
        packagePath: "",
        databaseBackupPath: "",
        restartRequired: false,
        deploymentMode: updateInfo?.deploymentMode ?? "source",
        shutdownRequired: false
      });
    } finally {
      setUpdatePreparing(false);
    }
  }

  useEffect(() => {
    void detectSystemUpdate();
    void refreshSystemUpdateStatus();
  }, []);

  useEffect(() => {
    if (updateStatus && !updateStatus.finished) {
      return;
    }
    const timer = window.setInterval(() => {
      void detectSystemUpdate();
    }, updatePollIntervalMs);
    return () => window.clearInterval(timer);
  }, [updatePollIntervalMs, updateStatus?.finished]);

  useEffect(() => {
    if (!updateStatus || updateStatus.finished) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshSystemUpdateStatus(true);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [updateStatus?.finished, updateStatus?.phase]);

  const versionLabel = updateInfo?.currentVersion
    ? `v${updateInfo.currentVersion}`
    : "版本";
  const activeUpdate = Boolean(updateStatus && !updateStatus.finished);
  const hasFinishedStatus = Boolean(
    updateStatus
    && updateStatus.phase !== "idle"
    && (updateStatus.succeeded || updateStatus.rolledBack || updateStatus.phase === "failed")
  );
  const statusText = activeUpdate || hasFinishedStatus
    ? authorText(updateStatus?.status || updatePhaseFallback[updateStatus?.phase as keyof typeof updatePhaseFallback] || "正在更新")
    : updateInfo?.updateAvailable
      ? `发现新版本 v${updateInfo.latestVersion}`
      : updateInfo?.checkSucceeded
        ? "已经是最新版本"
        : updateInfo?.status ?? "正在检查更新";
  const statusTone = activeUpdate
    ? "updating"
    : updateInfo?.updateAvailable
      ? "available"
      : updateInfo?.checkSucceeded
        ? "current"
        : "failed";
  const detailMessage = activeUpdate || hasFinishedStatus
    ? authorText(updateStatus?.message)
    : updateInfo?.updateAvailable || !updateInfo?.checkSucceeded
      ? authorText(updateInfo?.message)
      : "";

  const content = (
    <div className="system-version-panel">
      <div className="system-version-panel-header">
        <Text strong>当前版本</Text>
        <Tooltip title="检查更新">
          <Button
            type="text"
            aria-label="检查更新"
            icon={<ReloadOutlined />}
            loading={updateLoading}
            disabled={activeUpdate}
            onClick={() => void detectSystemUpdate(true)}
          />
        </Tooltip>
      </div>

      <div className="system-version-panel-body">
        <div className="system-version-current">
          <span>{versionLabel}</span>
          <span className={`system-version-state-icon ${statusTone}`}>
            {updateInfo?.checkSucceeded && !updateInfo.updateAvailable && !activeUpdate
              ? <CheckOutlined />
              : statusTone === "failed"
                ? <ExclamationOutlined />
                : <CloudDownloadOutlined />}
          </span>
        </div>
        <div className={`system-version-status ${statusTone}`}>{statusText}</div>
        {detailMessage ? <div className="system-version-detail">{detailMessage}</div> : null}

        <Space direction="vertical" size={8} className="system-version-actions">
          {updateInfo?.releaseUrl ? (
            <Button
              type="text"
              icon={<GithubOutlined />}
              onClick={() => window.open(updateInfo.releaseUrl, "_blank", "noopener,noreferrer")}
            >
              查看发布
            </Button>
          ) : null}
          {updateInfo?.updateAvailable && updateInfo.downloadReady ? (
            <Button
              block
              type="primary"
              icon={<CloudDownloadOutlined />}
              loading={updatePreparing}
              disabled={!updateInfo.automaticUpdateReady || activeUpdate}
              onClick={() => void prepareSystemUpdate()}
            >
              {activeUpdate ? "正在更新" : "一键更新"}
            </Button>
          ) : null}
        </Space>
        {updateInfo?.updateAvailable && !updateInfo.downloadReady ? (
          <div className="system-version-notice">新版本尚未提供完整更新包。</div>
        ) : null}
        {updateInfo && !updateInfo.automaticUpdateReady ? (
          <div className="system-version-notice warning">
            {authorText(updateInfo.automaticUpdateMessage)}
          </div>
        ) : null}
        {updatePreparation && !updatePreparation.planPath ? (
          <div className="system-version-notice error">
            {authorText(updatePreparation.message)}
          </div>
        ) : null}
      </div>

      <div className="system-version-panel-footer">
        <ClockCircleOutlined />
        <span>{updateInfo?.deploymentLabel || "当前部署"} · 每分钟自动检查</span>
      </div>
    </div>
  );

  return (
    <div className={`system-update-control ${collapsed ? "is-collapsed" : ""}`} aria-label="系统版本与更新">
      <Popover
        content={content}
        trigger="click"
        placement="bottomLeft"
        rootClassName="system-update-overlay"
      >
        <Badge dot={Boolean(updateInfo?.updateAvailable)} color="#f59e0b">
          <Button
            className="system-version-button"
            aria-label={`当前版本 ${versionLabel}`}
          >
            {collapsed ? "V" : versionLabel}
          </Button>
        </Badge>
      </Popover>
    </div>
  );
}
