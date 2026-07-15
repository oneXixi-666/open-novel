from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

from open_novel.agents.detection import AgentDetectionService
from open_novel.core.book_analysis import BookAnalysisService
from open_novel.core.chapter_drafting import ChapterDraftService
from open_novel.core.chapter_gate import ChapterGateService
from open_novel.core.chapter_pipeline import ChapterPipelineService
from open_novel.core.context_pack import ContextPackService
from open_novel.core.continuity import ContinuityService
from open_novel.core.director import DirectorService
from open_novel.core.editorial_profile import EditorialProfileService
from open_novel.core.editorial_review import EditorialReviewService
from open_novel.core.gate_recovery import GateRecoveryService
from open_novel.core.local_training import LocalTrainingService
from open_novel.core.memory_distillation import MemoryDistillationService
from open_novel.core.memory_validation import MemoryValidationService
from open_novel.core.model_comparison import ModelComparisonService
from open_novel.core.models import SkillRunRequest
from open_novel.core.plot_direction import PlotDirectionService
from open_novel.core.post_chapter import PostChapterService
from open_novel.core.project import ProjectService
from open_novel.core.prompt_eval import PromptEvalService
from open_novel.core.prompt_registry import PromptRegistryService
from open_novel.core.sequence_evaluation import ChapterSequenceEvaluationService
from open_novel.core.skills import SkillLoader, SkillRunner
from open_novel.core.story_guidance import StoryGuidanceService
from open_novel.core.style_profile import DEFAULT_STYLE_PROFILE_PATH, StyleProfileService
from open_novel.core.style_promotion import StyleProfilePromotionService
from open_novel.core.writing_formula import WritingFormulaService
from open_novel.core.writing_model import WritingModelService
from open_novel.core.writing_quality import WritingQualityService
from open_novel.exporters.service import ExportService

app = typer.Typer(help="Open Novel local-first writing workspace.")
project_app = typer.Typer(help="Manage local novel projects.")
skill_app = typer.Typer(help="Inspect and run local skills.")
agent_app = typer.Typer(help="Detect and inspect local agents.")
export_app = typer.Typer(help="Export manuscripts.")
train_app = typer.Typer(help="Plan and run local model tuning.")
model_app = typer.Typer(help="Manage local writing model profiles.")
editor_app = typer.Typer(help="Manage editorial review profiles.")
style_app = typer.Typer(help="Manage platform and genre style profiles.")
director_app = typer.Typer(help="Plan auditable chapter production work.")
prompt_app = typer.Typer(help="Inspect and validate prompt registry entries.")
app.add_typer(project_app, name="project")
app.add_typer(skill_app, name="skill")
app.add_typer(agent_app, name="agent")
app.add_typer(export_app, name="export")
app.add_typer(train_app, name="train")
app.add_typer(model_app, name="model")
app.add_typer(editor_app, name="editor")
app.add_typer(style_app, name="style")
app.add_typer(director_app, name="director")
app.add_typer(prompt_app, name="prompt-registry")
console = Console()


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8765,
) -> None:
    """Start the local FastAPI server."""
    uvicorn.run("open_novel.server:app", host=host, port=port, reload=False)


@project_app.command("create")
def create_project(
    path: Annotated[Path, typer.Argument(help="Project folder to create.")],
    title: Annotated[str, typer.Option(help="Novel title.")] = "Untitled Novel",
    language: Annotated[str, typer.Option(help="Novel language code.")] = "zh-CN",
) -> None:
    """Create a local novel project folder."""
    project = ProjectService().create_project(path=path, title=title, language=language)
    console.print(f"[green]Created[/green] {project.root}")


@project_app.command("tree")
def project_tree(path: Annotated[Path, typer.Argument(help="Novel project folder.")]) -> None:
    """Print a safe file tree for a project."""
    project = ProjectService().open_project(path)
    for item in ProjectService().list_files(project.root):
        console.print(item)


@project_app.command("new-chapter")
def new_chapter(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str | None, typer.Option(help="Chapter id.")] = None,
    title: Annotated[str | None, typer.Option(help="Chapter title.")] = None,
) -> None:
    """Create a canonical chapter file."""
    output = ProjectService().create_chapter(project, chapter_id=chapter_id, title=title)
    console.print(f"[green]Created[/green] {output}")


@project_app.command("accept-draft")
def accept_draft(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    draft: Annotated[str, typer.Argument(help="Draft path, e.g. drafts/001.generated.md.")],
    chapter_id: Annotated[str | None, typer.Option(help="Target chapter id.")] = None,
    force: Annotated[bool, typer.Option(help="Accept even when chapter gate blocks.")] = False,
) -> None:
    """Accept a draft into canonical chapters."""
    target_chapter_id = (
        ProjectService().chapter_path_for_draft(draft).removeprefix("chapters/").removesuffix(".md")
        if chapter_id is None
        else ProjectService().normalize_chapter_id(chapter_id)
    )
    gate = ChapterGateService().check_chapter(
        project,
        target_chapter_id,
        draft_path=draft,
        include_review=False,
    )
    if gate.status == "block" and not force:
        console.print(
            f"[red]Blocked[/red] chapter gate {gate.score}\t{len(gate.issues)} issues"
        )
        report_path = ChapterGateService().report_path(target_chapter_id)
        console.print(f"Review {report_path} or rerun with --force")
        recovery = GateRecoveryService().recovery_plan(gate)
        for step in recovery["steps"][:3]:
            console.print(
                f"- {step['stage']}: {step['action']} "
                f"({step['issueCount']} issues)"
            )
        raise typer.Exit(1)
    output = ProjectService().accept_draft(project, draft_path=draft, chapter_id=chapter_id)
    console.print(f"[green]Accepted[/green] {draft} -> {output}")
    target_chapter_id = output.removeprefix("chapters/").removesuffix(".md")
    try:
        patch = PostChapterService().build_review_and_patch(project, target_chapter_id)
    except FileNotFoundError:
        console.print("[yellow]Skipped[/yellow] review: missing scene contract or context pack")
    else:
        console.print(f"[green]Proposed[/green] {len(patch.operations)} canon patch operations")


