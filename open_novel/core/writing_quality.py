from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from open_novel.core.models import WritingQualityIssue, WritingQualityReport
from open_novel.core.project import ProjectService
from open_novel.core.quality_calibration import QualityThresholdConfig
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.text_support import text_supports_claim
from open_novel.core.workbench_repository import WorkbenchRepository


class WritingQualityService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)

    def report_path(self, chapter_id: str) -> str:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        return f"runs/writing-quality-{normalized}.json"

    def evaluate_chapter(
        self,
        root: Path,
        chapter_id: str,
        draft_path: str | None = None,
        style_profile: str = "tomato",
        threshold_config: QualityThresholdConfig | None = None,
    ) -> WritingQualityReport:
        normalized = self.project_service.normalize_chapter_id(chapter_id)
        thresholds = threshold_config or WorkbenchRepository().read_quality_thresholds(root)
        source = draft_path or f"drafts/{normalized}.generated.md"
        text = self.project_service.read_text(root, source)
        contract = self.story_guidance.read_scene_contract(root, normalized)
        body = self._body_text(text)
        paragraphs = [paragraph.strip() for paragraph in body.splitlines() if paragraph.strip()]
        previous_similarity = self._previous_chapter_similarity_metrics(root, normalized, body)
        dialogue_lines = self._dialogue_line_count(paragraphs)
        scene_switches = self._marker_count(body, self.scene_switch_markers)
        anti_ai_markers = self._marker_count(body, self.anti_ai_markers)
        metrics = {
            "characters": len(body),
            "paragraphs": len(paragraphs),
            "dialogueLines": dialogue_lines,
            "dialogueRatio": round(dialogue_lines / max(1, len(paragraphs)), 3),
            "sceneSwitches": scene_switches,
            "antiAiMarkers": anti_ai_markers,
            "choiceMarkers": self._marker_count(body, self.choice_markers),
            "choiceMarkersDistinct": self._marker_distinct_count(body, self.choice_markers),
            "emotionMarkers": self._marker_count(body, self.emotion_markers),
            "emotionMarkersDistinct": self._marker_distinct_count(body, self.emotion_markers),
            "conflictMarkers": self._marker_count(body, self.conflict_markers),
            "conflictMarkersDistinct": self._marker_distinct_count(body, self.conflict_markers),
            "expositionMarkers": self._marker_count(body, self.exposition_markers),
            "expositionMarkersDistinct": self._marker_distinct_count(
                body,
                self.exposition_markers,
            ),
            "staticDescriptionMarkers": self._marker_count(
                body,
                self.static_description_markers,
            ),
            "staticDescriptionMarkersDistinct": self._marker_distinct_count(
                body,
                self.static_description_markers,
            ),
            "previousSimilarity": previous_similarity["jaccard"],
            "previousJaccardSimilarity": previous_similarity["jaccard"],
            "previousParagraphSimilarity": previous_similarity["paragraph"],
        }
        issues: list[WritingQualityIssue] = []
        issues.extend(self._length_issues(source, body, paragraphs, thresholds))
        issues.extend(self._sequence_quality_issues(source, body, metrics, thresholds))
        issues.extend(self._dialogue_ratio_issues(source, body, paragraphs, metrics))
        issues.extend(self._scene_switch_issues(source, metrics))
        issues.extend(self._anti_ai_issues(source, metrics))
        issues.extend(self._tomato_rhythm_issues(source, body, paragraphs, metrics, thresholds))
        issues.extend(
            self._contract_quality_issues(
                source,
                body,
                paragraphs,
                contract.model_dump(mode="json"),
                thresholds,
            )
        )
        issues.extend(self._emotional_continuity_issues(root, normalized, source, body))
        issues.extend(self._character_name_consistency_issues(root, source, body))

        report = WritingQualityReport(
            chapterId=normalized,
            source=source,
            styleProfile=style_profile,
            score=self._score(issues),
            issues=issues,
            metrics=metrics,
        )
        self.project_service.write_text(
            root,
            self.report_path(normalized),
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return report

    choice_markers = {
        "决定",
        "选择",
        "必须",
        "不能",
        "只好",
        "抬手",
        "转身",
        "咬牙",
        "踏",
        "挡",
        "握",
    }
    emotion_markers = {
        "心",
        "喉",
        "胸口",
        "指尖",
        "呼吸",
        "沉默",
        "咬牙",
        "发冷",
        "发烫",
        "警惕",
        "压抑",
        "震惊",
    }
    conflict_markers = {
        "阻",
        "逼",
        "压",
        "冷笑",
        "质问",
        "拦",
        "威胁",
        "代价",
        "忽然",
        "异动",
        "变了",
    }
    exposition_markers = {
        "据说",
        "传闻",
        "原来",
        "事实上",
        "很多年前",
        "设定",
        "规则是",
    }
    static_description_markers = {
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
    scene_switch_markers = {
        "与此同时",
        "另一边",
        "同一时间",
        "镜头一转",
        "画面一转",
        "回到",
        "转到",
        "另一处",
        "几分钟后",
        "片刻后",
        "次日",
    }
    anti_ai_markers = {
        "这让他意识到",
        "这让她意识到",
        "内心深处",
        "不禁感叹",
        "不禁想到",
        "某种意义上",
        "一种复杂的情绪",
        "无法言喻",
        "命运的齿轮",
        "空气仿佛凝固",
        "心中涌起",
    }

    def _length_issues(
        self,
        source: str,
        body: str,
        paragraphs: list[str],
        thresholds: QualityThresholdConfig,
    ) -> list[WritingQualityIssue]:
        issues: list[WritingQualityIssue] = []
        if len(body) < thresholds.min_chars_blocker:
            issues.append(
                WritingQualityIssue(
                    type="too_short",
                    severity="blocker",
                    evidence=[source],
                    message="章节正文过短，难以形成番茄式的冲突推进、情绪价值和结尾钩子。",
                    suggestions=["扩展到至少一个完整目标、阻碍、转折、结果、钩子链条。"],
                )
            )
        elif len(body) < thresholds.min_chars_medium:
            issues.append(
                WritingQualityIssue(
                    type="word_count_out_of_range",
                    severity="medium",
                    evidence=[source],
                    message="章节正文篇幅偏短，适合样章验证，但不宜作为稳定自动连载输出。",
                    suggestions=["扩展冲突过程、人物选择和结尾余波。"],
                )
            )
        if len(body) > thresholds.max_chars_medium:
            issues.append(
                WritingQualityIssue(
                    type="word_count_out_of_range",
                    severity="medium",
                    evidence=[source],
                    message="章节正文过长，当前自动生成链路难以稳定审稿和回滚。",
                    suggestions=["拆分为更清晰的章节目标，或压缩说明性段落。"],
                )
            )
        long_paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) > 420]
        if long_paragraphs:
            issues.append(
                WritingQualityIssue(
                    type="paragraph_too_long",
                    severity="medium",
                    evidence=[source],
                    message="存在过长段落，移动端阅读节奏会变慢。",
                    suggestions=["拆成更短的动作、对白、反应段落。"],
                )
            )
        return issues

    def _emotional_continuity_issues(
        self,
        root: Path,
        chapter_id: str,
        source: str,
        body: str,
    ) -> list[WritingQualityIssue]:
        incoming = self._incoming_emotion(root, chapter_id)
        if not incoming:
            return []
        opening = body[:300]
        if self._opening_handles_incoming_emotion(opening, incoming):
            return []
        return [
            WritingQualityIssue(
                type="emotional_discontinuity",
                severity="high",
                evidence=[source, f"memory/emotional-arcs.json#{incoming['source']}"],
                message="章节开头没有承接上一章的情绪出口，人物状态出现跳跃。",
                suggestions=["在开头补上一章情绪余波，或写出冷静、压抑、强作镇定等过渡动作。"],
            )
        ]

    def _character_name_consistency_issues(
        self,
        root: Path,
        source: str,
        body: str,
    ) -> list[WritingQualityIssue]:
        canonical_names = self._canonical_character_names(root)
        if not canonical_names:
            return []
        candidates = self._candidate_character_names(body)
        suspicious: list[tuple[str, str]] = []
        for candidate in candidates:
            if candidate in canonical_names:
                continue
            match = next(
                (
                    name
                    for name in canonical_names
                    if abs(len(candidate) - len(name)) <= 1
                    and self._edit_distance(candidate, name) == 1
                ),
                "",
            )
            if match:
                suspicious.append((candidate, match))
        return [
            WritingQualityIssue(
                type="character_name_inconsistency",
                severity="medium",
                evidence=[source, "memory/character-states.json"],
                message=f"疑似人物名称不一致：正文出现“{wrong}”，可能应为“{expected}”。",
                suggestions=["核对已登记角色名，统一正文中的人物称呼。"],
            )
            for wrong, expected in suspicious[:3]
        ]

    def _sequence_quality_issues(
        self,
        source: str,
        body: str,
        metrics: dict[str, object],
        thresholds: QualityThresholdConfig,
    ) -> list[WritingQualityIssue]:
        issues: list[WritingQualityIssue] = []
        previous_similarity = float(metrics.get("previousSimilarity") or 0)
        if previous_similarity >= thresholds.similarity_blocker:
            issues.append(
                WritingQualityIssue(
                    type="too_similar_to_previous",
                    severity="blocker",
                    evidence=[source],
                    message="本章和上一章正文高度相似，不能继续自动堆章节。",
                    suggestions=["重写本章场景、行动目标、阻力形式和结尾钩子。"],
                )
            )
        elif previous_similarity >= thresholds.similarity_high:
            issues.append(
                WritingQualityIssue(
                    type="too_similar_to_previous",
                    severity="high",
                    evidence=[source],
                    message="本章和上一章有明显重复，章节差异度不足。",
                    suggestions=["增加不同的场景推进、人物互动和信息转折。"],
                )
            )
        if len(body) < 900 and previous_similarity >= 0.5:
            issues.append(
                WritingQualityIssue(
                    type="word_count_out_of_range",
                    severity="medium",
                    evidence=[source],
                    message="章节篇幅偏短且与前章重复度偏高，质量证据不足。",
                    suggestions=["扩展本章独立目标、冲突过程和结果余波。"],
                )
            )
        return issues

    def _dialogue_ratio_issues(
        self,
        source: str,
        body: str,
        paragraphs: list[str],
        metrics: dict[str, object],
    ) -> list[WritingQualityIssue]:
        if len(body) < 600 or len(paragraphs) < 6:
            return []
        ratio = float(metrics.get("dialogueRatio") or 0)
        if ratio < 0.1:
            return [
                WritingQualityIssue(
                    type="dialogue_ratio_out_of_range",
                    severity="medium",
                    evidence=[source],
                    message="对白比例偏低，人物互动和关系压力容易不够直接。",
                    suggestions=["把关键冲突或试探改成短对白，让角色用话语推动选择。"],
                )
            ]
        if ratio > 0.6:
            return [
                WritingQualityIssue(
                    type="dialogue_ratio_out_of_range",
                    severity="medium",
                    evidence=[source],
                    message="对白比例过高，章节可能缺少动作、环境压力和结果落点。",
                    suggestions=["在对白之间补行动、反应、场景阻力和选择后果。"],
                )
            ]
        return []

    def _scene_switch_issues(
        self,
        source: str,
        metrics: dict[str, object],
    ) -> list[WritingQualityIssue]:
        switches = int(metrics.get("sceneSwitches") or 0)
        if switches <= 5:
            return []
        return [
            WritingQualityIssue(
                type="scene_switch_too_frequent",
                severity="low",
                evidence=[source],
                message="场景切换频率偏高，读者可能难以稳定跟住本章主冲突。",
                suggestions=["合并相邻视角或把切换压到章节点，确保每次切换都有明确目的。"],
            )
        ]

    def _anti_ai_issues(
        self,
        source: str,
        metrics: dict[str, object],
    ) -> list[WritingQualityIssue]:
        markers = int(metrics.get("antiAiMarkers") or 0)
        if markers < 2:
            return []
        return [
            WritingQualityIssue(
                type="anti_ai_trace",
                severity="low",
                evidence=[source],
                message="正文出现多处常见 AI 化表达，可能削弱具体场景质感。",
                suggestions=["把抽象感叹改成可见动作、具体感官、可验证的情绪触发。"],
            )
        ]

    def _tomato_rhythm_issues(
        self,
        source: str,
        body: str,
        paragraphs: list[str],
        metrics: dict[str, object],
        thresholds: QualityThresholdConfig,
    ) -> list[WritingQualityIssue]:
        issues: list[WritingQualityIssue] = []
        if metrics["dialogueLines"] == 0 and len(body) >= 600:
            issues.append(
                WritingQualityIssue(
                    type="missing_dialogue",
                    severity="medium",
                    evidence=[source],
                    message="章节缺少对白，人物关系和冲突容易显得没有人味。",
                    suggestions=["加入能改变局势或态度的短对白。"],
                )
            )
        if metrics["choiceMarkers"] < thresholds.choice_marker_min:
            issues.append(
                WritingQualityIssue(
                    type="missing_choice",
                    severity="medium",
                    evidence=[source],
                    message="角色选择和动作不足，章节容易变成说明而不是推进。",
                    suggestions=["让主角在压力下做至少两次具体选择或行动。"],
                )
            )
        if metrics["conflictMarkers"] < thresholds.conflict_marker_min:
            issues.append(
                WritingQualityIssue(
                    type="weak_conflict_escalation",
                    severity="high",
                    evidence=[source],
                    message="冲突升级不明显，番茄式爽点和压力不足。",
                    suggestions=["增加阻力、代价、误判、反击或局势反转。"],
                )
            )
        if (
            metrics["expositionMarkers"] >= thresholds.exposition_marker_max
            and metrics["choiceMarkers"] < 3
        ):
            issues.append(
                WritingQualityIssue(
                    type="over_exposition",
                    severity="medium",
                    evidence=[source],
                    message="说明性内容偏多，且没有足够动作承接。",
                    suggestions=["把设定压进冲突、对白或选择后果里。"],
                )
            )
        if metrics["staticDescriptionMarkers"] >= 6 and metrics["conflictMarkers"] < 3:
            issues.append(
                WritingQualityIssue(
                    type="over_exposition",
                    severity="low",
                    evidence=[source],
                    message="静态描写偏多，容易拖慢番茄式阅读节奏。",
                    suggestions=["把景物压缩成一两笔，让动作和冲突先走。"],
                )
            )
        ending = "\n".join(paragraphs[-3:]) if paragraphs else body[-300:]
        if not self._has_ending_pull(ending):
            issues.append(
                WritingQualityIssue(
                    type="weak_ending_hook",
                    severity="high",
                    evidence=[source],
                    message="结尾缺少继续追读的未完成问题、危险或承诺。",
                    suggestions=["用新信息、危险逼近、未完成动作或关系转折收尾。"],
                )
            )
        return issues

    def _contract_quality_issues(
        self,
        source: str,
        body: str,
        paragraphs: list[str],
        contract: dict[str, object],
        thresholds: QualityThresholdConfig,
    ) -> list[WritingQualityIssue]:
        issues: list[WritingQualityIssue] = []
        focus = str(contract.get("focus") or "")
        if focus and not text_supports_claim(body, focus):
            issues.append(
                WritingQualityIssue(
                    type="focus_not_supported",
                    severity="high",
                    evidence=[source],
                    message="正文没有明显支撑本章重点，容易抓不到主线。",
                    suggestions=["删减旁支，让关键场景直接服务 focus。"],
                )
            )
        goal = str(contract.get("goal") or "")
        if goal and not text_supports_claim(body, goal):
            issues.append(
                WritingQualityIssue(
                    type="chapter_goal_not_advanced",
                    severity="high",
                    evidence=[source],
                    message="正文没有明显推进本章目标，自动生成不应直接进入接收。",
                    suggestions=["把主角本章想达成的目标写成可见行动和阶段结果。"],
                )
            )
        emotional_beat = str(contract.get("emotionalBeat") or "")
        if emotional_beat and (
            not text_supports_claim(body, emotional_beat)
            or self._marker_count(body, self.emotion_markers) < max(
                2,
                thresholds.emotion_marker_min,
            )
        ):
            issues.append(
                WritingQualityIssue(
                    type="weak_emotional_grounding",
                    severity="high",
                    evidence=[source],
                    message="情绪节拍没有被动作、对白或身体反应充分落地。",
                    suggestions=["把情绪写成选择、停顿、反应、误解或关系余波。"],
                )
            )
        if (
            self._marker_count(body, self.emotion_markers) < thresholds.emotion_marker_min
            and len(body) >= 600
        ):
            issues.append(
                WritingQualityIssue(
                    type="weak_emotional_grounding",
                    severity="medium",
                    evidence=[source],
                    message="情绪落点太弱，正文里看不到明显的人物感受。",
                    suggestions=["补一处身体反应、停顿、犹豫、咬牙或关系余波。"],
                )
            )
        stakes = str(contract.get("stakes") or "")
        if stakes and not text_supports_claim(body, stakes):
            issues.append(
                WritingQualityIssue(
                    type="missing_stakes",
                    severity="high",
                    evidence=[source],
                    message="正文没有明显写出失败代价，人物选择缺少重量。",
                    suggestions=["把失败后会失去什么、伤到谁或错过什么写进冲突压力里。"],
                )
            )
        cost = str(contract.get("cost") or "")
        if cost and not text_supports_claim(body, cost):
            issues.append(
                WritingQualityIssue(
                    type="missing_cost",
                    severity="high",
                    evidence=[source],
                    message="正文没有明显写出行动代价，爽点容易显得无成本。",
                    suggestions=["让推进目标带来暴露、损失、债务、伤害或关系变化。"],
                )
            )
        subtext = str(contract.get("subtext") or "")
        if subtext and not self._supports_subtext(body, subtext):
            issues.append(
                WritingQualityIssue(
                    type="weak_subtext",
                    severity="medium",
                    evidence=[source],
                    message="潜台词没有被对白、停顿、回避或动作承接。",
                    suggestions=["让角色说半句、避开问题、误解对方，或用动作暴露真意。"],
                )
            )
        aftertaste = str(contract.get("aftertaste") or "")
        if aftertaste and not self._supports_aftertaste(paragraphs, aftertaste):
            issues.append(
                WritingQualityIssue(
                    type="weak_aftertaste",
                    severity="medium",
                    evidence=[source],
                    message="结尾缺少情绪余味，只有剧情钩子不够有回声。",
                    suggestions=["在最后两段留下爽感、酸涩、不安、期待或关系余波。"],
                )
            )
        promises = contract.get("readerPromises")
        if isinstance(promises, list):
            for promise in promises:
                promise_text = str(promise)
                if promise_text and not text_supports_claim(body, promise_text):
                    issues.append(
                        WritingQualityIssue(
                            type="reader_promise_not_advanced",
                            severity="medium",
                            evidence=[source],
                            message=f"读者承诺没有被明显建立或推进：{promise_text}",
                            suggestions=["加入能让读者感到承诺被推进或部分兑现的桥段。"],
                        )
                    )
                    break
        return issues

    def _body_text(self, text: str) -> str:
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            return "\n".join(lines[1:]).strip()
        return text.strip()

    def _incoming_emotion(self, root: Path, chapter_id: str) -> dict[str, str]:
        previous = self._previous_chapter_id(chapter_id)
        if not previous:
            return {}
        data = self._read_json(root, "memory/emotional-arcs.json")
        characters = data.get("characters") if isinstance(data, dict) else None
        if not isinstance(characters, list):
            return {}
        for character in characters:
            if not isinstance(character, dict) or not isinstance(character.get("beats"), list):
                continue
            beats = [
                beat
                for beat in character["beats"]
                if isinstance(beat, dict) and str(beat.get("chapterId") or "") == previous
            ]
            if not beats:
                continue
            beat = beats[-1]
            emotion = str(beat.get("beat") or beat.get("emotion") or "").strip()
            if emotion:
                return {"emotion": emotion, "source": previous}
        return {}

    def _opening_handles_incoming_emotion(self, opening: str, incoming: dict[str, str]) -> bool:
        emotion = incoming["emotion"]
        if text_supports_claim(opening, emotion):
            return True
        transition_markers = {
            "冷静下来",
            "压抑",
            "强作镇定",
            "强行镇定",
            "表面平静",
            "没有发作",
            "忍住",
            "克制",
            "余怒",
            "仍然警惕",
        }
        if any(marker in opening for marker in transition_markers):
            return True
        emotion_terms = {
            "愤怒",
            "不信任",
            "警惕",
            "压抑",
            "冷静",
            "克制",
            "决断",
            "紧张",
            "怀疑",
            "疑惑",
            "忌惮",
            "恐惧",
            "不安",
            "震惊",
        }
        required = [term for term in emotion_terms if term in emotion]
        return bool(required and any(term in opening for term in required))

    def _canonical_character_names(self, root: Path) -> set[str]:
        data = self._read_json(root, "memory/character-states.json")
        characters = data.get("characters") if isinstance(data, dict) else None
        if not isinstance(characters, list):
            return set()
        names: set[str] = set()
        for character in characters:
            if not isinstance(character, dict):
                continue
            for key in ("name", "characterId"):
                value = str(character.get(key) or "").strip()
                if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", value):
                    names.add(value)
        return names

    def _candidate_character_names(self, body: str) -> set[str]:
        matches = re.findall(
            r"(?<![\u4e00-\u9fa5])([\u4e00-\u9fa5]{2,4}?)(?:说|道|想|问|看|听)",
            body,
        )
        stop_words = {
            "这里",
            "如果",
            "他们",
            "所有",
            "正文",
            "章节",
            "读者",
            "下一刻",
            "今天",
            "昨天",
            "明天",
            "现在",
            "刚才",
            "忽然",
            "终于",
            "已经",
            "因为",
            "所以",
            "虽然",
            "但是",
            "然后",
            "最后",
            "第一",
            "这个",
            "那个",
            "什么",
            "怎么",
            "为什么",
            "怎样",
            "如何",
            "可能",
            "应该",
        }
        return {candidate for candidate in matches if candidate not in stop_words}

    def _edit_distance(self, left: str, right: str) -> int:
        previous = list(range(len(right) + 1))
        for left_index, left_char in enumerate(left, start=1):
            current = [left_index]
            for right_index, right_char in enumerate(right, start=1):
                current.append(
                    min(
                        previous[right_index] + 1,
                        current[right_index - 1] + 1,
                        previous[right_index - 1] + (left_char != right_char),
                    )
                )
            previous = current
        return previous[-1]

    def _read_json(self, root: Path, relative_path: str) -> object:
        if not self.project_service.file_exists(root, relative_path):
            return {}
        try:
            return json.loads(self.project_service.read_text(root, relative_path))
        except json.JSONDecodeError:
            return {}

    def _dialogue_line_count(self, paragraphs: list[str]) -> int:
        return sum(1 for paragraph in paragraphs if "“" in paragraph or '"' in paragraph)

    def _marker_count(self, text: str, markers: set[str]) -> int:
        return sum(text.count(marker) for marker in markers)

    def _marker_distinct_count(self, text: str, markers: set[str]) -> int:
        return sum(1 for marker in markers if marker in text)

    def _previous_chapter_similarity_metrics(
        self,
        root: Path,
        chapter_id: str,
        body: str,
    ) -> dict[str, float]:
        previous = self._previous_chapter_id(chapter_id)
        if not previous:
            return {"jaccard": 0.0, "paragraph": 0.0}
        previous_path = f"chapters/{previous}.md"
        if not self.project_service.file_exists(root, previous_path):
            return {"jaccard": 0.0, "paragraph": 0.0}
        previous_text = self._body_text(
            self.project_service.read_text(root, previous_path)
        )
        return self.text_similarity_metrics(body, previous_text)

    def text_similarity_metrics(self, left: str, right: str) -> dict[str, float]:
        jaccard = self._text_similarity(left, right)
        paragraph = self._paragraph_minhash_similarity(left, right) if jaccard >= 0.5 else 0.0
        return {"jaccard": round(jaccard, 3), "paragraph": round(paragraph, 3)}

    def _previous_chapter_id(self, chapter_id: str) -> str:
        if not chapter_id.isdigit():
            return ""
        number = int(chapter_id)
        if number <= 1:
            return ""
        return f"{number - 1:03d}"

    def _text_similarity(self, left: str, right: str) -> float:
        left_tokens = self._char_ngrams(left)
        right_tokens = self._char_ngrams(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _char_ngrams(self, text: str) -> set[str]:
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 4:
            return {compact} if compact else set()
        return {compact[index : index + 4] for index in range(len(compact) - 3)}

    def _paragraph_minhash_similarity(self, left: str, right: str) -> float:
        left_signatures = self._paragraph_signatures(left)
        right_signatures = self._paragraph_signatures(right)
        if not left_signatures or not right_signatures:
            return 0.0
        return max(
            self._signature_similarity(left_signature, right_signature)
            for left_signature in left_signatures
            for right_signature in right_signatures
        )

    def _paragraph_signatures(self, text: str) -> list[tuple[int, ...]]:
        signatures: list[tuple[int, ...]] = []
        for paragraph in [item.strip() for item in text.splitlines() if item.strip()]:
            tokens = self._char_ngrams(paragraph)
            if tokens:
                signatures.append(self._minhash_signature(tokens))
        return signatures

    def _minhash_signature(self, tokens: set[str]) -> tuple[int, ...]:
        values: list[int] = []
        for seed in range(32):
            values.append(
                min(
                    int.from_bytes(
                        hashlib.blake2b(
                            f"{seed}:{token}".encode(),
                            digest_size=8,
                        ).digest(),
                        "big",
                    )
                    for token in tokens
                )
            )
        return tuple(values)

    def _signature_similarity(self, left: tuple[int, ...], right: tuple[int, ...]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        matches = sum(
            1
            for left_item, right_item in zip(left, right, strict=True)
            if left_item == right_item
        )
        return matches / len(left)

    def _has_ending_pull(self, ending: str) -> bool:
        if "？" in ending or "?" in ending:
            return True
        patterns = [
            r"(忽然|却在这时|下一刻|身后|门外|信物|来信|名单|封锁|盯上|出现)",
            r"(不对劲|说不清|没想到|来不及|怎么可能|不可能|变了|不一样了)",
            r"[\d一二三四五六七八九十百千万亿]+[天年月日时分秒后]",
            r"(……|—{2,})",
            r"(他的名字|她的名字|那个人|一个声音|一道身影)",
            r"(拿出|掏出|递来|落在|映入)[^。]{0,20}(令牌|玉佩|信封|名帖|印鉴|血书)",
        ]
        return any(re.search(pattern, ending) for pattern in patterns)

    def _supports_subtext(self, body: str, subtext: str) -> bool:
        if text_supports_claim(body, subtext):
            return True
        has_dialogue = "“" in body or '"' in body
        has_subtext_action = re.search(
            r"(沉默|停顿|避开|没说|没有解释|冷笑|咬牙|攥|低声|盯着)",
            body,
        )
        return bool(has_dialogue and has_subtext_action)

    def _supports_aftertaste(self, paragraphs: list[str], aftertaste: str) -> bool:
        ending = "\n".join(paragraphs[-2:]) if paragraphs else ""
        if text_supports_claim(ending, aftertaste):
            return True
        return bool(
            re.search(
                r"(爽|疼|酸|不安|期待|危险|警惕|代价|沉默|余|盯上|线索|信物|裂痕)",
                ending,
            )
        )

    def _score(self, issues: list[WritingQualityIssue]) -> int:
        penalty = {
            "blocker": 35,
            "high": 18,
            "medium": 9,
            "low": 3,
        }
        return max(0, 100 - sum(penalty[issue.severity] for issue in issues))
