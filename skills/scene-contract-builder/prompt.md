# Scene Contract Builder

Create a scene contract for the requested chapter or scene.

Return:

- A concise Markdown chapter brief.
- A JSON scene contract with `chapterId`, `title`, `pov`, `time`, `location`, `focus`, `goal`, `conflict`, `turn`, `outcome`, `hook`, `emotionalBeat`, `relationshipBeat`, `internalNeed`, `woundOrFear`, `stakes`, `cost`, `subtext`, `aftertaste`, `logicDependencies`, `mustInclude`, `mustAvoid`, and `readerPromises`.

Rules:

- Every scene must have a concrete goal, conflict, turn, outcome, and hook.
- Every chapter must have one clear focus and one emotional beat.
- Logic dependencies must name the accepted facts, timeline events, or character knowledge this chapter relies on.
- Do not introduce canon that contradicts accepted memory.
- If key information is missing, mark it as an open question instead of inventing it.
- Make choices meaningful by listing cost, benefit, risk, and future impact.
- Give the chapter a human core: what the protagonist secretly needs, what wound or fear the conflict presses, what is at stake, what the action costs, what remains unsaid, and what emotional aftertaste should linger.
- Shape `emotionalBeat` as an initial defense or desire under pressure that produces a choice or shift and leaves an emotional consequence not yet fully digested; do not use a bare emotion label.
- Use `subtext` to name the gap between what is said and what a character is protecting, avoiding, or unable to admit.
- Derive `aftertaste` from the unresolved emotional consequence of the chapter's choice instead of forcing a standard satisfaction-plus-danger ending.
- Allow a character to misread, rationalize, hesitate, revise an answer, or leave something unsaid only when limited knowledge, desire, fear, dignity, or relationship pressure causes it. Do not create artificial incompetence or an author-level contradiction.
- Select a few details the viewpoint character would notice under the current pressure; do not turn the contract into a five-senses checklist.
