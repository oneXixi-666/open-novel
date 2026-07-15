import { useEffect, useRef, useState } from "react";
import { Modal, message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import { materialDetailLabels } from "../domain/bookWorkspace";
import type { Chapter, Material, MaterialAiSuggestion, MaterialSaveAction, MaterialType } from "../types";
import { authorText } from "../utils/authorText";

type AiMode = "new" | "improve" | "advice";
type SideMode = "detail" | "edit" | "ai";

export function useLibraryMaterialWorkflow({
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
  resetKey
}: {
  bookId: string;
  activeChapter: Chapter;
  materialType: MaterialType;
  materials: Material[];
  activeMaterial?: Material;
  visibleMaterial?: Material;
  onMaterialChange: (id: string) => void;
  onCreateMaterial: (material: Omit<Material, "bookId"> & { bookId?: string }) => void | Promise<void>;
  onUpdateMaterial: (material: Material) => void | Promise<void>;
  onDeleteMaterial: (materialId: string) => void | Promise<void>;
  materialSaveAction: MaterialSaveAction;
  resetKey: string;
}) {
  const contextRef = useRef({ bookId, chapterId: activeChapter.id, materialType, materialId: activeMaterial?.id ?? "" });
  const materialAiRequestRef = useRef(0);
  const [editorMode, setEditorMode] = useState<"create" | "edit" | null>(null);
  const [sideMode, setSideMode] = useState<SideMode>("detail");
  const [editingMaterial, setEditingMaterial] = useState<Material | null>(null);
  const [aiSeed, setAiSeed] = useState("");
  const [aiSuggestion, setAiSuggestion] = useState<MaterialAiSuggestion | null>(null);
  const [lastAiMode, setLastAiMode] = useState<AiMode>("new");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftSummary, setDraftSummary] = useState("");
  const [draftInfluence, setDraftInfluence] = useState("");
  const [draftRelated, setDraftRelated] = useState("");
  const [draftDetailA, setDraftDetailA] = useState("");
  const [draftDetailB, setDraftDetailB] = useState("");
  const [draftDetailC, setDraftDetailC] = useState("");
  const [draftConfidence, setDraftConfidence] = useState(60);
  const [formError, setFormError] = useState("");
  const [materialActionError, setMaterialActionError] = useState("");
  const [agentAction, setAgentAction] = useState<string | null>(null);

  useEffect(() => {
    contextRef.current = { bookId, chapterId: activeChapter.id, materialType, materialId: activeMaterial?.id ?? "" };
  }, [activeMaterial?.id, activeChapter.id, bookId, materialType]);

  useEffect(() => {
    materialAiRequestRef.current += 1;
    setAiSuggestion(null);
    setAgentAction(null);
  }, [resetKey]);

  const editorSaveLoading = editorMode === "create"
    ? materialSaveAction?.type === "create"
    : Boolean(editingMaterial && materialSaveAction?.type === "update" && materialSaveAction.materialId === editingMaterial.id);
  const aiApplyLoading = aiSuggestion?.targetId
    ? materialSaveAction?.type === "update" && materialSaveAction.materialId === aiSuggestion.targetId
    : materialSaveAction?.type === "create";

  async function createAiSuggestion(mode: AiMode) {
    const target = mode === "new" ? undefined : visibleMaterial;
    const requestId = materialAiRequestRef.current + 1;
    const requestKey = target
      ? materialAiRequestKey(bookId, activeChapter.id, materialType, target.id)
      : materialAiScopeRequestKey(bookId, activeChapter.id, materialType);
    const isCurrentRequest = () => isCurrentMaterialAiRequest(contextRef.current, requestKey, Boolean(target)) && materialAiRequestRef.current === requestId;
    materialAiRequestRef.current = requestId;
    setSideMode("ai");
    setLastAiMode(mode);
    setAgentAction(mode);
    setMaterialActionError("");
    try {
      const response = await workbenchClient.runAgentAssist({
        bookId,
        scope: "material",
        action: mode === "new" ? "新建资料" : mode === "improve" ? "优化资料" : "提出资料建议",
        input: aiSeed,
        materialId: target?.id,
        materialType,
        currentMaterial: target
      });
      if (!response.material) {
        if (!isCurrentRequest()) {
          return;
        }
        setAiSuggestion(null);
        setMaterialActionError("AI 暂时没有返回可应用的资料候选，请调整想法后再试。");
        return;
      }
      if (!isCurrentRequest()) {
        return;
      }
      setAiSuggestion({
        targetId: target?.id,
        type: response.material.type,
        title: response.material.title,
        summary: response.material.summary,
        influence: response.material.influence,
        details: response.material.details ?? {}
      });
      message.success(mode === "new" ? `AI 已生成${materialType}候选。` : "AI 已生成可应用的优化建议。");
    } catch (error) {
      if (isCurrentRequest()) {
        setMaterialActionError(authorText(error instanceof Error ? error.message : "AI 资料生成失败，请稍后重试。"));
      }
    } finally {
      if (isCurrentRequest()) {
        setAgentAction(null);
      }
    }
  }

  function isMaterialAiActionDisabled(mode: AiMode) {
    return Boolean((agentAction && agentAction !== mode) || aiApplyLoading);
  }

  async function applyAiSuggestion() {
    if (!aiSuggestion) {
      message.warning("请先生成 AI 建议。");
      return;
    }
    const requestKey = aiSuggestion.targetId
      ? materialAiRequestKey(bookId, activeChapter.id, materialType, aiSuggestion.targetId)
      : materialAiScopeRequestKey(bookId, activeChapter.id, materialType);
    const isCurrentRequest = () =>
      aiSuggestion.targetId
        ? currentMaterialAiRequestKey(contextRef.current) === requestKey
        : currentMaterialAiScopeRequestKey(contextRef.current) === requestKey;
    setMaterialActionError("");
    if (aiSuggestion.targetId) {
      const target = materials.find((item) => item.id === aiSuggestion.targetId);
      if (!target) {
        message.warning("当前资料已不存在。");
        return;
      }
      try {
        await onUpdateMaterial({
          ...target,
          summary: aiSuggestion.summary,
          influence: aiSuggestion.influence,
          confidence: Math.min(100, target.confidence + 10),
          details: {
            ...target.details,
            ...aiSuggestion.details
          }
        });
      } catch (error) {
        if (isCurrentRequest()) {
          setMaterialActionError(authorText(error instanceof Error ? error.message : "AI 资料建议应用失败，请稍后重试。"));
        }
        return;
      }
    } else {
      try {
        await onCreateMaterial({
          id: "",
          type: aiSuggestion.type,
          title: aiSuggestion.title,
          summary: aiSuggestion.summary,
          influence: aiSuggestion.influence,
          related: ["当前章节", "AI 候选"],
          confidence: 72,
          details: aiSuggestion.details
        });
      } catch (error) {
        if (isCurrentRequest()) {
          setMaterialActionError(authorText(error instanceof Error ? error.message : "AI 资料建议应用失败，请稍后重试。"));
        }
        return;
      }
    }
    if (!isCurrentRequest()) {
      return;
    }
    setAiSuggestion(null);
    setAiSeed("");
  }

  function openCreateEditor() {
    setEditingMaterial(null);
    setDraftTitle("");
    setDraftSummary("");
    setDraftInfluence("");
    setDraftRelated(`当前章节, ${activeChapter.title}`);
    setDraftDetailA("");
    setDraftDetailB("");
    setDraftDetailC("");
    setDraftConfidence(60);
    setFormError("");
    setMaterialActionError("");
    setEditorMode("create");
    setSideMode("edit");
  }

  function openUpdateEditor(material: Material) {
    onMaterialChange(material.id);
    setEditingMaterial(material);
    setDraftTitle(material.title);
    setDraftSummary(material.summary);
    setDraftInfluence(material.influence);
    setDraftRelated(material.related.join(", "));
    const [labelA, labelB, labelC] = materialDetailLabels[material.type];
    setDraftDetailA(material.details?.[labelA] ?? "");
    setDraftDetailB(material.details?.[labelB] ?? "");
    setDraftDetailC(material.details?.[labelC] ?? "");
    setDraftConfidence(material.confidence);
    setFormError("");
    setMaterialActionError("");
    setEditorMode("edit");
    setSideMode("edit");
  }

  async function saveMaterial() {
    if (!draftTitle.trim()) {
      setFormError("先填写资料名称。");
      return;
    }
    setFormError("");
    setMaterialActionError("");
    if (editingMaterial) {
      const [labelA, labelB, labelC] = materialDetailLabels[editingMaterial.type];
      try {
        await onUpdateMaterial({
          ...editingMaterial,
          title: draftTitle.trim(),
          summary: draftSummary.trim() || editingMaterial.summary,
          influence: draftInfluence.trim() || editingMaterial.influence,
          related: parseRelated(draftRelated, editingMaterial.related),
          confidence: normalizeConfidence(draftConfidence),
          details: {
            ...editingMaterial.details,
            [labelA]: draftDetailA.trim(),
            [labelB]: draftDetailB.trim(),
            [labelC]: draftDetailC.trim()
          }
        });
      } catch (error) {
        setFormError(authorText(error instanceof Error ? error.message : "资料保存失败，请稍后重试。"));
        return;
      }
    } else {
      const [labelA, labelB, labelC] = materialDetailLabels[materialType];
      try {
        await onCreateMaterial({
          id: "",
          type: materialType,
          title: draftTitle.trim(),
          summary: draftSummary.trim() || "待继续补全的资料。",
          influence: draftInfluence.trim() || "AI 将根据当前章节继续补全它的作用。",
          related: parseRelated(draftRelated, ["当前章节", activeChapter.title]),
          confidence: normalizeConfidence(draftConfidence),
          details: {
            [labelA]: draftDetailA.trim(),
            [labelB]: draftDetailB.trim(),
            [labelC]: draftDetailC.trim()
          }
        });
      } catch (error) {
        setFormError(authorText(error instanceof Error ? error.message : "资料保存失败，请稍后重试。"));
        return;
      }
    }
    setEditorMode(null);
    setSideMode("detail");
  }

  function removeMaterial(material: Material) {
    Modal.confirm({
      title: authorText(`删除资料：${material.title}`),
      content: "删除后会同步清理章节里引用它的资料，且不可恢复。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setMaterialActionError("");
        try {
          await onDeleteMaterial(material.id);
        } catch (error) {
          setMaterialActionError(authorText(error instanceof Error ? error.message : "资料删除失败，请稍后重试。"));
        }
      }
    });
  }

  function backToDetail() {
    setEditorMode(null);
    setSideMode("detail");
  }

  return {
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
  };
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

function materialAiRequestKey(bookId: string, chapterId: string, type: MaterialType, materialId: string) {
  return `${bookId}:${chapterId}:${type}:${materialId}`;
}

function materialAiScopeRequestKey(bookId: string, chapterId: string, type: MaterialType) {
  return `${bookId}:${chapterId}:${type}`;
}

function currentMaterialAiRequestKey(context: { bookId: string; chapterId: string; materialType: MaterialType; materialId: string }) {
  return materialAiRequestKey(context.bookId, context.chapterId, context.materialType, context.materialId);
}

function currentMaterialAiScopeRequestKey(context: { bookId: string; chapterId: string; materialType: MaterialType }) {
  return materialAiScopeRequestKey(context.bookId, context.chapterId, context.materialType);
}

function isCurrentMaterialAiRequest(
  context: { bookId: string; chapterId: string; materialType: MaterialType; materialId: string },
  requestKey: string,
  hasTarget: boolean
) {
  return hasTarget
    ? currentMaterialAiRequestKey(context) === requestKey
    : currentMaterialAiScopeRequestKey(context) === requestKey;
}
