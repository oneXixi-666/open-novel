from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from open_novel.core.models import StyleProfile

if TYPE_CHECKING:
    from open_novel.core.project import ProjectService


DEFAULT_STYLE_PROFILE_ID = "generic-web-serial"
DEFAULT_STYLE_PROFILE_PATH = "story/style-profile.json"
ALLOWED_TEMPLATE_STATUSES = {"active", "candidate", "planned", "deprecated"}
ALLOWED_TEMPLATE_MATURITIES = {"baseline", "candidate", "validated", "reserved"}

BUILTIN_STYLE_PROFILES: dict[str, StyleProfile] = {
    DEFAULT_STYLE_PROFILE_ID: StyleProfile(
        id=DEFAULT_STYLE_PROFILE_ID,
        label="通用网文连载",
        platform="generic",
        genres=[],
        tone=["表达清晰", "情绪有依据", "适合连载"],
        readerExpectations=[
            "每章至少推进一个明确承诺、冲突、关系变化或问题。",
            "主角的选择应带来压力、代价或信息变化。",
            "章尾既要保留剧情牵引，也要留下情绪余味。",
        ],
        plotRhythm=[
            "从正在发生的场面切入，避免长篇铺垫。",
            "让原因、阻碍、转折、结果和钩子保持清晰。",
            "除非说明会改变当前冲突，否则压缩解释性内容。",
        ],
        emotionGuidance=[
            "通过行为、沉默、误读的对白、身体反应和选择表现情绪。",
            "把外部目标和人物的需要、伤口、恐惧、关系或尊严连接起来。",
            "即使本章有满足感，也要让回报伴随代价。",
        ],
        descriptionGuidance=[
            "描写应制造压力、揭示人物或改变可选行动。",
            "避免与当前场景无关的静态景物、机制和背景堆叠。",
        ],
        taboo=[
            "不要让平台或题材风格覆盖作品既定事实。",
            "不要通过忽略明确约束来解决场景。",
            "不要只用悲伤、愤怒、害怕等标签代替具体行动。",
        ],
        editorialFocus=[
            "人物具体性",
            "个人动机",
            "有依据的关系转折",
            "读者关注点",
            "带代价的回报",
            "连载钩子",
        ],
        notes=(
            "内置通用模板。作品可以保存自己的调整，后续版本也可以继续补充平台和题材模板。"
        ),
    ),
    "fanqie-xuanhuan-upgrade": StyleProfile(
        id="fanqie-xuanhuan-upgrade",
        label="番茄风格玄幻升级",
        extends=DEFAULT_STYLE_PROFILE_ID,
        platform="fanqie",
        genres=["xuanhuan", "upgrade", "web-serial"],
        tone=["爽点清晰", "压迫感强", "情绪直接但要有动作承托"],
        readerExpectations=[
            "每章至少推进一个可感知爽点、危机、反转、关系变化或升级线索。",
            "主角的赢要带代价或暴露新风险，避免无成本碾压。",
            "章尾保留明确钩子，让读者知道下一章要看什么。",
        ],
        plotRhythm=[
            "开场快速进入测试、冲突、追杀、审判、交易或选择现场。",
            "用压迫、误判、反击、代价、余波组织段落，不长时间解释体系。",
            "升级信息要和当章行动绑定，避免单独堆设定。",
        ],
        emotionGuidance=[
            "废柴、羞辱、亲情、尊严和旧怨要落到具体动作、对白和沉默。",
            "爽点前先让读者看见主角承受了什么，而不是直接宣布逆袭。",
            "配角态度转变要有可见证据，不能一句话从轻蔑变敬畏。",
        ],
        descriptionGuidance=[
            "环境描写服务压迫、等级差、危险感或选择限制。",
            "功法、灵器、境界描写要短，并立刻影响战局或人物判断。",
        ],
        taboo=[
            "不要用大段世界观解释替代当前冲突。",
            "不要让主角胜利没有代价、没有见证者、没有后续风险。",
            "不要把情绪只写成愤怒、震惊、激动等标签。",
        ],
        editorialFocus=[
            "爽点兑现",
            "升级代价",
            "压迫到反击",
            "尊严伤口",
            "章尾追读",
            "体系信息节制",
        ],
        notes=(
            "用于后续番茄玄幻调优的内置候选模板，只包含通用读者预期经验，"
            "不复制平台作品文本。"
        ),
    ),
    "urban-emotion-suspense": StyleProfile(
        id="urban-emotion-suspense",
        label="都市情感悬疑",
        extends=DEFAULT_STYLE_PROFILE_ID,
        platform="generic",
        genres=["urban", "emotion", "suspense"],
        tone=["克制", "关系张力强", "细节有指向"],
        readerExpectations=[
            "每章要同时推进现实压力、关系误会或线索疑点中的至少一项。",
            "人物说出口的话和真正想保护/隐藏的东西应有差异。",
            "悬念必须公平留痕，不能只靠作者隐瞒关键信息。",
        ],
        plotRhythm=[
            "从可见压力或关系场面切入，少用纯背景说明。",
            "线索、情绪和现实代价交替推进，避免单线拖沓。",
            "章尾用新证据、关系错位或选择后果制造追读。",
        ],
        emotionGuidance=[
            "情感冲突通过选择、回避、试探、误读和代价表现。",
            "亲密关系变化要有前后因果，不要突兀和解或突兀决裂。",
            "让人物保留体面、秘密或自欺，避免把内心全部解释干净。",
        ],
        descriptionGuidance=[
            "城市空间描写要服务身份、压力、阶层差异或线索。",
            "细节应能回扣人物关系或后续疑点。",
        ],
        taboo=[
            "不要用旁白直接解释所有误会。",
            "不要让线索只在揭晓时突然出现。",
            "不要把情绪冲突写成重复争吵。",
        ],
        editorialFocus=[
            "关系潜台词",
            "公平线索",
            "现实压力",
            "克制情绪",
            "选择代价",
        ],
        notes="用于后续扩充的都市情感悬疑通用候选模板。",
    ),
    "female-romance-growth": StyleProfile(
        id="female-romance-growth",
        label="女频情感成长",
        extends=DEFAULT_STYLE_PROFILE_ID,
        platform="generic",
        genres=["romance", "growth", "relationship"],
        tone=["细腻", "有拉扯", "人物成长清晰"],
        readerExpectations=[
            "每章推进关系认知、个人成长、外部阻力或承诺变化。",
            "情感转折要由互动和选择推动，而不是旁白宣布。",
            "甜、虐、爽都要和人物自尊、边界或愿望有关。",
        ],
        plotRhythm=[
            "场景围绕一次关系测试、边界选择或外部压力展开。",
            "用互动细节制造情绪波动，避免长段心理独白堆叠。",
            "章尾留下关系新状态或未说出口的问题。",
        ],
        emotionGuidance=[
            "让人物在喜欢、害怕、骄傲、退让之间做具体选择。",
            "关系升温要有试探、误解、保护或共同承担。",
            "成长线要体现边界感和自我判断，而不只是被拯救。",
        ],
        descriptionGuidance=[
            "外貌和场景描写优先服务情绪距离、身份差异或关系变化。",
            "细节要能反映人物是否被看见、被误解或被尊重。",
        ],
        taboo=[
            "不要让情感推进只依赖误会不沟通。",
            "不要让角色成长被单纯宠爱替代。",
            "不要用过密描写稀释场景核心情绪。",
        ],
        editorialFocus=[
            "关系递进",
            "边界与成长",
            "情绪细节",
            "互动因果",
            "未说出口的张力",
        ],
        notes="用于后续平台细分的情感成长通用候选模板。",
    ),
}

