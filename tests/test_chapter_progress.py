from open_novel.core.chapter_progress import calculate_chapter_progress


def test_chapter_progress_uses_word_completion_inside_draft_stage() -> None:
    assert calculate_chapter_progress("待写", 0, 2000) == 0
    assert calculate_chapter_progress("草稿", 0, 2000) == 10
    assert calculate_chapter_progress("草稿", 500, 2000) == 28
    assert calculate_chapter_progress("草稿", 1000, 2000) == 45
    assert calculate_chapter_progress("草稿", 2000, 2000) == 80
    assert calculate_chapter_progress("草稿", 3000, 2000) == 80
    assert calculate_chapter_progress("审阅", 1000, 2000) == 90
    assert calculate_chapter_progress("完成", 1000, 2000) == 100
