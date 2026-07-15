from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from open_novel.core.project import ProjectService
from open_novel.core.text_support import important_terms, text_supports_claim


class LongFormPlanService:
    plan_path = "story/long-form-plan.json"
    candidate_path = "story/generation-candidates/long-form-plan.json"
    replan_candidate_path = "story/generation-candidates/long-form-replan.json"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_plan(self, root: Path) -> dict[str, Any]:
        return self._read_json(root, self.plan_path)

    def has_plan(self, root: Path) -> bool:
        plan = self.read_plan(root)
        volumes = plan.get("volumes") if isinstance(plan, dict) else None
        return bool(plan.get("mainline") and isinstance(volumes, list) and len(volumes) >= 2)

    def validate_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        book_plan = payload.get("bookPlan")
        if not isinstance(book_plan, dict):
            raise ValueError("整书规划缺少 bookPlan。")
        required_book = [
            "mainline",
            "endingDirection",
            "longTermOpposition",
        ]
        for field in required_book:
            if not str(book_plan.get(field) or "").strip():
                raise ValueError(f"整书规划缺少 {field}。")
        core_promises = self._strings(book_plan.get("corePromises"))
        if not core_promises:
            raise ValueError("整书规划必须包含核心承诺。")
        volumes = payload.get("volumes")
        if not isinstance(volumes, list) or len(volumes) < 2:
            raise ValueError("长篇规划必须至少包含两卷策略。")
        normalized_volumes: list[dict[str, Any]] = []
        required_volume = [
            "title",
            "chapterRange",
            "goal",
            "mainConflict",
            "endingChange",
            "failureCondition",
        ]
        for index, raw in enumerate(volumes, start=1):
            if not isinstance(raw, dict):
                raise ValueError("卷策略格式不完整。")
            volume = {field: self._required(raw, field) for field in required_volume}
            volume["volumeId"] = str(raw.get("volumeId") or f"volume-{index:03d}").strip()
            volume["payoffs"] = self._strings(raw.get("payoffs"))
            segments = raw.get("beatSegments")
            if not isinstance(segments, list) or len(segments) < 2:
                raise ValueError("每卷至少需要两个节奏段。")
            normalized_segments: list[dict[str, Any]] = []
            for segment_index, segment_raw in enumerate(segments, start=1):
                if not isinstance(segment_raw, dict):
                    raise ValueError("节奏段格式不完整。")
                normalized_segments.append(
                    {
                        "segmentId": str(
                            segment_raw.get("segmentId")
                            or f"{volume['volumeId']}-segment-{segment_index:02d}"
                        ),
                        "title": self._required(segment_raw, "title"),
                        "chapterRange": self._required(segment_raw, "chapterRange"),
                        "purpose": self._required(segment_raw, "purpose"),
                        "pressure": self._required(segment_raw, "pressure"),
                        "payoff": self._required(segment_raw, "payoff"),
                        "density": self._required(segment_raw, "density"),
                    }
                )
            volume["beatSegments"] = normalized_segments
            normalized_volumes.append(volume)
        chapter_adjustments = []
        for raw in payload.get("chapterAdjustments", []):
            if not isinstance(raw, dict):
                continue
            chapter_id = str(raw.get("chapterId") or "").strip()
            if not chapter_id:
                continue
            chapter_adjustments.append(
                {
                    "chapterId": chapter_id,
                    "segmentId": str(raw.get("segmentId") or "").strip(),
                    "goal": self._required(raw, "goal"),
                    "hook": self._required(raw, "hook"),
                    "promiseProgression": self._required(raw, "promiseProgression"),
                    "logicDependencies": self._strings(raw.get("logicDependencies")),
                }
            )
        return {
            "schemaVersion": 1,
            "mainline": str(book_plan["mainline"]).strip(),
            "endingDirection": str(book_plan["endingDirection"]).strip(),
            "longTermOpposition": str(book_plan["longTermOpposition"]).strip(),
            "corePromises": core_promises,
            "estimatedVolumes": len(normalized_volumes),
            "currentVolumeId": normalized_volumes[0]["volumeId"],
            "volumes": normalized_volumes,
            "chapterAdjustments": chapter_adjustments,
            "warnings": self._theme_convergence_warnings(normalized_volumes),
        }

    def _theme_convergence_warnings(
        self, volumes: list[dict[str, Any]], threshold: float = 0.6
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for index, current in enumerate(volumes):
            current_terms = self._theme_terms(current)
            if not current_terms:
                continue
            for previous in volumes[:index]:
                previous_terms = self._theme_terms(previous)
                denominator = min(len(current_terms), len(previous_terms))
                overlap = len(current_terms & previous_terms) / denominator if denominator else 0
                if overlap < threshold:
                    continue
                warnings.append(
                    {
                        "type": "volume_theme_convergence",
                        "severity": "warn",
                        "volumeIds": [
                            str(previous.get("volumeId") or ""),
                            str(current.get("volumeId") or ""),
                        ],
                        "overlap": round(overlap, 3),
                        "message": (
                            f"{current.get('title', '当前卷')}与"
                            f"{previous.get('title', '前卷')}的目标和核心冲突高度趋同，"
                            "建议差异化主要对手、胜负条件或阶段代价。"
                        ),
                    }
                )
        return warnings

    def _theme_terms(self, volume: dict[str, Any]) -> set[str]:
        text = " ".join([str(volume.get("goal") or ""), str(volume.get("mainConflict") or "")])
        return {term for term in important_terms(text) if len(term) >= 2}

    def apply_candidate(self, root: Path, candidate_path: str | None = None) -> dict[str, Any]:
        path = candidate_path or self.candidate_path
        candidate = self._read_json(root, path)
        plan = candidate.get("plan") if isinstance(candidate, dict) else None
        if not isinstance(plan, dict):
            raise ValueError("当前没有可确认的长篇规划候选。")
        accepted = {
            **plan,
            "sourceRunId": str(candidate.get("runId") or ""),
            "acceptedAt": datetime.now(UTC).isoformat(),
        }
        self._write_json(root, self.plan_path, accepted)
        for volume in accepted["volumes"]:
            self._write_volume_and_arc(root, volume)
        if path == self.replan_candidate_path:
            self._apply_future_chapter_adjustments(root, accepted)
        candidate["status"] = "accepted"
        self._write_json(root, path, candidate)
        return accepted

    def update_volume_goal(self, root: Path, volume_id: str, goal: str) -> dict[str, Any]:
        plan = self.read_plan(root)
        volumes = plan.get("volumes") if isinstance(plan.get("volumes"), list) else []
        updated = False
        for volume in volumes:
            if isinstance(volume, dict) and str(volume.get("volumeId") or "") == volume_id:
                volume["goal"] = goal.strip()
                updated = True
                self._write_volume_and_arc(root, volume)
                break
        if not updated:
            raise FileNotFoundError(f"missing volume: {volume_id}")
        plan["manualRevisionAt"] = datetime.now(UTC).isoformat()
        self._write_json(root, self.plan_path, plan)
        return plan

    def update_volume(
        self, root: Path, volume_id: str, *, goal: str, chapter_range: str = ""
    ) -> dict[str, Any]:
        plan = self.read_plan(root)
        volumes = plan.get("volumes") if isinstance(plan.get("volumes"), list) else []
        target = next(
            (
                item
                for item in volumes
                if isinstance(item, dict) and item.get("volumeId") == volume_id
            ),
            None,
        )
        if target is None:
            raise FileNotFoundError(f"missing volume: {volume_id}")
        normalized_range = str(target.get("chapterRange") or "")
        if chapter_range.strip():
            start, end = self._range_parts(chapter_range)
            for segment in target.get("beatSegments", []):
                segment_start, segment_end = self._range_parts(
                    str(segment.get("chapterRange") or "")
                )
                if segment_start < start or segment_end > end:
                    raise ValueError("卷边界必须覆盖当前卷的全部节奏段。")
            normalized_range = f"{start:03d}-{end:03d}"
        target["goal"] = goal.strip()
        target["chapterRange"] = normalized_range
        plan["manualRevisionAt"] = datetime.now(UTC).isoformat()
        self._write_json(root, self.plan_path, plan)
        self._write_volume_and_arc(root, target)
        return plan

    def update_volume_boundary(
        self, root: Path, volume_id: str, chapter_range: str
    ) -> dict[str, Any]:
        start, end = self._range_parts(chapter_range)
        plan = self.read_plan(root)
        volumes = plan.get("volumes") if isinstance(plan.get("volumes"), list) else []
        target = next(
            (
                item
                for item in volumes
                if isinstance(item, dict) and item.get("volumeId") == volume_id
            ),
            None,
        )
        if target is None:
            raise FileNotFoundError(f"missing volume: {volume_id}")
        for segment in target.get("beatSegments", []):
            segment_start, segment_end = self._range_parts(str(segment.get("chapterRange") or ""))
            if segment_start < start or segment_end > end:
                raise ValueError("卷边界必须覆盖当前卷的全部节奏段。")
        target["chapterRange"] = f"{start:03d}-{end:03d}"
        plan["manualRevisionAt"] = datetime.now(UTC).isoformat()
        self._write_json(root, self.plan_path, plan)
        self._write_volume_and_arc(root, target)
        return plan

    def update_chapter_landing(
        self,
        root: Path,
        chapter_id: str,
        *,
        goal: str,
        hook: str,
        promise_progression: str,
        logic_dependencies: list[str],
        segment_id: str = "",
    ) -> dict[str, Any]:
        blueprint = self._read_json(root, "story/chapter-blueprint.json")
        chapters = blueprint.get("chapters") if isinstance(blueprint.get("chapters"), list) else []
        landing = next(
            (
                item
                for item in chapters
                if isinstance(item, dict) and str(item.get("chapterId") or "") == chapter_id
            ),
            None,
        )
        if landing is None:
            raise FileNotFoundError(f"missing chapter landing: {chapter_id}")
        landing.update(
            {
                "goal": goal.strip(),
                "hook": hook.strip(),
                "promiseProgression": promise_progression.strip(),
                "logicDependencies": logic_dependencies,
                "segmentId": segment_id.strip(),
            }
        )
        blueprint["manualRevisionAt"] = datetime.now(UTC).isoformat()
        self._write_json(root, "story/chapter-blueprint.json", blueprint)
        return landing

    def chapter_landings(self, root: Path) -> list[dict[str, Any]]:
        blueprint = self._read_json(root, "story/chapter-blueprint.json")
        chapters = blueprint.get("chapters") if isinstance(blueprint.get("chapters"), list) else []
        states = self._chapter_states(root)
        return [
            {
                "chapterId": str(item.get("chapterId") or ""),
                "title": str(item.get("title") or ""),
                "status": states.get(str(item.get("chapterId") or ""), "待写"),
                "goal": str(item.get("goal") or ""),
                "hook": str(item.get("hook") or ""),
                "characterChange": str(item.get("characterChange") or ""),
                "promiseProgression": str(item.get("promiseProgression") or ""),
                "logicDependencies": self._strings(item.get("logicDependencies")),
                "segmentId": str(
                    item.get("segmentId")
                    or self._segment_for_chapter(root, str(item.get("chapterId") or ""))
                ),
            }
            for item in chapters
            if isinstance(item, dict)
        ]

    def serial_risks(self, root: Path) -> list[dict[str, Any]]:
        landings = self.chapter_landings(root)
        signals = [
            self._sequence_signal(
                "weak_hooks",
                "连续弱钩子",
                landings,
                lambda item: (
                    len(str(item.get("hook") or "").strip()) < 6
                    or str(item.get("hook") or "").strip() in {"无", "待定"}
                ),
                "连续章节缺少明确的章尾推动力。",
                "读者可能缺少继续阅读的直接理由。",
                "优先修改相关章节的结尾钩子。",
            ),
            self._promise_pressure_signal(root, landings),
            self._repeated_value_signal(
                "rhythm_imbalance",
                "节奏失衡",
                landings,
                "goal",
                "连续章节目标重复，缺少阶段变化。",
                "铺垫或同类冲突可能持续过久。",
                "调整节奏段内的目标和兑现顺序。",
            ),
            self._sequence_signal(
                "character_stagnation",
                "角色停滞",
                landings,
                lambda item: (
                    not str(item.get("characterChange") or "").strip()
                    or str(item.get("characterChange") or "").strip() in {"无", "无变化"}
                ),
                "连续章节没有记录角色选择或状态变化。",
                "核心角色的成长和关系推进可能停滞。",
                "为相关章节补入可观察的人物变化。",
            ),
            self._volume_deviation_signal(root, landings),
        ]
        return signals

    def current_position(self, root: Path, chapter_id: str) -> dict[str, Any]:
        plan = self.read_plan(root)
        order = self._chapter_order(chapter_id)
        if order is None:
            return {}
        for volume in plan.get("volumes", []):
            if not isinstance(volume, dict) or not self._range_contains(
                str(volume.get("chapterRange") or ""), order
            ):
                continue
            segment = next(
                (
                    item
                    for item in volume.get("beatSegments", [])
                    if isinstance(item, dict)
                    and self._range_contains(str(item.get("chapterRange") or ""), order)
                ),
                {},
            )
            return {
                "volumeId": str(volume.get("volumeId") or ""),
                "volumeTitle": str(volume.get("title") or ""),
                "volumeGoal": str(volume.get("goal") or ""),
                "segmentId": str(segment.get("segmentId") or ""),
                "segmentTitle": str(segment.get("title") or ""),
                "segmentPurpose": str(segment.get("purpose") or ""),
                "chapterRange": str(
                    segment.get("chapterRange") or volume.get("chapterRange") or ""
                ),
            }
        return {}

    def evaluate_deviation(self, root: Path, chapter_id: str) -> dict[str, Any]:
        position = self.current_position(root, chapter_id)
        chapter_path = f"chapters/{chapter_id}.md"
        body = self.project_service.read_text_if_exists(root, chapter_path)
        target = " ".join(
            value
            for value in [
                str(position.get("volumeGoal") or ""),
                str(position.get("segmentPurpose") or ""),
            ]
            if value
        )
        plan = self.read_plan(root)
        manual_revision = str(plan.get("manualRevisionAt") or "")
        planned_revision = str(plan.get("lastPlannedRevisionAt") or "")
        supported = bool(target and text_supports_claim(body, target))
        significant = bool(manual_revision and manual_revision != planned_revision)
        report = {
            "schemaVersion": 1,
            "chapterId": chapter_id,
            "status": "needs_replan" if significant else "aligned" if supported else "watch",
            "significant": significant,
            "position": position,
            "evidence": [f"chapters/{chapter_id}.md", self.plan_path],
            "reason": (
                "卷目标已被作者修改，需要为未定稿章节生成重规划候选。"
                if significant
                else "当前章节与卷目标仍在可接受范围内。"
                if supported
                else "当前章节与卷目标支撑较弱，先观察下一批，不立即重规划。"
            ),
        }
        self._write_json(root, f"runs/long-form-deviation-{chapter_id}.json", report)
        return report

    def mark_replanned(self, root: Path) -> None:
        plan = self.read_plan(root)
        plan["lastPlannedRevisionAt"] = str(plan.get("manualRevisionAt") or "")
        self._write_json(root, self.plan_path, plan)

    def _apply_future_chapter_adjustments(self, root: Path, plan: dict[str, Any]) -> None:
        states = self._chapter_states(root)
        for adjustment in plan.get("chapterAdjustments", []):
            if not isinstance(adjustment, dict):
                continue
            chapter_id = str(adjustment.get("chapterId") or "")
            if states.get(chapter_id) == "完成":
                continue
            try:
                self.update_chapter_landing(
                    root,
                    chapter_id,
                    goal=str(adjustment.get("goal") or ""),
                    hook=str(adjustment.get("hook") or ""),
                    promise_progression=str(adjustment.get("promiseProgression") or ""),
                    logic_dependencies=self._strings(adjustment.get("logicDependencies")),
                    segment_id=str(adjustment.get("segmentId") or ""),
                )
            except FileNotFoundError:
                continue

    def _chapter_states(self, root: Path) -> dict[str, str]:
        payload = self._read_json(root, "memory/workbench-chapter-states.json")
        states = payload.get("chapters") if isinstance(payload.get("chapters"), dict) else {}
        return {str(key): str(value) for key, value in states.items()}

    def _segment_for_chapter(self, root: Path, chapter_id: str) -> str:
        return str(self.current_position(root, chapter_id).get("segmentId") or "")

    def _sequence_signal(
        self,
        key: str,
        title: str,
        landings: list[dict[str, Any]],
        predicate: Any,
        reason: str,
        impact: str,
        action: str,
    ) -> dict[str, Any]:
        enough = len(landings) >= 3
        evidence: list[str] = []
        streak: list[str] = []
        for item in landings:
            if predicate(item):
                streak.append(str(item.get("chapterId") or ""))
                if len(streak) >= 2:
                    evidence = streak[:5]
                    break
            else:
                streak = []
        active = enough and bool(evidence)
        return {
            "key": key,
            "title": title,
            "status": "risk" if active else "clear" if enough else "insufficient",
            "evidenceChapters": evidence if active else [],
            "reason": reason
            if active
            else "当前样本不足，暂不判断。"
            if not enough
            else "当前未发现连续异常。",
            "impact": impact if active else "暂无需要处理的影响。",
            "action": action if active else "继续积累章节证据。",
        }

    def _repeated_value_signal(
        self,
        key: str,
        title: str,
        landings: list[dict[str, Any]],
        field: str,
        reason: str,
        impact: str,
        action: str,
    ) -> dict[str, Any]:
        enough = len(landings) >= 3
        evidence: list[str] = []
        for index in range(1, len(landings)):
            previous = str(landings[index - 1].get(field) or "").strip()
            current = str(landings[index].get(field) or "").strip()
            if previous and current == previous:
                evidence = [
                    str(landings[index - 1].get("chapterId") or ""),
                    str(landings[index].get("chapterId") or ""),
                ]
                break
        active = enough and bool(evidence)
        return {
            "key": key,
            "title": title,
            "status": "risk" if active else "clear" if enough else "insufficient",
            "evidenceChapters": evidence,
            "reason": reason
            if active
            else "当前样本不足，暂不判断。"
            if not enough
            else "当前未发现连续异常。",
            "impact": impact if active else "暂无需要处理的影响。",
            "action": action if active else "继续积累章节证据。",
        }

    def _promise_pressure_signal(
        self, root: Path, landings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload = self._read_json(root, "memory/promises.json")
        items = (
            payload.get("promises")
            if isinstance(payload.get("promises"), list)
            else payload.get("items")
            if isinstance(payload.get("items"), list)
            else []
        )
        latest_order = max(
            (self._chapter_order(str(item.get("chapterId") or "")) or 0 for item in landings),
            default=0,
        )
        pressured = [
            item
            for item in items
            if isinstance(item, dict) and self._promise_is_pressured(item, latest_order)
        ]
        evidence = []
        for item in pressured:
            evidence.extend(self._strings(item.get("relatedChapters") or item.get("related")))
        enough = bool(landings or items)
        return {
            "key": "promise_pressure",
            "title": "承诺压力",
            "status": "risk" if pressured else "clear" if enough else "insufficient",
            "evidenceChapters": evidence[:5],
            "reason": f"有 {len(pressured)} 条承诺临近或超过计划兑现范围。"
            if pressured
            else "当前样本不足，暂不判断。"
            if not enough
            else "当前承诺仍在计划范围内。",
            "impact": "后续章节可能继续新增承诺却没有兑现空间。"
            if pressured
            else "暂无需要处理的影响。",
            "action": "在章节落点中安排推进或兑现，并减少新承诺。"
            if pressured
            else "继续维护承诺状态。",
        }

    def _promise_is_pressured(self, item: dict[str, Any], latest_order: int) -> bool:
        if str(item.get("dueStatus") or item.get("status") or "") in {"at_risk", "overdue"}:
            return True
        if str(item.get("status") or "") in {"closed", "paid_off"}:
            return False
        opened = self._chapter_order(str(item.get("openedIn") or ""))
        window_end = self._range_end(str(item.get("payoffWindow") or ""))
        return bool(
            opened is not None
            and window_end is not None
            and latest_order >= opened + window_end - 1
        )

    def _volume_deviation_signal(
        self, root: Path, landings: list[dict[str, Any]]
    ) -> dict[str, Any]:
        plan = self.read_plan(root)
        changed = bool(
            plan.get("manualRevisionAt")
            and plan.get("manualRevisionAt") != plan.get("lastPlannedRevisionAt")
        )
        evidence = [str(item.get("chapterId") or "") for item in landings[:5]]
        return {
            "key": "volume_deviation",
            "title": "卷目标偏离",
            "status": "risk" if changed else "clear" if landings else "insufficient",
            "evidenceChapters": evidence if changed else [],
            "reason": "卷目标已修改，但未来章节落点尚未完成重规划。"
            if changed
            else "当前样本不足，暂不判断。"
            if not landings
            else "当前章节落点与已确认卷目标一致。",
            "impact": "后续合同可能继续沿用旧目标。" if changed else "暂无需要处理的影响。",
            "action": "生成重规划候选并比较后确认。" if changed else "继续按当前卷目标推进。",
        }

    def _write_volume_and_arc(self, root: Path, volume: dict[str, Any]) -> None:
        volume_id = str(volume["volumeId"])
        self._write_json(root, f"story/volume-plans/{volume_id}.json", volume)
        milestones = []
        for segment in volume.get("beatSegments", []):
            end = self._range_end(str(segment.get("chapterRange") or ""))
            if end is not None:
                milestones.append(
                    {
                        "chapterId": f"{end:03d}",
                        "milestone": str(segment.get("payoff") or ""),
                    }
                )
        self._write_json(
            root,
            f"story/arc-contracts/{volume_id}.json",
            {
                "schemaVersion": 1,
                "arcId": volume_id,
                "title": str(volume.get("title") or volume_id),
                "chapterRange": str(volume.get("chapterRange") or ""),
                "arcGoal": str(volume.get("goal") or ""),
                "antagonist": str(volume.get("mainConflict") or ""),
                "emotionalArc": str(volume.get("endingChange") or ""),
                "failureCondition": str(volume.get("failureCondition") or ""),
                "keyMilestones": milestones,
                "status": "in_progress",
            },
        )

    def _read_json(self, root: Path, relative_path: str) -> dict[str, Any]:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            data = json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_json(self, root: Path, relative_path: str, data: dict[str, Any]) -> None:
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        )

    def _required(self, data: dict[str, Any], key: str) -> str:
        value = str(data.get(key) or "").strip()
        if not value:
            raise ValueError(f"长篇规划缺少 {key}。")
        return value

    def _strings(self, value: Any) -> list[str]:
        return (
            [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, list)
            else []
        )

    def _chapter_order(self, value: str) -> int | None:
        digits = "".join(character for character in value if character.isdigit())
        return int(digits) if digits else None

    def _range_contains(self, value: str, order: int) -> bool:
        parts = [int(item) for item in re.findall(r"\d+", value)]
        return len(parts) >= 2 and parts[0] <= order <= parts[1]

    def _range_end(self, value: str) -> int | None:
        parts = [int(item) for item in re.findall(r"\d+", value)]
        return parts[1] if len(parts) >= 2 else None

    def _range_parts(self, value: str) -> tuple[int, int]:
        parts = [int(item) for item in re.findall(r"\d+", value)]
        if len(parts) < 2 or parts[0] > parts[1]:
            raise ValueError("章节范围格式应为起始章-结束章。")
        return parts[0], parts[1]
