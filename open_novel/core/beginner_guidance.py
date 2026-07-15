from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from open_novel.core.models import NovelMetadata, SceneContract
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import StyleProfileService


class BeginnerProjectInput(BaseModel):
    path: Path
    title: str = "Untitled Novel"
    language: str = "zh-CN"
    idea: str = ""
    platform: str = "generic"
    genre: str = ""
    targetReaders: str = ""
    chapterWordTarget: int = 2500
    protagonistName: str = "主角"
    protagonistDesire: str = ""
    protagonistWound: str = ""
    opponent: str = ""
    worldRule: str = ""
    longMystery: str = ""
    corePromise: str = ""
    volumeGoal: str = ""
    styleProfileId: str = "generic-web-serial"
    chapterCount: int = 5


class BeginnerProjectResult(BaseModel):
    root: Path
    title: str
    chapterCount: int
    nextRoute: str
    createdFiles: list[str] = Field(default_factory=list)


class BeginnerGuidanceService:
    def __init__(
        self,
        project_service: ProjectService | None = None,
        story_guidance: StoryGuidanceService | None = None,
        style_profile_service: StyleProfileService | None = None,
    ) -> None:
        self.project_service = project_service or ProjectService()
        self.story_guidance = story_guidance or StoryGuidanceService(self.project_service)
        self.style_profile_service = style_profile_service or StyleProfileService(
            self.project_service
        )

    def create_guided_project(self, request: BeginnerProjectInput) -> BeginnerProjectResult:
        normalized = self._normalize_request(request)
        project = self.project_service.create_project(
            normalized.path,
            title=normalized.title,
            language=normalized.language,
        )
        metadata = NovelMetadata(
            title=normalized.title,
            language=normalized.language,
            genre=self._list_from_text(normalized.genre),
            targetReaders=normalized.targetReaders,
            chapterWordTarget=normalized.chapterWordTarget,
        )
        self.project_service.write_text(
            project.root,
            "novel.json",
            json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        self._apply_style(project.root, normalized)
        created = self._write_story_foundation(project.root, normalized)
        created.extend(self._write_memory(project.root, normalized))
        created.extend(self._write_scene_contracts(project.root, normalized))
        return BeginnerProjectResult(
            root=project.root,
            title=normalized.title,
            chapterCount=normalized.chapterCount,
            nextRoute=f"/chapter?root={project.root.as_posix()}&chapterId=001",
            createdFiles=created,
        )

    def _normalize_request(self, request: BeginnerProjectInput) -> BeginnerProjectInput:
        data = request.model_dump()
        data["title"] = self._fallback(request.title, "未命名小说")
        data["idea"] = self._fallback(request.idea, "一个普通人被迫面对改变命运的选择。")
        data["genre"] = self._fallback(request.genre, "通用网文")
        data["targetReaders"] = self._fallback(request.targetReaders, "喜欢连续追读的网文读者")
        data["protagonistName"] = self._fallback(request.protagonistName, "主角")
        data["protagonistDesire"] = self._fallback(
            request.protagonistDesire,
            "想改变现状，并证明自己能掌控命运。",
        )
        data["protagonistWound"] = self._fallback(
            request.protagonistWound,
            "害怕再次被否定，也害怕重要的人因自己受伤。",
        )
        data["opponent"] = self._fallback(request.opponent, "一个掌握规则和资源的阻力方")
        data["worldRule"] = self._fallback(
            request.worldRule,
            "每次获得机会都必须付出代价或暴露新的风险。",
        )
        data["longMystery"] = self._fallback(
            request.longMystery,
            "改变主角命运的真相尚未揭开。",
        )
        data["corePromise"] = self._fallback(
            request.corePromise,
            "主角会在压力下反击，但每次胜利都带来新的问题。",
        )
        data["volumeGoal"] = self._fallback(
            request.volumeGoal,
            "第一卷让主角完成第一次公开证明，并引出更大的危险。",
        )
        data["chapterWordTarget"] = max(800, min(int(request.chapterWordTarget or 2500), 12000))
        data["chapterCount"] = max(3, min(int(request.chapterCount or 5), 10))
        return BeginnerProjectInput.model_validate(data)

    def _apply_style(self, root: Path, request: BeginnerProjectInput) -> None:
        profile_id = request.styleProfileId.strip() or "generic-web-serial"
        try:
            self.style_profile_service.write_project_profile_from_builtin(root, profile_id)
        except ValueError:
            self.style_profile_service.write_project_profile_from_builtin(
                root,
                "generic-web-serial",
            )

    def _write_story_foundation(self, root: Path, request: BeginnerProjectInput) -> list[str]:
        protagonist_slug = self._slug(request.protagonistName)
        files = {
            "bible.md": self._bible(request),
            "style.md": self._style(request),
            "rules.md": self._rules(request),
            "outline.md": self._outline(request),
            "timeline.md": self._timeline(request),
            "notes/ideas.md": self._ideas(request),
            f"characters/{protagonist_slug}.md": self._protagonist_card(request),
        }
        for path, content in files.items():
            self.project_service.write_text(root, path, content)
        return sorted(files)

    def _write_memory(self, root: Path, request: BeginnerProjectInput) -> list[str]:
        protagonist_id = self._slug(request.protagonistName)
        memories: dict[str, object] = {
            "memory/facts.json": {
                "schemaVersion": 1,
                "facts": [
                    {
                        "id": "fact_initial_premise",
                        "text": request.idea,
                        "validFrom": "chapter:001",
                        "importance": "critical",
                        "confidence": 1,
                    },
                    {
                        "id": "fact_world_rule",
                        "text": request.worldRule,
                        "validFrom": "chapter:001",
                        "importance": "high",
                        "confidence": 1,
                    },
                ],
            },
            "memory/promises.json": {
                "schemaVersion": 1,
                "promises": [
                    {
                        "id": "promise_core_reader_payoff",
                        "text": request.corePromise,
                        "openedIn": "chapter:001",
                        "status": "active",
                        "payoffWindow": "1-5 chapters",
                    },
                    {
                        "id": "promise_long_mystery",
                        "text": request.longMystery,
                        "openedIn": "chapter:001",
                        "status": "active",
                        "payoffWindow": "5-20 chapters",
                    },
                ],
            },
            "memory/open-loops.json": {
                "schemaVersion": 1,
                "loops": [
                    {
                        "id": "loop_core_mystery",
                        "question": request.longMystery,
                        "openedIn": "chapter:001",
                        "status": "open",
                        "payoffExpectation": "first volume",
                    }
                ],
            },
            "memory/character-states.json": {
                "schemaVersion": 1,
                "characters": [
                    {
                        "characterId": protagonist_id,
                        "name": request.protagonistName,
                        "states": [
                            {
                                "chapterId": "001",
                                "externalGoal": request.protagonistDesire,
                                "emotion": "被压力推到必须选择的起点。",
                                "relationshipChanges": [],
                                "source": "beginner-wizard",
                                "evidence": ["characters/" + protagonist_id + ".md"],
                            }
                        ],
                    }
                ],
            },
        }
        for path, payload in memories.items():
            self.project_service.write_text(
                root,
                path,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
        return sorted(memories)

    def _write_scene_contracts(self, root: Path, request: BeginnerProjectInput) -> list[str]:
        created: list[str] = []
        for index in range(1, request.chapterCount + 1):
            contract = self._contract_for_index(request, index)
            self.story_guidance.write_scene_contract(root, contract)
            created.append(self.story_guidance.contract_path(contract.chapterId))
        return created

    def _contract_for_index(self, request: BeginnerProjectInput, index: int) -> SceneContract:
        chapter_id = f"{index:03d}"
        beats = [
            (
                "被迫选择",
                "让主角在可见压力下第一次面对核心矛盾。",
                "主角想守住眼前最重要的机会。",
                "阻力方用规则、资源或舆论压住主角。",
                "主角发现一个能撬动局面的异常线索。",
                "主角暂时保住机会，但也暴露了自己。",
                "新的问题把主角推向下一步调查。",
            ),
            (
                "代价反击",
                "让主角用行动反击一次误判。",
                "主角想证明自己不是只能被动挨打。",
                "阻力方设置一个失败就会失去更多的条件。",
                "主角利用第一章线索反推局面。",
                "主角赢下小局，但付出身体、关系或处境代价。",
                "线索指向更深的规则漏洞。",
            ),
            (
                "救人与失去",
                "让主角在收益和良心之间做选择。",
                "主角想拿到关键答案。",
                "旁人被卷入危险，逼主角分心。",
                "主角选择先救人，因此错过完整答案。",
                "主角获得信任，也留下证据和风险。",
                "被救的人透露长期谜题的一角。",
            ),
            (
                "深入规则",
                "让主角进入更危险的规则核心。",
                "主角想确认长期谜题和自己有什么关系。",
                "阻力方加强搜查，朋友或线人也可能不可靠。",
                "主角发现陷阱里藏着真正有用的证据。",
                "主角拿到阶段性证据，但暴露底牌。",
                "阻力方准备公开追责。",
            ),
            (
                "公开反转",
                "让主角用前面证据完成阶段性反击。",
                "主角想洗清眼前指控并保住继续追查的资格。",
                "阻力方试图把罪名和失败都压到主角身上。",
                "主角用代价换来的证据反咬对方逻辑漏洞。",
                "主角暂时获胜，但引来更高层注意。",
                "更大的势力提出新的问题或交易。",
            ),
        ]
        title, focus_tail, goal, conflict, turn, outcome, hook = beats[(index - 1) % len(beats)]
        protagonist = request.protagonistName
        return SceneContract(
            chapterId=chapter_id,
            title=f"第{index}章 {title}",
            pov=protagonist,
            time="第一卷开端",
            location="核心冲突现场",
            focus=f"{focus_tail} 核心创意：{request.idea}",
            goal=goal,
            conflict=f"{conflict} 主要阻力：{request.opponent}",
            turn=turn,
            outcome=outcome,
            hook=hook,
            emotionalBeat=f"{protagonist}从被压住转为主动做选择。",
            relationshipBeat=f"{protagonist}与阻力方的关系从被动承压变成正面拉扯。",
            internalNeed=request.protagonistDesire,
            woundOrFear=request.protagonistWound,
            stakes=f"如果失败，{protagonist}会失去推进目标的机会，并让长期谜题被别人掌控。",
            cost="每次推进都必须付出代价、暴露弱点或引来更大的风险。",
            subtext=f"{protagonist}表面处理眼前事件，实际在保护自己的尊严、秘密或重要关系。",
            aftertaste="读者应看到阶段推进，同时意识到问题还没有真正结束。",
            logicDependencies=[request.idea, request.worldRule],
            mustInclude=[request.protagonistName, request.opponent, request.worldRule],
            mustAvoid=["提前揭开长期谜题全部真相", "无代价解决冲突", "只用旁白说明情绪"],
            readerPromises=[request.corePromise, request.longMystery],
        )

    def _bible(self, request: BeginnerProjectInput) -> str:
        return (
            f"# Story Bible\n\n"
            f"## 一句话创意\n\n{request.idea}\n\n"
            f"## 主角\n\n- 名字：{request.protagonistName}\n"
            f"- 想要：{request.protagonistDesire}\n"
            f"- 伤口/恐惧：{request.protagonistWound}\n\n"
            f"## 核心阻力\n\n{request.opponent}\n\n"
            f"## 世界规则\n\n{request.worldRule}\n\n"
            f"## 长线谜题\n\n{request.longMystery}\n\n"
            f"## 第一卷目标\n\n{request.volumeGoal}\n"
        )

    def _style(self, request: BeginnerProjectInput) -> str:
        return (
            "# Style Guide\n\n"
            f"- 平台/题材：{request.platform} / {request.genre}\n"
            f"- 目标读者：{request.targetReaders}\n"
            "- 新手写作优先级：先写清目标、阻力、选择、代价和钩子，再追求辞藻。\n"
            "- 情绪不要只写标签，要落到动作、沉默、误解、对白和选择。\n"
            "- 每章结尾要留下新问题、危险、关系变化或未完成动作。\n"
        )

    def _rules(self, request: BeginnerProjectInput) -> str:
        return (
            "# Writing Rules\n\n"
            f"- 不提前揭开：{request.longMystery}\n"
            f"- 每次推进都受这条规则约束：{request.worldRule}\n"
            "- 主角不能无代价胜利。\n"
            "- 配角态度变化必须有证据。\n"
            "- 章节必须推进至少一个读者承诺、关系变化或剧情问题。\n"
        )

    def _outline(self, request: BeginnerProjectInput) -> str:
        return (
            "# Outline\n\n"
            f"## 第一卷目标\n\n{request.volumeGoal}\n\n"
            "## 前五章\n\n"
            "1. 被迫选择：主角进入核心冲突，发现异常线索。\n"
            "2. 代价反击：主角小胜，但付出代价。\n"
            "3. 救人与失去：主角为了人情或底线错过完整答案。\n"
            "4. 深入规则：主角拿到阶段证据，同时暴露底牌。\n"
            "5. 公开反转：主角阶段性获胜，引出更大势力。\n"
        )

    def _timeline(self, request: BeginnerProjectInput) -> str:
        return (
            "# Timeline\n\n"
            f"- 第1章：{request.protagonistName}被迫面对核心选择。\n"
            "- 第2章：主角用线索反击，但付出代价。\n"
            "- 第3章：主角在答案和人之间做选择。\n"
            "- 第4章：主角深入规则核心并暴露底牌。\n"
            "- 第5章：主角公开反转，引出更大的危险。\n"
        )

    def _ideas(self, request: BeginnerProjectInput) -> str:
        return (
            "# Ideas\n\n"
            f"- 初始灵感：{request.idea}\n"
            f"- 核心承诺：{request.corePromise}\n"
            f"- 长线谜题：{request.longMystery}\n"
        )

    def _protagonist_card(self, request: BeginnerProjectInput) -> str:
        return (
            f"# {request.protagonistName}\n\n"
            f"- 外部目标：{request.protagonistDesire}\n"
            f"- 内在伤口/恐惧：{request.protagonistWound}\n"
            f"- 初始误区：以为只要忍住或赢一次就能解决问题。\n"
            f"- 成长方向：学会在代价、关系和真相之间主动选择。\n"
            "- 语言习惯：先压住情绪，再用短句回应压力。\n"
        )

    def _fallback(self, value: str, fallback: str) -> str:
        return value.strip() if value and value.strip() else fallback

    def _list_from_text(self, value: str) -> list[str]:
        parts = [part.strip() for part in value.replace("，", ",").split(",")]
        return [part for part in parts if part]

    def _slug(self, value: str) -> str:
        ascii_slug = "".join(
            char.lower() if char.isalnum() else "-" for char in value.strip() if char.isascii()
        )
        ascii_slug = "-".join(part for part in ascii_slug.split("-") if part)
        return ascii_slug or "protagonist"