PLANNED_STYLE_PROFILE_SLOTS: list[dict[str, object]] = [
    {
        "id": "fanqie-urban-system",
        "platform": "fanqie",
        "genres": ["urban", "system", "comedy"],
        "label": "番茄都市系统流预留模板",
    },
    {
        "id": "fanqie-female-revenge",
        "platform": "fanqie",
        "genres": ["female", "revenge", "growth"],
        "label": "番茄女频复仇成长预留模板",
    },
    {
        "id": "fanqie-urban-combat-business",
        "platform": "fanqie",
        "genres": ["urban", "combat", "business", "power-progression"],
        "label": "番茄都市战斗商战预留模板",
    },
    {
        "id": "fanqie-male-fantasy-power-strategy",
        "platform": "fanqie",
        "genres": ["male", "fantasy", "power-strategy", "upgrade"],
        "label": "番茄男频玄幻权谋升级预留模板",
    },
    {
        "id": "fanqie-female-family-rebirth",
        "platform": "fanqie",
        "genres": ["female", "family", "rebirth", "revenge"],
        "label": "番茄女频家庭重生预留模板",
    },
    {
        "id": "douyin-micro-drama-reversal",
        "platform": "douyin",
        "genres": ["micro-drama", "reversal", "revenge", "high-hook"],
        "label": "抖音微短剧高反转预留模板",
    },
    {
        "id": "qidian-xianxia-longform",
        "platform": "qidian",
        "genres": ["xianxia", "cultivation", "longform"],
        "label": "起点仙侠长篇预留模板",
    },
    {
        "id": "qidian-sci-fi-tech",
        "platform": "qidian",
        "genres": ["sci-fi", "technology", "civilization"],
        "label": "起点科幻技术流预留模板",
    },
    {
        "id": "qidian-fantasy-kingdom-war",
        "platform": "qidian",
        "genres": ["fantasy", "kingdom-war", "faction", "longform"],
        "label": "起点奇幻王国战争预留模板",
    },
    {
        "id": "qidian-infinite-flow-survival",
        "platform": "qidian",
        "genres": ["infinite-flow", "survival", "team", "mystery"],
        "label": "起点无限流生存预留模板",
    },
    {
        "id": "jjwxc-romance-slowburn",
        "platform": "jjwxc",
        "genres": ["romance", "slowburn", "relationship"],
        "label": "晋江慢热情感预留模板",
    },
    {
        "id": "jjwxc-historical-romance",
        "platform": "jjwxc",
        "genres": ["historical", "romance", "court"],
        "label": "晋江古言宫廷预留模板",
    },
    {
        "id": "jjwxc-modern-romance-career",
        "platform": "jjwxc",
        "genres": ["modern-romance", "career", "relationship", "growth"],
        "label": "晋江现代情感职场预留模板",
    },
    {
        "id": "jjwxc-danmei-case-unit",
        "platform": "jjwxc",
        "genres": ["danmei", "case-unit", "relationship", "suspense"],
        "label": "晋江关系向单元悬疑预留模板",
    },
    {
        "id": "tomato-short-drama-revenge",
        "platform": "fanqie",
        "genres": ["short-drama", "revenge", "twist"],
        "label": "短剧复仇反转预留模板",
    },
    {
        "id": "suspense-crime-investigation",
        "platform": "generic",
        "genres": ["suspense", "crime", "investigation"],
        "label": "悬疑犯罪调查预留模板",
    },
    {
        "id": "historical-power-struggle",
        "platform": "generic",
        "genres": ["historical", "power-struggle", "strategy"],
        "label": "历史权谋预留模板",
    },
    {
        "id": "light-novel-adventure",
        "platform": "generic",
        "genres": ["light-novel", "adventure", "team"],
        "label": "轻小说冒险预留模板",
    },
    {
        "id": "horror-folk-mystery",
        "platform": "generic",
        "genres": ["horror", "folk", "mystery"],
        "label": "民俗恐怖悬疑预留模板",
    },
    {
        "id": "workplace-business-growth",
        "platform": "generic",
        "genres": ["workplace", "business", "growth"],
        "label": "职场商战成长预留模板",
    },
    {
        "id": "generic-military-techno-thriller",
        "platform": "generic",
        "genres": ["military", "techno-thriller", "mission", "strategy"],
        "label": "军事科技惊悚预留模板",
    },
    {
        "id": "generic-sports-competition-growth",
        "platform": "generic",
        "genres": ["sports", "competition", "team", "growth"],
        "label": "体育竞技成长预留模板",
    },
    {
        "id": "generic-food-healing-slice-of-life",
        "platform": "generic",
        "genres": ["food", "healing", "slice-of-life", "community"],
        "label": "美食治愈日常预留模板",
    },
    {
        "id": "generic-children-adventure-mystery",
        "platform": "generic",
        "genres": ["children", "adventure", "mystery", "friendship"],
        "label": "儿童冒险解谜预留模板",
    },
]

