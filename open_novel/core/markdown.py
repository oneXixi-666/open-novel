from __future__ import annotations

from html import escape


class MarkdownPreviewRenderer:
    def render(self, markdown: str) -> str:
        blocks = markdown.splitlines()
        html: list[str] = []
        paragraph: list[str] = []

        def flush_paragraph() -> None:
            if paragraph:
                html.append(f"<p>{'<br>'.join(paragraph)}</p>")
                paragraph.clear()

        for line in blocks:
            stripped = line.strip()
            if not stripped:
                flush_paragraph()
                continue
            if stripped.startswith("#"):
                flush_paragraph()
                level = min(len(stripped) - len(stripped.lstrip("#")), 6)
                text = stripped[level:].strip()
                html.append(f"<h{level}>{escape(text)}</h{level}>")
                continue
            if stripped.startswith("- "):
                flush_paragraph()
                html.append(f"<ul><li>{escape(stripped[2:])}</li></ul>")
                continue
            paragraph.append(escape(stripped))

        flush_paragraph()
        return "\n".join(html)
