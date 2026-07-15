# Book Architecture Builder

Expand the confirmed book direction into an executable long-form novel architecture.

Confirmed direction:

{selectedDirection}

Return one JSON object and nothing else with these fields:

`directionTitle`, `genrePositioning`, `coreSellingPoints`, `protagonistGoal`, `centralConflict`, `storyEngine`, `escalationPath`, `longTermHooks`, `targetReaderExperience`, `risks`, `recommendation`.

Rules:

- `coreSellingPoints`, `longTermHooks`, and `risks` must be non-empty string arrays.
- Preserve the confirmed direction while making its serial engine, escalation path, and reader payoff concrete.
- The architecture must support multiple volumes and causal chapter planning.
- Do not use generic hidden organizations, memory costs, fixed locations, or numbered clues unless the confirmed direction requires them.
- Do not write files, Markdown commentary, or code fences around the final JSON.
