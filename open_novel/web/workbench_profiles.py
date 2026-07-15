from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from open_novel.core.style_profile import DEFAULT_STYLE_PROFILE_ID


class WorkbenchProfileService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def creation_options(self) -> dict[str, Any]:
        builtin_profiles = self.presenter.style_profile_service.list_builtin_profiles()
        platform_styles = [
            {
                "id": profile.id,
                "label": self.style_option_label(profile.id, profile.label),
                "platform": profile.platform or "generic",
                "status": "active" if profile.id == DEFAULT_STYLE_PROFILE_ID else "candidate",
                "genres": self.genre_labels(profile.genres),
                "summary": self.style_option_summary(
                    profile.id, profile.notes, profile.platform, profile.genres
                ),
            }
            for profile in builtin_profiles
        ]
        return {
            "platformStyles": platform_styles,
            "genres": self.genre_options(platform_styles),
            "platformLabels": self.platform_labels(),
        }

    def list_style_profiles(self, book_id: str = "") -> dict[str, Any]:
        root = self.presenter._target_root(book_id)
        current_style_id = (
            self.presenter._style_profile_id(root) if root is not None else DEFAULT_STYLE_PROFILE_ID
        )
        current_style_label = (
            self.presenter._style_profile_label(root)
            if root is not None
            else self.style_option_label(DEFAULT_STYLE_PROFILE_ID, "通用网文连载")
        )
        activation = self.presenter.style_profile_service.template_maintenance_policy().get(
            "plannedSlotActivationCriteria",
            {},
        )
        if not isinstance(activation, dict):
            activation = {}
        return {
            "bookId": root.as_posix() if root is not None else "",
            "currentStyleProfileId": current_style_id,
            "currentStyleProfileLabel": current_style_label,
            "profiles": [
                {
                    "id": profile.id,
                    "label": self.style_option_label(profile.id, profile.label),
                    "platform": profile.platform or "generic",
                    "platformLabel": self.platform_labels().get(
                        profile.platform or "generic",
                        profile.platform or "generic",
                    ),
                    "status": str(profile.templateStatus or "active"),
                    "maturity": str(profile.maturity or "baseline"),
                    "genres": self.genre_labels(profile.genres),
                    "summary": self.style_option_summary(
                        profile.id, profile.notes, profile.platform, profile.genres
                    ),
                    "notes": profile.notes,
                    "isCurrent": profile.id == current_style_id,
                    "canApply": True,
                }
                for profile in self.presenter.style_profile_service.list_builtin_profiles()
            ],
            "plannedSlots": [
                {
                    "id": str(slot.get("id") or ""),
                    "label": self.style_option_label(
                        str(slot.get("id") or ""),
                        str(slot.get("label") or ""),
                    ),
                    "platform": str(slot.get("platform") or "generic"),
                    "platformLabel": self.platform_labels().get(
                        str(slot.get("platform") or "generic"),
                        str(slot.get("platform") or "generic"),
                    ),
                    "genres": self.genre_labels(slot.get("genres", [])),
                    "summary": self.planned_style_summary(slot),
                    "status": "planned",
                }
                for slot in self.presenter.style_profile_service.list_planned_profile_slots()
            ],
            "coverageCatalog": [
                {
                    "platform": str(item.get("platform") or ""),
                    "label": self.platform_labels().get(
                        str(item.get("platform") or ""),
                        str(item.get("platform") or ""),
                    ),
                    "activeCount": len(
                        [value for value in item.get("templateIds", []) if str(value).strip()]
                    ),
                    "plannedCount": len(
                        [
                            value
                            for value in item.get("plannedTemplateIds", [])
                            if str(value).strip()
                        ]
                    ),
                }
                for item in self.presenter.style_profile_service.list_coverage_catalog()
            ],
            "templatePacks": [
                {
                    "id": str(item.get("id") or ""),
                    "label": str(item.get("label") or item.get("id") or ""),
                    "status": str(item.get("status") or ""),
                    "summary": self.template_pack_summary(item),
                }
                for item in self.presenter.style_profile_service.list_template_packs()
            ],
            "maintenancePolicy": {
                "requiredSampleChapters": int(activation.get("requiredSampleChapters") or 5),
                "minimumGateScore": int(activation.get("minimumGateScore") or 90),
                "minimumQualityScore": int(activation.get("minimumQualityScore") or 90),
            },
            "creationOptions": self.creation_options(),
        }

    def apply_style_profile(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可应用风格模板的作品。")
        try:
            profile = self.presenter.style_profile_service.write_project_profile_from_builtin(
                root,
                request.profileId,
                project_profile_id=request.projectProfileId.strip() or "project-style",
                label=request.label.strip() or "Project style override",
                relative_path=request.path.strip() or "story/style-profile.json",
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "profileId": request.profileId,
            "label": self.style_option_label(
                request.profileId, profile.label or request.profileId
            ),
            "path": request.path.strip() or "story/style-profile.json",
            "styleProfileId": self.presenter._style_profile_id(root),
            "styleProfileLabel": self.presenter._style_profile_label(root),
            "summary": (
                f"已将《{self.presenter.book_for_root(root)['title']}》切换到 "
                f"{self.presenter._style_profile_label(root)}。"
            ),
        }

    def list_editorial_models(self, book_id: str = "") -> dict[str, Any]:
        root = self.presenter._target_root(book_id)
        if root is None:
            return {
                "bookId": "",
                "defaultProfileId": "",
                "profiles": [],
                "promptPresets": [],
            }
        registry = self.presenter.editorial_profile_service.read_registry(root)
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "profiles": [
                self.editorial_profile_payload(profile, registry.defaultProfileId)
                for profile in registry.profiles
            ],
            "promptPresets": [
                {
                    "id": preset.id,
                    "label": preset.label,
                    "description": preset.description,
                    "focus": preset.focus,
                }
                for preset in self.presenter.editorial_profile_service.list_prompt_presets()
            ],
        }

    def create_editorial_model(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可注册审稿模型的作品。")
        try:
            profile = self.presenter.editorial_profile_service.register_profile(
                root,
                profile_id=request.profileId,
                backend=request.backend,
                command_template=request.commandTemplate,
                label=request.label,
                reviewer=request.reviewer,
                prompt_preset=request.promptPreset,
                style_profile_path=request.styleProfilePath,
                rubric=request.rubric,
                timeout_seconds=request.timeoutSeconds,
                set_default=request.setDefault,
                notes=request.notes,
            )
            registry = self.presenter.editorial_profile_service.read_registry(root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "profile": self.editorial_profile_payload(profile, registry.defaultProfileId),
            "summary": f"已登记审稿模型：{profile.label or profile.id}",
        }

    def set_default_editorial_model(self, request: Any) -> dict[str, Any]:
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(
                status_code=400,
                detail="当前工作区还没有可设置默认审稿模型的作品。",
            )
        try:
            registry = self.presenter.editorial_profile_service.set_default_profile(
                root, request.profileId
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "bookId": root.as_posix(),
            "defaultProfileId": registry.defaultProfileId,
            "summary": f"已将默认审稿模型切换为：{request.profileId}",
        }

    def editorial_profile_payload(self, profile: Any, default_profile_id: str) -> dict[str, Any]:
        return {
            "id": profile.id,
            "label": profile.label or profile.id,
            "backend": profile.backend,
            "reviewer": profile.reviewer,
            "commandTemplate": profile.commandTemplate,
            "timeoutSeconds": profile.timeoutSeconds,
            "styleProfilePath": profile.styleProfilePath,
            "promptPreset": profile.promptPreset,
            "rubric": profile.rubric,
            "notes": profile.notes,
            "updatedAt": self.presenter._short_datetime(profile.updatedAt),
            "isDefault": profile.id == default_profile_id,
        }

    def template_pack_summary(self, item: dict[str, Any]) -> str:
        active_count = len(
            [value for value in item.get("activeProfileIds", []) if str(value).strip()]
        )
        planned_count = len(
            [value for value in item.get("plannedProfileIds", []) if str(value).strip()]
        )
        platform_count = len(
            [value for value in item.get("coveragePlatforms", []) if str(value).strip()]
        )
        return (
            f"覆盖 {platform_count} 个平台方向，已启用 {active_count} 个模板，"
            f"预留 {planned_count} 个模板。"
        )

    def platform_labels(self) -> dict[str, str]:
        return {
            "generic": "跨平台",
            "fanqie": "番茄",
            "qidian": "起点",
            "douyin": "抖音短剧",
            "jjwxc": "晋江",
            "extension": "用户扩展",
        }

    def style_option_label(self, profile_id: str, raw_label: str) -> str:
        curated = {
            "generic-web-serial": "通用网文连载",
            "fanqie-xuanhuan-upgrade": "番茄玄幻升级流",
            "urban-emotion-suspense": "都市情绪悬疑",
            "female-romance-growth": "女频情感成长",
            "fanqie-urban-system": "番茄都市系统流",
            "fanqie-female-revenge": "番茄女频复仇成长",
            "fanqie-urban-combat-business": "番茄都市战斗商战",
            "fanqie-male-fantasy-power-strategy": "番茄男频玄幻权谋升级",
            "fanqie-female-family-rebirth": "番茄女频家庭重生",
            "douyin-micro-drama-reversal": "短剧高反转",
            "qidian-xianxia-longform": "起点仙侠长篇",
            "qidian-sci-fi-tech": "起点科幻技术流",
            "qidian-fantasy-kingdom-war": "起点奇幻王国战争",
            "qidian-infinite-flow-survival": "起点无限流生存",
            "jjwxc-romance-slowburn": "晋江慢热情感",
            "jjwxc-historical-romance": "晋江古言宫廷",
            "jjwxc-modern-romance-career": "晋江现代情感职场",
            "jjwxc-danmei-case-unit": "晋江关系向单元悬疑",
            "tomato-short-drama-revenge": "番茄短剧复仇反转",
            "suspense-crime-investigation": "悬疑犯罪调查",
            "historical-power-struggle": "历史权谋",
            "light-novel-adventure": "轻小说冒险",
            "horror-folk-mystery": "民俗恐怖悬疑",
            "workplace-business-growth": "职场商战成长",
            "generic-military-techno-thriller": "军事科技惊悚",
            "generic-sports-competition-growth": "体育竞技成长",
            "generic-food-healing-slice-of-life": "美食治愈日常",
            "generic-children-adventure-mystery": "儿童冒险解谜",
        }
        return curated.get(profile_id, raw_label or profile_id)

    def style_option_summary(
        self,
        profile_id: str,
        notes: str,
        platform: str,
        genres: list[str],
    ) -> str:
        curated = {
            "generic-web-serial": "适合尚未锁定平台的新书，强调冲突推进、章节承诺和章尾追读。",
            "fanqie-xuanhuan-upgrade": "强调压迫到反击、升级代价、爽点兑现和章尾追读。",
            "urban-emotion-suspense": "强调现实压力、关系潜台词、公平线索和克制情绪。",
            "female-romance-growth": "强调关系递进、边界感、互动因果和人物成长。",
        }
        if profile_id in curated:
            return curated[profile_id]
        if notes.strip() and any("\u4e00" <= char <= "\u9fff" for char in notes):
            return notes.strip()
        platform_label = self.platform_labels().get(platform or "generic", platform or "跨平台")
        genre_labels = self.genre_labels(genres)
        if genre_labels:
            return f"适合 {platform_label} 方向，重点覆盖 {'、'.join(genre_labels[:3])} 等题材。"
        return f"适合 {platform_label} 方向的新书开局和章节承诺管理。"

    def planned_style_summary(self, slot: dict[str, object]) -> str:
        genres = self.genre_labels(slot.get("genres", []))
        platform = str(slot.get("platform") or "generic")
        platform_label = self.platform_labels().get(platform, platform)
        if genres:
            return f"适合 {platform_label} 方向，重点参考 {'、'.join(genres[:3])} 等题材。"
        return f"适合 {platform_label} 方向的新书开局，可作为平台风格参考。"

    def genre_options(self, platform_styles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _ = platform_styles
        genre_catalog = [
            {
                "slug": "urban-suspense",
                "label": "都市悬疑",
                "tokens": {"urban", "suspense"},
                "platformHints": ["generic", "fanqie"],
            },
            {
                "slug": "urban-emotion",
                "label": "都市情感",
                "tokens": {"urban", "emotion"},
                "platformHints": ["generic", "jjwxc"],
            },
            {
                "slug": "xuanhuan-upgrade",
                "label": "玄幻升级",
                "tokens": {"xuanhuan", "upgrade"},
                "platformHints": ["fanqie", "qidian"],
            },
            {
                "slug": "xianxia-cultivation",
                "label": "仙侠修真",
                "tokens": {"xianxia", "cultivation"},
                "platformHints": ["qidian"],
            },
            {
                "slug": "sci-fi-adventure",
                "label": "科幻冒险",
                "tokens": {"sci-fi", "technology", "civilization"},
                "platformHints": ["generic", "qidian"],
            },
            {
                "slug": "female-growth",
                "label": "女频成长",
                "tokens": {"female", "growth", "relationship"},
                "platformHints": ["generic", "jjwxc"],
            },
            {
                "slug": "micro-drama-revenge",
                "label": "短剧复仇",
                "tokens": {
                    "micro-drama",
                    "reversal",
                    "revenge",
                    "high-hook",
                    "short-drama",
                    "twist",
                },
                "platformHints": ["douyin", "fanqie"],
            },
            {
                "slug": "workplace-business",
                "label": "职场商战",
                "tokens": {"workplace", "business"},
                "platformHints": ["generic"],
            },
        ]
        return [
            {
                "label": item["label"],
                "value": item["label"],
                "platformHints": item["platformHints"],
            }
            for item in genre_catalog
        ]

    def genre_labels(self, genres: object) -> list[str]:
        curated = {
            "urban": "都市",
            "system": "系统",
            "comedy": "喜剧",
            "female": "女频",
            "revenge": "复仇",
            "growth": "成长",
            "combat": "战斗",
            "business": "商战",
            "power-progression": "升级",
            "male": "男频",
            "fantasy": "玄幻",
            "xuanhuan": "玄幻",
            "power-strategy": "权谋",
            "upgrade": "升级",
            "family": "家庭",
            "rebirth": "重生",
            "micro-drama": "短剧",
            "reversal": "反转",
            "high-hook": "强钩子",
            "xianxia": "仙侠",
            "cultivation": "修真",
            "longform": "长篇",
            "sci-fi": "科幻",
            "technology": "技术",
            "civilization": "文明",
            "kingdom-war": "王国战争",
            "faction": "势力",
            "infinite-flow": "无限流",
            "survival": "生存",
            "team": "团队",
            "mystery": "悬疑",
            "romance": "情感",
            "slowburn": "慢热",
            "relationship": "关系",
            "historical": "历史",
            "court": "宫廷",
            "modern-romance": "现代情感",
            "career": "职场",
            "danmei": "关系向",
            "case-unit": "单元案件",
            "suspense": "悬疑",
            "short-drama": "短剧",
            "twist": "反转",
            "crime": "犯罪",
            "investigation": "调查",
            "power-struggle": "权谋",
            "strategy": "策略",
            "light-novel": "轻小说",
            "adventure": "冒险",
            "horror": "恐怖",
            "folk": "民俗",
            "workplace": "职场",
            "military": "军事",
            "techno-thriller": "科技惊悚",
            "mission": "任务",
            "sports": "体育",
            "competition": "竞技",
            "food": "美食",
            "healing": "治愈",
            "slice-of-life": "日常",
            "community": "群像",
            "children": "儿童",
            "friendship": "友情",
            "web-serial": "网文连载",
            "emotion": "情感",
        }
        if not isinstance(genres, (list, tuple, set)):
            return []
        return [
            curated.get(str(item), str(item))
            for item in genres
            if str(item).strip()
        ]
