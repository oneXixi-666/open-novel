from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterProgressPolicy:
    pending: int = 0
    draft_start: int = 10
    draft_end: int = 80
    review: int = 90
    complete: int = 100


DEFAULT_CHAPTER_PROGRESS_POLICY = ChapterProgressPolicy()


def calculate_chapter_progress(
    status: str,
    word_count: int,
    target_word_count: int,
    *,
    policy: ChapterProgressPolicy = DEFAULT_CHAPTER_PROGRESS_POLICY,
) -> int:
    if status == "完成":
        return policy.complete
    if status == "审阅":
        return policy.review
    if status != "草稿":
        return policy.pending

    safe_word_count = max(0, word_count)
    safe_target = max(1, target_word_count)
    draft_ratio = min(1.0, safe_word_count / safe_target)
    draft_span = policy.draft_end - policy.draft_start
    return round(policy.draft_start + draft_span * draft_ratio)