STYLE_PROFILE_COVERAGE_CATALOG: list[dict[str, object]] = [
    {
        "platform": "fanqie",
        "label": "番茄商业网文",
        "status": "mixed",
        "templateIds": ["fanqie-xuanhuan-upgrade"],
        "plannedTemplateIds": [
            "fanqie-urban-system",
            "fanqie-female-revenge",
            "fanqie-urban-combat-business",
            "fanqie-male-fantasy-power-strategy",
            "fanqie-female-family-rebirth",
            "tomato-short-drama-revenge",
        ],
        "genreFamilies": [
            "xuanhuan upgrade",
            "urban system",
            "female revenge/growth",
            "urban combat/business",
            "male fantasy power strategy",
            "female family rebirth",
            "short-drama twist",
        ],
        "maintenanceNotes": (
            "仅使用经过调校和验证的已启用模板；规划中模板用于预留后续平台与题材扩展。"
        ),
    },
    {
        "platform": "douyin",
        "label": "抖音短篇与微短剧预留模板",
        "status": "planned",
        "templateIds": [],
        "plannedTemplateIds": ["douyin-micro-drama-reversal"],
        "genreFamilies": ["micro-drama reversal", "revenge", "high-frequency hooks"],
        "maintenanceNotes": (
            "用于短篇章节节奏和高密度反转；五章评估确认可读性与情绪清晰度后再启用。"
        ),
    },
    {
        "platform": "qidian",
        "label": "起点长篇类型小说",
        "status": "planned",
        "templateIds": [],
        "plannedTemplateIds": [
            "qidian-xianxia-longform",
            "qidian-sci-fi-tech",
            "qidian-fantasy-kingdom-war",
            "qidian-infinite-flow-survival",
        ],
        "genreFamilies": [
            "xianxia cultivation",
            "sci-fi technology",
            "civilization and power progression",
            "long-form faction conflict",
            "kingdom war",
            "infinite flow survival",
        ],
        "maintenanceNotes": (
            "用于较慢的长篇推进、势力经营、体系成长和设定承载。"
        ),
    },
    {
        "platform": "jjwxc",
        "label": "晋江关系驱动小说",
        "status": "planned",
        "templateIds": [],
        "plannedTemplateIds": [
            "jjwxc-romance-slowburn",
            "jjwxc-historical-romance",
            "jjwxc-modern-romance-career",
            "jjwxc-danmei-case-unit",
        ],
        "genreFamilies": [
            "slow-burn romance",
            "historical romance",
            "modern romance career",
            "relationship-led case unit",
            "relationship growth",
            "court and family pressure",
        ],
        "maintenanceNotes": (
            "用于细腻情绪、关系状态变化和较慢兑现节奏。"
        ),
    },
    {
        "platform": "generic",
        "label": "跨平台题材预留模板",
        "status": "mixed",
        "templateIds": [
            "generic-web-serial",
            "urban-emotion-suspense",
            "female-romance-growth",
        ],
        "plannedTemplateIds": [
            "suspense-crime-investigation",
            "historical-power-struggle",
            "light-novel-adventure",
            "horror-folk-mystery",
            "workplace-business-growth",
            "generic-military-techno-thriller",
            "generic-sports-competition-growth",
            "generic-food-healing-slice-of-life",
            "generic-children-adventure-mystery",
        ],
        "genreFamilies": [
            "urban emotion suspense",
            "romance growth",
            "crime investigation",
            "historical power struggle",
            "light novel adventure",
            "folk horror",
            "workplace/business growth",
            "military techno-thriller",
            "sports competition",
            "food healing",
            "children adventure mystery",
        ],
        "maintenanceNotes": (
            "为尚未锁定平台的作品提供通用覆盖，作者可随时通过项目写法配置进行调整。"
        ),
    },
    {
        "platform": "broad-reserve",
        "label": "内置题材预留总览",
        "status": "extension-point",
        "templateIds": [],
        "plannedTemplateIds": [
            "fanqie-urban-combat-business",
            "fanqie-male-fantasy-power-strategy",
            "fanqie-female-family-rebirth",
            "qidian-fantasy-kingdom-war",
            "qidian-infinite-flow-survival",
            "jjwxc-modern-romance-career",
            "jjwxc-danmei-case-unit",
            "generic-military-techno-thriller",
            "generic-sports-competition-growth",
            "generic-food-healing-slice-of-life",
            "generic-children-adventure-mystery",
        ],
        "genreFamilies": [
            "urban combat/business",
            "male fantasy power strategy",
            "female family rebirth",
            "kingdom war",
            "infinite flow survival",
            "modern romance career",
            "relationship-led case unit",
            "military techno-thriller",
            "sports competition",
            "food healing",
            "children adventure mystery",
        ],
        "maintenanceNotes": (
            "这是扩展更多平台和题材的内置入口；规划中模板通过评估后可以直接升级为启用模板。"
        ),
    },
    {
        "platform": "extension",
        "label": "用户维护的平台或题材模板",
        "status": "extension-point",
        "templateIds": [],
        "plannedTemplateIds": [],
        "genreFamilies": [
            "custom platform",
            "custom genre",
            "house style",
            "author-specific constraints",
        ],
        "maintenanceNotes": (
            "当前支持作者通过项目写法配置扩展；经过验证的项目写法后续可以沉淀为内置模板。"
        ),
    },
]

