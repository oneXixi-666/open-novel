from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from open_novel.agents.process_control import run_cancellable_process
from open_novel.core.workspace_registry import WorkspaceRegistryService

DEFAULT_MODEL_CATEGORIES = (
    ("fantasy", "玄幻"),
    ("urban", "都市"),
    ("romance", "言情"),
    ("mystery", "悬疑"),
    ("history", "历史"),
    ("science-fiction", "科幻"),
    ("other", "其他"),
)

BUILTIN_MODEL_TEMPLATES = (
    {
        "id": "fantasy-progression",
        "name": "东方玄幻升级流",
        "categoryId": "fantasy",
        "genre": "东方玄幻",
        "style": "热血爽快",
        "purpose": "模仿节奏",
        "description": "强化升级反馈、阶段目标、冲突递进和章末钩子。",
    },
    {
        "id": "xianxia-cultivation",
        "name": "仙侠修真成长流",
        "categoryId": "fantasy",
        "genre": "仙侠修真",
        "style": "古典沉浸",
        "purpose": "模仿叙事风格",
        "description": "侧重修行体系、意境表达、人物心境和长线成长。",
    },
    {
        "id": "urban-superpower",
        "name": "都市异能爽文",
        "categoryId": "urban",
        "genre": "都市异能",
        "style": "快节奏爽文",
        "purpose": "综合模仿",
        "description": "突出快速入局、能力展示、现实冲突和连续回报。",
    },
    {
        "id": "urban-workplace",
        "name": "都市现实职场",
        "categoryId": "urban",
        "genre": "都市职场",
        "style": "克制写实",
        "purpose": "模仿写法",
        "description": "强调真实职业细节、人物关系、选择代价和生活质感。",
    },
    {
        "id": "modern-romance",
        "name": "现代甜宠言情",
        "categoryId": "romance",
        "genre": "现代言情",
        "style": "轻松细腻",
        "purpose": "模仿叙事风格",
        "description": "突出情绪互动、关系推进、生活细节和轻松对话。",
    },
    {
        "id": "historical-romance",
        "name": "古代权谋言情",
        "categoryId": "romance",
        "genre": "古代言情",
        "style": "克制拉扯",
        "purpose": "综合模仿",
        "description": "兼顾情感张力、身份约束、利益博弈和人物成长。",
    },
    {
        "id": "classic-mystery",
        "name": "本格悬疑推理",
        "categoryId": "mystery",
        "genre": "悬疑推理",
        "style": "线索严密",
        "purpose": "模仿节奏",
        "description": "强调公平线索、误导控制、推理推进和真相回收。",
    },
    {
        "id": "social-crime",
        "name": "社会派罪案",
        "categoryId": "mystery",
        "genre": "现实罪案",
        "style": "冷峻现实",
        "purpose": "模仿写法",
        "description": "侧重案件背后的社会关系、人物动机和现实压力。",
    },
    {
        "id": "historical-conquest",
        "name": "历史争霸群像",
        "categoryId": "history",
        "genre": "历史争霸",
        "style": "宏大厚重",
        "purpose": "综合模仿",
        "description": "强化势力博弈、战争推进、群像塑造和时代氛围。",
    },
    {
        "id": "historical-slice-of-life",
        "name": "历史日常种田",
        "categoryId": "history",
        "genre": "历史生活",
        "style": "温和生活流",
        "purpose": "模仿写法",
        "description": "突出生产经营、日常关系、时代细节和稳定成长。",
    },
    {
        "id": "hard-science-fiction",
        "name": "硬科幻探索",
        "categoryId": "science-fiction",
        "genre": "硬科幻",
        "style": "理性克制",
        "purpose": "模仿叙事风格",
        "description": "侧重科学设定、探索过程、认知冲击和严谨表达。",
    },
    {
        "id": "post-apocalyptic",
        "name": "末日生存科幻",
        "categoryId": "science-fiction",
        "genre": "末日生存",
        "style": "高压快节奏",
        "purpose": "模仿节奏",
        "description": "强化资源压力、生存决策、团队冲突和连续危机。",
    },
    {
        "id": "light-novel-daily",
        "name": "轻小说日常",
        "categoryId": "other",
        "genre": "轻小说",
        "style": "轻快对话",
        "purpose": "模仿写法",
        "description": "突出角色辨识度、轻快对白、日常事件和情绪反差。",
    },
    {
        "id": "folk-horror",
        "name": "民俗恐怖怪谈",
        "categoryId": "other",
        "genre": "恐怖怪谈",
        "style": "阴冷留白",
        "purpose": "模仿叙事风格",
        "description": "强调民俗规则、未知压迫、细节暗示和克制留白。",
    },
)