@project_app.command("sync-timeline")
def sync_timeline(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Sync timeline.md list items into structured memory."""
    memory = ProjectService().sync_timeline_events_from_markdown(project)
    console.print(f"[green]Synced[/green] {len(memory.events)} timeline events")


@project_app.command("new-contract")
def new_contract(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    title: Annotated[str | None, typer.Option(help="Chapter title.")] = None,
) -> None:
    """Create a structured scene contract for drafting readiness."""
    contract = StoryGuidanceService().create_scene_contract(project, chapter_id, title=title)
    console.print(f"[green]Created[/green] story/chapter-briefs/{contract.chapterId}.json")


@project_app.command("readiness")
def readiness(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
) -> None:
    """Check whether a chapter contract is ready for drafting."""
    report = StoryGuidanceService().check_readiness(project, chapter_id)
    console.print(f"{report.status}\t{report.score}")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.field}\t{issue.message}")


@project_app.command("build-context")
def build_context(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    max_estimated_tokens: Annotated[
        int | None,
        typer.Option(help="Approximate token budget for the context pack."),
    ] = None,
) -> None:
    """Build the context pack used for chapter drafting."""
    context_pack = ContextPackService().build_context_pack(
        project,
        chapter_id,
        max_estimated_tokens=max_estimated_tokens,
    )
    console.print(
        f"[green]Built[/green] {context_pack.path}\t{len(context_pack.included)} included"
    )


@project_app.command("pipeline")
def chapter_pipeline(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    refresh: Annotated[
        bool,
        typer.Option(help="Refresh the pipeline from existing chapter artifacts."),
    ] = True,
) -> None:
    """Show the auditable chapter production pipeline."""
    service = ChapterPipelineService()
    pipeline = (
        service.refresh(project, chapter_id)
        if refresh
        else service.read_pipeline(project, chapter_id)
    )
    console.print(f"{pipeline.chapterId}\t{service.pipeline_path(pipeline.chapterId)}")
    for step in pipeline.steps:
        console.print(f"{step.status}\t{step.id}\t{step.artifact}\t{step.message}")


@project_app.command("draft-chapter")
def draft_chapter(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    chapter_title: Annotated[
        str,
        typer.Option(help="Chapter title. Defaults to the scene contract title."),
    ] = "",
    agent_id: Annotated[
        str,
        typer.Option(
            help=(
                "Agent id. Leave empty to use the default trained local model when one is "
                "registered, otherwise local-dry-run."
            )
        ),
    ] = "",
    model_profile: Annotated[
        str | None,
        typer.Option(help="Writing model profile id. Implies local-model when agent is empty."),
    ] = None,
    prefer_trained_model: Annotated[
        bool,
        typer.Option(help="Prefer a registered local writing model over local-dry-run."),
    ] = True,
) -> None:
    """Draft a chapter through readiness, context pack, and model routing."""
    result = ChapterDraftService().draft_chapter(
        project,
        chapter_id,
        chapter_title=chapter_title,
        agent_id=agent_id,
        model_profile=model_profile,
        prefer_trained_model=prefer_trained_model,
    )
    console.print(
        f"[green]Drafted[/green] {chapter_id}\tagent={result.agentId}"
        f"\tmodel={result.modelProfile or '-'}"
    )
    if result.outputPath:
        console.print(f"[green]Output[/green] {result.outputPath}")


@project_app.command("review-chapter")
def review_chapter(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
) -> None:
    """Create a post-chapter review and canon patch proposal."""
    patch = PostChapterService().build_review_and_patch(project, chapter_id)
    console.print(f"[green]Reviewed[/green] {chapter_id}\t{len(patch.operations)} operations")


@project_app.command("apply-canon-patch")
def apply_canon_patch(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
) -> None:
    """Apply accepted canon patch operations to memory."""
    patch = PostChapterService().apply_canon_patch(project, chapter_id)
    applied = sum(1 for operation in patch.operations if operation.status == "applied")
    console.print(f"[green]Applied[/green] {applied} canon patch operations")


@project_app.command("accept-canon-patch")
def accept_canon_patch(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
) -> None:
    """Accept all proposed canon patch operations for later apply."""
    patch = PostChapterService().accept_canon_patch(project, chapter_id)
    accepted = sum(1 for operation in patch.operations if operation.status == "accepted")
    console.print(f"[green]Accepted[/green] {accepted} canon patch operations")


@project_app.command("check-continuity")
def check_continuity(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    draft: Annotated[str | None, typer.Option(help="Draft path.")] = None,
) -> None:
    """Run deterministic continuity checks for a chapter draft."""
    report = ContinuityService().check_draft(project, chapter_id, draft_path=draft)
    console.print(f"{report.score}\t{len(report.issues)} issues")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.type}\t{issue.message}")


@project_app.command("check-writing-quality")
def check_writing_quality(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    draft: Annotated[str | None, typer.Option(help="Draft path.")] = None,
) -> None:
    """Run Tomato-style rhythm, emotion, focus, and hook checks."""
    report = WritingQualityService().evaluate_chapter(project, chapter_id, draft_path=draft)
    console.print(f"{report.score}\t{len(report.issues)} issues")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.type}\t{issue.message}")


@project_app.command("editorial-review")
def editorial_review(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    draft: Annotated[str | None, typer.Option(help="Draft path.")] = None,
    backend: Annotated[
        str,
        typer.Option(help="Editorial backend: local or command."),
    ] = "local",
    command_template: Annotated[
        str,
        typer.Option(help="Command template for backend=command."),
    ] = "",
    timeout_seconds: Annotated[
        int,
        typer.Option(help="Command backend timeout in seconds."),
    ] = 600,
    editorial_profile: Annotated[
        str,
        typer.Option("--editorial-profile", help="Registered editorial profile id."),
    ] = "",
) -> None:
    """Run editor-grade checks for emotion, subtext, payoff, and aftertaste."""
    report = EditorialReviewService().review_chapter(
        project,
        chapter_id,
        draft_path=draft,
        backend=backend,
        command_template=command_template,
        timeout_seconds=timeout_seconds,
        profile_id=editorial_profile,
    )
    console.print(f"{report.status}\t{report.score}\t{len(report.issues)} issues")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.dimension}\t{issue.type}\t{issue.message}")


@project_app.command("evaluate-sequence")
def evaluate_sequence(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    start_chapter: Annotated[str, typer.Option(help="Start chapter id.")],
    end_chapter: Annotated[str, typer.Option(help="End chapter id.")],
) -> None:
    """Evaluate quality and gate status across a chapter range."""
    report = ChapterSequenceEvaluationService().evaluate(project, start_chapter, end_chapter)
    console.print(
        f"{report.status}\tquality>={report.minQualityScore}\tgate>={report.minGateScore}"
    )
    for chapter in report.chapters:
        console.print(
            f"{chapter.chapterId}\tquality={chapter.qualityScore}/"
            f"{chapter.qualityIssueCount}\tgate={chapter.gateStatus}/{chapter.gateScore}/"
            f"{chapter.gateIssueCount}"
        )


@project_app.command("analyze-book")
def analyze_book(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    start_chapter: Annotated[str, typer.Option(help="Start chapter id.")],
    end_chapter: Annotated[str, typer.Option(help="End chapter id.")],
) -> None:
    """Analyze accepted chapters and write a book-analysis report."""
    report = BookAnalysisService().analyze_range(project, start_chapter, end_chapter)
    console.print(
        f"{report.status}\t{len(report.chapters)} chapters\t"
        f"{len(report.formulaCandidates)} formulas\t{report.path}"
    )
    for candidate in report.formulaCandidates:
        console.print(
            f"{candidate['id']}\tchapters={','.join(candidate['evidenceChapters'])}"
        )


@project_app.command("promote-writing-formulas")
def promote_writing_formulas(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    report: Annotated[str, typer.Argument(help="Book analysis report path.")],
) -> None:
    """Promote formula candidates into suggested writing formulas."""
    memory = WritingFormulaService().promote_from_analysis(project, report)
    console.print(
        f"[green]Promoted[/green] {len(memory.formulas)} suggested formulas -> "
        f"{WritingFormulaService.memory_path}"
    )
    for formula in memory.formulas:
        console.print(f"{formula.status}\t{formula.id}\t{','.join(formula.evidenceChapters)}")


@project_app.command("validate-memory")
def validate_memory(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Validate standard memory JSON files."""
    report = MemoryValidationService().validate_project(project)
    console.print(f"{report.status}\t{report.score}\t{len(report.issues)} issues")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.path}\t{issue.type}\t{issue.message}")