STYLE_TEMPLATE_PACKS: list[dict[str, object]] = [
    {
        "id": "builtin-broad-genre-reserve",
        "label": "内置综合题材预留包",
        "status": "reserved",
        "scope": "platform-and-genre",
        "activeProfileIds": [],
        "plannedProfileIds": [str(slot["id"]) for slot in PLANNED_STYLE_PROFILE_SLOTS],
        "coveragePlatforms": [
            "fanqie",
            "douyin",
            "qidian",
            "jjwxc",
            "generic",
            "broad-reserve",
            "extension",
        ],
        "maintenancePolicy": {
            "activation": "planned-slot-to-candidate-to-active",
            "minimumSampleChapters": 5,
            "requiresHumanReview": True,
            "allowDirectUserOverride": "story/style-profile.json",
        },
        "maintenanceNotes": (
            "预留给后续大型平台与题材模板包。"
            "候选模板通过五章评估和人工复核前保持计划状态。"
        ),
    }
]


class StyleProfileService:
    default_profile_path = DEFAULT_STYLE_PROFILE_PATH

    def __init__(self, project_service: ProjectService | None = None) -> None:
        from open_novel.core.project import ProjectService as _ProjectService

        self.project_service = project_service or _ProjectService()

    @staticmethod
    def default_project_profile_text() -> str:
        profile = StyleProfile(
            id="project-style",
            label="作品自定义写法",
            extends=DEFAULT_STYLE_PROFILE_ID,
            platform="generic",
            genres=[],
            notes=(
                "可按平台或题材调整。保留继承关系即可沿用通用网文模板，也可以覆盖具体字段。"
            ),
        )
        return json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    def read_project_profile(
        self,
        root: Path,
        relative_path: str = DEFAULT_STYLE_PROFILE_PATH,
    ) -> StyleProfile:
        if not self.project_service.file_exists(root, relative_path):
            return self.get_builtin_profile(DEFAULT_STYLE_PROFILE_ID)
        raw = json.loads(self.project_service.read_text(root, relative_path))
        if not isinstance(raw, dict):
            raise ValueError(f"style profile must be a JSON object: {relative_path}")
        return self.resolve_profile(raw)

    def resolve_profile(self, raw: dict[str, Any]) -> StyleProfile:
        extends = str(raw.get("extends") or "").strip()
        if extends:
            base = self.builtin_catalog().get(extends)
            if base is None:
                raise FileNotFoundError(f"missing built-in style profile: {extends}")
            merged = self._merge_profile_data(base.model_dump(mode="json"), raw)
            return StyleProfile.model_validate(merged)
        return StyleProfile.model_validate(raw)

    def builtin_catalog(self) -> dict[str, StyleProfile]:
        return self._load_builtin_profiles()

    def list_builtin_profiles(self) -> list[StyleProfile]:
        return sorted(self.builtin_catalog().values(), key=lambda profile: profile.id)

    def list_planned_profile_slots(self) -> list[dict[str, object]]:
        existing = set(self.builtin_catalog())
        return sorted(
            [
                slot
                for slot in self._load_planned_profile_slots()
                if str(slot.get("id", "")) not in existing
            ],
            key=lambda slot: str(slot["id"]),
        )

    def list_coverage_catalog(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._load_coverage_catalog()]

    def list_template_packs(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._load_template_packs()]

    def get_planned_profile_slot(self, slot_id: str) -> dict[str, object]:
        normalized = self._normalize_profile_id(slot_id)
        for slot in self.list_planned_profile_slots():
            if str(slot.get("id", "")) == normalized:
                return dict(slot)
        raise FileNotFoundError(f"missing planned style profile slot: {normalized}")

    def template_maintenance_policy(self) -> dict[str, object]:
        policy = self._load_catalog_data().get("templateMaintenancePolicy", {})
        if not isinstance(policy, dict):
            raise ValueError("style catalog templateMaintenancePolicy must be an object")
        return dict(policy)

    def validate_catalog(self) -> dict[str, object]:
        """Validate built-in style catalog references for maintenance workflows."""
        profiles = self.builtin_catalog()
        builtin_ids = set(profiles)
        planned_ids = {str(slot["id"]) for slot in self._load_planned_profile_slots()}
        coverage_platforms = {
            str(item.get("platform", ""))
            for item in self._load_coverage_catalog()
            if str(item.get("platform", "")).strip()
        }
        unknown_active: list[str] = []
        unknown_planned: list[str] = []
        unknown_pack_coverage: list[str] = []
        invalid_profiles: list[str] = []
        for profile in profiles.values():
            data = profile.model_dump(mode="json")
            status = str(data.get("templateStatus") or "").strip()
            maturity = str(data.get("maturity") or "").strip()
            criteria = data.get("promotionCriteria")
            if status not in ALLOWED_TEMPLATE_STATUSES:
                invalid_profiles.append(f"{profile.id}:templateStatus")
            if status != "active":
                invalid_profiles.append(f"{profile.id}:must-be-active")
            if maturity not in ALLOWED_TEMPLATE_MATURITIES:
                invalid_profiles.append(f"{profile.id}:maturity")
            if not isinstance(criteria, dict):
                invalid_profiles.append(f"{profile.id}:promotionCriteria")
            else:
                if int(criteria.get("requiredSampleChapters") or 0) < 5:
                    invalid_profiles.append(f"{profile.id}:requiredSampleChapters")
                if int(criteria.get("minimumGateScore") or 0) < 80:
                    invalid_profiles.append(f"{profile.id}:minimumGateScore")
                if int(criteria.get("minimumQualityScore") or 0) < 80:
                    invalid_profiles.append(f"{profile.id}:minimumQualityScore")
                checklist = criteria.get("reviewChecklist")
                if not isinstance(checklist, list) or len(checklist) < 3:
                    invalid_profiles.append(f"{profile.id}:reviewChecklist")
        for item in self._load_coverage_catalog():
            for profile_id in item.get("templateIds", []):
                if str(profile_id) not in builtin_ids:
                    unknown_active.append(str(profile_id))
            for profile_id in item.get("plannedTemplateIds", []):
                if str(profile_id) not in planned_ids and str(profile_id) not in builtin_ids:
                    unknown_planned.append(str(profile_id))
        for pack in self._load_template_packs():
            pack_id = str(pack.get("id") or "").strip()
            status = str(pack.get("status") or "").strip()
            if not pack_id:
                invalid_profiles.append("templatePacks:id")
            if status not in {"active", "candidate", "reserved", "deprecated"}:
                invalid_profiles.append(f"{pack_id or 'templatePacks'}:status")
            for profile_id in pack.get("activeProfileIds", []):
                if str(profile_id) not in builtin_ids:
                    unknown_active.append(str(profile_id))
            for profile_id in pack.get("plannedProfileIds", []):
                if str(profile_id) not in planned_ids and str(profile_id) not in builtin_ids:
                    unknown_planned.append(str(profile_id))
            for platform in pack.get("coveragePlatforms", []):
                if str(platform) not in coverage_platforms:
                    unknown_pack_coverage.append(f"{pack_id}:{platform}")
        policy = self.template_maintenance_policy()
        activation_criteria = policy.get("plannedSlotActivationCriteria")
        if not isinstance(activation_criteria, dict):
            invalid_profiles.append("templateMaintenancePolicy:plannedSlotActivationCriteria")
        elif int(activation_criteria.get("requiredSampleChapters") or 0) < 5:
            invalid_profiles.append("templateMaintenancePolicy:requiredSampleChapters")
        if unknown_active or unknown_planned or unknown_pack_coverage or invalid_profiles:
            details = {
                "unknownActiveTemplateIds": sorted(set(unknown_active)),
                "unknownPlannedTemplateIds": sorted(set(unknown_planned)),
                "unknownPackCoveragePlatforms": sorted(set(unknown_pack_coverage)),
                "invalidProfiles": sorted(set(invalid_profiles)),
            }
            raise ValueError(f"invalid style catalog references: {details}")
        return {
            "profileCount": len(builtin_ids),
            "plannedSlotCount": len(planned_ids - builtin_ids),
            "coverageCount": len(self._load_coverage_catalog()),
            "templatePackCount": len(self._load_template_packs()),
            "policy": policy,
        }

    def get_builtin_profile(self, profile_id: str) -> StyleProfile:
        profile_id = self._normalize_profile_id(profile_id)
        profile = self.builtin_catalog().get(profile_id)
        if profile is None:
            raise FileNotFoundError(f"missing built-in style profile: {profile_id}")
        return profile

    def draft_profile_from_planned_slot(
        self,
        slot_id: str,
        *,
        label: str = "",
    ) -> StyleProfile:
        slot = self.get_planned_profile_slot(slot_id)
        slot_id = str(slot["id"])
        activation = self.template_maintenance_policy().get(
            "plannedSlotActivationCriteria",
            {},
        )
        if not isinstance(activation, dict):
            activation = {}
        required_reviews = [
            str(item) for item in activation.get("requiredReviews", []) if str(item).strip()
        ]
        profile = StyleProfile(
            id=slot_id,
            label=label or str(slot.get("label") or slot_id),
            extends=DEFAULT_STYLE_PROFILE_ID,
            platform=str(slot.get("platform") or "generic"),
            genres=[str(item) for item in slot.get("genres", [])],
            tone=["TODO: define platform and genre-specific tone."],
            readerExpectations=[
                "TODO: define reader-facing promise, payoff, and pacing expectations.",
            ],
            plotRhythm=[
                "TODO: define opening pressure, middle turn, outcome, and chapter hook rhythm.",
            ],
            emotionGuidance=[
                "TODO: define how this template renders emotion through action and choice.",
            ],
            descriptionGuidance=[
                "TODO: define which descriptions carry pressure, clue, relationship, or payoff.",
            ],
            taboo=[
                "TODO: list genre-specific failure modes and platform rhythm risks.",
            ],
            editorialFocus=required_reviews
            or [
                "continuity",
                "humanity",
                "platform-rhythm",
                "risk-control",
            ],
            notes=(
                f"Candidate draft generated from planned slot {slot_id}. "
                "Fill TODO fields, run five-chapter evaluation, then promote only after "
                "the catalog activation gate passes."
            ),
            templateStatus="candidate",
            maturity="candidate",
            sourcePlannedSlotId=slot_id,
            promotionCriteria={
                "requiredSampleChapters": activation.get("requiredSampleChapters", 5),
                "minimumGateScore": activation.get("minimumGateScore", 90),
                "minimumQualityScore": activation.get("minimumQualityScore", 90),
                "reviewChecklist": required_reviews,
                "requiredArtifacts": activation.get("requiredArtifacts", []),
                "riskControls": activation.get("riskControls", []),
            },
        )
        return profile

    def draft_profile_text_from_planned_slot(
        self,
        slot_id: str,
        *,
        label: str = "",
    ) -> str:
        profile = self.draft_profile_from_planned_slot(slot_id, label=label)
        return json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"

    def write_project_profile_from_builtin(
        self,
        root: Path,
        profile_id: str,
        *,
        project_profile_id: str = "project-style",
        label: str = "Project style override",
        relative_path: str = DEFAULT_STYLE_PROFILE_PATH,
    ) -> StyleProfile:
        builtin = self.get_builtin_profile(profile_id)
        profile = StyleProfile(
            id=self._normalize_profile_id(project_profile_id),
            label=label or builtin.label,
            extends=builtin.id,
            platform=builtin.platform,
            genres=builtin.genres,
            notes=(
                f"Project override extending built-in style profile {builtin.id}. "
                "Edit this file to tune platform, genre, rhythm, taboo, and editorial focus."
            ),
        )
        self.project_service.write_text(
            root,
            relative_path,
            json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return profile

    def _merge_profile_data(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if key == "schemaVersion":
                merged[key] = value
                continue
            if isinstance(value, list):
                if value:
                    merged[key] = value
                continue
            if isinstance(value, str):
                if value.strip() or key in {"id", "label", "extends", "platform", "notes"}:
                    merged[key] = value
                continue
            if value is not None:
                merged[key] = value
        return merged

    def _normalize_profile_id(self, profile_id: str) -> str:
        value = (profile_id or "").strip()
        if not value:
            raise ValueError("style profile id is required")
        return self.project_service._normalize_slug(value, "style profile id")

    def _load_builtin_profiles(self) -> dict[str, StyleProfile]:
        catalog = self._load_catalog_data()
        profiles = catalog.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("style catalog profiles must be a list")
        loaded: dict[str, StyleProfile] = {}
        for item in profiles:
            profile = StyleProfile.model_validate(item)
            loaded[profile.id] = profile
        if DEFAULT_STYLE_PROFILE_ID not in loaded:
            raise ValueError(f"style catalog missing default profile: {DEFAULT_STYLE_PROFILE_ID}")
        return loaded

    def _load_planned_profile_slots(self) -> list[dict[str, object]]:
        catalog = self._load_catalog_data()
        slots = catalog.get("plannedSlots", [])
        if not isinstance(slots, list):
            raise ValueError("style catalog plannedSlots must be a list")
        return [dict(slot) for slot in slots if isinstance(slot, dict)]

    def _load_coverage_catalog(self) -> list[dict[str, object]]:
        catalog = self._load_catalog_data()
        coverage = catalog.get("coverageCatalog", [])
        if not isinstance(coverage, list):
            raise ValueError("style catalog coverageCatalog must be a list")
        return [dict(item) for item in coverage if isinstance(item, dict)]

    def _load_template_packs(self) -> list[dict[str, object]]:
        catalog = self._load_catalog_data()
        packs = catalog.get("templatePacks", [])
        if not isinstance(packs, list):
            raise ValueError("style catalog templatePacks must be a list")
        return [dict(item) for item in packs if isinstance(item, dict)]

    def _load_catalog_data(self) -> dict[str, object]:
        try:
            catalog_path = resources.files("open_novel.builtin_style_profiles").joinpath(
                "catalog.json"
            )
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            raw = self._merge_catalog_fragments(raw)
        except (FileNotFoundError, ModuleNotFoundError):
            raw = self._fallback_catalog_data()
        if not isinstance(raw, dict):
            raise ValueError("style catalog must be a JSON object")
        return raw

    def _fallback_catalog_data(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "profiles": [
                profile.model_dump(mode="json")
                for profile in sorted(
                    BUILTIN_STYLE_PROFILES.values(),
                    key=lambda item: item.id,
                )
            ],
            "plannedSlots": [dict(slot) for slot in PLANNED_STYLE_PROFILE_SLOTS],
            "coverageCatalog": [dict(item) for item in STYLE_PROFILE_COVERAGE_CATALOG],
            "templatePacks": [dict(item) for item in STYLE_TEMPLATE_PACKS],
        }

    def _merge_catalog_fragments(self, raw: object) -> object:
        if not isinstance(raw, dict):
            return raw
        package = resources.files("open_novel.builtin_style_profiles")
        merged = dict(raw)
        fragment_specs = {
            "profiles": "profiles",
            "planned_slots": "plannedSlots",
            "coverage": "coverageCatalog",
            "packs": "templatePacks",
        }
        for directory_name, catalog_key in fragment_specs.items():
            items = list(merged.get(catalog_key, []))
            directory = package.joinpath(directory_name)
            if not directory.is_dir():
                merged[catalog_key] = items
                continue
            for child in sorted(directory.iterdir(), key=lambda item: item.name):
                if not child.is_file() or not child.name.endswith(".json"):
                    continue
                fragment = json.loads(child.read_text(encoding="utf-8"))
                if isinstance(fragment, list):
                    items.extend(item for item in fragment if isinstance(item, dict))
                elif isinstance(fragment, dict):
                    items.append(fragment)
                else:
                    raise ValueError(f"style catalog fragment must be an object or list: {child}")
            merged[catalog_key] = items
        return merged
