import type { Dispatch, RefObject, SetStateAction } from "react";
import { message } from "antd";
import { workbenchClient } from "../api/workbenchClient";
import {
  prependMaterial,
  removeMaterial,
  replaceChaptersInBooks,
  replaceMaterial
} from "../domain/workbenchActions";
import type { Book, Material, MaterialType } from "../types";
import { authorText } from "../utils/authorText";

export function useWorkbenchMaterials({
  activeBook,
  activeBookIdRef,
  materials,
  setBooks,
  setMaterials,
  setActiveMaterialId,
  setMaterialType,
  runAction,
  syncBookWorkspaceAfterWrite
}: {
  activeBook: Book;
  activeBookIdRef: RefObject<string>;
  materials: Material[];
  setBooks: Dispatch<SetStateAction<Book[]>>;
  setMaterials: Dispatch<SetStateAction<Material[]>>;
  setActiveMaterialId: Dispatch<SetStateAction<string>>;
  setMaterialType: Dispatch<SetStateAction<MaterialType>>;
  runAction: <T>(key: string, action: () => Promise<T>, options?: { shouldReportError?: () => boolean }) => Promise<T>;
  syncBookWorkspaceAfterWrite: (bookId: string, options?: {
    preferredChapterId?: string;
    preferredMaterialId?: string;
    preferredReviewId?: string;
  }, fallback?: () => void) => Promise<void>;
}) {
  async function createMaterial(material: Material) {
    const requestBookId = material.bookId;
    const { material: createdMaterial } = await runAction(
      "material-create",
      () => workbenchClient.createMaterial(material),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(createdMaterial.bookId, {
      preferredMaterialId: createdMaterial.id
    }, () => {
      setMaterials((current) => prependMaterial(current, createdMaterial));
    });
    if (activeBookIdRef.current !== createdMaterial.bookId) {
      return;
    }
    setMaterialType(createdMaterial.type);
    setActiveMaterialId(createdMaterial.id);
    message.success(authorText(`已新增${createdMaterial.type}：${createdMaterial.title}`));
  }

  async function updateMaterial(material: Material) {
    const requestBookId = material.bookId;
    const { material: updatedMaterial } = await runAction(
      `material-update-${material.id}`,
      () => workbenchClient.updateMaterial(material),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(updatedMaterial.bookId, {
      preferredMaterialId: updatedMaterial.id
    }, () => {
      setMaterials((current) => replaceMaterial(current, updatedMaterial));
    });
    if (activeBookIdRef.current !== updatedMaterial.bookId) {
      return;
    }
    setActiveMaterialId(updatedMaterial.id);
    message.success(authorText(`已更新${updatedMaterial.type}：${updatedMaterial.title}`));
  }

  async function deleteMaterial(materialId: string) {
    const target = materials.find((item) => item.id === materialId);
    if (!target) {
      return;
    }
    const requestBookId = activeBook.id;
    const result = await runAction(
      `material-delete-${materialId}`,
      () => workbenchClient.deleteMaterial(requestBookId, materialId),
      { shouldReportError: () => activeBookIdRef.current === requestBookId }
    );
    await syncBookWorkspaceAfterWrite(result.bookId, {}, () => {
      setMaterials((current) => removeMaterial(current, materialId));
      if (result.affectedChapters.length) {
        setBooks((current) =>
          replaceChaptersInBooks(current, result.bookId, result.affectedChapters)
        );
      }
    });
    if (activeBookIdRef.current !== result.bookId) {
      return;
    }
    setActiveMaterialId((current) => (current === materialId ? "" : current));
    message.success(authorText(result.summary || `已删除资料：${target.title}`));
  }

  return {
    createMaterial,
    updateMaterial,
    deleteMaterial
  };
}
