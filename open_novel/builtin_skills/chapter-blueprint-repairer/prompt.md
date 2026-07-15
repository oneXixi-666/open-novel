# Chapter Blueprint Repairer

Repair the rejected blueprint into exactly {chapterCount} consecutive chapters.

Validation feedback: {validationFeedback}

Rejected blueprint:

{previousBlueprint}

Return one JSON object with the same chapter fields as the rejected blueprint and nothing else.

Rules:

- Return exactly {chapterCount} chapters. Count them before answering.
- Preserve the accepted direction and strongest causal sequence, but merge or split chapters as needed.
- Titles, goals, and hooks must be unique.
- Every chapter must include title, goal, conflict, turn, outcome, hook, characterChange, promiseProgression, and logicDependencies.
- Do not truncate the ending mechanically; keep a causal final hook for the requested range.
- Do not write files, Markdown commentary, or code fences around the final JSON.
