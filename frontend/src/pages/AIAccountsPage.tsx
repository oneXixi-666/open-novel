import { useEffect, useState } from "react";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Divider,
  Flex,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography
} from "antd";
import {
  ApiOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined
} from "@ant-design/icons";
import type { AIAccountInput } from "../api/contracts";
import { workbenchClient } from "../api/workbenchClient";
import type { AIAccount, AIProtocol, AISettings } from "../types";
import { authorText } from "../utils/authorText";

const { Paragraph, Text, Title } = Typography;

const emptySettings: AISettings = {
  accounts: [],
  roles: { writingAccountId: "", reviewAccountId: "" },
  usageSummary: {
    callCount: 0,
    totalTokens: 0,
    inputTokens: 0,
    outputTokens: 0,
    cachedInputTokens: 0,
    reasoningTokens: 0,
    cacheHits: 0
  },
  usageEvents: []
};

type AccountFormValue = Omit<AIAccountInput, "maxContextTokens"> & {
  id?: string;
  maxContextK: number;
};

export function AIAccountsPage() {
  const [settings, setSettings] = useState<AISettings>(emptySettings);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<AIAccount | null>(null);
  const [savingAccount, setSavingAccount] = useState(false);
  const [savingRoles, setSavingRoles] = useState(false);
  const [probingId, setProbingId] = useState("");
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [formProbing, setFormProbing] = useState(false);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [formProbeResult, setFormProbeResult] = useState("");
  const [roleSaveResult, setRoleSaveResult] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [form] = Form.useForm<AccountFormValue>();

  useEffect(() => {
    void loadSettings();
  }, []);

  async function loadSettings() {
    setLoading(true);
    setError("");
    try {
      setSettings(await workbenchClient.fetchAISettings());
    } catch (loadError) {
      setError(authorText(loadError instanceof Error ? loadError.message : "AI 账号加载失败。"));
    } finally {
      setLoading(false);
    }
  }

  function openAccount(account?: AIAccount) {
    setEditingAccount(account ?? null);
    form.setFieldsValue(account ? {
      id: account.id,
      name: account.name,
      purpose: account.purpose,
      baseUrl: account.baseUrl,
      apiKey: undefined,
      model: account.model,
      protocol: account.protocol,
      maxContextK: Math.max(3, Math.round(account.maxContextTokens / 1000)),
      enabled: account.enabled
    } : {
      name: "",
      purpose: "",
      baseUrl: "https://api.openai.com/v1",
      apiKey: "",
      model: "",
      protocol: "responses",
      maxContextK: 128,
      enabled: true
    });
    setModelOptions(account?.model ? [account.model] : []);
    setModelDropdownOpen(false);
    setFormProbeResult("");
    setAccountOpen(true);
  }

  async function saveAccount() {
    const values = await form.validateFields();
    setSavingAccount(true);
    setError("");
    try {
      const payload: AIAccountInput = {
        name: values.name.trim(),
        purpose: values.purpose.trim(),
        baseUrl: values.baseUrl.trim(),
        apiKey: values.apiKey?.trim() || (editingAccount ? undefined : ""),
        model: values.model.trim(),
        protocol: values.protocol,
        maxContextTokens: Math.round(values.maxContextK) * 1000,
        enabled: values.enabled
      };
      const next = editingAccount
        ? await workbenchClient.updateAIAccount(editingAccount.id, payload)
        : await workbenchClient.createAIAccount(payload);
      setSettings(next);
      setAccountOpen(false);
      message.success(editingAccount ? "AI 账号已更新。" : "AI 账号已添加。");
    } catch (saveError) {
      setError(authorText(saveError instanceof Error ? saveError.message : "AI 账号保存失败。"));
    } finally {
      setSavingAccount(false);
    }
  }

  async function deleteAccount(accountId: string) {
    setError("");
    try {
      setSettings(await workbenchClient.deleteAIAccount(accountId));
      message.success("AI 账号已删除。");
    } catch (deleteError) {
      setError(authorText(deleteError instanceof Error ? deleteError.message : "AI 账号删除失败。"));
    }
  }

  async function probeAccount(account: AIAccount) {
    setProbingId(account.id);
    setError("");
    try {
      const result = await workbenchClient.probeAIAccount(account.id);
      message.success(
        `拨测成功：${result.latencyMs} ms，Token ${result.usage.totalTokens.toLocaleString()}`
      );
      await loadSettings();
    } catch (probeError) {
      setError(authorText(probeError instanceof Error ? probeError.message : "账号拨测失败。"));
    } finally {
      setProbingId("");
    }
  }

  async function discoverModels() {
    await form.validateFields(["baseUrl"]);
    const values = form.getFieldsValue();
    setDiscoveringModels(true);
    setFormProbeResult("");
    setError("");
    try {
      const models = await workbenchClient.discoverAIModels({
        accountId: editingAccount?.id,
        baseUrl: values.baseUrl.trim(),
        apiKey: values.apiKey?.trim() || undefined
      });
      setModelOptions(models);
      setModelDropdownOpen(models.length > 0);
      message.success(`已获取 ${models.length} 个模型。`);
    } catch (discoverError) {
      setFormProbeResult(authorText(discoverError instanceof Error ? discoverError.message : "模型列表获取失败。"));
    } finally {
      setDiscoveringModels(false);
    }
  }

  async function probeFormConfiguration() {
    const values = await form.validateFields(["baseUrl", "model", "protocol", "maxContextK"]);
    setFormProbing(true);
    setFormProbeResult("");
    setError("");
    try {
      const result = await workbenchClient.probeAIConfiguration({
        accountId: editingAccount?.id,
        baseUrl: values.baseUrl.trim(),
        apiKey: values.apiKey?.trim() || undefined,
        model: values.model.trim(),
        protocol: values.protocol,
        maxContextTokens: Math.round(values.maxContextK) * 1000
      });
      setFormProbeResult(
        `拨测成功：收到“${authorText(result.text || "hi")}”，耗时 ${result.latencyMs} ms，本次使用 ${result.usage.totalTokens.toLocaleString()} Token。`
      );
      await loadSettings();
    } catch (probeError) {
      setFormProbeResult(authorText(probeError instanceof Error ? probeError.message : "账号拨测失败。"));
    } finally {
      setFormProbing(false);
    }
  }

  async function saveRoles() {
    setSavingRoles(true);
    setRoleSaveResult(null);
    setError("");
    try {
      setSettings(await workbenchClient.bindAIRoles(
        settings.roles.writingAccountId,
        settings.roles.reviewAccountId
      ));
      setRoleSaveResult({ type: "success", text: "角色分配已保存并立即生效。" });
      message.success("写作和审核角色已保存。");
    } catch (roleError) {
      const text = authorText(roleError instanceof Error ? roleError.message : "角色保存失败。");
      setRoleSaveResult({ type: "error", text });
      setError(text);
    } finally {
      setSavingRoles(false);
    }
  }

  const enabledOptions = settings.accounts
    .filter((account) => account.enabled)
    .map((account) => ({
      value: account.id,
      label: `${account.name} · ${account.model}`
    }));

  return (
    <div className="single-page model-settings-page">
      {error ? (
        <Alert
          showIcon
          closable
          type="error"
          message="AI 模型设置未完成"
          description={error}
          onClose={() => setError("")}
        />
      ) : null}
      <Tabs
        defaultActiveKey="models"
        items={[
          {
            key: "models",
            label: "模型方案",
            children: (
              <ModelRoutingPanel
                settings={settings}
                enabledOptions={enabledOptions}
                savingRoles={savingRoles}
                saveResult={roleSaveResult}
                onRolesChange={(roles) => setSettings((current) => ({ ...current, roles }))}
                onSaveRoles={saveRoles}
              />
            )
          },
          {
            key: "accounts",
            label: "AI 账号",
            children: (
              <AccountSettings
                settings={settings}
                loading={loading}
                probingId={probingId}
                onReload={loadSettings}
                onCreate={() => openAccount()}
                onEdit={openAccount}
                onDelete={deleteAccount}
                onProbe={probeAccount}
              />
            )
          }
        ]}
      />
      <Modal
        title={editingAccount ? "编辑 AI 账号" : "新增 AI 账号"}
        open={accountOpen}
        okText="保存账号"
        cancelText="取消"
        confirmLoading={savingAccount}
        onOk={() => void saveAccount()}
        onCancel={() => {
          setAccountOpen(false);
          setModelDropdownOpen(false);
          setFormProbeResult("");
        }}
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item name="name" label="账号名称" rules={[{ required: true, message: "请输入账号名称" }]}>
            <Input placeholder="例如：DeepSeek 写作" />
          </Form.Item>
          <Form.Item
            name="purpose"
            label="适合内容"
            rules={[{ required: true, message: "请说明这个模型适合写什么" }]}
            extra="用于区分多个模型，例如玄幻升级、细腻感情、悬疑推理或严格审稿。"
          >
            <Input placeholder="例如：玄幻升级、强冲突和快节奏章节" />
          </Form.Item>
          <Form.Item name="protocol" label="请求通道" rules={[{ required: true }]}>
            <Select options={[
              { value: "responses", label: "Responses API" },
              { value: "chat_completions", label: "Chat Completions API" }
            ]} />
          </Form.Item>
          <Form.Item name="baseUrl" label="Base URL" rules={[{ required: true, message: "请输入 Base URL" }]}>
            <Input placeholder="https://api.example.com/v1" />
          </Form.Item>
          <Form.Item
            name="apiKey"
            label="API Key"
            extra={editingAccount?.hasApiKey ? "留空表示继续使用已保存的 Key。" : "Key 仅保存在本机安全存储中。"}
          >
            <Input.Password placeholder={editingAccount?.hasApiKey ? "已保存，留空不修改" : "输入 API Key"} />
          </Form.Item>
          <Form.Item
            label="模型"
            required
            extra="点击“自动获取模型”会调用常见的 /v1/models 接口；也可以直接手动填写模型 ID。"
          >
            <Space.Compact block>
              <Form.Item name="model" noStyle rules={[{ required: true, message: "请输入模型名称" }]}>
                <AutoComplete
                  id="model"
                  aria-label="模型"
                  open={modelDropdownOpen}
                  onOpenChange={setModelDropdownOpen}
                  options={modelOptions.map((value) => ({ value }))}
                  placeholder="例如：gpt-5.4、deepseek-chat"
                  filterOption={(input, option) => String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())}
                />
              </Form.Item>
              <Button loading={discoveringModels} onClick={() => void discoverModels()}>
                自动获取模型
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item
            name="maxContextK"
            label="最大上下文"
            rules={[
              { required: true, message: "请输入最大上下文" },
              { type: "integer", message: "最大上下文必须是整数 K" }
            ]}
            extra="单位为 K，128 代表约 128,000 Token。系统会按该上限自动压缩过长上下文。"
          >
            <InputNumber min={3} max={2000} step={1} precision={0} className="wide" addonAfter="K" />
          </Form.Item>
          <Form.Item name="enabled" label="启用账号" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button block icon={<ApiOutlined />} loading={formProbing} onClick={() => void probeFormConfiguration()}>
            拨测当前配置（发送 hi）
          </Button>
          {formProbeResult ? (
            <Alert
              showIcon
              type={formProbeResult.startsWith("拨测成功") ? "success" : "error"}
              message={formProbeResult.startsWith("拨测成功") ? "拨测通过" : "拨测未通过"}
              description={formProbeResult}
            />
          ) : null}
        </Form>
      </Modal>
    </div>
  );
}

