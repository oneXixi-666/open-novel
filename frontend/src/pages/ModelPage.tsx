import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Form,
  Input,
  List,
  message,
  Modal,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  Upload
} from "antd";
import {
  BookOutlined,
  DeleteOutlined,
  DownOutlined,
  ExperimentOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  UpOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload/interface";
import type {
  ModelLibraryItem,
  ModelLibraryReadiness,
  ModelLibrarySource,
  ModelLibraryTemplate,
  ModelTrainingBackend
} from "../api/contracts";
import { workbenchClient } from "../api/workbenchClient";
import type { Book } from "../types";
import { authorText } from "../utils/authorText";

const { Dragger } = Upload;
const { Paragraph, Text, Title } = Typography;

const emptyReadiness: ModelLibraryReadiness = {
  modelId: "",
  status: "block",
  eligibleCount: 0,
  skippedCount: 0,
  totalCharacters: 0,
  minRecommendedExamples: 20,
  items: [],
  recommendedNextAction: "请先添加训练文章。"
};

export function ModelPage({
  activeBook,
  books,
  onModelChange
}: {
  activeBook: Book;
  books: Book[];
  onModelChange: (modelId: string) => void | Promise<void>;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [categories, setCategories] = useState<{ id: string; label: string; builtin: boolean }[]>([]);
  const [templates, setTemplates] = useState<ModelLibraryTemplate[]>([]);
  const [models, setModels] = useState<ModelLibraryItem[]>([]);
  const [trainingBackends, setTrainingBackends] = useState<ModelTrainingBackend[]>([]);
  const [trainingBackendId, setTrainingBackendId] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [detail, setDetail] = useState<ModelLibraryItem | null>(null);
  const [readiness, setReadiness] = useState<ModelLibraryReadiness>(emptyReadiness);
  const [createOpen, setCreateOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [bookSourceOpen, setBookSourceOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([]);
  const [uploadResults, setUploadResults] = useState<ModelLibrarySource[]>([]);
  const [templatesExpanded, setTemplatesExpanded] = useState(false);
  const [categoryName, setCategoryName] = useState("");
  const [sourceBookId, setSourceBookId] = useState(activeBook.id);
  const [sourceChapterIds, setSourceChapterIds] = useState<string[]>([]);
  const [form] = Form.useForm<{
    name: string;
    categoryId: string;
    purpose: string;
    description: string;
  }>();

  useEffect(() => {
    void loadLibrary();
  }, []);

  useEffect(() => {
    if (!selectedModelId) {
      setDetail(null);
      setReadiness(emptyReadiness);
      return;
    }
    void loadDetail(selectedModelId);
  }, [selectedModelId]);

  const sourceBook = books.find((book) => book.id === sourceBookId) ?? activeBook;
  const eligibleBookChapters = useMemo(
    () => sourceBook.chapters.filter((chapter) => chapter.status === "完成"),
    [sourceBook]
  );
  const filteredModels = useMemo(
    () => (
      categoryFilter
        ? models.filter((model) => model.categoryId === categoryFilter)
        : models
    ),
    [categoryFilter, models]
  );
  const acceptedUploadResults = uploadResults.filter((item) => item.status === "eligible");
  const rejectedUploadResults = uploadResults.filter((item) => item.status !== "eligible");

  async function loadLibrary(preferredModelId = "") {
    setLoading(true);
    setError("");
    try {
      const [result, backends] = await Promise.all([
        workbenchClient.fetchModelLibrary(),
        workbenchClient.fetchModelTrainingBackends()
      ]);
      setCategories(result.categories);
      setTemplates(Array.isArray(result.templates) ? result.templates : []);
      setModels(result.models);
      setTrainingBackends(backends);
      setTrainingBackendId((current) => (
        backends.some((backend) => backend.id === current && backend.available)
          ? current
          : backends.find((backend) => backend.recommended && backend.available)?.id
            ?? backends.find((backend) => backend.available)?.id
            ?? ""
      ));
      setSelectedModelId((current) => (
        preferredModelId
        || (current && result.models.some((model) => model.id === current) ? current : "")
        || result.models[0]?.id
        || ""
      ));
    } catch (loadError) {
      setError(authorText(loadError instanceof Error ? loadError.message : "模型库加载失败。"));
    } finally {
      setLoading(false);
    }
  }

  function openBlankModel() {
    form.resetFields();
    setCreateOpen(true);
  }

  function openTemplate(template: ModelLibraryTemplate) {
    form.setFieldsValue({
      name: template.name,
      categoryId: template.categoryId,
      purpose: template.purpose,
      description: template.description
    });
    setCreateOpen(true);
  }

  async function loadDetail(modelId: string) {
    setError("");
    try {
      const [model, nextReadiness] = await Promise.all([
        workbenchClient.fetchModelLibraryDetail(modelId),
        workbenchClient.fetchModelLibraryReadiness(modelId)
      ]);
      setDetail(model);
      setReadiness(nextReadiness);
    } catch (loadError) {
      setError(authorText(loadError instanceof Error ? loadError.message : "模型详情加载失败。"));
    }
  }

  async function createModel() {
    const values = await form.validateFields();
    setSaving(true);
    setError("");
    try {
      const result = await workbenchClient.createModelLibraryItem(values);
      setCreateOpen(false);
      form.resetFields();
      message.success(result.summary);
      await loadLibrary(result.model.id);
    } catch (createError) {
      setError(authorText(createError instanceof Error ? createError.message : "模型创建失败。"));
    } finally {
      setSaving(false);
    }
  }

  async function createCategory() {
    if (!categoryName.trim()) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const category = await workbenchClient.createModelCategory(categoryName.trim());
      setCategories((current) => [...current, category]);
      form.setFieldValue("categoryId", category.id);
      setCategoryName("");
      setCategoryOpen(false);
      message.success(`已创建分类：${category.label}`);
    } catch (categoryError) {
      setError(authorText(categoryError instanceof Error ? categoryError.message : "分类创建失败。"));
    } finally {
      setSaving(false);
    }
  }

  async function uploadSources() {
    if (!detail) {
      return;
    }
    const files: File[] = uploadFiles.flatMap((item) => (
      item.originFileObj ? [item.originFileObj] : []
    ));
    if (!files.length) {
      message.warning("请先选择 TXT 或 DOCX 文件。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await workbenchClient.uploadModelSources(detail.id, files);
      setUploadFiles([]);
      setUploadResults(result.items);
      setUploadOpen(false);
      message.success(result.summary);
      await loadLibrary(detail.id);
      await loadDetail(detail.id);
    } catch (uploadError) {
      setError(authorText(uploadError instanceof Error ? uploadError.message : "训练文章上传失败。"));
    } finally {
      setSaving(false);
    }
  }

  function openUpload() {
    setUploadFiles([]);
    setUploadResults([]);
    setUploadOpen(true);
  }

  function closeUpload() {
    setUploadOpen(false);
    setUploadFiles([]);
    setUploadResults([]);
  }

  async function addBookSources() {
    if (!detail || !sourceChapterIds.length) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await workbenchClient.addModelBookSources(
        detail.id,
        sourceChapterIds.map((chapterId) => ({ bookId: sourceBook.id, chapterId }))
      );
      setSourceChapterIds([]);
      setBookSourceOpen(false);
      message.success(result.summary);
      await loadLibrary(detail.id);
      await loadDetail(detail.id);
    } catch (sourceError) {
      setError(authorText(sourceError instanceof Error ? sourceError.message : "作品章节添加失败。"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteSource(sourceId: string) {
    if (!detail) {
      return;
    }
    setSaving(true);
    try {
      const result = await workbenchClient.deleteModelSource(detail.id, sourceId);
      message.success(result.summary);
      await loadLibrary(detail.id);
      await loadDetail(detail.id);
    } catch (deleteError) {
      setError(authorText(deleteError instanceof Error ? deleteError.message : "训练素材删除失败。"));
    } finally {
      setSaving(false);
    }
  }

  function confirmTraining() {
    if (!detail) {
      return;
    }
    Modal.confirm({
      title: `开始训练“${detail.name}”`,
      content: `将使用 ${readiness.eligibleCount} 篇合格文章生成新的模型版本。`,
      okText: "开始训练",
      cancelText: "取消",
      onOk: async () => {
        setSaving(true);
        try {
          const result = await workbenchClient.startModelLibraryTraining(detail.id, {
            sourceIds: readiness.items
              .filter((item) => item.status === "eligible")
              .map((item) => item.id),
            bookId: activeBook.id,
            backendId: trainingBackendId,
            confirm: true
          });
          message.success(result.summary);
          window.setTimeout(() => void loadDetail(detail.id), 600);
        } catch (trainingError) {
          setError(authorText(trainingError instanceof Error ? trainingError.message : "训练任务提交失败。"));
        } finally {
          setSaving(false);
        }
      }
    });
  }

  return (
    <div className="single-page model-library-page">
      <Flex justify="space-between" align="center" gap={16} wrap="wrap" className="page-section-head">
        <div>
          <Text type="secondary">工作区公共模型</Text>
          <Title level={3}>我的模型</Title>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openBlankModel}>
          新增模型
        </Button>
      </Flex>

      <section className="model-template-section" aria-labelledby="model-template-title">
        <Flex justify="space-between" align="center" gap={12} wrap="wrap">
          <div>
            <Title level={5} id="model-template-title">内置模板</Title>
            <Text type="secondary">题材与风格起点，不包含训练文章</Text>
          </div>
          <Text type="secondary">{templates.length} 种</Text>
        </Flex>
        <div className={`model-template-grid ${templatesExpanded ? "expanded" : ""}`}>
          {templates.map((template) => (
            <button
              key={template.id}
              type="button"
              className="model-template-option"
              aria-label={`使用 ${template.name} 模板`}
              onClick={() => openTemplate(template)}
            >
              <span className="model-template-option-head">
                <Text strong>{template.name}</Text>
                <Tag>{template.genre}</Tag>
              </span>
              <Text type="secondary">{template.style} · {template.purpose}</Text>
              <Text type="secondary" className="model-template-description">
                {template.description}
              </Text>
            </button>
          ))}
        </div>
        {templates.length > 6 ? (
          <Button
            className="model-template-toggle"
            icon={templatesExpanded ? <UpOutlined /> : <DownOutlined />}
            onClick={() => setTemplatesExpanded((current) => !current)}
          >
            {templatesExpanded ? "收起模板" : `查看全部 ${templates.length} 种模板`}
          </Button>
        ) : null}
      </section>

      {error ? (
        <Alert
          showIcon
          closable
          type="error"
          message="模型操作未完成"
          description={error}
          onClose={() => setError("")}
        />
      ) : null}

      {uploadResults.length ? (
        <Alert
          showIcon
          closable
          type={rejectedUploadResults.length ? "warning" : "success"}
          message="文章检查结果"
          onClose={() => setUploadResults([])}
          description={(
            <Space direction="vertical" size={12} className="wide">
              {acceptedUploadResults.length ? (
                <div>
                  <Text strong>已添加 {acceptedUploadResults.length} 个</Text>
                  <List
                    size="small"
                    dataSource={acceptedUploadResults}
                    renderItem={(item) => (
                      <List.Item>
                        <Text>{authorText(item.originalName)}</Text>
                        <Tag color="success">可训练</Tag>
                      </List.Item>
                    )}
                  />
                </div>
              ) : null}
              {rejectedUploadResults.length ? (
                <div>
                  <Text strong>未通过 {rejectedUploadResults.length} 个</Text>
                  <List
                    size="small"
                    dataSource={rejectedUploadResults}
                    renderItem={(item) => (
                      <List.Item>
                        <List.Item.Meta
                          title={authorText(item.originalName)}
                          description={authorText(item.reasonLabel || "文章未通过训练素材检查。")}
                        />
                        <Tag color={sourceStatusColor(item.status)}>
                          {sourceStatusLabel(item.status)}
                        </Tag>
                      </List.Item>
                    )}
                  />
                </div>
              ) : null}
            </Space>
          )}
        />
      ) : null}

      <div className={`model-library-layout ${!models.length ? "model-library-layout-empty" : ""}`}>
        <Card className="content-card model-library-list" variant="borderless" loading={loading}>
          {models.length ? (
            <Space direction="vertical" size={12} className="wide">
              <Select
                value={categoryFilter}
                aria-label="按分类筛选"
                options={[
                  { value: "", label: "全部分类" },
                  ...categories.map((category) => ({
                    value: category.id,
                    label: category.label
                  }))
                ]}
                onChange={setCategoryFilter}
              />
              <List
              dataSource={filteredModels}
              locale={{ emptyText: "这个分类还没有模型。" }}
              renderItem={(model) => (
                <List.Item>
                  <button
                    className={`model-library-row ${selectedModelId === model.id ? "active" : ""}`}
                    onClick={() => setSelectedModelId(model.id)}
                  >
                    <span className="model-library-row-main">
                      <Text strong>{authorText(model.name)}</Text>
                      <Text type="secondary">
                        {authorText(model.categoryLabel)} · {authorText(model.purpose)}
                      </Text>
                    </span>
                    <span className="model-library-row-meta">
                      <Tag color={modelStatusColor(model.status)}>{modelStatusLabel(model.status)}</Tag>
                      <Text type="secondary">{model.eligibleCount} 篇</Text>
                      <Text type="secondary">用于 {model.usedByBooks?.length ?? 0} 本书</Text>
                    </span>
                  </button>
                </List.Item>
              )}
            />
            </Space>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有训练模型，可从上方模板或“新增模型”开始。"
            />
          )}
        </Card>

        {models.length ? <Card className="content-card model-library-detail" variant="borderless">
          {detail ? (
            <Space direction="vertical" size={20} className="wide">
              <Flex justify="space-between" align="start" gap={16} wrap="wrap">
                <div className="min-w-0">
                  <Space wrap>
                    <Tag>{authorText(detail.categoryLabel)}</Tag>
                    <Tag color={modelStatusColor(detail.status)}>{modelStatusLabel(detail.status)}</Tag>
                  </Space>
                  <Title level={4}>{authorText(detail.name)}</Title>
                  <Paragraph className="muted-text">
                    {authorText(detail.description || detail.purpose)}
                  </Paragraph>
                </div>
                <Space wrap>
                  <Button icon={<UploadOutlined />} onClick={openUpload}>
                    上传文章
                  </Button>
                  <Button icon={<BookOutlined />} onClick={() => setBookSourceOpen(true)}>
                    从作品选择
                  </Button>
                </Space>
              </Flex>

              <div className="model-library-metrics">
                <Statistic title="合格文章" value={readiness.eligibleCount} suffix="篇" />
                <Statistic title="待处理" value={readiness.skippedCount} suffix="篇" />
                <Statistic title="训练字数" value={readiness.totalCharacters} />
                <Statistic title="模型版本" value={detail.versions?.length ?? 0} />
              </div>

              <div className="model-training-backend-picker">
                <Text type="secondary">训练方式</Text>
                <Segmented
                  block
                  value={trainingBackendId}
                  onChange={(value) => setTrainingBackendId(String(value))}
                  options={trainingBackends.map((backend) => ({
                    value: backend.id,
                    label: backend.label,
                    disabled: !backend.available
                  }))}
                />
              </div>

              <Alert
                showIcon
                type={readiness.status === "ready" && trainingBackendId ? "success" : "info"}
                message={
                  readiness.status === "ready" && trainingBackendId
                    ? "可以开始训练"
                    : readiness.status === "ready"
                      ? "训练方式尚未配置"
                      : "继续添加训练文章"
                }
                description={
                  readiness.status === "ready" && !trainingBackendId
                    ? "当前没有可用的系统训练方式。"
                    : authorText(readiness.recommendedNextAction)
                }
                action={(
                  <Button
                    type="primary"
                    icon={readiness.status === "ready" ? <ExperimentOutlined /> : <UploadOutlined />}
                    disabled={
                      (readiness.status === "ready" && !trainingBackendId)
                      || detail.status === "training"
                    }
                    loading={saving && detail.status === "training"}
                    onClick={readiness.status === "ready" ? confirmTraining : openUpload}
                  >
                    {detail.status === "training"
                      ? "训练中"
                      : readiness.status !== "ready"
                        ? "继续添加"
                        : trainingBackendId
                          ? "开始训练"
                          : "等待配置"}
                  </Button>
                )}
              />

              <Flex justify="space-between" align="center" gap={12}>
                <Title level={5}>训练素材</Title>
                {detail.status === "usable" ? (
                  <Button
                    type={activeBook.currentModelId === detail.id ? "default" : "primary"}
                    disabled={activeBook.currentModelId === detail.id}
                    onClick={() => void onModelChange(detail.id)}
                  >
                    {activeBook.currentModelId === detail.id ? "当前书正在使用" : "用于当前书"}
                  </Button>
                ) : null}
              </Flex>

              <List
                className="model-source-list"
                dataSource={detail.sources ?? []}
                locale={{ emptyText: "还没有训练文章。" }}
                renderItem={(source) => (
                  <List.Item
                    actions={[
                      <Button
                        key="delete"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={`删除 ${source.originalName}`}
                        onClick={() => void deleteSource(source.id)}
                      />
                    ]}
                  >
                    <List.Item.Meta
                      avatar={<FolderOpenOutlined />}
                      title={authorText(source.originalName)}
                      description={(
                        <Space wrap>
                          <Tag>{sourceFormatLabel(source.format)}</Tag>
                          <Tag color={sourceStatusColor(source.status)}>
                            {sourceStatusLabel(source.status)}
                          </Tag>
                          <Text type="secondary">{source.wordCount.toLocaleString()} 字</Text>
                          {source.reasonLabel ? <Text type="secondary">{authorText(source.reasonLabel)}</Text> : null}
                        </Space>
                      )}
                    />
                  </List.Item>
                )}
              />

              <Title level={5}>训练版本</Title>
              <List
                dataSource={detail.versions ?? []}
                locale={{ emptyText: "训练完成后会在这里生成版本。" }}
                renderItem={(version) => (
                  <List.Item>
                    <List.Item.Meta
                      title={`版本 ${version.versionNumber}`}
                      description={(
                        <Space wrap>
                          <Tag color={modelStatusColor(version.status)}>
                            {modelStatusLabel(version.status)}
                          </Tag>
                          <Text type="secondary">{version.sourceIds.length} 篇素材</Text>
                          <Text type="secondary">{formatCreatedAt(version.createdAt)}</Text>
                        </Space>
                      )}
                    />
                  </List.Item>
                )}
              />

              <Title level={5}>使用中的作品</Title>
              {(detail.usedByBooks?.length ?? 0) > 0 ? (
                <Space wrap>
                  {detail.usedByBooks?.map((bookId) => (
                    <Tag key={bookId}>
                      {authorText(books.find((book) => book.id === bookId)?.title || "已登记作品")}
                    </Tag>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">还没有作品使用这个模型。</Text>
              )}
            </Space>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个模型查看详情" />
          )}
        </Card> : null}
      </div>

      <Modal
        open={createOpen}
        title="新增模型"
        okText="创建模型"
        cancelText="取消"
        confirmLoading={saving}
        onOk={() => void createModel()}
        onCancel={() => setCreateOpen(false)}
      >
        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{ purpose: "综合模仿", categoryId: "other", description: "" }}
        >
          <Form.Item name="name" label="模型名称" rules={[{ required: true, message: "请输入模型名称。" }]}>
            <Input placeholder="例如：玄幻升级风格" maxLength={80} />
          </Form.Item>
          <Form.Item label="分类" required>
            <Flex gap={8}>
              <Form.Item name="categoryId" noStyle rules={[{ required: true, message: "请选择分类。" }]}>
                <Select
                  className="flex-1"
                  options={categories.map((category) => ({
                    value: category.id,
                    label: category.label
                  }))}
                />
              </Form.Item>
              <Button icon={<PlusOutlined />} onClick={() => setCategoryOpen(true)} aria-label="新增分类" />
            </Flex>
          </Form.Item>
          <Form.Item name="purpose" label="训练目标">
            <Segmented
              block
              options={["模仿写法", "模仿节奏", "模仿叙事风格", "综合模仿"]}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} maxLength={240} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={categoryOpen}
        title="新增分类"
        okText="创建分类"
        cancelText="取消"
        confirmLoading={saving}
        okButtonProps={{ disabled: !categoryName.trim() }}
        onOk={() => void createCategory()}
        onCancel={() => setCategoryOpen(false)}
      >
        <Input
          value={categoryName}
          onChange={(event) => setCategoryName(event.target.value)}
          placeholder="输入分类名称"
          maxLength={40}
        />
      </Modal>

      <Modal
        open={uploadOpen}
        title="上传训练文章"
        okText="添加文章"
        cancelText="关闭"
        confirmLoading={saving}
        okButtonProps={{ disabled: !uploadFiles.length }}
        onOk={() => void uploadSources()}
        onCancel={closeUpload}
      >
        <Dragger
          multiple
          accept=".txt,.docx"
          beforeUpload={() => false}
          fileList={uploadFiles}
          onChange={({ fileList }) => setUploadFiles(fileList)}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">选择或拖入 TXT、DOCX 文件</p>
        </Dragger>
      </Modal>

      <Modal
        open={bookSourceOpen}
        title="从作品选择章节"
        okText="添加章节"
        cancelText="取消"
        confirmLoading={saving}
        okButtonProps={{ disabled: !sourceChapterIds.length }}
        onOk={() => void addBookSources()}
        onCancel={() => setBookSourceOpen(false)}
      >
        <Space direction="vertical" size={16} className="wide">
          <Select
            value={sourceBook.id}
            className="wide"
            options={books.map((book) => ({ value: book.id, label: book.title }))}
            onChange={(bookId) => {
              setSourceBookId(bookId);
              setSourceChapterIds([]);
            }}
          />
          {eligibleBookChapters.length ? (
            <Checkbox.Group
              className="model-chapter-picker"
              value={sourceChapterIds}
              onChange={(values) => setSourceChapterIds(values as string[])}
              options={eligibleBookChapters.map((chapter) => ({
                value: chapter.id,
                label: `${chapter.title} · ${chapter.wordCount.toLocaleString()} 字`
              }))}
            />
          ) : (
            <Alert showIcon type="info" message="这本书还没有已完成章节。" />
          )}
        </Space>
      </Modal>
    </div>
  );
}

function modelStatusLabel(status: string) {
  const labels: Record<string, string> = {
    awaiting_sources: "待上传素材",
    collecting_sources: "继续添加素材",
    ready: "可以训练",
    training: "训练中",
    validating: "待验证",
    usable: "可使用"
  };
  return labels[status] ?? "待处理";
}

function modelStatusColor(status: string) {
  if (status === "usable") {
    return "success";
  }
  if (status === "training") {
    return "processing";
  }
  if (status === "ready") {
    return "blue";
  }
  return "default";
}

function sourceStatusLabel(status: string) {
  return status === "eligible" ? "可训练" : status === "failed" ? "解析失败" : "已跳过";
}

function sourceStatusColor(status: string) {
  return status === "eligible" ? "success" : status === "failed" ? "error" : "warning";
}

function sourceFormatLabel(format: string) {
  return format === "chapter" ? "作品章节" : format.toUpperCase();
}

function formatCreatedAt(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN");
}
