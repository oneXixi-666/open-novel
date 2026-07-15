from __future__ import annotations

import re


def pipeline_step_label(step_id: str) -> str:
    labels = {
        "scene_contract": "章节要求",
        "readiness": "开写准备",
        "context_pack": "本章资料",
        "draft": "候选稿",
        "gate": "审稿诊断",
        "post_review": "复盘报告",
        "canon_patch": "故事记忆更新",
    }
    return labels.get(step_id, step_id.replace("_", " ") if step_id else "进度步骤")


def pipeline_status_label(status: str) -> str:
    labels = {
        "missing": "未准备",
        "pending": "待准备",
        "ready": "已准备",
        "blocked": "需处理",
        "skipped": "已跳过",
        "complete": "已完成",
        "completed": "已完成",
    }
    return labels.get(status, status.replace("-", " ") if status else "待准备")


def pipeline_message_label(message: str) -> str:
    labels = {
        "artifact exists": "已准备好",
        "waiting for artifact": "等待准备",
        "context pack rebuilt after scene contract save": "本章资料已随章节要求更新",
    }
    if message in labels:
        return labels[message]
    updated = message or ""
    replacements = {
        "context pack": "本章资料",
        "Context Pack": "本章资料",
        "drafts": "候选稿",
        "chapters": "正文",
    }
    for source, target in replacements.items():
        updated = updated.replace(source, target)
    return updated


def run_preview(markdown: str, empty_message: str) -> str:
    if not markdown.strip():
        return empty_message
    hidden_markers = (
        "skillId",
        "agentId",
        "runId",
        "outputPath",
        "packageId",
        "diagnosisPath",
        "reportPath",
        "command",
        "运行 JSON",
    )
    replacements = {
        "Context Pack": "本章资料",
        "context pack": "本章资料",
        "prompt": "写作要求",
        "Prompt": "写作要求",
        "drafts": "候选稿",
        "chapters": "正文",
        "memory": "故事记忆",
        "runs": "任务记录",
        "JSON": "原始记录",
    }
    visible_lines: list[str] = []
    in_code_block = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not stripped:
            continue
        if any(marker in stripped for marker in hidden_markers):
            continue
        if stripped.startswith(("{", "}", "[", "]")):
            continue
        if re.search(r'"[A-Za-z][A-Za-z0-9_]*"\s*:', stripped):
            continue
        updated = stripped
        updated = re.sub(
            r"\b(?:runs|drafts|chapters|memory|story)/[^\s`'\"，。；、]+",
            "相关资料",
            updated,
        )
        for source, target in replacements.items():
            updated = updated.replace(source, target)
        updated = re.sub(r"\s+", " ", updated).strip()
        if updated:
            visible_lines.append(updated)
    if not visible_lines:
        return empty_message
    return "\n".join(visible_lines)


def run_status_label(status: object) -> str:
    value = str(status or "").strip()
    labels = {
        "queued": "等待中",
        "running": "进行中",
        "completed": "已完成",
        "success": "已完成",
        "recorded": "已有记录",
        "failed": "失败",
        "error": "失败",
        "cancelled": "已取消",
        "interrupted": "已中断",
        "skipped": "已跳过",
    }
    return labels.get(value, value.replace("-", " ") if value else "已有记录")


def job_kind_label(kind: object) -> str:
    labels = {
        "skill-run": "写作任务",
        "local-training": "模型训练",
        "five-chapter-regression": "五章回归",
        "model-comparison": "模型对比",
        "style-profile-promotion": "风格模板评估",
        "chapter-draft": "AI 起草",
        "line-polish": "一键润色",
        "revision-rerun": "修订复测",
    }
    return labels.get(str(kind or ""), "写作任务")


def job_status_label(status: object) -> str:
    labels = {
        "queued": "等待中",
        "running": "进行中",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
        "interrupted": "已中断",
    }
    return labels.get(str(status or ""), str(status or "") or "-")


def job_progress_label(progress: object) -> str:
    if not isinstance(progress, dict) or not progress:
        return ""
    completed = progress.get("completed")
    total = progress.get("total")
    if completed is not None and total:
        return f"进度 {completed}/{total}"
    step = progress.get("step") or progress.get("message")
    if step:
        return f"进度 {step}"
    return "正在处理"
