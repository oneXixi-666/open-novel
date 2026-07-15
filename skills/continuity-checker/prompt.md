# Continuity Checker

Review the draft against accepted canon.

Return JSON:

```json
{
  "score": 0,
  "issues": [
    {
      "type": "missing_must_include | violated_must_avoid | focus_drift | outcome_drift | hook_drift | emotional_discontinuity | relationship_discontinuity | reader_promise_drift | character_state_contradiction | payoff_due_soon | payoff_overdue | ungrounded_logic_dependency | timeline_order_conflict | contradiction | weak_motivation | unsupported_reveal | power_rule_error",
      "severity": "low | medium | high | blocker",
      "evidence": "",
      "message": "",
      "suggestions": []
    }
  ]
}
```

Use `memory/character-states.json` continuity anchors when judging character-state reversals.
Only cite facts present in the provided context. Do not invent hidden canon to solve a contradiction.
Distinguish a character's evidence-based misreading, self-deception, incomplete answer, or revised judgment from an author-level factual contradiction. Report it only when the draft presents the subjective belief as objective canon or breaks established knowledge without cause.
Use `emotional_discontinuity` when an important reaction or choice lacks a perceptible emotional cause, pressure, or consequence. Do not require an emotion label, a body reaction, or a complete explanation at every beat.
Suppressed emotion still counts when it changes attention, avoidance, wording, action, choice, or cost. Do not treat restraint or unresolved feeling as missing emotion by itself.
Do not recommend deliberate typos, factual mistakes, logic gaps, random stammering, or arbitrary bad decisions as signs of humanity.
