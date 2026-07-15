# Long Form Replanner

Create a replan candidate for future, unfinalized chapters after a significant goal change.

Deviation report:

{deviationReport}

Return the same JSON contract as `long-form-planner`.

Also return `chapterAdjustments` for every affected unfinalized chapter. Each item must contain `chapterId`, `segmentId`, `goal`, `hook`, `promiseProgression`, and `logicDependencies`.

Rules:

- The whole book target is {targetChapterCount} chapters.
- Future beat segments should normally cover about {targetChaptersPerPlot} chapters; only deviate when the revised story pressure or payoff clearly requires it.
- Preserve all finalized chapter outcomes and accepted memory.
- Change only the current and future volume strategy and beat segments.
- Explain the revised causal path through concrete goals, pressure, and payoff.
- Return JSON only, without Markdown or file writes.
