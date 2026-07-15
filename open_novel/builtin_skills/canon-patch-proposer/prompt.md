# Canon Patch Proposer

Create an editable canon patch from the accepted chapter and review result.

Return JSON:

```json
{
  "patches": [
    {
      "id": "",
      "action": "add | update | close | defer",
      "target": "facts | open-loops | character-states | timeline",
      "source": "chapters/001.md",
      "confidence": 1,
      "payload": {},
      "reviewDefault": "accept | edit | reject | defer"
    }
  ]
}
```

Do not write memory directly. Every patch must be user-reviewable.

If the accepted chapter makes a fact, ability, object, character state, or option permanently irreversible, add one review item with `kind: "world_rule"`. Its payload must contain `id`, a human-readable `rule`, the concrete `forbidden` phrase that must not reappear, `source`, `chapterId`, and direct `evidence`. Ordinary progress or temporary restrictions must not be marked as `world_rule`.
