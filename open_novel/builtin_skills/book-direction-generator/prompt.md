# Book Direction Generator

Generate exactly {optionCount} genuinely different long-form novel directions for this book.

Book title: {bookTitle}
Genre: {genre}
Initial idea: {idea}
Style: {styleLabel}

Return one JSON object and nothing else:

```json
{
  "recommendedOptionId": "direction-1",
  "options": [
    {
      "id": "direction-1",
      "title": "short direction name",
      "genrePositioning": "specific genre and serial positioning",
      "protagonistDesire": "concrete long-term desire",
      "centralConflict": "sustainable central conflict",
      "serialHook": "long-term reader hook",
      "targetReaderExperience": "intended reader experience",
      "risks": ["main execution risk"],
      "recommendation": "why this direction should or should not be selected"
    }
  ]
}
```

Rules:

- The options must differ in story engine, protagonist pressure, escalation path, and reader payoff.
- Use the supplied idea and project context. Do not substitute a generic mystery, hidden organization, memory cost, or numbered clue template.
- Each direction must sustain a long serial, not only an opening chapter.
- Do not write files, Markdown commentary, or code fences around the final JSON.
