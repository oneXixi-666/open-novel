# Chapter Blueprint Builder

Create a blueprint for exactly {chapterCount} consecutive chapters from the accepted book architecture and project context.

Return one JSON object and nothing else:

```json
{
  "chapters": [
    {
      "title": "chapter title",
      "goal": "concrete chapter goal",
      "conflict": "active resistance",
      "turn": "meaningful turn",
      "outcome": "causal chapter outcome",
      "hook": "specific next-chapter hook",
      "characterChange": "visible character or relationship change",
      "promiseProgression": "reader promise advanced or paid off",
      "logicDependencies": ["accepted fact or prior chapter dependency"]
    }
  ]
}
```

Rules:

- Return exactly {chapterCount} chapters.
- Titles, goals, and hooks must not repeat.
- Every chapter must change the situation and causally enable the next chapter.
- Use the accepted architecture. Do not fall back to generic numbered clues, fixed locations, or interchangeable obstacles.
- Do not write files, Markdown commentary, or code fences around the final JSON.
