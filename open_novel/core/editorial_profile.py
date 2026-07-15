from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.models import (
    EditorialProfile,
    EditorialProfileRegistry,
    EditorialPromptPreset,
    utc_now,
)
from open_novel.core.project import ProjectService
from open_novel.core.style_profile import DEFAULT_STYLE_PROFILE_PATH

DEFAULT_EDITORIAL_PROFILE_ID = "generic-humanity-editor"

EDITORIAL_PROMPT_PRESETS: dict[str, EditorialPromptPreset] = {
    "generic-humanity": EditorialPromptPreset(
        id="generic-humanity",
        label="通用人性化审稿",
        description="面向通用网文，重点检查人物温度、真实动机和追读吸引力。",
        focus=[
            "人物具体性",
            "个人动机",
            "关系转折铺垫",
            "有代价的兑现",
        ],
        rubric=[
            "检查情绪是否改变注意力、措辞、行为、选择、省略或代价。",
            "检查主角动机是否具有个人原因，而不只是推动剧情。",
            "检查关系转折是否通过互动获得足够铺垫。",
            "检查兑现是否带有可见代价并形成连载吸引力。",
            "检查章节是否始终围绕核心读者承诺。",
            "允许有因果依据的误解、自欺、犹豫和不完整表达，不要将其误判为作者错误。",
            "不要把故意错字、事实错误、逻辑漏洞或无依据的降智当作人性化。",
            "优先引用章节中的具体证据，不给空泛建议。",
        ],
    ),
    "continuity-editor": EditorialPromptPreset(
        id="continuity-editor",
        label="长篇连续性审稿",
        description="面向长篇连载，重点检查设定压力、前后连续性和伏笔兑现安全。",
        focus=[
            "设定一致性",
            "关系状态",
            "承诺追踪",
            "动机连续性",
        ],
        rubric=[
            "检查场景是否遵守当前场景合同和已知设定。",
            "标记缺少铺垫的关系、动机和承诺转折。",
            "优先指出会破坏后续章节的问题，而不是只做文字润色。",
            "使用章节和场景合同中的具体证据。",
            "标记与已知状态冲突或跳过必要后果的剧情推进。",
        ],
    ),
    "emotion-line-editor": EditorialPromptPreset(
        id="emotion-line-editor",
        label="情绪表达审稿",
        description="将扁平情绪标签转化为行为、潜台词和人物选择。",
        focus=[
            "情绪落地",
            "潜台词",
            "对白张力",
            "描写克制",
        ],
        rubric=[
            "检查情绪是否具有可感知的原因，并影响注意力、措辞、行动、省略、选择或代价。",
            "只在情绪标签取代人物专属证据时标记问题，不要求每种情绪都配身体反应。",
            "当误解、回避、不完整表达和未解决情绪符合视角与关系压力时，应予保留。",
            "优先给出与具体段落证据对应的改写建议。",
            "保持节奏，一次动作足以表达时不要建议长篇解释。",
            "标记没有改变压力、选择或关系的密集描写。",
            "标记重复的套话动作、五感清单和固定的动作加解释模式。",
            "不要用错字、事实错误、逻辑漏洞、随意结巴或无意义闲聊制造人性化。",
        ],
    ),
    "platform-genre-commercial-editor": EditorialPromptPreset(
        id="platform-genre-commercial-editor",
        label="平台与题材商业审稿",
        description="检查当前写法是否真正体现在节奏、禁区和章节钩子中。",
        focus=[
            "读者预期",
            "平台节奏",
            "题材兑现",
            "章节钩子",
        ],
        rubric=[
            "检查当前写法是否体现在场景节奏和兑现方式中。",
            "标记被低效描写稀释核心卖点的章节。",
            "检查章节是否至少推进一项平台或题材承诺。",
            "标记缺少代价、见证、反转、后果或下一章吸引力的兑现。",
            "优先强化章节核心承诺，再考虑增加细节。",
        ],
    ),
}

PROMPT_PRESETS: dict[str, list[str]] = {
    preset_id: preset.rubric for preset_id, preset in EDITORIAL_PROMPT_PRESETS.items()
}