TRAINING_BACKEND_DEFINITIONS = (
    ("system", "系统默认", "OPEN_NOVEL_TRAIN_COMMAND"),
    ("mlx-lm", "MLX-LM", "OPEN_NOVEL_MLX_TRAIN_COMMAND"),
    ("llama-factory", "LLaMA Factory", "OPEN_NOVEL_LLAMA_FACTORY_TRAIN_COMMAND"),
)


class ModelLibraryService:
    max_file_bytes = 5 * 1024 * 1024
    max_batch_bytes = 20 * 1024 * 1024
    min_source_characters = 500

    def __init__(
        self,
        db_path: Path | None = None,
        library_root: Path | None = None,
    ) -> None:
        self.db_path = (db_path or WorkspaceRegistryService.default_registry_path()).resolve()
        self.library_root = (
            library_root or self.db_path.parent / "model-library"
        ).resolve()
        self._ensure_schema()

    def list_categories(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, label, is_builtin, created_at, updated_at
                FROM model_categories
                ORDER BY is_builtin DESC, label ASC
                """
            ).fetchall()
        return [self._category_payload(row) for row in rows]

    def list_templates(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, category_id, genre, style, purpose, description
                FROM model_templates
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "categoryId": str(row["category_id"]),
                "genre": str(row["genre"]),
                "style": str(row["style"]),
                "purpose": str(row["purpose"]),
                "description": str(row["description"]),
            }
            for row in rows
        ]

    def list_training_backends(self) -> list[dict[str, Any]]:
        configured = [
            {
                "id": backend_id,
                "label": label,
                "available": bool(os.environ.get(env_name, "").strip()),
                "recommended": False,
            }
            for backend_id, label, env_name in TRAINING_BACKEND_DEFINITIONS
        ]
        available_count = sum(item["available"] for item in configured)
        return [
            {
                "id": "auto",
                "label": "自动选择",
                "available": available_count > 0,
                "recommended": True,
            },
            *configured,
        ]

    def create_category(self, label: str) -> dict[str, Any]:
        value = label.strip()
        if not value:
            raise ValueError("分类名称不能为空。")
        now = self._now()
        category_id = f"category-{uuid4().hex[:12]}"
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO model_categories (id, label, is_builtin, created_at, updated_at)
                    VALUES (?, ?, 0, ?, ?)
                    """,
                    (category_id, value, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个模型分类已经存在。") from exc
        return self.get_category(category_id)

    def get_category(self, category_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, label, is_builtin, created_at, updated_at
                FROM model_categories
                WHERE id = ?
                """,
                (category_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"missing model category: {category_id}")
        return self._category_payload(row)

    def create_model(
        self,
        *,
        name: str,
        category_id: str,
        purpose: str,
        description: str = "",
    ) -> dict[str, Any]:
        model_name = name.strip()
        if not model_name:
            raise ValueError("模型名称不能为空。")
        self.get_category(category_id)
        now = self._now()
        model_id = f"model-{uuid4().hex[:12]}"
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO model_library (
                        id, name, category_id, purpose, description, status,
                        active_version_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'awaiting_sources', '', ?, ?)
                    """,
                    (
                        model_id,
                        model_name,
                        category_id,
                        purpose.strip() or "综合模仿",
                        description.strip(),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个模型名称已经存在。") from exc
        return self.get_model(model_id)

    def list_models(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._model_select_sql() + " ORDER BY m.updated_at DESC"
            ).fetchall()
        return [self._model_payload(row) for row in rows]

    def get_model(self, model_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                self._model_select_sql("WHERE m.id = ?"),
                (model_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"missing model: {model_id}")
        model = self._model_payload(row)
        model["sources"] = self.list_sources(model_id)
        model["versions"] = self.list_versions(model_id)
        model["usedByBooks"] = self.list_model_books(model_id)
        return model

    def add_uploaded_source(
        self,
        model_id: str,
        *,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        self.get_model(model_id)
        if len(content) > self.max_file_bytes:
            raise ValueError(f"{filename} 超过单文件 5 MB 限制。")
        suffix = Path(filename).suffix.lower()
        if suffix == ".txt":
            text = self._decode_txt(content)
            source_format = "txt"
        elif suffix == ".docx":
            text = self._decode_docx(content)
            source_format = "docx"
        else:
            raise ValueError(f"{filename} 不是支持的 TXT 或 DOCX 文件。")
        return self._add_source(
            model_id,
            source_type="upload",
            source_book_id="",
            source_chapter_id="",
            original_name=Path(filename).name,
            source_format=source_format,
            text=text,
        )

    def add_book_chapter_source(
        self,
        model_id: str,
        *,
        book_id: str,
        chapter_id: str,
        label: str,
        text: str,
    ) -> dict[str, Any]:
        self.get_model(model_id)
        return self._add_source(
            model_id,
            source_type="book_chapter",
            source_book_id=book_id,
            source_chapter_id=chapter_id,
            original_name=label,
            source_format="chapter",
            text=text,
        )

    def list_sources(self, model_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, model_id, source_type, source_book_id, source_chapter_id,
                       original_name, format, stored_path, sha256, word_count,
                       status, reason_code, reason_label, created_at
                FROM model_training_sources
                WHERE model_id = ?
                ORDER BY created_at DESC
                """,
                (model_id,),
            ).fetchall()
        return [self._source_payload(row) for row in rows]

    def delete_source(self, model_id: str, source_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT stored_path FROM model_training_sources
                WHERE id = ? AND model_id = ?
                """,
                (source_id, model_id),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"missing training source: {source_id}")
            conn.execute(
                "DELETE FROM model_training_sources WHERE id = ? AND model_id = ?",
                (source_id, model_id),
            )
            self._refresh_model_status(conn, model_id)
        return self.get_model(model_id)

    def readiness(self, model_id: str) -> dict[str, Any]:
        model = self.get_model(model_id)
        sources = model["sources"]
        eligible = [item for item in sources if item["status"] == "eligible"]
        skipped = [item for item in sources if item["status"] != "eligible"]
        minimum = 20
        status = "ready" if len(eligible) >= minimum else "block"
        return {
            "modelId": model_id,
            "status": status,
            "eligibleCount": len(eligible),
            "skippedCount": len(skipped),
            "totalCharacters": sum(int(item["wordCount"]) for item in eligible),
            "minRecommendedExamples": minimum,
            "items": sources,
            "recommendedNextAction": (
                "训练素材已经准备完成，可以开始训练。"
                if status == "ready"
                else f"还需要 {minimum - len(eligible)} 篇合格文章。"
            ),
        }

    def run_training(
        self,
        model_id: str,
        *,
        source_ids: list[str] | None = None,
        backend_id: str = "auto",
        timeout_seconds: int = 3600,
        cancel_check: Any = None,
    ) -> dict[str, Any]:
        model = self.get_model(model_id)
        requested_ids = {item.strip() for item in (source_ids or []) if item.strip()}
        eligible = [
            item
            for item in model["sources"]
            if item["status"] == "eligible"
            and (not requested_ids or item["id"] in requested_ids)
        ]
        if len(eligible) < 20:
            raise ValueError(f"当前只有 {len(eligible)} 篇合格文章，至少需要 20 篇。")
        version_id = f"version-{uuid4().hex[:12]}"
        run_id = f"training-{uuid4().hex[:12]}"
        records: list[str] = []
        source_texts = self._source_texts([item["id"] for item in eligible])
        for source in eligible:
            text = source_texts.get(source["id"], "")
            if not text:
                raise ValueError(f"训练素材正文不存在：{source['originalName']}")
            records.append(
                json.dumps(
                    {
                        "prompt": "请按照训练素材中的写法完成下面的正文。",
                        "completion": text,
                        "metadata": {
                            "sourceId": source["id"],
                            "sourceName": source["originalName"],
                        },
                    },
                    ensure_ascii=False,
                )
            )
        base_model = os.environ.get("OPEN_NOVEL_BASE_MODEL", "").strip()
        resolved_backend_id, train_template = self._resolve_training_backend(backend_id)
        infer_template = os.environ.get("OPEN_NOVEL_INFER_COMMAND", "").strip()
        self.library_root.mkdir(parents=True, exist_ok=True)
        version_root = self.library_root / model_id / "versions" / version_id
        version_root.mkdir(parents=True, exist_ok=True)
        output_dir = version_root / "artifact"
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="open-novel-training-",
            dir=self.library_root,
        ) as temp_dir:
            dataset_path = Path(temp_dir) / "training.jsonl"
            dataset_path.write_text("\n".join(records) + "\n", encoding="utf-8")
            command = self._training_command(
                train_template,
                dataset_path=dataset_path,
                output_dir=output_dir,
                base_model=base_model,
                model_id=model_id,
                version_id=version_id,
            )
            now = self._now()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO model_versions (
                        id, model_id, version_number, status, source_snapshot,
                        artifact_path, base_model_ref, inference_template, backend_id,
                        training_run_id, created_at
                    ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        model_id,
                        self._next_version_number(conn, model_id),
                        json.dumps([item["id"] for item in eligible]),
                        output_dir.relative_to(self.library_root).as_posix(),
                        base_model,
                        infer_template,
                        resolved_backend_id,
                        run_id,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO model_training_runs (
                        id, model_id, version_id, status, dataset_path,
                        backend_id, command_preview, message, created_at, updated_at
                    ) VALUES (?, ?, ?, 'running', '', ?, ?, '', ?, ?)
                    """,
                    (
                        run_id,
                        model_id,
                        version_id,
                        resolved_backend_id,
                        " ".join(shlex.quote(item) for item in command),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE model_library SET status = 'training', updated_at = ? WHERE id = ?",
                    (now, model_id),
                )
            if not command:
                message = "系统尚未配置默认训练能力，请先配置 OPEN_NOVEL_TRAIN_COMMAND。"
                self._finish_training(model_id, version_id, run_id, "failed", message)
                raise ValueError(message)
            completed = run_cancellable_process(
                command,
                cwd=self.library_root,
                timeout_seconds=max(1, timeout_seconds),
                cancel_check=cancel_check,
            )
        if completed["cancelled"]:
            status = "cancelled"
            message = "训练任务已取消。"
        elif completed["timedOut"]:
            status = "failed"
            message = "训练任务超时。"
        elif int(completed["exitCode"]) != 0:
            status = "failed"
            message = str(completed["stderr"] or "默认训练任务执行失败")[-2000:]
        else:
            status = "usable" if infer_template else "validating"
            message = (
                "训练完成，模型版本已生成。"
                if infer_template
                else "训练完成，但系统尚未配置默认推理能力，模型暂不能用于作品。"
            )
        self._finish_training(model_id, version_id, run_id, status, message)
        return {
            "modelId": model_id,
            "versionId": version_id,
            "runId": run_id,
            "status": status,
            "message": message,
        }

    def list_versions(self, model_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, model_id, version_number, status, source_snapshot,
                       artifact_path, base_model_ref, inference_template,
                       backend_id, training_run_id, created_at
                FROM model_versions
                WHERE model_id = ?
                ORDER BY version_number DESC
                """,
                (model_id,),
            ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "modelId": str(row["model_id"]),
                "versionNumber": int(row["version_number"]),
                "status": str(row["status"]),
                "sourceIds": json.loads(str(row["source_snapshot"] or "[]")),
                "artifactPath": str(row["artifact_path"] or ""),
                "baseModel": str(row["base_model_ref"] or ""),
                "inferenceTemplate": str(row["inference_template"] or ""),
                "backendId": str(row["backend_id"] or ""),
                "trainingRunId": str(row["training_run_id"] or ""),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    def runtime_profile(self, model_id: str) -> dict[str, str]:
        model = self.get_model(model_id)
        active_version_id = str(model.get("activeVersionId") or "")
        version = next(
            (
                item
                for item in model["versions"]
                if item["id"] == active_version_id and item["status"] == "usable"
            ),
            None,
        )
        if version is None:
            raise ValueError("模型还没有可使用的训练版本。")
        inference_template = str(version.get("inferenceTemplate") or "").strip()
        if not inference_template:
            raise ValueError("模型还没有配置可用的推理能力。")
        artifact_path = (self.library_root / str(version["artifactPath"])).resolve()
        if not artifact_path.is_relative_to(self.library_root):
            raise ValueError("模型产物路径无效。")
        return {
            "profileId": model_id,
            "label": str(model["name"]),
            "baseModel": str(version.get("baseModel") or ""),
            "adapterPath": artifact_path.as_posix(),
            "commandTemplate": inference_template,
            "trainingRunPath": f"workspace:{version['trainingRunId']}",
        }

    def set_book_selection(
        self,
        *,
        book_id: str,
        model_id: str,
        model_version_id: str = "",
    ) -> dict[str, str]:
        if model_id:
            self.get_model(model_id)
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO book_model_selections (
                    book_id, model_id, model_version_id, selected_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    model_id = excluded.model_id,
                    model_version_id = excluded.model_version_id,
                    selected_at = excluded.selected_at
                """,
                (book_id, model_id, model_version_id, now),
            )
        return {
            "bookId": book_id,
            "modelId": model_id,
            "modelVersionId": model_version_id,
        }

    def get_book_selection(self, book_id: str) -> dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT book_id, model_id, model_version_id
                FROM book_model_selections
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
        if row is None:
            return {"bookId": book_id, "modelId": "", "modelVersionId": ""}
        return {
            "bookId": str(row["book_id"]),
            "modelId": str(row["model_id"] or ""),
            "modelVersionId": str(row["model_version_id"] or ""),
        }

    def list_model_books(self, model_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT book_id FROM book_model_selections
                WHERE model_id = ?
                ORDER BY selected_at DESC
                """,
                (model_id,),
            ).fetchall()
        return [str(row["book_id"]) for row in rows]

    def _add_source(
        self,
        model_id: str,
        *,
        source_type: str,
        source_book_id: str,
        source_chapter_id: str,
        original_name: str,
        source_format: str,
        text: str,
    ) -> dict[str, Any]:
        normalized = self._normalize_text(text)
        source_id = f"source-{uuid4().hex[:12]}"
        created_at = self._now()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""
        word_count = len("".join(normalized.split()))
        status = "eligible"
        reason_code = ""
        reason_label = ""
        if not normalized:
            status = "failed"
            reason_code = "empty_content"
            reason_label = "没有读取到正文内容"
        elif word_count < self.min_source_characters:
            status = "skipped"
            reason_code = "too_short"
            reason_label = f"正文少于 {self.min_source_characters} 字"
        elif self._duplicate_source(model_id, digest):
            status = "skipped"
            reason_code = "duplicate"
            reason_label = "与已有训练素材重复"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_training_sources (
                    id, model_id, source_type, source_book_id, source_chapter_id,
                    original_name, format, stored_path, content, sha256, word_count,
                    status, reason_code, reason_label, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    model_id,
                    source_type,
                    source_book_id,
                    source_chapter_id,
                    original_name,
                    source_format,
                    normalized,
                    digest,
                    word_count,
                    status,
                    reason_code,
                    reason_label,
                    created_at,
                ),
            )
            self._refresh_model_status(conn, model_id)
        return next(item for item in self.list_sources(model_id) if item["id"] == source_id)

    def _source_texts(self, source_ids: list[str]) -> dict[str, str]:
        if not source_ids:
            return {}
        placeholders = ",".join("?" for _ in source_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, content
                FROM model_training_sources
                WHERE id IN ({placeholders})
                """,
                source_ids,
            ).fetchall()
        return {str(row["id"]): str(row["content"] or "") for row in rows}

    def _duplicate_source(self, model_id: str, digest: str) -> bool:
        if not digest:
            return False
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM model_training_sources
                WHERE model_id = ? AND sha256 = ? AND status = 'eligible'
                LIMIT 1
                """,
                (model_id, digest),
            ).fetchone()
        return row is not None

    def _refresh_model_status(self, conn: sqlite3.Connection, model_id: str) -> None:
        eligible_count = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM model_training_sources
                WHERE model_id = ? AND status = 'eligible'
                """,
                (model_id,),
            ).fetchone()[0]
        )
        status = "ready" if eligible_count >= 20 else (
            "collecting_sources" if eligible_count else "awaiting_sources"
        )
        conn.execute(
            "UPDATE model_library SET status = ?, updated_at = ? WHERE id = ?",
            (status, self._now(), model_id),
        )

    def _decode_txt(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030", "big5"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("TXT 文件编码无法识别，请转换为 UTF-8 后重试。")

    def _decode_docx(self, content: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                document_info = archive.getinfo("word/document.xml")
                if document_info.file_size > 20 * 1024 * 1024:
                    raise ValueError("DOCX 正文体积过大，无法作为训练素材。")
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ValueError("DOCX 文件损坏或不是有效的 Word 文档。") from exc
        root = ElementTree.fromstring(document_xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs: list[str] = []
        for paragraph in root.iter(f"{namespace}p"):
            text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
            if text.strip():
                paragraphs.append(text.strip())
        return "\n\n".join(paragraphs)

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in normalized.split("\n")]
        return "\n".join(lines).strip()

    def _model_select_sql(self, where_clause: str = "") -> str:
        return f"""
            SELECT
                m.id, m.name, m.category_id, c.label AS category_label,
                m.purpose, m.description, m.status, m.active_version_id,
                m.created_at, m.updated_at,
                COUNT(s.id) AS source_count,
                COALESCE(SUM(CASE WHEN s.status = 'eligible' THEN 1 ELSE 0 END), 0)
                    AS eligible_count,
                COALESCE(SUM(CASE WHEN s.status = 'eligible' THEN s.word_count ELSE 0 END), 0)
                    AS total_characters
            FROM model_library m
            JOIN model_categories c ON c.id = m.category_id
            LEFT JOIN model_training_sources s ON s.model_id = m.id
            {where_clause}
            GROUP BY m.id
        """

    def _model_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "categoryId": str(row["category_id"]),
            "categoryLabel": str(row["category_label"]),
            "purpose": str(row["purpose"]),
            "description": str(row["description"] or ""),
            "visibility": "workspace",
            "status": str(row["status"]),
            "activeVersionId": str(row["active_version_id"] or ""),
            "sourceCount": int(row["source_count"] or 0),
            "eligibleCount": int(row["eligible_count"] or 0),
            "totalCharacters": int(row["total_characters"] or 0),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    def _category_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "builtin": bool(row["is_builtin"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    def _source_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "modelId": str(row["model_id"]),
            "sourceType": str(row["source_type"]),
            "sourceBookId": str(row["source_book_id"] or ""),
            "sourceChapterId": str(row["source_chapter_id"] or ""),
            "originalName": str(row["original_name"]),
            "format": str(row["format"]),
            "storedPath": str(row["stored_path"] or ""),
            "wordCount": int(row["word_count"] or 0),
            "status": str(row["status"]),
            "reasonCode": str(row["reason_code"] or ""),
            "reasonLabel": str(row["reason_label"] or ""),
            "createdAt": str(row["created_at"]),
        }

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_categories (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL UNIQUE,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_library (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    category_id TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'awaiting_sources',
                    active_version_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(category_id) REFERENCES model_categories(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category_id TEXT NOT NULL,
                    genre TEXT NOT NULL,
                    style TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    is_builtin INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(category_id) REFERENCES model_categories(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_training_sources (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_book_id TEXT NOT NULL DEFAULT '',
                    source_chapter_id TEXT NOT NULL DEFAULT '',
                    original_name TEXT NOT NULL,
                    format TEXT NOT NULL,
                    stored_path TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    sha256 TEXT NOT NULL DEFAULT '',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT '',
                    reason_label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(model_id) REFERENCES model_library(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS book_model_selections (
                    book_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL DEFAULT '',
                    model_version_id TEXT NOT NULL DEFAULT '',
                    selected_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_versions (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source_snapshot TEXT NOT NULL,
                    artifact_path TEXT NOT NULL DEFAULT '',
                    base_model_ref TEXT NOT NULL DEFAULT '',
                    inference_template TEXT NOT NULL DEFAULT '',
                    backend_id TEXT NOT NULL DEFAULT '',
                    training_run_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(model_id, version_number),
                    FOREIGN KEY(model_id) REFERENCES model_library(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(
                conn,
                "model_training_sources",
                "content",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._migrate_source_files(conn)
            self._ensure_column(
                conn,
                "model_versions",
                "inference_template",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                "model_versions",
                "backend_id",
                "TEXT NOT NULL DEFAULT ''",
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_training_runs (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dataset_path TEXT NOT NULL,
                    backend_id TEXT NOT NULL DEFAULT '',
                    command_preview TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(model_id) REFERENCES model_library(id) ON DELETE CASCADE,
                    FOREIGN KEY(version_id) REFERENCES model_versions(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(
                conn,
                "model_training_runs",
                "backend_id",
                "TEXT NOT NULL DEFAULT ''",
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_model_sources_model
                ON model_training_sources(model_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_model_selections_model
                ON book_model_selections(model_id)
                """
            )
            for category_id, label in DEFAULT_MODEL_CATEGORIES:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO model_categories (
                        id, label, is_builtin, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?)
                    """,
                    (category_id, label, now, now),
                )
            for template in BUILTIN_MODEL_TEMPLATES:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO model_templates (
                        id, name, category_id, genre, style, purpose, description,
                        is_builtin, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        template["id"],
                        template["name"],
                        template["categoryId"],
                        template["genre"],
                        template["style"],
                        template["purpose"],
                        template["description"],
                        now,
                        now,
                    ),
                )

    def _migrate_source_files(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, stored_path
            FROM model_training_sources
            WHERE content = '' AND stored_path != ''
            """
        ).fetchall()
        for row in rows:
            stored_path = str(row["stored_path"] or "")
            path = (self.library_root / stored_path).resolve()
            if not path.is_relative_to(self.library_root) or not path.is_file():
                continue
            conn.execute(
                """
                UPDATE model_training_sources
                SET content = ?, stored_path = ''
                WHERE id = ?
                """,
                (path.read_text(encoding="utf-8"), str(row["id"])),
            )
            path.unlink()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _next_version_number(self, conn: sqlite3.Connection, model_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM model_versions WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        return int(row[0])

    def _training_command(
        self,
        template: str,
        *,
        dataset_path: Path,
        output_dir: Path,
        base_model: str,
        model_id: str,
        version_id: str,
    ) -> list[str]:
        if not template:
            return []
        formatted = template.format(
            dataset=str(dataset_path),
            dataset_rel=dataset_path.relative_to(self.library_root).as_posix(),
            output_dir=str(output_dir),
            output_dir_rel=output_dir.relative_to(self.library_root).as_posix(),
            base_model=base_model,
            model_id=model_id,
            version_id=version_id,
        )
        return shlex.split(formatted)

    def _resolve_training_backend(self, backend_id: str) -> tuple[str, str]:
        requested = (backend_id or "auto").strip()
        definitions = {
            item_id: (label, env_name)
            for item_id, label, env_name in TRAINING_BACKEND_DEFINITIONS
        }
        if requested == "auto":
            for item_id, _, env_name in TRAINING_BACKEND_DEFINITIONS:
                template = os.environ.get(env_name, "").strip()
                if template:
                    return item_id, template
            return "auto", ""
        if requested not in definitions:
            raise ValueError("选择的训练方式不存在。")
        _, env_name = definitions[requested]
        template = os.environ.get(env_name, "").strip()
        if not template:
            raise ValueError("选择的训练方式尚未在系统中配置。")
        return requested, template

    def _finish_training(
        self,
        model_id: str,
        version_id: str,
        run_id: str,
        status: str,
        message: str,
    ) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE model_versions SET status = ? WHERE id = ?",
                (status, version_id),
            )
            conn.execute(
                """
                UPDATE model_training_runs
                SET status = ?, message = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, message, now, run_id),
            )
            model_status = (
                "usable"
                if status == "usable"
                else "validating"
                if status == "validating"
                else "ready"
            )
            active_version = version_id if status == "usable" else ""
            conn.execute(
                """
                UPDATE model_library
                SET status = ?, active_version_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (model_status, active_version, now, model_id),
            )

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
