# Generation Scene Contract Builder

Create the scene contract for chapter {chapterId}.

Current chapter intent:

{chapterIntent}

Permanently forbidden items (must not be contradicted, regardless of any earlier chapter or memory content):

{activeProhibitions}

Return one JSON object and nothing else with these fields:

`chapterId`, `title`, `pov`, `time`, `location`, `focus`, `goal`, `conflict`, `turn`, `outcome`, `hook`, `openingHook`, `emotionalBeat`, `relationshipBeat`, `internalNeed`, `woundOrFear`, `stakes`, `cost`, `subtext`, `aftertaste`, `logicDependencies`, `mustInclude`, `mustAvoid`, `readerPromises`.

Rules:

- `pov` must contain only the canonical viewpoint character name, without perspective labels.
- Derive the contract from the accepted blueprint, prior chapter outcome, active promises, character state, relationships, and the supplied intent.
- Goal, conflict, turn, outcome, and hook must be concrete and causally connected.
- Include visible character and relationship movement, not only plot mechanics.
- Define `emotionalBeat` as a progression from an initial defense or desire, through pressure, to a choice or shift and its not-yet-digested emotional consequence; do not use a bare emotion label.
- Define `subtext` as the tension between what a character says and what they are protecting, avoiding, or unable to admit.
- Let `aftertaste` arise from the unresolved emotional consequence of this chapter's choice. Do not force every ending into the same satisfaction-plus-danger formula.
- A character may misread another person, rationalize a choice, hesitate, revise an answer, or leave something unsaid when limited knowledge, desire, fear, dignity, or relationship pressure causes it. Do not design artificial incompetence or an author-level contradiction.
- Choose only a few details the viewpoint character would notice under the current pressure, especially details that expose desire, relationship, risk, or misunderstanding; do not prescribe a five-senses checklist.
- Do not invent facts that contradict accepted memory.
- Fold every relevant permanently forbidden item above into `mustAvoid` explicitly.
- Do not use generic city-old-district, archive blockade, memory-cost, hidden-list, or numbered-clue templates unless the accepted project context explicitly requires them.
- Do not write files, Markdown commentary, or code fences around the final JSON.
