from __future__ import annotations

from open_novel.core.diff import TextDiffService


def test_unified_diff_marks_added_and_removed_lines() -> None:
    diff = TextDiffService().unified("old\n", "new\n", "left", "right")

    assert "--- left" in diff
    assert "+++ right" in diff
    assert "-old" in diff
    assert "+new" in diff


def test_diff_html_escapes_content() -> None:
    html = TextDiffService().render_html("+<script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
