from __future__ import annotations

from open_novel.core.markdown import MarkdownPreviewRenderer


def test_markdown_preview_renders_headings_and_paragraphs() -> None:
    html = MarkdownPreviewRenderer().render("# Title\n\nBody")

    assert "<h1>Title</h1>" in html
    assert "<p>Body</p>" in html


def test_markdown_preview_escapes_html() -> None:
    html = MarkdownPreviewRenderer().render("# <script>")

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