function ModelRoutingPanel({
  settings,
  enabledOptions,
  savingRoles,
  saveResult,
  onRolesChange,
  onSaveRoles
}: {
  settings: AISettings;
  enabledOptions: { value: string; label: string }[];
  savingRoles: boolean;
  saveResult: { type: "success" | "error"; text: string } | null;
  onRolesChange: (roles: AISettings["roles"]) => void;
  onSaveRoles: () => void | Promise<void>;
}) {
  return (
    <Space direction="vertical" size={16} className="wide">
      <Alert
        showIcon
        type="info"
        message="模型方案与 AI 账号统一管理"
        description="每个 AI 账号代表一个可调用模型。先在“AI 账号”标签新增并拨测，再把适合玄幻、感情、悬疑或审稿的模型分配给写作角色和审核角色。"
      />
      <Card className="content-card" variant="borderless">
        <Flex justify="space-between" align="center" gap={12} wrap="wrap">
          <div>
            <Text type="secondary">角色分配</Text>
            <Title level={4}>写作与审核</Title>
          </div>
          <Button type="primary" icon={<SaveOutlined />} loading={savingRoles} onClick={() => void onSaveRoles()}>
            保存角色
          </Button>
        </Flex>
        <div className="ai-role-grid">
          <div>
            <Text strong>写作角色</Text>
            <Paragraph className="muted-text">负责生成作品方向、蓝图、章节规划和章节正文。</Paragraph>
            <Select
              allowClear
              className="wide"
              placeholder="选择写作账号"
              value={settings.roles.writingAccountId || undefined}
              options={enabledOptions}
              onChange={(value) => onRolesChange({
                ...settings.roles,
                writingAccountId: value ?? ""
              })}
            />
          </div>
          <div>
            <Text strong>审核角色</Text>
            <Paragraph className="muted-text">负责审稿、修复建议和审核类候选。</Paragraph>
            <Select
              allowClear
              className="wide"
              placeholder="选择审核账号"
              value={settings.roles.reviewAccountId || undefined}
              options={enabledOptions}
              onChange={(value) => onRolesChange({
                ...settings.roles,
                reviewAccountId: value ?? ""
              })}
            />
          </div>
        </div>
        {saveResult ? (
          <Alert
            className="ai-role-save-result"
            showIcon
            type={saveResult.type}
            message={saveResult.type === "success" ? "保存成功" : "保存失败"}
            description={saveResult.text}
          />
        ) : null}
      </Card>
      <Card className="content-card" variant="borderless">
        <Text type="secondary">已登记模型</Text>
        <Title level={4}>按文风选择</Title>
        {settings.accounts.length ? (
          <div className="ai-model-grid">
            {settings.accounts.map((account) => (
              <div key={account.id} className="ai-model-item">
                <Flex justify="space-between" align="start" gap={12}>
                  <div className="min-w-0">
                    <Text strong>{authorText(account.name)}</Text>
                    <Paragraph className="muted-text">{authorText(account.purpose || "尚未填写适合内容，可到“AI 账号”编辑。")}</Paragraph>
                  </div>
                  <Tag color={account.enabled ? "success" : "default"}>{account.enabled ? "可选" : "停用"}</Tag>
                </Flex>
                <Space wrap>
                  <Tag>{authorText(account.model)}</Tag>
                  <Tag>{account.protocol === "responses" ? "Responses" : "Chat Completions"}</Tag>
                  {settings.roles.writingAccountId === account.id ? <Tag color="blue">当前写作</Tag> : null}
                  {settings.roles.reviewAccountId === account.id ? <Tag color="purple">当前审核</Tag> : null}
                </Space>
              </div>
            ))}
          </div>
        ) : (
          <Alert
            showIcon
            type="warning"
            message="还没有可选模型"
            description="切换到“AI 账号”标签新增一个账号并完成拨测，再回来分配用途。"
          />
        )}
      </Card>
    </Space>
  );
}

