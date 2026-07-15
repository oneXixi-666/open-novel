# Readiness Gate

Evaluate whether the selected scene is ready for chapter drafting.

Return JSON:

```json
{
  "status": "pass | warn | block",
  "score": 0,
  "issues": [
    {
      "severity": "low | medium | high | blocker",
      "field": "goal",
      "message": "",
      "quickFix": ""
    }
  ],
  "missingContext": [],
  "recommendedNextAction": ""
}
```

Block drafting when focus, goal, conflict, turn, outcome, hook, emotional beat, or required canon context is missing.
Warn when logic dependencies, must-avoid boundaries, reader promises, or relationship beats are weak.
