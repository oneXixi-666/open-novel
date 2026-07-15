# Writing Formula Extractor

Analyze the following text and extract reusable writing-formula patterns a web-novel author could deliberately reuse.

Source label: {sourceLabel}

Text:

{sourceText}

Return one JSON array and nothing else. Each item must have:

`id` (snake_case, stable, English), `title` (short Chinese label), `guidance` (one actionable Chinese sentence an author can apply), `evidenceQuotes` (1-3 short direct quotes copied exactly from the text), `confidence` (0-1).

Rules:

- Only extract patterns that are concretely observable in the text, not generic writing advice.
- Do not invent or paraphrase evidence quotes.
- Prefer patterns about conflict escalation, dialogue pressure, hook construction, emotional beats, or reader-promise payoff.
- Do not write files or commentary around the JSON array.