class EditorialProfileService:
    registry_path = "models/editorial-profiles.json"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_registry(self, root: Path) -> EditorialProfileRegistry:
        if not self.project_service.file_exists(root, self.registry_path):
            return self._default_registry()
        registry = EditorialProfileRegistry.model_validate_json(
            self.project_service.read_text(root, self.registry_path)
        )
        if not registry.profiles:
            return self._default_registry()
        if not registry.defaultProfileId:
            registry.defaultProfileId = registry.profiles[0].id
        return registry

    def write_registry(self, root: Path, registry: EditorialProfileRegistry) -> None:
        self.project_service.write_text(
            root,
            self.registry_path,
            json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def list_profiles(self, root: Path) -> list[EditorialProfile]:
        return self.read_registry(root).profiles

    def list_prompt_presets(self) -> list[EditorialPromptPreset]:
        return sorted(EDITORIAL_PROMPT_PRESETS.values(), key=lambda preset: preset.id)

    def get_prompt_preset(self, preset_id: str) -> EditorialPromptPreset:
        preset_id = (preset_id or "generic-humanity").strip()
        preset = EDITORIAL_PROMPT_PRESETS.get(preset_id)
        if preset is None:
            raise FileNotFoundError(f"找不到审稿提示词预设：{preset_id}")
        return preset

    def register_profile(
        self,
        root: Path,
        profile_id: str,
        backend: str = "local",
        command_template: str = "",
        label: str = "",
        reviewer: str = "",
        prompt_preset: str = "generic-humanity",
        style_profile_path: str = DEFAULT_STYLE_PROFILE_PATH,
        rubric: list[str] | None = None,
        timeout_seconds: int = 600,
        set_default: bool = True,
        notes: str = "",
    ) -> EditorialProfile:
        profile_id = self._normalize_profile_id(profile_id)
        backend = self._normalize_backend(backend)
        if backend == "command" and not command_template.strip():
            raise ValueError("命令型审稿模型必须填写命令模板。")
        prompt_preset = (prompt_preset or "generic-humanity").strip()
        if prompt_preset not in EDITORIAL_PROMPT_PRESETS:
            raise ValueError(f"不支持的审稿提示词预设：{prompt_preset}")
        style_profile_path = (style_profile_path or DEFAULT_STYLE_PROFILE_PATH).strip()
        registry = self.read_registry(root)
        now = utc_now()
        existing = next((item for item in registry.profiles if item.id == profile_id), None)
        profile_data = {
            "id": profile_id,
            "label": label or profile_id,
            "backend": backend,
            "reviewer": reviewer,
            "commandTemplate": command_template,
            "timeoutSeconds": max(1, timeout_seconds),
            "styleProfilePath": style_profile_path,
            "promptPreset": prompt_preset,
            "rubric": [item.strip() for item in (rubric or []) if item.strip()],
            "updatedAt": now,
            "notes": notes,
        }
        if existing is None:
            profile = EditorialProfile(**profile_data)
            registry.profiles.append(profile)
        else:
            profile = existing.model_copy(
                update={
                    **profile_data,
                    "createdAt": existing.createdAt,
                }
            )
            registry.profiles = [
                profile if item.id == profile_id else item for item in registry.profiles
            ]
        if set_default or not registry.defaultProfileId:
            registry.defaultProfileId = profile_id
        self.write_registry(root, registry)
        return profile

    def set_default_profile(self, root: Path, profile_id: str) -> EditorialProfileRegistry:
        profile_id = self._normalize_profile_id(profile_id)
        registry = self.read_registry(root)
        if not any(profile.id == profile_id for profile in registry.profiles):
            raise FileNotFoundError(f"missing editorial profile: {profile_id}")
        registry.defaultProfileId = profile_id
        self.write_registry(root, registry)
        return registry

    def get_profile(self, root: Path, profile_id: str | None = None) -> EditorialProfile:
        registry = self.read_registry(root)
        selected = self._normalize_profile_id(profile_id or registry.defaultProfileId)
        if not selected:
            return self._default_profile()
        for profile in registry.profiles:
            if profile.id == selected:
                return profile
        raise FileNotFoundError(f"missing editorial profile: {selected}")

    def rubric_for_profile(self, profile: EditorialProfile) -> list[str]:
        if profile.rubric:
            return profile.rubric
        return self.get_prompt_preset(profile.promptPreset).rubric

    def _default_registry(self) -> EditorialProfileRegistry:
        default = self._default_profile()
        return EditorialProfileRegistry(
            defaultProfileId=default.id,
            profiles=[default],
        )

    def _default_profile(self) -> EditorialProfile:
        return EditorialProfile(
            id=DEFAULT_EDITORIAL_PROFILE_ID,
            label="通用人性化审稿",
            backend="local",
            reviewer="local-editor-v1",
            styleProfilePath=DEFAULT_STYLE_PROFILE_PATH,
            promptPreset="generic-humanity",
            rubric=PROMPT_PRESETS["generic-humanity"],
            notes=(
                "Built-in local editor profile. It reads the project style profile so "
                "platform and genre rules can evolve without changing code."
            ),
        )

    def _normalize_profile_id(self, profile_id: str | None) -> str:
        value = (profile_id or "").strip()
        if not value:
            return ""
        return self.project_service._normalize_slug(value, "editorial profile id")

    def _normalize_backend(self, backend: str) -> str:
        value = (backend or "local").strip()
        if value not in {"local", "command"}:
            raise ValueError(f"unsupported editorial profile backend: {value}")
        return value
