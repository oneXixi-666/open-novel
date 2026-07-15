from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from open_novel.agents.cli_adapters import CliAgentService
from open_novel.core.active_prohibitions import ActiveProhibitionService
from open_novel.core.ai_runtime import AIRuntimeService
from open_novel.core.chapter_pipeline import ChapterPipelineService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.models import CliRunResult, SkillManifest, SkillRunRequest, SkillRunResult
from open_novel.core.project import ProjectService
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.writing_model import WritingModelService
from open_novel.security.path_guard import PathGuard
from open_novel.security.redaction import redact_for_log, redact_text


def default_skills_dir() -> Path:
    cwd_skills = Path("skills")
    if cwd_skills.exists():
        return cwd_skills

    package_skills = Path(__file__).resolve().parents[1] / "builtin_skills"
    if package_skills.exists():
        return package_skills

    source_skills = Path(__file__).resolve().parents[2] / "skills"
    return source_skills


class SkillLoader:
    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or default_skills_dir()
        package_skills = Path(__file__).resolve().parents[1] / "builtin_skills"
        self.fallback_skills_dir = (
            package_skills
            if skills_dir is None and package_skills != self.skills_dir and package_skills.exists()
            else None
        )

    def list_skills(self) -> list[SkillManifest]:
        if not self.skills_dir.exists():
            return []

        skill_ids = {path.parent.name for path in self.skills_dir.glob("*/skill.json")}
        if self.fallback_skills_dir is not None:
            skill_ids.update(
                path.parent.name for path in self.fallback_skills_dir.glob("*/skill.json")
            )
        return [self.load_manifest(skill_id) for skill_id in sorted(skill_ids)]

    def load_manifest(self, skill_id: str) -> SkillManifest:
        manifest_path = self._skill_file(skill_id, "skill.json")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return SkillManifest.model_validate(data)

    def load_prompt(self, skill_id: str) -> str:
        prompt_path = self._skill_file(skill_id, "prompt.md")
        return prompt_path.read_text(encoding="utf-8")

    def _skill_file(self, skill_id: str, filename: str) -> Path:
        primary = self.skills_dir / skill_id / filename
        if primary.is_file():
            return primary
        if self.fallback_skills_dir is not None:
            fallback = self.fallback_skills_dir / skill_id / filename
            if fallback.is_file():
                return fallback
        raise FileNotFoundError(f"missing skill {filename}: {skill_id}")


class MissingVariableError(ValueError):
    pass


class PromptRenderer:
    pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def render(self, template: str, variables: dict[str, str]) -> str:
        found = {match.group(1) for match in self.pattern.finditer(template)}
        missing = sorted(found - variables.keys())
        if missing:
            raise MissingVariableError(f"missing prompt variables: {', '.join(missing)}")
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace("{" + key + "}", value)
        return rendered


