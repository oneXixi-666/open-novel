from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path

from open_novel.agents.process_control import run_cancellable_process
from open_novel.core.models import WritingModelProfile, WritingModelRegistry, utc_now
from open_novel.core.project import ProjectService
from open_novel.security.path_guard import PathGuard


class WritingModelService:
    registry_path = "models/writing-models.json"

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def read_registry(self, root: Path) -> WritingModelRegistry:
        if not self.project_service.file_exists(root, self.registry_path):
            return WritingModelRegistry()
        return WritingModelRegistry.model_validate_json(
            self.project_service.read_text(root, self.registry_path)
        )

    def write_registry(self, root: Path, registry: WritingModelRegistry) -> None:
        self.project_service.write_text(
            root,
            self.registry_path,
            json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def list_profiles(self, root: Path) -> list[WritingModelProfile]:
        return self.read_registry(root).profiles

    def register_profile(
        self,
        root: Path,
        profile_id: str,
        base_model: str = "",
        adapter_path: str = "",
        command_template: str = "",
        label: str = "",
        timeout_seconds: int = 600,
        training_run_path: str = "",
        set_default: bool = True,
        notes: str = "",
    ) -> WritingModelProfile:
        profile_id = self._normalize_profile_id(profile_id)
        registry = self.read_registry(root)
        now = utc_now()
        existing = next((item for item in registry.profiles if item.id == profile_id), None)
        profile_data = {
            "id": profile_id,
            "label": label or profile_id,
            "backend": "local-command",
            "agentId": "local-model",
            "baseModel": base_model,
            "adapterPath": adapter_path,
            "commandTemplate": command_template,
            "timeoutSeconds": max(1, timeout_seconds),
            "trainingRunPath": training_run_path,
            "updatedAt": now,
            "notes": notes,
        }
        if existing is None:
            profile = WritingModelProfile(**profile_data)
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
        if set_default:
            registry.defaultProfileId = profile_id
        self.write_registry(root, registry)
        return profile

    def set_default_profile(self, root: Path, profile_id: str) -> WritingModelRegistry:
        profile_id = self._normalize_profile_id(profile_id)
        registry = self.read_registry(root)
        if not any(profile.id == profile_id for profile in registry.profiles):
            raise FileNotFoundError(f"missing writing model profile: {profile_id}")
        registry.defaultProfileId = profile_id
        self.write_registry(root, registry)
        return registry

    def get_profile(self, root: Path, profile_id: str | None = None) -> WritingModelProfile:
        registry = self.read_registry(root)
        selected = self._normalize_profile_id(profile_id or registry.defaultProfileId)
        if not selected:
            if not registry.profiles:
                raise FileNotFoundError(
                    "no writing model profile registered; run train local-run with "
                    "--inference-command-template or use model register."
                )
            return registry.profiles[0]
        for profile in registry.profiles:
            if profile.id == selected:
                return profile
        raise FileNotFoundError(f"missing writing model profile: {selected}")

    def run_profile(
        self,
        root: Path,
        profile_id: str | None,
        prompt_path: Path,
        output_path: Path,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[WritingModelProfile, list[str], str, str, int]:
        profile = self.get_profile(root, profile_id)
        if not profile.commandTemplate.strip():
            raise ValueError(
                f"writing model profile has no inference command template: {profile.id}"
            )
        command = self._command_for_profile(root, profile, prompt_path, output_path)
        completed = run_cancellable_process(
            command,
            cwd=root,
            timeout_seconds=profile.timeoutSeconds,
            cancel_check=cancel_check,
        )
        if completed["cancelled"]:
            raise RuntimeError(f"local model cancelled: {profile.id}")
        if completed["timedOut"]:
            raise RuntimeError(f"local model timed out: {profile.id}")
        exit_code = int(completed["exitCode"])
        stderr = str(completed["stderr"])
        stdout = str(completed["stdout"])
        if exit_code != 0:
            raise RuntimeError(stderr or f"local model failed: {profile.id}")
        output_text = stdout.strip()
        if not output_text and output_path.exists():
            output_text = output_path.read_text(encoding="utf-8").strip()
        return profile, command, output_text, stderr, exit_code

    def _command_for_profile(
        self,
        root: Path,
        profile: WritingModelProfile,
        prompt_path: Path,
        output_path: Path,
    ) -> list[str]:
        formatted = profile.commandTemplate.format(
            project=str(root),
            prompt_file=str(prompt_path),
            output_file=str(output_path),
            base_model=profile.baseModel,
            adapter_path=profile.adapterPath,
            profile_id=profile.id,
        )
        command = shlex.split(formatted)
        if not command:
            raise ValueError(f"empty inference command template: {profile.id}")
        executable = command[0]
        if "/" in executable:
            resolved = Path(executable).expanduser()
            if not resolved.is_absolute():
                resolved = PathGuard(root).resolve(executable)
            command[0] = str(resolved)
        return command

    def _normalize_profile_id(self, profile_id: str | None) -> str:
        value = (profile_id or "").strip()
        if not value:
            return ""
        return self.project_service._normalize_slug(value, "model profile id")