function AccountSettings({
  settings,
  loading,
  probingId,
  onReload,
  onCreate,
  onEdit,
  onDelete,
  onProbe
}: {
  settings: AISettings;
  loading: boolean;
  probingId: string;
  onReload: () => void | Promise<void>;
  onCreate: () => void;
  onEdit: (account: AIAccount) => void;
  onDelete: (accountId: string) => void | Promise<void>;
  onProbe: (account: AIAccount) => void | Promise<void>;
}) {
  return (
    <Space direction="vertical" size={16} className="wide">
      <Alert
        showIcon
        type="info"
        message="连接账号集中放在这里"
        description="新增、编辑和拨测 API 账号，并查看每次调用的 Token；写作模型与审核模型的分配在同页“模型方案”标签完成。"
      />
      <Card className="content-card" variant="borderless">
        <Flex justify="space-between" align="center" gap={12} wrap="wrap">
          <div>
            <Text type="secondary">全局设置</Text>
            <Title level={4}>AI 账号</Title>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void onReload()}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
              新增账号
            </Button>
          </Space>
        </Flex>
        <Table
          className="ai-account-table"
          rowKey="id"
          size="small"
          loading={loading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 960 }}
          dataSource={settings.accounts}
          locale={{ emptyText: "还没有 AI 账号，请先新增并拨测。" }}
          columns={[
            {
              title: "账号",
              dataIndex: "name",
              fixed: "left",
              width: 180,
              render: (value, account) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{authorText(value)}</Text>
                  <Text type="secondary">{account.hasApiKey ? "Key 已保存" : "未保存 Key"}</Text>
                </Space>
              )
            },
            {
              title: "通道",
              dataIndex: "protocol",
              width: 160,
              render: (value: AIProtocol) => value === "responses" ? "Responses" : "Chat Completions"
            },
            { title: "模型", dataIndex: "model", width: 180 },
            {
              title: "适合内容",
              dataIndex: "purpose",
              width: 220,
              ellipsis: true,
              render: (value: string) => authorText(value || "未填写")
            },
            {
              title: "最大上下文",
              dataIndex: "maxContextTokens",
              width: 130,
              render: (value: number) => `${Math.round(value / 1000)} K`
            },
            {
              title: "状态",
              dataIndex: "enabled",
              width: 90,
              render: (value: boolean) => <Tag color={value ? "success" : "default"}>{value ? "启用" : "停用"}</Tag>
            },
            {
              title: "操作",
              key: "actions",
              fixed: "right",
              width: 260,
              render: (_, account) => (
                <Space>
                  <Button
                    icon={<ApiOutlined />}
                    loading={probingId === account.id}
                    onClick={() => void onProbe(account)}
                  >
                    拨测
                  </Button>
                  <Button icon={<EditOutlined />} onClick={() => onEdit(account)} aria-label={`编辑${account.name}`} />
                  <Popconfirm
                    title="删除这个 AI 账号？"
                    description="角色绑定会同时取消，历史 Token 记录会保留。"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => void onDelete(account.id)}
                  >
                    <Button danger icon={<DeleteOutlined />} aria-label={`删除${account.name}`} />
                  </Popconfirm>
                </Space>
              )
            }
          ]}
        />
        <div className="ai-account-mobile-list">
          {settings.accounts.map((account) => (
            <article key={account.id} className="ai-account-mobile-card">
              <Flex justify="space-between" align="start" gap={10}>
                <div className="min-w-0">
                  <Text strong>{authorText(account.name)}</Text>
                  <Text type="secondary" className="ai-account-mobile-meta">
                    {account.hasApiKey ? "Key 已保存" : "未保存 Key"} · {account.enabled ? "启用" : "停用"}
                  </Text>
                </div>
                <Tag color={account.enabled ? "success" : "default"}>{account.enabled ? "启用" : "停用"}</Tag>
              </Flex>
              <dl className="ai-account-mobile-details">
                <div><dt>通道</dt><dd>{account.protocol === "responses" ? "Responses" : "Chat Completions"}</dd></div>
                <div><dt>模型</dt><dd>{authorText(account.model)}</dd></div>
                <div><dt>适合内容</dt><dd>{authorText(account.purpose || "未填写")}</dd></div>
                <div><dt>最大上下文</dt><dd>{Math.round(account.maxContextTokens / 1000)} K</dd></div>
              </dl>
              <Flex gap={8} wrap="wrap">
                <Button
                  icon={<ApiOutlined />}
                  loading={probingId === account.id}
                  onClick={() => void onProbe(account)}
                >
                  拨测
                </Button>
                <Button icon={<EditOutlined />} onClick={() => onEdit(account)}>
                  编辑
                </Button>
                <Popconfirm
                  title="删除这个 AI 账号？"
                  description="角色绑定会同时取消，历史 Token 记录会保留。"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => void onDelete(account.id)}
                >
                  <Button danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              </Flex>
            </article>
          ))}
          {!loading && !settings.accounts.length ? (
            <div className="ai-account-mobile-empty">还没有 AI 账号，请先新增并拨测。</div>
          ) : null}
        </div>
      </Card>
      <UsagePanel settings={settings} />
    </Space>
  );
}

