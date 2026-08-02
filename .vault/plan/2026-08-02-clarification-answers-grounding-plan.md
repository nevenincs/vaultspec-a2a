---
tags:
  - '#plan'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:5eacb3063732607388093a7961811c3555e07ef3a83742478b68123ccbe248be'
tier: L1
related:
  - '[[2026-08-02-clarification-answers-grounding-adr]]'
  - '[[2026-08-02-clarification-answers-grounding-research]]'
---

# `clarification-answers-grounding` plan

Make answered questionnaires reach downstream model turns through one gate-side
transcript append.

## Description

Implement the accepted clarification-answers-grounding ADR: a deterministic rendering
helper owned by the domain contract, one bounded human turn appended by the gate's
answers branch whenever at least one declared answer is present, and proof through the
contract, graph, and real-worker suites. Wire schema, receipts, and the lease service
are unchanged.

## Steps

- [x] `S01` - Render answered questionnaires into one bounded human transcript turn at the gate; `src/vaultspec_a2a/thread/clarification.py, src/vaultspec_a2a/graph/nodes/clarification.py`.
- [x] `S02` - Prove rendering bounds, skip-on-empty, gate append, and the real worker delivery; `src/vaultspec_a2a/thread/tests/test_clarification.py, src/vaultspec_a2a/graph/tests/nodes/test_clarification.py, src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`.

## Parallelization

The Steps are ordered: the proof consumes the production rendering and gate
behavior. No Step is delegated in parallel in the shared worktree.

## Verification

- Contract tests prove deterministic question-order rendering, only-answered
  inclusion, bounded output, and the empty-map skip rule.
- Graph tests prove an answered questionnaire appends exactly one rendered human
  turn alongside the recorded answers and receipt, and that an empty effective
  answer map appends nothing.
- The real gateway, worker app, and Executor loop proves the rendered turn reaches
  durable graph state.
- Existing answer, continuation, and decline behavior, focused lint, and the gating
  type check remain green.
- Formal review classifies every finding and appends deferred items to the feature's
  rolling audit queue.
