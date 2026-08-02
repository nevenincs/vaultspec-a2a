---
tags:
  - '#research'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:459f46f2cf0d168285013a24976b3fcb767ec980a2bd01313049c0b8259384a4'
related:
  - "[[2026-08-02-clarification-decline-research]]"
  - "[[2026-08-02-clarification-continuation-adr]]"
---

# `clarification-answers-grounding` research: `recorded answers reach no model turn`

An answered questionnaire's answers are checkpointed and disclosed on the wire but are
read by no production code, so the feature is decorative end to end: the product's
clarification card submits answers that never influence a single downstream model turn.
The evidence favors rendering the answered questionnaire into one appended human
transcript turn at the gate - the same mechanism the continuation and decline outcomes
already use - over teaching every producer to read the state channel. The ADR must
settle the rendering owner, the deterministic format, and whether the state channel is
retained.

## Findings

### The zero-reader status and the one mechanism that reaches turns

Both facts are established with locators in `2026-08-02-clarification-decline-research`:
`clarification_answers` state has no production reader, and downstream model turns read
only the `messages` transcript (plus per-role system prompts, rules, anchoring, and
mounted context). This document does not restate those locators; the finding here is
their consequence - the compiled graph's stated purpose for asking BEFORE the fan-out
("a researcher's brief can incorporate the human's answer",
`src/vaultspec_a2a/graph/compiler.py:1536`) is mechanically unfulfilled today.

### Per-producer state reads would be N sites; the gate append is one

The state-channel alternative requires each turn composer to read and render
`clarification_answers`: the researcher producer (`src/vaultspec_a2a/graph/compiler.py:1391`),
the worker message builder (`src/vaultspec_a2a/graph/nodes/worker.py:90`), and every
future producer - each a site that can drift or be forgotten, which is how the gap
shipped in the first place. The gate already appends exactly one human turn for a
continuation and (per the decline record) for a decline
(`src/vaultspec_a2a/graph/nodes/clarification.py:333`), and `TeamState.messages` uses
the `add_messages` reducer, so a single append in the resumed superstep reaches every
downstream role durably and replay-safely.

### The rendered turn is the user's own words, bounded by existing caps

Answers are what the human actually typed or chose, so a transcript turn rendering them
is honest human provenance, unlike fabricated prose. Bounds compose from the existing
contract: at most 4 answers of at most 2048 characters against prompts of at most 512
characters (`src/vaultspec_a2a/thread/clarification.py:116`), so a rendered message is
bounded well inside the 65536-character run-message ceiling by construction. Question
order in the committed request gives a deterministic rendering order independent of
answer-map insertion order.

### An all-optional questionnaire can resolve with nothing to render

`validate_clarification_answers` admits an empty answer map when every question is
optional (`src/vaultspec_a2a/thread/clarification.py:441`), so the rendering path must
decide between an empty append and no append. Appending an empty answers turn would
put a contentless human message in front of every downstream role.

## Sources

- `src/vaultspec_a2a/graph/compiler.py:1391`
- `src/vaultspec_a2a/graph/compiler.py:1536`
- `src/vaultspec_a2a/graph/nodes/clarification.py:333`
- `src/vaultspec_a2a/graph/nodes/worker.py:90`
- `src/vaultspec_a2a/thread/clarification.py:116`
- `src/vaultspec_a2a/thread/clarification.py:441`