function UsagePanel({ settings }: { settings: AISettings }) {
  const [mobilePage, setMobilePage] = useState(1);
  const summary = settings.usageSummary;
  const accountNames = new Map(settings.accounts.map((account) => [account.id, account.name]));
  const mobilePageSize = 8;
  const mobileEvents = settings.usageEvents.slice((mobilePage - 1) * mobilePageSize, mobilePage * mobilePageSize);
  return (
    <Card className="content-card" variant="borderless">
      <Text type="secondary">逐次调用记录</Text>
      <Title level={4}>Token 使用量</Title>
      <div className="ai-usage-metrics">
        <Statistic title="调用次数" value={summary.callCount} />
        <Statistic title="总 Token" value={summary.totalTokens} />
        <Statistic title="输入" value={summary.inputTokens} />
        <Statistic title="输出" value={summary.outputTokens} />
        <Statistic title="缓存输入" value={summary.cachedInputTokens} />
        <Statistic title="推理 Token" value={summary.reasoningTokens} />
        <Statistic title="缓存命中" value={summary.cacheHits} />
      </div>
      <Divider />
      <Table
        className="ai-usage-table"
        rowKey="id"
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 1200 }}
        dataSource={settings.usageEvents}
        locale={{ emptyText: "还没有 AI 调用记录。" }}
        columns={[
          {
            title: "时间",
            dataIndex: "createdAt",
            width: 170,
            render: (value: string) => value ? new Date(value).toLocaleString("zh-CN") : "-"
          },
          {
            title: "角色",
            dataIndex: "role",
            width: 80,
            render: (value: string) => value === "review" ? "审核" : "写作"
          },
          {
            title: "账号",
            dataIndex: "accountId",
            width: 160,
            ellipsis: true,
            render: (value: string) => authorText(accountNames.get(value) ?? value)
          },
          { title: "动作", dataIndex: "action", width: 180, ellipsis: true },
          { title: "模型", dataIndex: "model", width: 160, ellipsis: true },
          {
            title: "状态",
            dataIndex: "status",
            width: 110,
            render: (value: string, event) => (
              <Tag color={value === "completed" ? "success" : event.cacheHit ? "blue" : value === "cancelled" ? "warning" : value === "failed" ? "error" : "default"}>
                {usageStatusLabel(value)}
              </Tag>
            )
          },
          { title: "输入", dataIndex: "inputTokens", width: 90 },
          { title: "输出", dataIndex: "outputTokens", width: 90 },
          { title: "总量", dataIndex: "totalTokens", width: 90 },
          { title: "缓存输入", dataIndex: "cachedInputTokens", width: 100 },
          { title: "推理", dataIndex: "reasoningTokens", width: 90 },
          {
            title: "上下文",
            key: "context",
            width: 120,
            render: (_, event) => event.compressed ? (
              <Tag color="warning">{event.originalEstimatedTokens} → {event.sentEstimatedTokens}</Tag>
            ) : "未压缩"
          },
          {
            title: "耗时",
            dataIndex: "latencyMs",
            width: 90,
            render: (value: number) => `${value} ms`
          },
          {
            title: "统计来源",
            dataIndex: "usageSource",
            width: 110,
            render: (value: string) => usageSourceLabel(value)
          }
        ]}
      />
      <div className="ai-usage-mobile-list">
        {mobileEvents.map((event) => (
          <article key={event.id} className="ai-usage-mobile-card">
            <Flex justify="space-between" align="start" gap={10}>
              <div className="min-w-0">
                <Text strong>{authorText(event.action)}</Text>
                <Text type="secondary" className="ai-account-mobile-meta">
                  {event.createdAt ? new Date(event.createdAt).toLocaleString("zh-CN") : "-"}
                </Text>
              </div>
              <Tag color={event.status === "completed" ? "success" : event.cacheHit ? "blue" : event.status === "cancelled" ? "warning" : event.status === "failed" ? "error" : "default"}>
                {usageStatusLabel(event.status)}
              </Tag>
            </Flex>
            <dl className="ai-usage-mobile-details">
              <div><dt>角色</dt><dd>{event.role === "review" ? "审核" : "写作"}</dd></div>
              <div><dt>账号</dt><dd>{authorText(accountNames.get(event.accountId) ?? event.accountId)}</dd></div>
              <div><dt>模型</dt><dd>{authorText(event.model)}</dd></div>
              <div><dt>Token</dt><dd>{event.totalTokens.toLocaleString()}</dd></div>
              <div><dt>输入 / 输出</dt><dd>{event.inputTokens.toLocaleString()} / {event.outputTokens.toLocaleString()}</dd></div>
              <div><dt>耗时</dt><dd>{event.latencyMs} ms</dd></div>
            </dl>
          </article>
        ))}
        {!settings.usageEvents.length ? (
          <div className="ai-account-mobile-empty">还没有 AI 调用记录。</div>
        ) : null}
        {settings.usageEvents.length > mobilePageSize ? (
          <Pagination
            current={mobilePage}
            pageSize={mobilePageSize}
            total={settings.usageEvents.length}
            showSizeChanger={false}
            onChange={setMobilePage}
          />
        ) : null}
      </div>
    </Card>
  );
}

function usageStatusLabel(value: string) {
  return {
    completed: "完成",
    cached: "结果缓存",
    deduplicated: "并发复用",
    failed: "失败",
    cancelled: "已取消"
  }[value] ?? value;
}

function usageSourceLabel(value: string) {
  return {
    provider: "上游实报",
    estimated: "本地估算",
    cache: "结果缓存",
    deduplicated: "并发复用",
    unavailable: "上游未返回"
  }[value] ?? value;
}
