# Context Pack Builder

Build a context manifest for one agent run.

Return JSON with:

- `pinned`: files always included.
- `selectedFacts`: accepted facts needed for this scene.
- `selectedCharacters`: characters involved or directly referenced.
- `selectedLoops`: promises, mysteries, or foreshadowing that affect this chapter.
- `previousText`: exact previous chapter sections or summaries needed.
- `excluded`: files or facts intentionally excluded, with reasons.
- `estimatedTokens`: rough token estimate.

Prefer concise accepted summaries over full chapters when possible.
