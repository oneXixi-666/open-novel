from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from open_novel.core.models import ContextPack, NovelMetadata, SceneContract, utc_now
from open_novel.core.quality_calibration import QualityThresholdConfig
from open_novel.core.workspace_storage import ProjectDocumentStore, default_workspace_db_path


class WorkbenchRepository:
    """SQLite store for workbench authoring state."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or default_workspace_db_path()).resolve()
        self.documents = ProjectDocumentStore(self.db_path)
        self._ensure_schema()

    def upsert_chapter(self, root: Path, chapter: dict[str, Any]) -> None:
        chapter_id = str(chapter.get("id") or "").strip()
        if not chapter_id:
            return
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_chapters (
                    root, chapter_id, title, status, word_count, progress, summary,
                    content, tasks_json, plot_points_json, people_json, clues_json,
                    linked_material_ids_json, review_json, target_word_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root, chapter_id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    word_count = excluded.word_count,
                    progress = excluded.progress,
                    summary = excluded.summary,
                    content = excluded.content,
                    tasks_json = excluded.tasks_json,
                    plot_points_json = excluded.plot_points_json,
                    people_json = excluded.people_json,
                    clues_json = excluded.clues_json,
                    linked_material_ids_json = excluded.linked_material_ids_json,
                    review_json = excluded.review_json,
                    target_word_count = excluded.target_word_count,
                    updated_at = excluded.updated_at
                """,
                (
                    root.as_posix(),
                    chapter_id,
                    str(chapter.get("title") or ""),
                    str(chapter.get("status") or "待写"),
                    int(chapter.get("wordCount") or 0),
                    int(chapter.get("progress") or 0),
                    str(chapter.get("summary") or ""),
                    str(chapter.get("content") or ""),
                    self._dumps(chapter.get("tasks") or []),
                    self._dumps(chapter.get("plotPoints") or []),
                    self._dumps(chapter.get("people") or []),
                    self._dumps(chapter.get("clues") or []),
                    self._dumps(chapter.get("linkedMaterialIds") or []),
                    self._dumps(chapter.get("review") or []),
                    int(chapter.get("targetWordCount") or 3000),
                    now,
                ),
            )

    def update_chapter_status(self, root: Path, chapter_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workbench_chapters
                SET status = ?, updated_at = ?
                WHERE root = ? AND chapter_id = ?
                """,
                (status, utc_now().isoformat(), root.as_posix(), chapter_id),
            )

    def update_chapter_quality_gate(
        self,
        root: Path,
        chapter_id: str,
        quality_score: int,
        gate_status: str,
        gate_score: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workbench_chapters
                SET quality_score = ?, gate_status = ?, gate_score = ?, updated_at = ?
                WHERE root = ? AND chapter_id = ?
                """,
                (
                    int(quality_score),
                    str(gate_status or ""),
                    int(gate_score),
                    utc_now().isoformat(),
                    root.as_posix(),
                    chapter_id,
                ),
            )

    def list_chapters(self, root: Path) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workbench_chapters
                WHERE root = ?
                ORDER BY chapter_id ASC
                """,
                (root.as_posix(),),
            ).fetchall()
        return [self._chapter_from_row(row) for row in rows]

    def chapter_status(self, root: Path, chapter_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status FROM workbench_chapters
                WHERE root = ? AND chapter_id = ?
                """,
                (root.as_posix(), chapter_id),
            ).fetchone()
        return str(row["status"] or "") if row else ""

    def write_generation_state(self, root: Path, state: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_generation_states (root, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(root) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (root.as_posix(), self._dumps(state), utc_now().isoformat()),
            )

    def claim_continue_request(self, root: Path, request_id: str) -> bool:
        """Atomically reserve a continue request before generation side effects begin."""
        normalized = request_id.strip()
        if not normalized:
            return True
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state_json FROM workbench_generation_states WHERE root = ?",
                (root.as_posix(),),
            ).fetchone()
            state = self._loads_dict(str(row["state_json"] or "{}")) if row else {}
            if state.get("lastContinueRequestId") == normalized:
                return False
            state["lastContinueRequestId"] = normalized
            conn.execute(
                """
                INSERT INTO workbench_generation_states (root, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(root) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (root.as_posix(), self._dumps(state), utc_now().isoformat()),
            )
        return True

    def read_generation_state(self, root: Path) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM workbench_generation_states WHERE root = ?",
                (root.as_posix(),),
            ).fetchone()
        return self._loads_dict(str(row["state_json"] or "{}")) if row else {}

    def upsert_scene_contract(self, root: Path, contract: SceneContract) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_scene_contracts (
                    root, chapter_id, title, contract_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(root, chapter_id) DO UPDATE SET
                    title = excluded.title,
                    contract_json = excluded.contract_json,
                    updated_at = excluded.updated_at
                """,
                (
                    root.as_posix(),
                    contract.chapterId,
                    contract.title,
                    self._dumps(contract.model_dump(mode="json")),
                    utc_now().isoformat(),
                ),
            )

    def read_scene_contract(self, root: Path, chapter_id: str) -> SceneContract | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT contract_json FROM workbench_scene_contracts
                WHERE root = ? AND chapter_id = ?
                """,
                (root.as_posix(), chapter_id),
            ).fetchone()
        if row is None:
            return None
        return SceneContract.model_validate(self._loads_dict(str(row["contract_json"] or "{}")))

    def upsert_context_pack(self, root: Path, context_pack: ContextPack) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_context_packs (
                    root, chapter_id, path, included_count, estimated_tokens,
                    context_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root, chapter_id) DO UPDATE SET
                    path = excluded.path,
                    included_count = excluded.included_count,
                    estimated_tokens = excluded.estimated_tokens,
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at
                """,
                (
                    root.as_posix(),
                    context_pack.chapterId,
                    context_pack.path,
                    len(context_pack.included),
                    context_pack.estimatedTokens,
                    self._dumps(context_pack.model_dump(mode="json")),
                    utc_now().isoformat(),
                ),
            )

    def read_context_pack(self, root: Path, chapter_id: str) -> ContextPack | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT context_json FROM workbench_context_packs
                WHERE root = ? AND chapter_id = ?
                """,
                (root.as_posix(), chapter_id),
            ).fetchone()
        if row is None:
            return None
        return ContextPack.model_validate(self._loads_dict(str(row["context_json"] or "{}")))

    def upsert_material(self, root: Path, material: dict[str, Any]) -> None:
        material_id = str(material.get("id") or "").strip()
        if not material_id:
            return
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_materials (
                    root, material_id, type, title, summary, influence, confidence,
                    material_json, deleted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                ON CONFLICT(root, material_id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    summary = excluded.summary,
                    influence = excluded.influence,
                    confidence = excluded.confidence,
                    material_json = excluded.material_json,
                    deleted_at = '',
                    updated_at = excluded.updated_at
                """,
                (
                    root.as_posix(),
                    material_id,
                    str(material.get("type") or ""),
                    str(material.get("title") or ""),
                    str(material.get("summary") or ""),
                    str(material.get("influence") or ""),
                    int(material.get("confidence") or 0),
                    self._dumps(material),
                    now,
                ),
            )

    def replace_materials(self, root: Path, materials: list[dict[str, Any]]) -> None:
        active_ids = {str(item.get("id") or "").strip() for item in materials}
        active_ids.discard("")
        now = utc_now().isoformat()
        with self._connect() as conn:
            for material in materials:
                material_id = str(material.get("id") or "").strip()
                if not material_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO workbench_materials (
                        root, material_id, type, title, summary, influence,
                        confidence, material_json, deleted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)
                    ON CONFLICT(root, material_id) DO UPDATE SET
                        type = excluded.type,
                        title = excluded.title,
                        summary = excluded.summary,
                        influence = excluded.influence,
                        confidence = excluded.confidence,
                        material_json = excluded.material_json,
                        deleted_at = '',
                        updated_at = excluded.updated_at
                    """,
                    (
                        root.as_posix(),
                        material_id,
                        str(material.get("type") or ""),
                        str(material.get("title") or ""),
                        str(material.get("summary") or ""),
                        str(material.get("influence") or ""),
                        int(material.get("confidence") or 0),
                        self._dumps(material),
                        now,
                    ),
                )
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                conn.execute(
                    f"""
                    UPDATE workbench_materials
                    SET deleted_at = ?, updated_at = ?
                    WHERE root = ? AND material_id NOT IN ({placeholders})
                    """,
                    (now, now, root.as_posix(), *sorted(active_ids)),
                )
            else:
                conn.execute(
                    """
                    UPDATE workbench_materials
                    SET deleted_at = ?, updated_at = ?
                    WHERE root = ?
                    """,
                    (now, now, root.as_posix()),
                )

    def delete_material(self, root: Path, material_id: str) -> None:
        material_id = material_id.strip()
        if not material_id:
            return
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workbench_materials
                SET deleted_at = ?, updated_at = ?
                WHERE root = ? AND material_id = ?
                """,
                (now, now, root.as_posix(), material_id),
            )

    def list_materials(self, root: Path, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = """
            SELECT * FROM workbench_materials
            WHERE root = ?
        """
        if not include_deleted:
            query += " AND deleted_at = ''"
        query += " ORDER BY updated_at DESC, material_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, (root.as_posix(),)).fetchall()
        return [self._loads_dict(str(row["material_json"] or "{}")) for row in rows]

    def replace_review_inbox(
        self, root: Path, chapter_id: str, reviews: list[dict[str, Any]]
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM workbench_review_inbox WHERE root = ?", (root.as_posix(),))
            for review in reviews:
                review_id = str(review.get("id") or "").strip()
                if not review_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO workbench_review_inbox (
                        root, review_id, chapter_id, status, priority, title,
                        suggestion, review_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        root.as_posix(),
                        review_id,
                        str(review.get("chapterId") or chapter_id),
                        str(review.get("status") or "待处理"),
                        str(review.get("priority") or "中"),
                        str(review.get("title") or ""),
                        str(review.get("suggestion") or ""),
                        self._dumps(review),
                        now,
                    ),
                )

    def read_review_inbox(self, root: Path) -> tuple[str, list[dict[str, Any]]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workbench_review_inbox
                WHERE root = ?
                ORDER BY rowid ASC
                """,
                (root.as_posix(),),
            ).fetchall()
        reviews = [self._loads_dict(str(row["review_json"] or "{}")) for row in rows]
        chapter_id = str(rows[0]["chapter_id"] or "") if rows else ""
        return chapter_id, reviews

    def write_review_states(self, root: Path, states: dict[str, str]) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            for review_id, status in states.items():
                normalized_id = str(review_id).strip()
                if not normalized_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO workbench_review_states (root, review_id, status, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(root, review_id) DO UPDATE SET
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (root.as_posix(), normalized_id, str(status), now),
                )

    def read_review_states(self, root: Path) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT review_id, status FROM workbench_review_states
                WHERE root = ?
                """,
                (root.as_posix(),),
            ).fetchall()
        return {str(row["review_id"]): str(row["status"]) for row in rows}

    def upsert_calibration_annotation(
        self,
        root: Path,
        chapter_id: str,
        label: str,
        note: str = "",
    ) -> dict[str, Any]:
        normalized = str(chapter_id or "").strip()
        if not normalized:
            raise ValueError("chapter_id is required")
        if label not in {"acceptable", "repair", "block"}:
            raise ValueError("label must be acceptable, repair, or block")
        now = utc_now().isoformat()
        project_id = root.as_posix()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calibration_annotations (
                    project_id, chapter_id, label, note, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, chapter_id) DO UPDATE SET
                    label = excluded.label,
                    note = excluded.note,
                    created_at = excluded.created_at
                """,
                (project_id, normalized, label, note, now),
            )
        return {
            "projectId": project_id,
            "chapterId": normalized,
            "label": label,
            "note": note,
            "createdAt": now,
        }

    def list_calibration_annotations(self, root: Path) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT project_id, chapter_id, label, note, created_at
                FROM calibration_annotations
                WHERE project_id = ?
                ORDER BY chapter_id ASC
                """,
                (root.as_posix(),),
            ).fetchall()
        return [
            {
                "projectId": str(row["project_id"]),
                "chapterId": str(row["chapter_id"]),
                "label": str(row["label"]),
                "note": str(row["note"] or ""),
                "createdAt": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def read_quality_thresholds(self, root: Path) -> QualityThresholdConfig:
        if self.documents.is_database_project(root):
            metadata = NovelMetadata.model_validate_json(
                self.documents.read_text(root, "novel.json")
            )
            return QualityThresholdConfig.from_dict(metadata.qualityThresholds)
        path = root / "novel.json"
        if not path.is_file():
            return QualityThresholdConfig()
        metadata = NovelMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        return QualityThresholdConfig.from_dict(metadata.qualityThresholds)

    def write_quality_thresholds(
        self,
        root: Path,
        thresholds: QualityThresholdConfig,
    ) -> QualityThresholdConfig:
        database_project = self.documents.is_database_project(root)
        path = root / "novel.json"
        metadata = NovelMetadata.model_validate_json(
            self.documents.read_text(root, "novel.json")
            if database_project
            else path.read_text(encoding="utf-8")
        )
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calibration_threshold_history (
                    project_id, applied_at, thresholds_json
                ) VALUES (?, ?, ?)
                """,
                (
                    root.as_posix(),
                    now.isoformat(),
                    json.dumps(metadata.qualityThresholds or QualityThresholdConfig().to_dict()),
                ),
            )
        metadata = metadata.model_copy(
            update={
                "qualityThresholds": thresholds.to_dict(),
                "updatedAt": now,
            }
        )
        content = json.dumps(
            metadata.model_dump(mode="json"), ensure_ascii=False, indent=2
        ) + "\n"
        if database_project:
            self.documents.write_text(root, "novel.json", content)
        else:
            path.write_text(content, encoding="utf-8")
        return thresholds

    def list_quality_threshold_history(self, root: Path, limit: int = 5) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT applied_at, thresholds_json
                FROM calibration_threshold_history
                WHERE project_id = ?
                ORDER BY applied_at DESC
                LIMIT ?
                """,
                (root.as_posix(), max(1, limit)),
            ).fetchall()
        return [
            {
                "appliedAt": str(row["applied_at"] or ""),
                "thresholds": json.loads(str(row["thresholds_json"] or "{}")),
            }
            for row in rows
        ]

    def read_quality_threshold_history_item(
        self,
        root: Path,
        applied_at: str,
    ) -> QualityThresholdConfig:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT thresholds_json
                FROM calibration_threshold_history
                WHERE project_id = ? AND applied_at = ?
                """,
                (root.as_posix(), applied_at),
            ).fetchone()
        if row is None:
            raise ValueError("missing calibration threshold history item")
        return QualityThresholdConfig.from_dict(json.loads(str(row["thresholds_json"] or "{}")))

    def replace_memory_updates(
        self,
        root: Path,
        chapter_id: str,
        updates: list[dict[str, Any]],
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            for update in updates:
                update_id = str(update.get("id") or "").strip()
                if not update_id:
                    continue
                status = str(update.get("status") or "")
                conn.execute(
                    """
                    INSERT INTO workbench_memory_updates (
                        root, update_id, chapter_id, target, action, status,
                        payload_json, evidence_json, update_json, applied_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(root, update_id) DO UPDATE SET
                        chapter_id = excluded.chapter_id,
                        target = excluded.target,
                        action = excluded.action,
                        status = excluded.status,
                        payload_json = excluded.payload_json,
                        evidence_json = excluded.evidence_json,
                        update_json = excluded.update_json,
                        applied_at = CASE
                            WHEN excluded.status = 'applied' THEN excluded.applied_at
                            ELSE workbench_memory_updates.applied_at
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        root.as_posix(),
                        update_id,
                        str(update.get("chapterId") or chapter_id),
                        str(update.get("targetLabel") or ""),
                        str(update.get("action") or ""),
                        status,
                        self._dumps(update),
                        self._dumps(update.get("evidence") or []),
                        self._dumps(update),
                        now if status == "applied" else "",
                        now,
                    ),
                )

    def list_memory_updates(self, root: Path, chapter_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT update_json FROM workbench_memory_updates
                WHERE root = ? AND chapter_id = ?
                ORDER BY updated_at ASC, update_id ASC
                """,
                (root.as_posix(), chapter_id),
            ).fetchall()
        return [self._loads_dict(str(row["update_json"] or "{}")) for row in rows]

    def upsert_run_summary(self, root: Path, run: dict[str, Any]) -> None:
        run_id = str(run.get("id") or "").strip()
        if not run_id:
            return
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workbench_runs (
                    root, run_id, skill_id, kind, status, title, summary_json,
                    path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root, run_id) DO UPDATE SET
                    skill_id = excluded.skill_id,
                    kind = excluded.kind,
                    status = excluded.status,
                    title = excluded.title,
                    summary_json = excluded.summary_json,
                    path = excluded.path,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                (
                    root.as_posix(),
                    run_id,
                    str(run.get("skillId") or run.get("kind") or ""),
                    str(run.get("kind") or ""),
                    str(run.get("status") or ""),
                    str(run.get("title") or ""),
                    self._dumps(run),
                    str(run.get("path") or ""),
                    str(run.get("createdAt") or ""),
                    now,
                ),
            )

    def list_run_summaries(self, root: Path) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT summary_json FROM workbench_runs
                WHERE root = ?
                ORDER BY updated_at DESC, run_id ASC
                """,
                (root.as_posix(),),
            ).fetchall()
        return [self._loads_dict(str(row["summary_json"] or "{}")) for row in rows]

    def coverage_counts(self, root: Path) -> dict[str, int | bool]:
        root_key = root.as_posix()
        with self._connect() as conn:
            chapter_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_chapters WHERE root = ?",
                root_key,
            )
            contract_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_scene_contracts WHERE root = ?",
                root_key,
            )
            context_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_context_packs WHERE root = ?",
                root_key,
            )
            generation_state = conn.execute(
                "SELECT 1 FROM workbench_generation_states WHERE root = ?",
                (root_key,),
            ).fetchone()
            material_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_materials WHERE root = ? AND deleted_at = ''",
                root_key,
            )
            review_inbox_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_review_inbox WHERE root = ?",
                root_key,
            )
            review_state_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_review_states WHERE root = ?",
                root_key,
            )
            memory_update_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_memory_updates WHERE root = ?",
                root_key,
            )
            run_count = self._count(
                conn,
                "SELECT COUNT(*) FROM workbench_runs WHERE root = ?",
                root_key,
            )
        return {
            "chapters": chapter_count,
            "sceneContracts": contract_count,
            "contextPacks": context_count,
            "hasGenerationState": generation_state is not None,
            "materials": material_count,
            "reviewInbox": review_inbox_count,
            "reviewStates": review_state_count,
            "memoryUpdates": memory_update_count,
            "runs": run_count,
        }

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _count(self, conn: sqlite3.Connection, query: str, root: str) -> int:
        row = conn.execute(query, (root,)).fetchone()
        return int(row[0] or 0) if row else 0

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_chapters (
                    root TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '待写',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    progress INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    tasks_json TEXT NOT NULL DEFAULT '[]',
                    plot_points_json TEXT NOT NULL DEFAULT '[]',
                    people_json TEXT NOT NULL DEFAULT '[]',
                    clues_json TEXT NOT NULL DEFAULT '[]',
                    linked_material_ids_json TEXT NOT NULL DEFAULT '[]',
                    review_json TEXT NOT NULL DEFAULT '[]',
                    quality_score INTEGER NOT NULL DEFAULT 0,
                    gate_status TEXT NOT NULL DEFAULT '',
                    gate_score INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, chapter_id)
                )
                """
            )
            self._ensure_columns(
                conn,
                "workbench_chapters",
                {
                    "quality_score": "INTEGER NOT NULL DEFAULT 0",
                    "gate_status": "TEXT NOT NULL DEFAULT ''",
                    "gate_score": "INTEGER NOT NULL DEFAULT 0",
                    "target_word_count": "INTEGER NOT NULL DEFAULT 3000",
                },
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_generation_states (
                    root TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_scene_contracts (
                    root TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, chapter_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_context_packs (
                    root TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    included_count INTEGER NOT NULL DEFAULT 0,
                    estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, chapter_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_materials (
                    root TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    influence TEXT NOT NULL DEFAULT '',
                    confidence INTEGER NOT NULL DEFAULT 0,
                    material_json TEXT NOT NULL DEFAULT '{}',
                    deleted_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, material_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_review_inbox (
                    root TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '待处理',
                    priority TEXT NOT NULL DEFAULT '中',
                    title TEXT NOT NULL DEFAULT '',
                    suggestion TEXT NOT NULL DEFAULT '',
                    review_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, review_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_review_states (
                    root TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '待处理',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, review_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_annotations (
                    id INTEGER PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL,
                    label TEXT CHECK(label IN ('acceptable','repair','block')) NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, chapter_id)
                )
                """
            )
            if version < 2:
                self._migrate_calibration_labels(conn)
                conn.execute("PRAGMA user_version = 2")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_threshold_history (
                    id INTEGER PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    thresholds_json TEXT NOT NULL,
                    UNIQUE(project_id, applied_at)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_memory_updates (
                    root TEXT NOT NULL,
                    update_id TEXT NOT NULL,
                    chapter_id TEXT NOT NULL DEFAULT '',
                    target TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'proposed',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    update_json TEXT NOT NULL DEFAULT '{}',
                    applied_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, update_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workbench_runs (
                    root TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (root, run_id)
                )
                """
            )

    def _chapter_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["chapter_id"]),
            "title": str(row["title"] or ""),
            "status": str(row["status"] or "待写"),
            "wordCount": int(row["word_count"] or 0),
            "progress": int(row["progress"] or 0),
            "summary": str(row["summary"] or ""),
            "content": str(row["content"] or ""),
            "tasks": self._loads_list(str(row["tasks_json"] or "[]")),
            "plotPoints": self._loads_list(str(row["plot_points_json"] or "[]")),
            "people": self._loads_list(str(row["people_json"] or "[]")),
            "clues": self._loads_list(str(row["clues_json"] or "[]")),
            "linkedMaterialIds": self._loads_list(str(row["linked_material_ids_json"] or "[]")),
            "review": self._loads_list(str(row["review_json"] or "[]")),
            "qualityScore": int(row["quality_score"] or 0),
            "gateStatus": str(row["gate_status"] or ""),
            "gateScore": int(row["gate_score"] or 0),
            "targetWordCount": int(row["target_word_count"] or 3000),
        }

    def _ensure_columns(
        self,
        conn: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _migrate_calibration_labels(self, conn: sqlite3.Connection) -> None:
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'calibration_annotations'"
        ).fetchone()
        if table_sql is None or "'gold'" not in str(table_sql[0] or ""):
            return
        conn.execute("ALTER TABLE calibration_annotations RENAME TO calibration_annotations_legacy")
        conn.execute(
            """
            CREATE TABLE calibration_annotations (
                id INTEGER PRIMARY KEY,
                project_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                label TEXT CHECK(label IN ('acceptable','repair','block')) NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, chapter_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO calibration_annotations
                (id, project_id, chapter_id, label, note, created_at)
            SELECT id, project_id, chapter_id,
                   CASE label WHEN 'gold' THEN 'acceptable'
                              WHEN 'reject' THEN 'block' ELSE label END,
                   note, created_at
            FROM calibration_annotations_legacy
            """
        )
        conn.execute("DROP TABLE calibration_annotations_legacy")

    def _dumps(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _loads_list(self, text: str) -> list[Any]:
        try:
            value = json.loads(text)
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    def _loads_dict(self, text: str) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