@project_app.command("distill-memory")
def distill_memory(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    current_chapter: Annotated[str, typer.Option(help="Current or next chapter id.")],
    hot_window_chapters: Annotated[
        int,
        typer.Option(help="Recent chapters kept as hot memory before distillation."),
    ] = 5,
    max_topics: Annotated[int, typer.Option(help="Maximum long-term topics to keep.")] = 120,
) -> None:
    """Build a bounded long-term memory index for large novels."""
    report = MemoryDistillationService().distill_project(
        project,
        current_chapter,
        hot_window_chapters=hot_window_chapters,
        max_topics=max_topics,
    )
    console.print(
        f"[green]Distilled[/green] {report.topicCount} topics -> {report.outputPath}"
    )
    console.print(report.recommendedNextAction)


@project_app.command("propose-memory-repair")
def propose_memory_repair(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Write a proposal for repairing invalid memory files."""
    proposal = MemoryValidationService().propose_repair(project)
    console.print(
        f"[green]Proposed[/green] {len(proposal.operations)} memory repair operations"
    )
    for operation in proposal.operations:
        console.print(f"{operation.action}\t{operation.target}\t{operation.reason}")


@project_app.command("apply-memory-repair")
def apply_memory_repair(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Apply safe memory repair operations and skip manual fixes."""
    proposal = MemoryValidationService().apply_safe_repairs(project)
    applied = sum(1 for operation in proposal.operations if operation.status == "applied")
    skipped = sum(1 for operation in proposal.operations if operation.status == "skipped")
    console.print(f"[green]Applied[/green] {applied} safe memory repairs; skipped {skipped}")
    for operation in proposal.operations:
        console.print(
            f"{operation.status}\t{operation.action}\t{operation.target}\t{operation.message}"
        )


@project_app.command("chapter-gate")
def chapter_gate(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    draft: Annotated[str | None, typer.Option(help="Draft path.")] = None,
    editorial_profile: Annotated[
        str,
        typer.Option("--editorial-profile", help="Registered editorial profile id."),
    ] = "",
) -> None:
    """Aggregate readiness, context, continuity, and review risks."""
    report = ChapterGateService().check_chapter(
        project,
        chapter_id,
        draft_path=draft,
        editorial_profile_id=editorial_profile,
    )
    console.print(f"{report.status}\t{report.score}\t{len(report.issues)} issues")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.stage}\t{issue.type}\t{issue.message}")


