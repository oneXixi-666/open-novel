from __future__ import annotations

import json
import re
import shlex
import tempfile
from pathlib import Path

from open_novel.agents.process_control import run_cancellable_process
from open_novel.core.editorial_profile import PROMPT_PRESETS, EditorialProfileService
from open_novel.core.models import EditorialReviewIssue, EditorialReviewReport
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import DEFAULT_STYLE_PROFILE_PATH, StyleProfileService
from open_novel.core.text_support import text_supports_claim
from open_novel.core.writing_learning import WritingLearningService
from open_novel.security.path_guard import PathGuard


class EditorialReviewService:
    reviewer = "local-editor-v1"

    concrete_emotion_markers = {
        "心",
        "喉",
        "胸口",
        "指尖",
        "呼吸",
        "沉默",
        "停顿",
        "咬牙",
        "攥",
        "避开",
        "低声",
        "发冷",
        "发烫",
        "警惕",
        "压抑",
        "震惊",
    }
    told_emotion_markers = {
        "很伤心",
        "很难过",
        "十分愤怒",
        "非常害怕",
        "他感到",
        "她感到",
        "感觉到",
        "内心十分",
    }
    pressure_markers = {
        "逼",
        "压",
        "拦",
        "阻",
        "威胁",
        "代价",
        "失去",
        "暴露",
        "反噬",
        "追兵",
        "旧敌",
        "长老",
        "封锁",
        "不能",
        "必须",
    }
    cost_markers = {
        "代价",
        "失去",
        "暴露",
        "伤",
        "疼",
        "债",
        "牺牲",
        "反噬",
        "盯上",
        "危险",
        "关系",
    }
    static_markers = {
        "风景",
        "景色",
        "建筑",
        "院落",
        "山峰",
        "月光",
        "灯火",
        "空气",
        "四周",
        "周围",
        "安静",
        "静静",
        "缓缓",
        "慢慢",
    }

    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        editorial_profile_service: EditorialProfileService | None = None,
        style_profile_service: StyleProfileService | None = None,
        writing_learning_service: WritingLearningService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.editorial_profile_service = editorial_profile_service or EditorialProfileService(
            self.project_service
        )
        self.style_profile_service = style_profile_service or StyleProfileService(
            self.project_service
        )
        self.writing_learning_service = writing_learning_service or WritingLearningService(
            self.project_service
        )

    def report_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"runs/editorial-review-{normalized}.json"

    def read_report(self, root: Path, chapter_id: str) -> EditorialReviewReport:
        return EditorialReviewReport.model_validate_json(
            self.project_service.read_text(root, self.report_path(chapter_id))
        )

    def review_chapter(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None = None,
        backend: str = "local",
        command_template: str = "",
        timeout_seconds: int = 600,
        profile_id: str = "",
    ) -> EditorialReviewReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        source = draft_path or f"drafts/{normalized}.generated.md"
        text = self.project_service.read_text(root, source)
        contract = self.story_guidance.read_scene_contract(root, normalized).model_dump(
            mode="json"
        )
        active_profile = None
        reviewer = self.reviewer
        prompt_preset = "generic-humanity"
        style_profile_path = DEFAULT_STYLE_PROFILE_PATH
        style_profile = self.style_profile_service.read_project_profile(root, style_profile_path)
        rubric = PROMPT_PRESETS["generic-humanity"]
        if profile_id.strip():
            active_profile = self.editorial_profile_service.get_profile(root, profile_id)
            backend = active_profile.backend
            command_template = active_profile.commandTemplate
            timeout_seconds = active_profile.timeoutSeconds
            reviewer = active_profile.reviewer or active_profile.label or active_profile.id
            prompt_preset = active_profile.promptPreset
            style_profile_path = active_profile.styleProfilePath
            style_profile = self.style_profile_service.read_project_profile(
                root,
                style_profile_path,
            )
            rubric = self.editorial_profile_service.rubric_for_profile(active_profile)
        if backend == "command":
            return self._review_with_command(
                root,
                normalized,
                source,
                text,
                contract,
                command_template,
                timeout_seconds,
                reviewer if active_profile else "llm-editor-command",
                active_profile.id if active_profile else "",
                prompt_preset,
                style_profile_path,
                style_profile.model_dump(mode="json"),
                rubric,
            )
        if backend != "local":
            raise ValueError(f"unsupported editorial review backend: {backend}")
        return self._review_locally(
            root,
            normalized,
            source,
            text,
            contract,
            reviewer=reviewer,
            profile_id=active_profile.id if active_profile else "",
            prompt_preset=prompt_preset,
            style_profile_path=style_profile_path,
            style_profile_id=style_profile.id,
        )

    def _review_locally(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        text: str,
        contract: dict[str, object],
        reviewer: str | None = None,
        profile_id: str = "",
        prompt_preset: str = "generic-humanity",
        style_profile_path: str = DEFAULT_STYLE_PROFILE_PATH,
        style_profile_id: str = "",
    ) -> EditorialReviewReport:
        body = self._body_text(text)
        paragraphs = [paragraph.strip() for paragraph in body.splitlines() if paragraph.strip()]
        ending = "\n".join(paragraphs[-2:]) if paragraphs else body[-220:]
        metrics = {
            "characters": len(body),
            "paragraphs": len(paragraphs),
            "dialogueLines": self._dialogue_count(paragraphs),
            "concreteEmotionMarkers": self._marker_count(body, self.concrete_emotion_markers),
            "toldEmotionMarkers": self._marker_count(body, self.told_emotion_markers),
            "pressureMarkers": self._marker_count(body, self.pressure_markers),
            "costMarkers": self._marker_count(body, self.cost_markers),
            "staticDescriptionMarkers": self._marker_count(body, self.static_markers),
            "reactionParagraphs": self._reaction_paragraph_count(paragraphs),
            "backend": "local",
            "promptPreset": prompt_preset,
            "styleProfilePath": style_profile_path,
            "styleProfileId": style_profile_id,
        }
        if profile_id:
            metrics["profileId"] = profile_id
        issues: list[EditorialReviewIssue] = []
        issues.extend(self._emotion_issues(source, body, metrics, contract))
        issues.extend(self._human_core_issues(source, body, contract))
        issues.extend(self._pressure_issues(source, metrics))
        issues.extend(self._payoff_issues(source, body, contract, metrics))
        issues.extend(self._subtext_issues(source, body, contract, metrics))
        issues.extend(self._aftertaste_issues(source, ending, contract))
        issues.extend(self._pacing_issues(source, metrics))
        score = self._score(issues)
        report = EditorialReviewReport(
            chapterId=chapter_id,
            source=source,
            reviewer=reviewer or self.reviewer,
            score=score,
            status=self._status(issues, score),
            issues=issues,
            strengths=self._strengths(body, ending, contract, metrics),
            metrics=metrics,
            recommendedNextAction=self._recommended_next_action(issues, score),
        )
        self.project_service.write_text(
            root,
            self.report_path(chapter_id),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self.writing_learning_service.learn_from_editorial_review(root, report)
        return report

    def _review_with_command(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        text: str,
        contract: dict[str, object],
        command_template: str,
        timeout_seconds: int,
        reviewer: str,
        profile_id: str,
        prompt_preset: str,
        style_profile_path: str,
        style_profile: dict[str, object],
        rubric: list[str],
    ) -> EditorialReviewReport:
        if not command_template.strip():
            raise ValueError("editorial command backend requires a command template")
        database_project = self.project_service.is_database_project(root)
        run_relative_dir = f"runs/editorial-review-{chapter_id}-command"
        run_dir = (
            Path(tempfile.mkdtemp(prefix=f"open-novel-editorial-{chapter_id}-"))
            if database_project
            else PathGuard(root).resolve(run_relative_dir)
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.json"
        output_path = run_dir / "output.json"
        prompt = self._command_prompt(
            chapter_id,
            source,
            text,
            contract,
            prompt_preset,
            style_profile_path,
            style_profile,
            rubric,
        )
        prompt_text = json.dumps(prompt, ensure_ascii=False, indent=2) + "\n"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        if database_project:
            self.project_service.write_text(
                root,
                f"{run_relative_dir}/prompt.json",
                prompt_text,
            )
        execution_root = run_dir if database_project else root
        command = self._command_for_review(
            execution_root,
            command_template,
            prompt_path,
            output_path,
            chapter_id,
            source,
        )
        completed = run_cancellable_process(
            command,
            cwd=execution_root,
            timeout_seconds=max(1, timeout_seconds),
        )
        if completed["timedOut"]:
            raise RuntimeError("editorial review command timed out")
        if completed["cancelled"]:
            raise RuntimeError("editorial review command cancelled")
        exit_code = int(completed["exitCode"])
        stderr = str(completed["stderr"])
        stdout = str(completed["stdout"])
        if exit_code != 0:
            raise RuntimeError(stderr or "editorial review command failed")
        output_text = stdout.strip()
        if output_path.exists():
            file_output = output_path.read_text(encoding="utf-8").strip()
            if file_output:
                output_text = file_output
        if database_project:
            self.project_service.write_text(
                root,
                f"{run_relative_dir}/output.json",
                output_text,
            )
        report = self._parse_command_report(
            output_text,
            chapter_id,
            source,
            command,
            reviewer,
            profile_id,
            prompt_preset,
            style_profile_path,
            str(style_profile.get("id") or ""),
        )
        self.project_service.write_text(
            root,
            self.report_path(chapter_id),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self.writing_learning_service.learn_from_editorial_review(root, report)
        return report

    def _command_prompt(
        self,
        chapter_id: str,
        source: str,
        text: str,
        contract: dict[str, object],
        prompt_preset: str = "generic-humanity",
        style_profile_path: str = DEFAULT_STYLE_PROFILE_PATH,
        style_profile: dict[str, object] | None = None,
        rubric: list[str] | None = None,
    ) -> dict[str, object]:
        active_rubric = rubric or PROMPT_PRESETS["generic-humanity"]
        return {
            "task": "Return only an EditorialReviewReport JSON object.",
            "promptPreset": prompt_preset,
            "styleProfilePath": style_profile_path,
            "styleProfile": style_profile or {},
            "schema": {
                "chapterId": "string",
                "source": "string",
                "reviewer": "string",
                "score": "integer 0..100",
                "status": "pass|warn|block",
                "issues": [
                    {
                        "type": (
                            "emotion_told_not_felt|emotion_lacks_specificity|"
                            "abstract_human_core|motivation_not_personal|"
                            "relationship_turn_unearned|scene_lacks_pressure|"
                            "payoff_without_cost|dialogue_lacks_subtext|"
                            "ending_lacks_aftertaste|description_outweighs_drama|"
                            "reader_focus_diffuse"
                        ),
                        "severity": "low|medium|high|blocker",
                        "dimension": (
                            "emotion|character|conflict|payoff|subtext|aftertaste|pacing"
                        ),
                        "evidence": ["file path or short anchor"],
                        "message": "short Chinese editorial note",
                        "suggestions": ["short actionable revision"],
                    }
                ],
                "strengths": ["short Chinese strength"],
                "metrics": {"freeform": "JSON object"},
                "recommendedNextAction": "short action id",
            },
            "rubric": active_rubric,
            "chapterId": chapter_id,
            "source": source,
            "sceneContract": contract,
            "chapterText": text,
        }

    def _command_for_review(
        self,
        root: Path,
        command_template: str,
        prompt_path: Path,
        output_path: Path,
        chapter_id: str,
        source: str,
    ) -> list[str]:
        formatted = command_template.format(
            project=str(root),
            prompt_file=str(prompt_path),
            output_file=str(output_path),
            chapter_id=chapter_id,
            source=source,
        )
        command = shlex.split(formatted)
        if not command:
            raise ValueError("empty editorial review command template")
        executable = command[0]
        if "/" in executable:
            resolved = Path(executable).expanduser()
            if not resolved.is_absolute():
                resolved = PathGuard(root).resolve(executable)
            command[0] = str(resolved)
        return command

    def _parse_command_report(
        self,
        output_text: str,
        chapter_id: str,
        source: str,
        command: list[str],
        default_reviewer: str = "llm-editor-command",
        profile_id: str = "",
        prompt_preset: str = "generic-humanity",
        style_profile_path: str = DEFAULT_STYLE_PROFILE_PATH,
        style_profile_id: str = "",
    ) -> EditorialReviewReport:
        if not output_text:
            raise ValueError("editorial review command produced no JSON")
        try:
            raw = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ValueError("editorial review command must output JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError("editorial review command must output a JSON object")
        raw["chapterId"] = chapter_id
        raw["source"] = source
        raw.setdefault("reviewer", default_reviewer or "llm-editor-command")
        raw.setdefault("issues", [])
        raw.setdefault("strengths", [])
        raw.setdefault("metrics", {})
        if "score" not in raw or "status" not in raw:
            issues = [
                EditorialReviewIssue.model_validate(issue)
                for issue in raw["issues"]
                if isinstance(issue, dict)
            ]
            score = self._score(issues)
            raw.setdefault("score", score)
            raw.setdefault("status", self._status(issues, score))
        metrics = raw["metrics"]
        if not isinstance(metrics, dict):
            metrics = {}
            raw["metrics"] = metrics
        metrics.setdefault("backend", "command")
        metrics.setdefault("command", command)
        metrics.setdefault("promptPreset", prompt_preset)
        metrics.setdefault("styleProfilePath", style_profile_path)
        if style_profile_id:
            metrics.setdefault("styleProfileId", style_profile_id)
        if profile_id:
            metrics.setdefault("profileId", profile_id)
        report = EditorialReviewReport.model_validate(raw)
        return report.model_copy(
            update={
                "score": max(0, min(100, report.score)),
                "recommendedNextAction": report.recommendedNextAction
                or self._recommended_next_action(report.issues, report.score),
            }
        )

    def _emotion_issues(
        self,
        source: str,
        body: str,
        metrics: dict[str, object],
        contract: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        emotional_beat = str(contract.get("emotionalBeat") or "")
        concrete = int(metrics["concreteEmotionMarkers"])
        told = int(metrics["toldEmotionMarkers"])
        reaction_paragraphs = int(metrics["reactionParagraphs"])
        if not emotional_beat:
            return []
        if concrete < 2 or reaction_paragraphs < 1 or not text_supports_claim(body, emotional_beat):
            return [
                EditorialReviewIssue(
                    type="emotion_told_not_felt",
                    severity="high",
                    dimension="emotion",
                    evidence=[source, "story/chapter-briefs"],
                    message="情绪线还没有变成可感知的行动、停顿、对白或身体反应。",
                    suggestions=[
                        "把情绪节拍拆成一个压力点、一个克制反应、一个改变选择的瞬间。",
                    ],
                )
            ]
        if told > concrete and told >= 2:
            return [
                EditorialReviewIssue(
                    type="emotion_told_not_felt",
                    severity="medium",
                    dimension="emotion",
                    evidence=[source],
                    message="情绪说明多于情绪呈现，读者容易知道人物在难受但感受不到。",
                    suggestions=["删掉直接说明，改成手势、停顿、误解、压住话头或代价反应。"],
                )
            ]
        return []

    def _human_core_issues(
        self,
        source: str,
        body: str,
        contract: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        fields = ["internalNeed", "woundOrFear", "stakes"]
        unsupported = [
            field
            for field in fields
            if str(contract.get(field) or "")
            and not text_supports_claim(body, str(contract[field]))
        ]
        if len(unsupported) < 2:
            return []
        return [
            EditorialReviewIssue(
                type="abstract_human_core",
                severity="high",
                dimension="character",
                evidence=[source, *[f"story/chapter-briefs#{field}" for field in unsupported]],
                message="人物内在需求、旧伤或失败代价没有进入正文，章节容易只剩事件推进。",
                suggestions=["让主角在同一个外部选择里同时暴露想要、害怕和可能失去的东西。"],
            )
        ]

    def _pressure_issues(
        self,
        source: str,
        metrics: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        if int(metrics["pressureMarkers"]) >= 3:
            return []
        return [
            EditorialReviewIssue(
                type="scene_lacks_pressure",
                severity="medium",
                dimension="conflict",
                evidence=[source],
                message="场景压力不足，人物选择还没有被逼到必须付出代价。",
                suggestions=["增加一个外部阻力、时间压力、关系威胁或错误选择后的即时后果。"],
            )
        ]

    def _payoff_issues(
        self,
        source: str,
        body: str,
        contract: dict[str, object],
        metrics: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        promises = contract.get("readerPromises")
        has_promise = isinstance(promises, list) and any(str(item).strip() for item in promises)
        cost = str(contract.get("cost") or "")
        if not has_promise:
            return []
        if int(metrics["costMarkers"]) >= 2 and (not cost or text_supports_claim(body, cost)):
            return []
        return [
            EditorialReviewIssue(
                type="payoff_without_cost",
                severity="medium",
                dimension="payoff",
                evidence=[source, "story/chapter-briefs#readerPromises"],
                message="读者承诺有推进，但行动代价不够清楚，爽点可能显得轻飘。",
                suggestions=["把小爽点和新麻烦绑在一起：赢一寸，也暴露一分或失去一点。"],
            )
        ]

    def _subtext_issues(
        self,
        source: str,
        body: str,
        contract: dict[str, object],
        metrics: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        subtext = str(contract.get("subtext") or "")
        if not subtext:
            return []
        has_subtext_action = bool(
            re.search(r"(沉默|停顿|避开|没说|没有解释|冷笑|咬牙|攥|低声|盯着)", body)
        )
        if int(metrics["dialogueLines"]) > 0 and has_subtext_action:
            return []
        return [
            EditorialReviewIssue(
                type="dialogue_lacks_subtext",
                severity="medium",
                dimension="subtext",
                evidence=[source, "story/chapter-briefs#subtext"],
                message="潜台词还没有通过对白空白、回避、误解或动作泄露出来。",
                suggestions=["安排一句没说完的话，或让角色用动作暴露嘴上不承认的真意。"],
            )
        ]

    def _aftertaste_issues(
        self,
        source: str,
        ending: str,
        contract: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        aftertaste = str(contract.get("aftertaste") or "")
        if not aftertaste:
            return []
        if text_supports_claim(ending, aftertaste) or re.search(
            r"(爽|疼|酸|不安|期待|危险|警惕|代价|沉默|余|盯上|裂开|回声)",
            ending,
        ):
            return []
        return [
            EditorialReviewIssue(
                type="ending_lacks_aftertaste",
                severity="medium",
                dimension="aftertaste",
                evidence=[source, "story/chapter-briefs#aftertaste"],
                message="结尾有情节信息，但情绪回声不足，读完后的余味不够明确。",
                suggestions=["最后两段保留一个未说出口的反应、关系变化或带代价的期待。"],
            )
        ]

    def _pacing_issues(
        self,
        source: str,
        metrics: dict[str, object],
    ) -> list[EditorialReviewIssue]:
        static = int(metrics["staticDescriptionMarkers"])
        pressure = int(metrics["pressureMarkers"])
        if static < 6 or pressure >= 3:
            return []
        return [
            EditorialReviewIssue(
                type="description_outweighs_drama",
                severity="low",
                dimension="pacing",
                evidence=[source],
                message="静态描写占比偏高，当前场景的戏剧压力被稀释。",
                suggestions=["保留能改变行动判断的景物，其余压缩成一两笔。"],
            )
        ]

    def _strengths(
        self,
        body: str,
        ending: str,
        contract: dict[str, object],
        metrics: dict[str, object],
    ) -> list[str]:
        strengths: list[str] = []
        if int(metrics["pressureMarkers"]) >= 3:
            strengths.append("场景压力明确，人物不是在真空里完成动作。")
        if int(metrics["concreteEmotionMarkers"]) >= 3:
            strengths.append("情绪有身体反应、停顿或动作承接。")
        cost = str(contract.get("cost") or "")
        if cost and text_supports_claim(body, cost):
            strengths.append("行动推进带有代价，爽点不完全悬浮。")
        subtext = str(contract.get("subtext") or "")
        if subtext and re.search(r"(沉默|停顿|避开|没说|没有解释|咬牙|低声)", body):
            strengths.append("人物互动有潜台词空间。")
        if re.search(r"(危险|警惕|代价|沉默|盯上|裂开|回声)", ending):
            strengths.append("结尾保留了继续追读的情绪余波。")
        return strengths[:5]

    def _body_text(self, text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _dialogue_count(self, paragraphs: list[str]) -> int:
        return sum(1 for paragraph in paragraphs if "“" in paragraph or '"' in paragraph)

    def _marker_count(self, text: str, markers: set[str]) -> int:
        return sum(1 for marker in markers if marker in text)

    def _reaction_paragraph_count(self, paragraphs: list[str]) -> int:
        pattern = re.compile(r"(沉默|停顿|咬牙|攥|避开|低声|胸口|指尖|呼吸|没有解释)")
        return sum(1 for paragraph in paragraphs if pattern.search(paragraph))

    def _status(self, issues: list[EditorialReviewIssue], score: int) -> str:
        if any(issue.severity == "blocker" for issue in issues) or score < 55:
            return "block"
        if issues:
            return "warn"
        return "pass"

    def _score(self, issues: list[EditorialReviewIssue]) -> int:
        penalty = {
            "blocker": 35,
            "high": 18,
            "medium": 10,
            "low": 4,
        }
        return max(0, 100 - sum(penalty[issue.severity] for issue in issues))

    def _recommended_next_action(
        self,
        issues: list[EditorialReviewIssue],
        score: int,
    ) -> str:
        if not issues:
            return "ready"
        if score < 55 or any(issue.severity == "blocker" for issue in issues):
            return "rewrite-editorial-core-before-acceptance"
        if any(issue.dimension == "emotion" for issue in issues):
            return "revise-emotion-through-action-dialogue-and-cost"
        if any(issue.dimension == "payoff" for issue in issues):
            return "attach-reader-payoff-to-visible-cost"
        return "review-editorial-warnings-before-acceptance"
