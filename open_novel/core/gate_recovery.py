from __future__ import annotations

from typing import Any

from open_novel.core.issue_navigation import IssueNavigationService


class GateRecoveryService:
    action_by_stage = {
        "readiness": "补齐章节合同，再重建 context pack。",
        "memory": "先修复记忆文件或运行安全修复，再重新检查章节。",
        "context": "重建或预览 context pack，确认合同和关键记忆进入上下文。",
        "continuity": "修改草稿以承接合同、记忆和时间线，再重跑 continuity/gate。",
        "quality": "修改正文节奏、冲突、钩子和人情味落点，再重跑质量检查。",
        "editorial": "按编辑意见补动作、代价、潜台词和余味，再重跑审稿。",
        "review": "处理章节复盘风险或调整 canon patch 后再接受。",
    }

    priority_by_stage = {
        "memory": 10,
        "readiness": 20,
        "context": 30,
        "continuity": 40,
        "quality": 50,
        "editorial": 60,
        "review": 70,
    }

    def recovery_plan(
        self,
        gate_report: Any,
        issue_navigation: dict[str, object] | None = None,
    ) -> dict[str, object]:
        gate = (
            gate_report.model_dump(mode="json")
            if hasattr(gate_report, "model_dump")
            else gate_report
        )
        if not isinstance(gate, dict):
            gate = {}
        chapter_id = str(gate.get("chapterId") or "")
        issues = gate.get("issues")
        if not isinstance(issues, list):
            issues = []
        navigation = issue_navigation or IssueNavigationService().build_navigation(
            chapter_id,
            {"gate": gate},
        )
        navigation_items = navigation.get("items") if isinstance(navigation, dict) else []
        if not isinstance(navigation_items, list):
            navigation_items = []
        steps = self._steps(issues, navigation_items)
        return {
            "schemaVersion": 1,
            "chapterId": chapter_id,
            "status": gate.get("status") or "pass",
            "score": gate.get("score") or 0,
            "blocked": gate.get("status") == "block",
            "issueCount": len(issues),
            "steps": steps,
            "recommendedNextAction": self._recommended_next_action(steps),
        }

    def _steps(
        self,
        issues: list[Any],
        navigation_items: list[Any],
    ) -> list[dict[str, object]]:
        by_stage: dict[str, dict[str, object]] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            stage = str(issue.get("stage") or "review")
            step = by_stage.setdefault(
                stage,
                {
                    "stage": stage,
                    "severity": str(issue.get("severity") or ""),
                    "issueCount": 0,
                    "types": [],
                    "targets": [],
                    "action": self.action_by_stage.get(
                        stage,
                        "处理该阶段问题后重跑 Chapter Gate。",
                    ),
                },
            )
            step["issueCount"] = int(step["issueCount"]) + 1
            self._upgrade_severity(step, str(issue.get("severity") or ""))
            issue_type = str(issue.get("type") or "")
            types = step["types"]
            if isinstance(types, list) and issue_type and issue_type not in types:
                types.append(issue_type)
            if issue_type == "relationship_transition_needs_review":
                step["action"] = (
                    "打开关系历史页，补充关系转折证据或修正记忆后，再重跑 continuity/gate。"
                )
        for item in navigation_items:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("stage") or item.get("report") or "review")
            step = by_stage.get(stage)
            if step is None:
                continue
            targets = step["targets"]
            if not isinstance(targets, list):
                continue
            for target in item.get("targets", []):
                if not isinstance(target, dict):
                    continue
                compact = {
                    "kind": str(target.get("kind") or ""),
                    "path": str(target.get("path") or ""),
                    "field": str(target.get("field") or ""),
                    "label": str(target.get("label") or ""),
                }
                if compact not in targets:
                    targets.append(compact)
        return sorted(
            by_stage.values(),
            key=lambda step: self.priority_by_stage.get(str(step["stage"]), 99),
        )

    def _upgrade_severity(self, step: dict[str, object], severity: str) -> None:
        order = {"": 0, "low": 1, "medium": 2, "high": 3, "blocker": 4}
        current = str(step.get("severity") or "")
        if order.get(severity, 0) > order.get(current, 0):
            step["severity"] = severity

    def _recommended_next_action(self, steps: list[dict[str, object]]) -> str:
        if not steps:
            return "ready-to-accept-or-review"
        first = steps[0]
        stage = str(first.get("stage") or "")
        return f"resolve-{stage}-issues-and-rerun-chapter-gate"