@project_app.command("suggest-direction")
def suggest_direction(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    intent: Annotated[str, typer.Argument(help="User plot intent or setup.")],
) -> None:
    """Suggest plot direction options from user intent and current story state."""
    report = PlotDirectionService().suggest_directions(project, chapter_id, intent)
    console.print(f"[green]Recommended[/green] {report.recommendedOptionId}")
    for option in report.options:
        console.print(f"{option.recommendation}\t{option.id}\t{option.label}")


@project_app.command("apply-direction")
def apply_direction(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    option_id: Annotated[str, typer.Argument(help="Direction option id.")],
) -> None:
    """Apply a selected plot direction back to the scene contract."""
    contract = PlotDirectionService().apply_direction(project, chapter_id, option_id)
    console.print(
        f"[green]Applied[/green] {option_id} -> story/chapter-briefs/{contract.chapterId}.json"
    )


@skill_app.command("list")
def list_skills(
    skills_dir: Annotated[
        Path | None,
        typer.Option(help="Skills directory. Defaults to local ./skills or packaged built-ins."),
    ] = None,
) -> None:
    """List built-in or local skills."""
    for skill in SkillLoader(skills_dir).list_skills():
        console.print(f"{skill.id}\t{skill.priority}\t{skill.name}")


@skill_app.command("run")
def run_skill(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    skill_id: Annotated[str, typer.Argument(help="Skill id to run.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")] = "001",
    chapter_title: Annotated[str, typer.Option(help="Chapter title.")] = "Untitled Chapter",
    agent_id: Annotated[str, typer.Option(help="Agent id.")] = "local-dry-run",
    model_profile: Annotated[
        str | None,
        typer.Option(help="Writing model profile id for --agent-id local-model."),
    ] = None,
) -> None:
    """Run a skill against a project."""
    result = SkillRunner().run(
        SkillRunRequest(
            projectRoot=project,
            skillId=skill_id,
            variables={"chapterId": chapter_id, "chapterTitle": chapter_title},
            agentId=agent_id,
            modelProfile=model_profile,
        )
    )
    console.print(f"[green]Run[/green] {result.runId}")
    if result.outputPath:
        console.print(f"[green]Output[/green] {result.outputPath}")


@agent_app.command("detect")
def detect_agents() -> None:
    """Detect supported local CLI agents."""
    for agent in AgentDetectionService().detect_all():
        status = "installed" if agent.installed else "missing"
        detail = agent.version or agent.path or ""
        console.print(f"{agent.id}\t{status}\t{detail}")


@export_app.command("manuscript")
def export_manuscript(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    format: Annotated[str, typer.Option(help="Export format: markdown, txt, zip.")] = "txt",
) -> None:
    """Export canonical chapters."""
    output = ExportService().export(project, format)
    console.print(f"[green]Exported[/green] {output}")