class SkillRunner:
    def __init__(
        self,
        skills_dir: Path | None = None,
        project_service: ProjectService | None = None,
        cli_agent_service: CliAgentService | None = None,
        writing_model_service: WritingModelService | None = None,
        ai_runtime_service: AIRuntimeService | None = None,
    ) -> None:
        self.loader = SkillLoader(skills_dir)
        self.project_service = project_service or ProjectService()
        self.cli_agent_service = cli_agent_service or CliAgentService()
        self.writing_model_service = writing_model_service or WritingModelService(
            self.project_service
        )
        self.ai_runtime_service = ai_runtime_service
        self.renderer = PromptRenderer()
        self.story_guidance = StoryGuidanceService(self.project_service)
        self.context_pack_service = ContextPackService(self.project_service, self.story_guidance)

    def run(
        self,
        request: SkillRunRequest,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SkillRunResult:
        project = self.project_service.open_project(request.projectRoot)
        manifest = self.loader.load_manifest(request.skillId)
        variables = {
            "chapterId": "001",
            "chapterTitle": "Untitled Chapter",
            **request.variables,
        }
        run_id = request.runId or self._new_run_id()
        variables["runId"] = run_id

        if manifest.id == "chapter-writer":
            variables.setdefault(
                "activeProhibitions",
                ActiveProhibitionService(self.project_service).format_for_prompt(project.root),
            )
            self._enforce_chapter_readiness(project.root, variables["chapterId"])
            self.context_pack_service.build_context_pack(project.root, variables["chapterId"])
        if (
            manifest.allowedAgents
            and request.agentId not in manifest.allowedAgents
            and request.agentId not in {"api-writing", "api-review"}
        ):
            allowed = ", ".join(manifest.allowedAgents)
            raise ValueError(
                f"agent {request.agentId!r} is not allowed for {manifest.id}: {allowed}"
            )

        prompt = self.renderer.render(self.loader.load_prompt(request.skillId), variables)
        context_text = self._build_context(project.root, manifest.inputs, variables)
        full_prompt = self._compose_prompt(prompt, context_text, manifest.id)

        database_project = self.project_service.is_database_project(project.root)
        run_relative_dir = f"runs/{run_id}"
        run_dir = (
            Path(tempfile.mkdtemp(prefix=f"open-novel-{run_id}-"))
            if database_project
            else PathGuard(project.root).resolve(run_relative_dir)
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.md"
        output_path = run_dir / "output.md"
        run_json_path = run_dir / "run.json"
        redacted_prompt = redact_text(full_prompt)
        prompt_path.write_text(redacted_prompt, encoding="utf-8")
        if database_project:
            self.project_service.write_text(
                project.root,
                f"{run_relative_dir}/prompt.md",
                redacted_prompt,
            )

        cli_result: CliRunResult | None = None
        model_profile_id = request.modelProfile
        if request.agentId in {"api-writing", "api-review"}:
            if self.ai_runtime_service is None:
                raise RuntimeError("AI 账号运行时尚未初始化。")
            role = "review" if request.agentId == "api-review" else "writing"
            completion = self.ai_runtime_service.complete_sync(
                role=role,
                prompt=full_prompt,
                root=project.root.as_posix(),
                action=manifest.id,
                bypass_cache=request.bypassCache,
            )
            output_text = completion.text
        elif request.agentId == "local-dry-run":
            output_text = self._run_local_agent(manifest.id, variables, full_prompt)
        elif request.agentId == "local-model":
            profile, command, output_text, stderr, exit_code = (
                self.writing_model_service.run_profile(
                    run_dir if database_project else project.root,
                    request.modelProfile,
                    prompt_path,
                    output_path,
                    cancel_check=cancel_check,
                )
            )
            model_profile_id = profile.id
            cli_result = CliRunResult(
                command=command,
                cwd=project.root,
                exitCode=exit_code,
                stdout=output_text,
                stderr=stderr,
                timedOut=False,
            )
        else:
            try:
                cli_prompt_run = self.cli_agent_service.run_prompt(
                    request.agentId,
                    full_prompt,
                    run_dir if database_project else project.root,
                    writable=manifest.writePolicy == "workspace-write",
                    cancel_check=cancel_check,
                )
            except TypeError as exc:
                if "cancel_check" not in str(exc):
                    raise
                cli_prompt_run = self.cli_agent_service.run_prompt(
                    request.agentId,
                    full_prompt,
                    run_dir if database_project else project.root,
                    writable=manifest.writePolicy == "workspace-write",
                )
            cli_result = asyncio.run(cli_prompt_run)
            if cli_result.cancelled:
                raise RuntimeError(f"agent cancelled: {request.agentId}")
            if cli_result.exitCode != 0 or cli_result.timedOut:
                raise RuntimeError(cli_result.stderr or f"agent failed: {request.agentId}")
            output_text = cli_result.stdout.strip()

        redacted_output = redact_text(output_text)
        output_path.write_text(redacted_output, encoding="utf-8")
        if database_project:
            self.project_service.write_text(
                project.root,
                f"{run_relative_dir}/output.md",
                redacted_output,
            )

        saved_output_path = self._save_skill_output(
            project.root,
            manifest.outputs,
            manifest.writePolicy,
            variables,
            output_text,
        )
        if manifest.id == "chapter-writer" and saved_output_path:
            ChapterPipelineService(self.project_service).update_step(
                project.root,
                variables["chapterId"],
                "draft",
                artifact=saved_output_path,
                run_id=run_id,
                message="章节草稿已生成",
            )

        run_record = {
            "runId": run_id,
            "skillId": manifest.id,
            "agentId": request.agentId,
            "modelProfile": model_profile_id,
            "writePolicy": manifest.writePolicy,
            "outputPath": saved_output_path,
            "createdAt": datetime.now(UTC).isoformat(),
        }
        if cli_result is not None:
            run_record["cli"] = redact_for_log(cli_result.model_dump(mode="json"))
        run_record_text = json.dumps(run_record, ensure_ascii=False, indent=2) + "\n"
        run_json_path.write_text(run_record_text, encoding="utf-8")
        if database_project:
            self.project_service.write_text(
                project.root,
                f"{run_relative_dir}/run.json",
                run_record_text,
            )

        return SkillRunResult(
            runId=run_id,
            skillId=manifest.id,
            agentId=request.agentId,
            modelProfile=model_profile_id,
            outputPath=saved_output_path,
            runDir=run_dir,
            promptPath=prompt_path,
            outputText=output_text,
        )

    def _build_context(
        self,
        project_root: Path,
        inputs: list[str],
        variables: dict[str, str],
    ) -> str:
        sections: list[str] = []
        for input_path in inputs:
            if "{" in input_path:
                try:
                    relative_path = input_path.format(**variables)
                except KeyError:
                    continue
            else:
                relative_path = input_path

            if relative_path in variables:
                sections.append(f"## {relative_path}\n\n{variables[relative_path]}\n")
                continue

            try:
                if self.project_service.file_exists(project_root, relative_path):
                    sections.append(
                        f"## {relative_path}\n\n"
                        f"{self.project_service.read_text(project_root, relative_path)}\n"
                    )
            except ValueError:
                continue
        return "\n".join(sections).strip()

    def _compose_prompt(self, prompt: str, context_text: str, skill_id: str) -> str:
        if not context_text:
            return prompt
        return f"{prompt}\n\n---\n\n# Open Novel Context For {skill_id}\n\n{context_text}\n"

    def _run_local_agent(
        self,
        skill_id: str,
        variables: dict[str, str],
        full_prompt: str,
    ) -> str:
        if skill_id == "chapter-writer":
            title = variables.get("chapterTitle", f"Chapter {variables.get('chapterId', '001')}")
            contract = self._contract_from_prompt(full_prompt)
            return self._local_chapter_draft(title, contract)
        if skill_id == "line-editor":
            return self._local_line_edit(variables.get("sourceText", ""))
        return (
            f"# {skill_id} Result\n\n"
            "This is a local dry-run output. Configure an API or CLI agent for real generation.\n\n"
            f"Prompt size: {len(full_prompt)} characters.\n"
        )

    def _contract_from_prompt(self, full_prompt: str) -> dict[str, object]:
        marker = "## story/chapter-briefs/"
        start = full_prompt.find(marker)
        if start < 0:
            return {}
        json_start = full_prompt.find("{", start)
        if json_start < 0:
            return {}
        depth = 0
        for index, char in enumerate(full_prompt[json_start:], start=json_start):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(full_prompt[json_start : index + 1])
                    except json.JSONDecodeError:
                        return {}
                    return data if isinstance(data, dict) else {}
        return {}

    def _local_chapter_draft(self, title: str, contract: dict[str, object]) -> str:
        pov = str(contract.get("pov") or "主角")
        focus = str(contract.get("focus") or "主角推进当前危机。")
        goal = str(contract.get("goal") or "主角想达成本章目标。")
        conflict = str(contract.get("conflict") or "阻力突然压来。")
        turn = str(contract.get("turn") or "局势出现转折。")
        outcome = str(contract.get("outcome") or "主角付出代价后暂时脱身。")
        hook = str(contract.get("hook") or "新的危机在结尾出现。")
        emotional = str(contract.get("emotionalBeat") or "主角从压抑转为警惕。")
        relationship = str(contract.get("relationshipBeat") or "对手开始重新判断主角。")
        internal_need = str(contract.get("internalNeed") or "主角想证明自己并非任人摆布。")
        wound_or_fear = str(contract.get("woundOrFear") or "主角害怕再次被当众否定。")
        stakes = str(contract.get("stakes") or "如果失败，他会失去继续追查的机会。")
        cost = str(contract.get("cost") or "这次推进也暴露了新的风险。")
        subtext = str(contract.get("subtext") or "主角嘴上冷静，实际在保护最后一点尊严。")
        aftertaste = str(contract.get("aftertaste") or "读者应感到爽快，同时意识到危险刚刚开始。")
        must_include = self._first_string(contract.get("mustInclude"), "关键物件")
        promises = self._string_list(contract.get("readerPromises"))
        promise_line = self._promise_progression_line(promises)
        promise_flag = self._promise_flag(promises)
        return (
            f"# {title}\n\n"
            f"{must_include}前，{pov}停了一息，胸口那口压抑的气几乎要炸开。"
            f"这一章的重点很清楚：{focus}{wound_or_fear}这根刺先一步扎进心口，"
            f"也把他真正不肯退的原因逼了出来：{internal_need}\n\n"
            f"阻力方拦在前方，把选择压到{pov}面前：“你确定还要继续？”\n\n"
            f"{pov}没有退。他选择往前一步，咬牙把手按在{must_include}上。"
            f"他知道自己必须做到一件事：{goal}{stakes}\n\n"
            f"{conflict}四周的目光压了过来，连呼吸都像被人攥住。"
            "他没有解释，也没有求饶，只把最后一点力气压进当前选择里。\n\n"
            f"下一刻，{turn}{must_include}给出了和众人预期不同的回应。"
            f"{promise_line}的第一声惊呼在人群里炸开，那些曾经看轻他的人，"
            "下意识后退了半步。\n\n"
            f"阻力方还想再拦，场面却已经变了。{relationship}"
            f"{pov}看见对方眼底那点笃定裂开，变成了藏不住的迟疑。\n\n"
            f"可压力没有因此散去。有人低声喝令封住现场，想把所有见证者都拦在原地。"
            f"{pov}听见人群里有人倒吸冷气，也听见自己越来越重的呼吸。"
            "他知道，只要此刻低头，刚刚亮起的光就会被他们重新按回尘土里。\n\n"
            "于是他抬手挡住对方递来的封口令，声音不高，却让最近几个人都听清了。"
            f"“{must_include}已经给出结果。若要改判，也请先告诉我，规则到底还算不算数？”"
            f"这一句话像刀锋切开沉默，{subtext}对面的脸色更难看，场上的气息也冷了下来。\n\n"
            f"{outcome}{cost}{pov}这才明白，自己推进了目标，也把更深的危险引到了身上。\n\n"
            f"他没有急着庆祝，而是重新核对{must_include}留下的变化。"
            f"刚才的{turn}已经改变了现场每个人的选择，{relationship}"
            f"他必须带着这个结果继续行动，也必须承担这一决定留下的后果：{cost}"
            "围观者的议论没有停下，阻力方也没有真正退场，这场冲突只是换了新的形态。\n\n"
            f"{emotional}他刚要追问，新的线索已经被送到门外。\n\n"
            f"这一章把{promise_line}都往前推了一步，让读者看到新的问题已经被真正点亮。"
            f"{promise_flag}\n\n"
            f"{hook}新的线索出现，未完成的问题被推到下一章。{aftertaste}\n"
        )

    def _first_string(self, value: object, fallback: str) -> str:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _promise_progression_line(self, promises: list[str]) -> str:
        if not promises:
            return "核心承诺"
        if len(promises) == 1:
            return promises[0]
        if len(promises) == 2:
            return f"{promises[0]}和{promises[1]}"
        return "、".join(promises[:-1]) + f"和{promises[-1]}"

    def _promise_flag(self, promises: list[str]) -> str:
        if not promises:
            return ""
        return "".join(f"{promise}的线索开始浮出水面。" for promise in promises)

    def _local_line_edit(self, source_text: str) -> str:
        text = source_text.strip()
        if not text:
            return "# Polished Draft\n\n"
        replacements = {
            "很": "",
            "非常": "",
            "然后": "随即",
            "突然": "骤然",
            "说道": "开口",
            "他感觉": "他察觉",
            "她感觉": "她察觉",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        paragraphs = []
        for paragraph in text.split("\n\n"):
            cleaned = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
            if cleaned.startswith("#"):
                paragraphs.append(cleaned)
            elif cleaned:
                paragraphs.append(cleaned)
        polished = "\n\n".join(paragraphs)
        if "（润色稿）" not in polished.split("\n", 1)[0]:
            lines = polished.splitlines()
            if lines and lines[0].startswith("#"):
                lines[0] = f"{lines[0]}（润色稿）"
                polished = "\n".join(lines)
        return polished.rstrip() + "\n"

    def _enforce_chapter_readiness(self, project_root: Path, chapter_id: str) -> None:
        report = self.story_guidance.check_readiness(project_root, chapter_id)
        if report.status != "block":
            return
        details = "; ".join(f"{issue.field}: {issue.message}" for issue in report.issues[:3])
        raise ValueError(f"chapter is not ready for drafting: {details}")

    def _save_skill_output(
        self,
        project_root: Path,
        outputs: list[str],
        write_policy: str,
        variables: dict[str, str],
        output_text: str,
    ) -> str | None:
        if not outputs or write_policy == "read-only":
            return None

        relative_output = outputs[0].format(**variables)
        self._validate_write_policy(relative_output, write_policy)
        self.project_service.write_text(project_root, relative_output, output_text)
        return relative_output

    def _validate_write_policy(self, relative_output: str, write_policy: str) -> None:
        if write_policy == "draft-only" and not relative_output.startswith("drafts/"):
            raise ValueError("draft-only skills may only write to drafts/")
        if write_policy == "proposal-only" and not (
            relative_output.startswith("patches/")
            or relative_output.startswith("runs/")
            or relative_output.startswith("story/")
            or relative_output.startswith("memory/")
        ):
            raise ValueError("proposal-only skills may only write proposal paths")
        if relative_output.startswith("chapters/"):
            raise ValueError("skills may not write canonical chapters directly")

    def _new_run_id(self) -> str:
        return "run_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
