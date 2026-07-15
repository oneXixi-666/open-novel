from __future__ import annotations

from difflib import unified_diff
from html import escape


class TextDiffService:
    def unified(self, left: str, right: str, fromfile: str, tofile: str) -> str:
        return "".join(
            unified_diff(
                left.splitlines(keepends=True),
                right.splitlines(keepends=True),
                fromfile=fromfile,
                tofile=tofile,
            )
        )

    def render_html(self, diff_text: str) -> str:
        lines: list[str] = []
        for line in diff_text.splitlines():
            css_class = "diff-line"
            if line.startswith("+") and not line.startswith("+++"):
                css_class = "diff-add"
            elif line.startswith("-") and not line.startswith("---"):
                css_class = "diff-remove"
            elif line.startswith("@@"):
                css_class = "diff-hunk"
            lines.append(f'<div class="{css_class}">{escape(line)}</div>')
        return "\n".join(lines)