@export_app.command("training-data")
def export_training_data(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Export accepted writing examples for offline local model tuning."""
    output = ExportService().export_writing_training_jsonl(project)
    console.print(f"[green]Exported[/green] {output}")


@export_app.command("training-readiness")
def export_training_readiness(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """Check whether accepted chapters are ready for offline local tuning."""
    report = ExportService().training_readiness(project)
    console.print(
        f"{report.status}\teligible={report.eligibleCount}\tskipped={report.skippedCount}"
    )
    console.print(report.recommendedNextAction)


@train_app.command("local-plan")
def local_training_plan(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    backend: Annotated[
        str,
        typer.Option(help="Local tuning backend: custom, mlx-lm, llama-factory."),
    ] = "custom",
    base_model: Annotated[str, typer.Option(help="Local base model path or id.")] = "",
    output_dir: Annotated[
        str,
        typer.Option(help="Adapter output directory inside the project."),
    ] = "models/adapters/latest",
    model_profile_id: Annotated[
        str,
        typer.Option(help="Writing model profile id to register after successful tuning."),
    ] = "latest-trained",
    inference_command_template: Annotated[
        str | None,
        typer.Option(
            help=(
                "Local inference command template. Supports {prompt_file}, {output_file}, "
                "{base_model}, {adapter_path}, {project}, and {profile_id}."
            )
        ),
    ] = None,
    min_examples: Annotated[
        int | None,
        typer.Option(help="Minimum eligible examples required before ready status."),
    ] = None,
    train_command: Annotated[
        str | None,
        typer.Option(help="Explicit local training command template."),
    ] = None,
) -> None:
    """Create a local fine-tuning plan from accepted high-quality chapters."""
    plan = LocalTrainingService().plan_local_tuning(
        project,
        backend=backend,
        base_model=base_model,
        output_dir=output_dir,
        model_profile_id=model_profile_id,
        inference_command_template=inference_command_template,
        min_examples=min_examples,
        train_command=train_command,
    )
    console.print(
        f"{plan.status}\teligible={plan.eligibleCount}/{plan.minRecommendedExamples}"
    )
    console.print(f"dataset={plan.datasetPath}")
    console.print(f"profile={plan.modelProfileId}")
    if plan.commandPreview:
        console.print(plan.commandPreview)
    console.print(plan.recommendedNextAction)


@train_app.command("local-run")
def local_training_run(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    backend: Annotated[
        str,
        typer.Option(help="Local tuning backend: custom, mlx-lm, llama-factory."),
    ] = "custom",
    base_model: Annotated[str, typer.Option(help="Local base model path or id.")] = "",
    output_dir: Annotated[
        str,
        typer.Option(help="Adapter output directory inside the project."),
    ] = "models/adapters/latest",
    model_profile_id: Annotated[
        str,
        typer.Option(help="Writing model profile id to register after successful tuning."),
    ] = "latest-trained",
    inference_command_template: Annotated[
        str | None,
        typer.Option(
            help=(
                "Local inference command template. Supports {prompt_file}, {output_file}, "
                "{base_model}, {adapter_path}, {project}, and {profile_id}."
            )
        ),
    ] = None,
    min_examples: Annotated[
        int | None,
        typer.Option(help="Minimum eligible examples required before ready status."),
    ] = None,
    train_command: Annotated[
        str | None,
        typer.Option(help="Explicit local training command template."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(help="Run even when the plan is warning/blocking."),
    ] = False,
    timeout_seconds: Annotated[int, typer.Option(help="Training command timeout.")] = 3600,
) -> None:
    """Run an explicit local fine-tuning command after readiness checks."""
    run = LocalTrainingService().run_local_tuning(
        project,
        backend=backend,
        base_model=base_model,
        output_dir=output_dir,
        model_profile_id=model_profile_id,
        inference_command_template=inference_command_template,
        min_examples=min_examples,
        train_command=train_command,
        force=force,
        timeout_seconds=timeout_seconds,
    )
    console.print(f"{run.status}\texit={run.exitCode}")
    if run.modelProfileId:
        console.print(f"profile={run.modelProfileId}\tregistry={run.modelProfilePath}")
    console.print(run.message)


@model_app.command("list")
def list_model_profiles(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """List registered local writing model profiles."""
    registry = WritingModelService().read_registry(project)
    console.print(f"default={registry.defaultProfileId or '-'}")
    for profile in registry.profiles:
        default_marker = "*" if profile.id == registry.defaultProfileId else " "
        console.print(
            f"{default_marker} {profile.id}\t{profile.agentId}\t"
            f"base={profile.baseModel or '-'}\tadapter={profile.adapterPath or '-'}"
        )


@model_app.command("register")
def register_model_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile_id: Annotated[str, typer.Argument(help="Profile id.")],
    base_model: Annotated[str, typer.Option(help="Local base model path or id.")] = "",
    adapter_path: Annotated[str, typer.Option(help="Adapter path inside the project.")] = "",
    command_template: Annotated[
        str,
        typer.Option(
            help=(
                "Local inference command template. Supports {prompt_file}, {output_file}, "
                "{base_model}, {adapter_path}, {project}, and {profile_id}."
            )
        ),
    ] = "",
    label: Annotated[str, typer.Option(help="Human-readable label.")] = "",
    timeout_seconds: Annotated[int, typer.Option(help="Inference timeout.")] = 600,
    set_default: Annotated[bool, typer.Option(help="Make this the default profile.")] = True,
) -> None:
    """Register an existing local adapter or model for chapter drafting."""
    profile = WritingModelService().register_profile(
        project,
        profile_id=profile_id,
        base_model=base_model,
        adapter_path=adapter_path,
        command_template=command_template,
        label=label,
        timeout_seconds=timeout_seconds,
        set_default=set_default,
    )
    console.print(f"[green]Registered[/green] {profile.id}")


@model_app.command("use")
def use_model_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile_id: Annotated[str, typer.Argument(help="Profile id.")],
) -> None:
    """Set the default local writing model profile."""
    WritingModelService().set_default_profile(project, profile_id)
    console.print(f"[green]Default[/green] {profile_id}")


@model_app.command("compare")
def compare_model_profiles(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    start_chapter_id: Annotated[str, typer.Option(help="Start chapter id.")] = "001",
    chapter_count: Annotated[
        int,
        typer.Option(help="Number of chapters to compare."),
    ] = 5,
    base_profile_id: Annotated[
        str,
        typer.Option(help="Baseline local writing model profile id."),
    ] = "",
    tuned_profile_id: Annotated[
        str,
        typer.Option(help="Candidate tuned local writing model profile id."),
    ] = "",
    reference_agent_id: Annotated[
        str,
        typer.Option(help="Reference agent id for a non-model baseline."),
    ] = "local-dry-run",
    include_reference_agent: Annotated[
        bool,
        typer.Option(help="Include a CLI/dry-run reference candidate."),
    ] = True,
) -> None:
    """Run a five-chapter model comparison and write a comparison report."""
    report = ModelComparisonService().compare_five_chapter_profiles(
        project,
        start_chapter_id=start_chapter_id,
        chapter_count=chapter_count,
        base_profile_id=base_profile_id,
        tuned_profile_id=tuned_profile_id,
        reference_agent_id=reference_agent_id,
        include_reference_agent=include_reference_agent,
    )
    best_candidate = report.summary.bestCandidateLabel or report.summary.bestCandidateId
    console.print(
        f"{report.summary.bestStatus}\tbest={best_candidate}"
    )
    console.print(
        f"base={report.summary.baseCandidateId}/{report.summary.baseQualityScore}/"
        f"{report.summary.baseGateScore}/editorial={report.summary.baseEditorialScore}"
        f"/issues={report.summary.baseEditorialHighOrBlockerCount}"
    )
    console.print(
        f"tuned={report.summary.tunedCandidateId}/{report.summary.tunedQualityScore}/"
        f"{report.summary.tunedGateScore}/editorial={report.summary.tunedEditorialScore}"
        f"/issues={report.summary.tunedEditorialHighOrBlockerCount}"
    )
    if report.summary.referenceCandidateId:
        console.print(
            f"reference={report.summary.referenceCandidateId}/"
            f"{report.summary.referenceQualityScore}/{report.summary.referenceGateScore}"
            f"/editorial={report.summary.referenceEditorialScore}"
        )
    console.print(
        f"decision={report.summary.promotionDecision or '-'}\t"
        f"safeDefault={str(report.summary.safeToSetDefault).lower()}"
    )
    if report.summary.promotionReasons:
        console.print("reasons=" + ",".join(report.summary.promotionReasons))
    console.print(report.recommendedNextAction)
    report_path = ModelComparisonService().report_path(report.comparisonId)
    console.print(f"[green]Report[/green] {report_path}")


@model_app.command("promote-comparison")
def promote_model_comparison(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    report: Annotated[str, typer.Argument(help="Comparison report path in the project.")],
) -> None:
    """Set the tuned model as default from a safe five-chapter comparison report."""
    registry = ModelComparisonService().promote_tuned_profile_from_report(project, report)
    console.print(f"[green]Default[/green] {registry.defaultProfileId}")


@editor_app.command("list")
def list_editorial_profiles(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
) -> None:
    """List registered editorial review profiles."""
    registry = EditorialProfileService().read_registry(project)
    console.print(f"default={registry.defaultProfileId or '-'}")
    for profile in registry.profiles:
        default_marker = "*" if profile.id == registry.defaultProfileId else " "
        command_marker = "command" if profile.commandTemplate else "-"
        console.print(
            f"{default_marker} {profile.id}\t{profile.backend}\t"
            f"preset={profile.promptPreset}\tcommand={command_marker}"
        )


@editor_app.command("presets")
def list_editorial_prompt_presets() -> None:
    """List built-in editorial prompt presets."""
    for preset in EditorialProfileService().list_prompt_presets():
        focus = ",".join(preset.focus) or "-"
        console.print(f"{preset.id}\t{focus}\t{preset.label}")


@editor_app.command("register")
def register_editorial_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile_id: Annotated[str, typer.Argument(help="Profile id.")],
    backend: Annotated[
        str,
        typer.Option(help="Editorial backend: local or command."),
    ] = "local",
    command_template: Annotated[
        str,
        typer.Option(
            help=(
                "Command template for backend=command. Supports {project}, "
                "{prompt_file}, {output_file}, {chapter_id}, and {source}."
            )
        ),
    ] = "",
    label: Annotated[str, typer.Option(help="Human-readable label.")] = "",
    reviewer: Annotated[str, typer.Option(help="Reviewer name written to reports.")] = "",
    prompt_preset: Annotated[
        str,
        typer.Option(help="Built-in prompt preset id. Use `editor presets` to list options."),
    ] = "generic-humanity",
    style_profile_path: Annotated[
        str,
        typer.Option(help="Project style profile path."),
    ] = DEFAULT_STYLE_PROFILE_PATH,
    rubric: Annotated[
        str,
        typer.Option(help="Optional custom rubric, one item per line."),
    ] = "",
    timeout_seconds: Annotated[int, typer.Option(help="Command timeout.")] = 600,
    set_default: Annotated[bool, typer.Option(help="Make this the default profile.")] = True,
) -> None:
    """Register a local or command-backed editorial review profile."""
    profile = EditorialProfileService().register_profile(
        project,
        profile_id=profile_id,
        backend=backend,
        command_template=command_template,
        label=label,
        reviewer=reviewer,
        prompt_preset=prompt_preset,
        style_profile_path=style_profile_path,
        rubric=rubric.splitlines(),
        timeout_seconds=timeout_seconds,
        set_default=set_default,
    )
    console.print(f"[green]Registered[/green] {profile.id}")


@editor_app.command("use")
def use_editorial_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile_id: Annotated[str, typer.Argument(help="Profile id.")],
) -> None:
    """Set the default editorial review profile."""
    EditorialProfileService().set_default_profile(project, profile_id)
    console.print(f"[green]Default[/green] {profile_id}")


@style_app.command("list")
def list_style_profiles() -> None:
    """List built-in platform and genre style templates."""
    service = StyleProfileService()
    for profile in service.list_builtin_profiles():
        profile_data = profile.model_dump(mode="json")
        console.print(
            f"{profile.id}\tplatform={profile.platform}\t"
            f"genres={','.join(profile.genres) or '-'}\t"
            f"maturity={profile_data.get('maturity', '-')}\t{profile.label}"
        )
    planned = service.list_planned_profile_slots()
    if planned:
        console.print("[dim]planned slots[/dim]")
        for slot in planned:
            genres = ",".join(str(item) for item in slot.get("genres", [])) or "-"
            console.print(
                f"{slot['id']}\tplatform={slot['platform']}\t"
                f"genres={genres}\t{slot['label']}"
            )
    coverage = service.list_coverage_catalog()
    if coverage:
        console.print("[dim]coverage catalog[/dim]")
        for item in coverage:
            families = ",".join(str(value) for value in item.get("genreFamilies", [])) or "-"
            console.print(
                f"{item['platform']}\tstatus={item['status']}\t"
                f"families={families}\t{item['label']}"
            )
    packs = service.list_template_packs()
    if packs:
        console.print("[dim]template packs[/dim]")
        for pack in packs:
            planned_count = len(pack.get("plannedProfileIds", []))
            active_count = len(pack.get("activeProfileIds", []))
            console.print(
                f"{pack['id']}\tstatus={pack['status']}\t"
                f"active={active_count}\tplanned={planned_count}\t{pack['label']}"
            )


@style_app.command("validate-catalog")
def validate_style_catalog() -> None:
    """Validate built-in style catalog profile and coverage references."""
    result = StyleProfileService().validate_catalog()
    policy = result.get("policy", {})
    activation = policy.get("plannedSlotActivationCriteria", {})
    required_samples = (
        activation.get("requiredSampleChapters", "-")
        if isinstance(activation, dict)
        else "-"
    )
    console.print(
        "[green]STYLE_CATALOG: PASS[/green] "
        f"profiles={result['profileCount']} "
        f"planned={result['plannedSlotCount']} "
        f"coverage={result['coverageCount']} "
        f"packs={result['templatePackCount']} "
        f"planned-samples={required_samples}"
    )


@style_app.command("draft-profile")
def draft_style_profile(
    slot_id: Annotated[str, typer.Argument(help="Planned style slot id.")],
    output: Annotated[
        Path | None,
        typer.Option(help="Write candidate profile JSON to this path; prints JSON when omitted."),
    ] = None,
    label: Annotated[str, typer.Option(help="Override candidate profile label.")] = "",
) -> None:
    """Draft a candidate built-in style profile from a planned slot."""
    text = StyleProfileService().draft_profile_text_from_planned_slot(slot_id, label=label)
    if output is None:
        console.print(text.rstrip())
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    console.print(f"[green]Drafted[/green] {slot_id} -> {output}")


@style_app.command("evaluate-promotion")
def evaluate_style_profile_promotion(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    candidate: Annotated[str, typer.Option(help="Candidate style profile path in project.")],
    start_chapter: Annotated[str, typer.Option(help="Start chapter id.")],
    end_chapter: Annotated[str, typer.Option(help="End chapter id.")],
    prefer_drafts: Annotated[
        bool,
        typer.Option(help="Prefer drafts/{chapter}.generated.md when available."),
    ] = True,
) -> None:
    """Evaluate whether a candidate style profile is ready for promotion."""
    report = StyleProfilePromotionService().evaluate_candidate(
        project,
        candidate,
        start_chapter,
        end_chapter,
        prefer_drafts=prefer_drafts,
    )
    console.print(
        f"{report['status']}\tprofile={report['profileId']}\t"
        f"quality>={report['sequence']['minQualityScore']}\t"
        f"gate>={report['sequence']['minGateScore']}\t"
        f"issues={len(report['issues'])}"
    )
    for issue in report["issues"]:
        console.print(f"{issue['severity']}\t{issue['type']}\t{issue['message']}")


@style_app.command("export-promoted-profile")
def export_promoted_style_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    report: Annotated[str, typer.Option(help="Promotion report path in project.")],
    output: Annotated[
        str,
        typer.Option(help="Output path in project for the exported active profile."),
    ] = "",
) -> None:
    """Export a ready promotion report into an active profile JSON for human review."""
    result = StyleProfilePromotionService().export_promotable_profile(
        project,
        report,
        output_path=output,
    )
    console.print(f"[green]Exported[/green] {result['profileId']} -> {result['outputPath']}")


@style_app.command("validate-exported-profile")
def validate_exported_style_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile: Annotated[str, typer.Option(help="Exported active profile path in project.")],
) -> None:
    """Validate an exported active style profile before manual catalog merge."""
    result = StyleProfilePromotionService().validate_exported_profile(project, profile)
    console.print(
        f"{result['status']}\tprofile={result['profileId']}\t"
        f"issues={len(result['issues'])}\t{result['recommendedNextAction']}"
    )
    for issue in result["issues"]:
        console.print(f"{issue['severity']}\t{issue['type']}\t{issue['message']}")


@style_app.command("apply")
def apply_style_profile(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    profile_id: Annotated[str, typer.Argument(help="Built-in style profile id.")],
    project_profile_id: Annotated[
        str,
        typer.Option(help="Project style profile id written to story/style-profile.json."),
    ] = "project-style",
    label: Annotated[str, typer.Option(help="Project style profile label.")] = "",
    path: Annotated[str, typer.Option(help="Project style profile path.")] = (
        DEFAULT_STYLE_PROFILE_PATH
    ),
) -> None:
    """Apply a built-in style template as the project editable style override."""
    profile = StyleProfileService().write_project_profile_from_builtin(
        project,
        profile_id,
        project_profile_id=project_profile_id,
        label=label or "Project style override",
        relative_path=path,
    )
    console.print(f"[green]Applied[/green] {profile.extends} -> {path}")


@director_app.command("plan")
def director_plan(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")],
    intent: Annotated[str, typer.Argument(help="User intent for this chapter.")],
) -> None:
    """Create an auditable director plan without writing canon."""
    plan = DirectorService().create_plan(project, chapter_id, intent)
    console.print(f"[green]Planned[/green] {plan.planId} -> {plan.planPath}")
    for step in plan.steps:
        approval = "approval" if step.requiresApproval else "auto"
        console.print(f"{step.status}\t{step.id}\t{approval}\t{step.artifact}")


@director_app.command("dry-run")
def director_dry_run(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    plan: Annotated[str, typer.Argument(help="Director plan path in project.")],
) -> None:
    """Validate a director plan and record a no-op dry run."""
    report = DirectorService().dry_run(project, plan)
    console.print(f"[green]Dry run[/green] {report.planId} -> {report.status}")
    console.print(report.message)


@director_app.command("run")
def director_run(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    plan: Annotated[str, typer.Argument(help="Director plan path in project.")],
) -> None:
    """Run safe automatic director steps without accepting canon changes."""
    report = DirectorService().run(project, plan)
    console.print(f"[green]Run[/green] {report.planId} -> {report.status}")
    for step in report.executedSteps:
        console.print(f"{step.status}\t{step.id}\t{step.artifact}\t{step.rationale}")
    if report.status == "blocked":
        raise typer.Exit(1)


@prompt_app.command("list")
def prompt_registry_list() -> None:
    """List prompt registry entries built from current skills."""
    report = PromptRegistryService().build_from_skills()
    console.print(f"{report.status}\tentries={len(report.entries)}\tissues={len(report.issues)}")
    for entry in report.entries:
        console.print(f"{entry.status}\t{entry.id}\t{entry.kind}\t{entry.source}")


@prompt_app.command("validate")
def prompt_registry_validate() -> None:
    """Validate prompt registry entries built from current skills."""
    report = PromptRegistryService().build_from_skills()
    console.print(f"{report.status}\tentries={len(report.entries)}\tissues={len(report.issues)}")
    for issue in report.issues:
        console.print(f"{issue.severity}\t{issue.entryId}\t{issue.message}")
    if report.status == "block":
        raise typer.Exit(1)


@prompt_app.command("export")
def prompt_registry_export(
    output: Annotated[
        Path,
        typer.Option(help="Output path for the generated prompt registry catalog."),
    ] = Path("open_novel/builtin_prompt_registry/catalog.json"),
) -> None:
    """Export the generated prompt registry catalog for review."""
    report = PromptRegistryService().write_builtin_catalog(output)
    console.print(f"[green]Exported[/green] entries={len(report.entries)} -> {output}")


@prompt_app.command("eval")
def prompt_registry_eval(
    project: Annotated[Path, typer.Option(help="Novel project folder.")],
    entry_id: Annotated[
        str,
        typer.Option(help="Prompt registry entry id to evaluate."),
    ] = "chapter-writer.v1",
    chapter_id: Annotated[str, typer.Option(help="Chapter id.")] = "001",
    chapter_title: Annotated[str, typer.Option(help="Chapter title.")] = "",
    all_active: Annotated[
        bool,
        typer.Option(help="Evaluate all active prompt registry entries."),
    ] = False,
) -> None:
    """Run local prompt evals and write a report without touching canon."""
    report = PromptEvalService().evaluate(
        project,
        entry_id=entry_id,
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        all_active=all_active,
    )
    console.print(
        f"{report.status}\tentries={len(report.entries)}\tissues={len(report.issues)}"
        f"\t{report.path}"
    )
    for result in report.results:
        console.print(
            f"{result.status}\t{result.entryId}\tscore={result.score}"
            f"\t{result.outputPath or '-'}"
        )
    if report.status == "block":
        raise typer.Exit(1)
