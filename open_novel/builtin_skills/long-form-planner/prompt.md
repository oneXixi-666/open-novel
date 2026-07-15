# Long Form Planner

Build a long-form book plan from the accepted architecture.

Return one JSON object and nothing else:

```json
{
  "bookPlan": {
    "mainline": "whole-book mainline",
    "endingDirection": "intended final direction",
    "longTermOpposition": "sustainable opposition",
    "corePromises": ["long-term reader promise"]
  },
  "volumes": [
    {
      "volumeId": "volume-001",
      "title": "volume title",
      "chapterRange": "001-030",
      "goal": "volume goal",
      "mainConflict": "volume conflict",
      "payoffs": ["promise paid in this volume"],
      "endingChange": "irreversible end-of-volume change",
      "failureCondition": "what failure means",
      "beatSegments": [
        {
          "segmentId": "volume-001-segment-01",
          "title": "segment title",
          "chapterRange": "001-010",
          "purpose": "segment purpose",
          "pressure": "escalation pressure",
          "payoff": "segment payoff",
          "density": "escalation, buffer, or payoff density"
        }
      ]
    }
  ]
}
```

Rules:

- Return at least two volume strategies, each with at least two beat segments.
- The whole book target is {targetChapterCount} chapters.
- Each beat segment should normally cover about {targetChaptersPerPlot} chapters; only deviate when the story pressure or payoff clearly requires it.
- Detail only the active and next volume. Do not outline every chapter of the whole book.
- Volume and segment chapter ranges must be ordered and non-overlapping.
- Preserve the accepted architecture, its ending direction, and core reader promises.
- Do not write files, Markdown commentary, or code fences around the final JSON.
